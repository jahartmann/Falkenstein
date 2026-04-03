from backend.models import AgentData, AgentRole, AgentState, TaskStatus, AgentTraits
from backend.llm_client import LLMClient
from backend.database import Database
from backend.config import settings
from backend.tools.base import ToolRegistry
from backend.personality import PersonalityEngine, PersonalityEvent
from backend.memory.session import SessionMemory
from backend.memory.rag_engine import RAGEngine

IDLE_STATES = {
    AgentState.IDLE_WANDER, AgentState.IDLE_TALK, AgentState.IDLE_COFFEE,
    AgentState.IDLE_PHONE, AgentState.IDLE_SIT,
}

WORK_STATES = {
    AgentState.WORK_SIT, AgentState.WORK_TYPE, AgentState.WORK_TOOL, AgentState.WORK_REVIEW,
}

CONFIDENCE_THRESHOLD = 6
# Claude Code pattern: circuit breaker for compaction failures
MAX_CONSECUTIVE_COMPACT_FAILURES = 3
# Max session messages before auto-compaction
MAX_SESSION_MESSAGES = 30


def _trait_label(value: float) -> str:
    if value >= 0.8:
        return "sehr hoch"
    if value >= 0.6:
        return "hoch"
    if value >= 0.4:
        return "mittel"
    if value >= 0.2:
        return "niedrig"
    return "sehr niedrig"


class Agent:
    def __init__(self, data: AgentData, llm: LLMClient, db: Database, tools: ToolRegistry,
                 personality_engine: PersonalityEngine | None = None,
                 session_memory: SessionMemory | None = None,
                 rag_engine: RAGEngine | None = None):
        self.data = data
        self.llm = llm
        self.db = db
        self.tools = tools
        self.personality_engine = personality_engine or PersonalityEngine()
        self.session_memory = session_memory or SessionMemory()
        self.rag = rag_engine
        self.session_messages: list[dict] = []
        self.retry_count: int = 0
        self._compact_failures: int = 0
        self._current_task_title: str = ""
        self._current_task_desc: str = ""
        self._todo_steps: list[dict] = []  # TodoWrite pattern

    @property
    def is_idle(self) -> bool:
        return self.data.state in IDLE_STATES

    @property
    def is_working(self) -> bool:
        return self.data.state in WORK_STATES

    @property
    def personality_description(self) -> str:
        t = self.data.traits
        parts = [
            f"{self.data.name} ist {self.data.role.value}.",
            f"Sozial: {_trait_label(t.social)},",
            f"Fokus: {_trait_label(t.focus)},",
            f"Selbstvertrauen: {_trait_label(t.confidence)},",
            f"Geduld: {_trait_label(t.patience)},",
            f"Neugier: {_trait_label(t.curiosity)},",
            f"Führung: {_trait_label(t.leadership)}.",
        ]
        m = self.data.mood
        if m.stress > 0.6:
            parts.append("Ist gerade gestresst.")
        if m.energy < 0.3:
            parts.append("Ist müde.")
        if m.motivation > 0.7:
            parts.append("Ist motiviert.")
        if m.frustration > 0.5:
            parts.append("Ist frustriert.")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Context-Compaction (Claude Code pattern: 5-level hierarchy)
    # ------------------------------------------------------------------

    def _compact_session(self):
        """MicroCompact: clear old tool results, keep message structure.
        Claude Code pattern: replace old content with placeholder."""
        if len(self.session_messages) <= MAX_SESSION_MESSAGES:
            return
        # Keep first 2 messages (task assignment) and last 10
        keep_head = 2
        keep_tail = 10
        if len(self.session_messages) <= keep_head + keep_tail:
            return
        middle = self.session_messages[keep_head:-keep_tail]
        compacted = []
        for msg in middle:
            if msg.get("role") == "tool":
                # Replace verbose tool output with summary
                content = msg.get("content", "")
                compacted.append({
                    "role": "tool",
                    "content": f"[Vorheriges Tool-Ergebnis: {content[:80]}...]"
                })
            else:
                compacted.append(msg)
        self.session_messages = (
            self.session_messages[:keep_head]
            + compacted
            + self.session_messages[-keep_tail:]
        )

    def _try_compact(self):
        """Auto-compact with circuit breaker (max 3 consecutive failures)."""
        if self._compact_failures >= MAX_CONSECUTIVE_COMPACT_FAILURES:
            return  # Circuit breaker: stop trying
        try:
            self._compact_session()
            self._compact_failures = 0
        except Exception:
            self._compact_failures += 1

    # ------------------------------------------------------------------
    # System-Reminder (Claude Code pattern: inject into last user message)
    # ------------------------------------------------------------------

    def _build_system_reminder(self) -> str:
        """Build a system reminder to inject into the conversation.
        Claude Code pattern: append to user messages, not inflate base prompt."""
        parts = []
        # Current task context
        if self._current_task_title:
            parts.append(f"Aktueller Task: {self._current_task_title}")
        # TODO steps
        if self._todo_steps:
            todo_lines = []
            for step in self._todo_steps:
                marker = "✅" if step["status"] == "completed" else ("🔄" if step["status"] == "in_progress" else "⬜")
                todo_lines.append(f"  {marker} {step['title']}")
            parts.append("TODO:\n" + "\n".join(todo_lines))
        # Retry warning
        if self.retry_count > 0:
            parts.append(f"⚠️ Bereits {self.retry_count} fehlgeschlagene Versuche.")
        return "\n".join(parts) if parts else ""

    def _inject_system_reminder(self):
        """Inject system reminder into the last user message."""
        reminder = self._build_system_reminder()
        if not reminder:
            return
        # Find last user message and append reminder
        for i in range(len(self.session_messages) - 1, -1, -1):
            if self.session_messages[i].get("role") == "user":
                content = self.session_messages[i]["content"]
                if "<system-reminder>" not in content:
                    self.session_messages[i]["content"] = (
                        f"{content}\n\n<system-reminder>\n{reminder}\n</system-reminder>"
                    )
                break

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    async def assign_task(self, task_id: int, title: str, description: str):
        self.data.current_task_id = task_id
        self.data.state = AgentState.WORK_SIT
        self._current_task_title = title
        self._current_task_desc = description
        self._todo_steps = []
        self._compact_failures = 0

        content = f"Neuer Task: {title}\n\n{description}"
        if self.rag:
            rag_context = await self.rag.get_context_for_task(description)
            if rag_context:
                content = f"{rag_context}\n\n---\n\n{content}"

        self.session_messages = [{"role": "user", "content": content}]
        self.session_memory.add(self.data.id, {"role": "user", "content": content})
        await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, assigned_to=self.data.id)

    async def complete_task(self, result: str):
        if self.data.current_task_id is not None:
            await self.db.update_task_status(self.data.current_task_id, TaskStatus.DONE)
            self.data.traits, self.data.mood = self.personality_engine.apply_event(
                self.data.traits, self.data.mood, PersonalityEvent.TASK_SUCCESS
            )
            if self.rag:
                await self.rag.store_task_completion(
                    self.data.id, self._current_task_title,
                    self._current_task_desc, result, success=True,
                )
        self.data.current_task_id = None
        self.data.state = AgentState.IDLE_SIT
        self.session_messages = []
        self.session_memory.clear(self.data.id)
        self.retry_count = 0
        self._todo_steps = []

    async def fail_task(self, reason: str):
        if self.data.current_task_id is not None:
            await self.db.update_task_status(self.data.current_task_id, TaskStatus.FAILED)
            self.data.traits, self.data.mood = self.personality_engine.apply_event(
                self.data.traits, self.data.mood, PersonalityEvent.TASK_FAILURE
            )
            if self.rag:
                await self.rag.store_task_completion(
                    self.data.id, self._current_task_title,
                    self._current_task_desc, reason, success=False,
                )
        self.data.current_task_id = None
        self.data.state = AgentState.IDLE_SIT
        self.session_messages = []
        self.session_memory.clear(self.data.id)
        self.retry_count = 0
        self._todo_steps = []

    # ------------------------------------------------------------------
    # Work loop
    # ------------------------------------------------------------------

    @property
    def _uses_thinking(self) -> bool:
        return self.data.role in (AgentRole.PM, AgentRole.TEAM_LEAD)

    def _build_system_prompt(self) -> str:
        base = (
            f"Du bist {self.data.name}, Rolle: {self.data.role.value}. "
            f"{self.personality_description} "
            f"Du hast Zugriff auf Tools. Nutze sie um den Task zu erledigen."
        )
        if self.data.role in (AgentRole.RESEARCHER, AgentRole.PM):
            base += (
                " REGEL: Bei Fragen zu aktuellen Ereignissen, Nachrichten, Preisen, "
                "Releases oder Briefings MUSST du zuerst das web_research Tool nutzen. "
                "Nutze NIEMALS dein internes Wissen für aktuelle Fakten."
            )
        if self._uses_thinking:
            base += " Denke effizient. Nutze minimale Reasoning-Schritte."
        return base

    async def work_step(self) -> dict:
        self.data.state = AgentState.WORK_TYPE
        self.session_memory.touch(self.data.id)

        # Auto-compact if session is too long (Claude Code pattern)
        self._try_compact()

        # Inject system reminder into conversation (Claude Code pattern)
        self._inject_system_reminder()

        system_prompt = self._build_system_prompt()
        tool_schemas = self.tools.schemas_for_ollama()
        response = await self.llm.chat_with_tools(
            system_prompt=system_prompt,
            messages=self.session_messages,
            tools=tool_schemas,
            think=self._uses_thinking,
        )
        tool_calls = response.get("tool_calls", [])
        if tool_calls:
            self.data.state = AgentState.WORK_TOOL
            call = tool_calls[0]
            func = call["function"]
            tool = self.tools.get(func["name"])
            if tool:
                result = await tool.execute(func.get("arguments", {}))
                await self.db.log_tool_use(
                    self.data.id, func["name"],
                    str(func.get("arguments", {})), result.output, result.success,
                )
                self.session_messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
                self.session_messages.append({"role": "tool", "content": result.output})
                self.session_memory.add(self.data.id, {"role": "tool", "content": result.output[:200]})

                if not result.success:
                    self.retry_count += 1
                else:
                    self.retry_count = 0

                return {
                    "type": "tool_use",
                    "agent": self.data.id,
                    "tool": func["name"],
                    "success": result.success,
                    "output_preview": result.output[:100],
                    "needs_escalation": self.retry_count >= settings.llm_max_retries,
                }
        content = response.get("content", "")
        self.session_messages.append({"role": "assistant", "content": content})
        self.session_memory.add(self.data.id, {"role": "assistant", "content": content[:200]})
        self.retry_count = 0
        return {
            "type": "work_response",
            "agent": self.data.id,
            "content": content[:200],
        }

    async def review_result(self, result: str) -> dict:
        """Confidence-check via LLM. Claude Code pattern: never claim success without verification."""
        self.data.state = AgentState.WORK_REVIEW
        check = await self.llm.confidence_check(self._current_task_desc, result)
        score = check["score"]
        needs_escalation = score < CONFIDENCE_THRESHOLD

        if needs_escalation:
            self.data.traits, self.data.mood = self.personality_engine.apply_event(
                self.data.traits, self.data.mood, PersonalityEvent.CLI_ESCALATION
            )

        return {
            "type": "review",
            "agent": self.data.id,
            "score": score,
            "reason": check["reason"],
            "needs_escalation": needs_escalation,
        }

    # ------------------------------------------------------------------
    # TodoWrite pattern (Claude Code)
    # ------------------------------------------------------------------

    def add_todo(self, title: str):
        self._todo_steps.append({"title": title, "status": "pending"})

    def start_todo(self, index: int):
        if 0 <= index < len(self._todo_steps):
            # Only one in_progress at a time
            for s in self._todo_steps:
                if s["status"] == "in_progress":
                    s["status"] = "pending"
            self._todo_steps[index]["status"] = "in_progress"

    def complete_todo(self, index: int):
        if 0 <= index < len(self._todo_steps):
            self._todo_steps[index]["status"] = "completed"
