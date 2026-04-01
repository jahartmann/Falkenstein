from backend.models import AgentData, AgentState, TaskStatus, AgentTraits
from backend.llm_client import LLMClient
from backend.database import Database
from backend.tools.base import ToolRegistry
from backend.personality import PersonalityEngine, PersonalityEvent

IDLE_STATES = {
    AgentState.IDLE_WANDER, AgentState.IDLE_TALK, AgentState.IDLE_COFFEE,
    AgentState.IDLE_PHONE, AgentState.IDLE_SIT,
}

WORK_STATES = {
    AgentState.WORK_SIT, AgentState.WORK_TYPE, AgentState.WORK_TOOL, AgentState.WORK_REVIEW,
}


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
                 personality_engine: PersonalityEngine | None = None):
        self.data = data
        self.llm = llm
        self.db = db
        self.tools = tools
        self.personality_engine = personality_engine or PersonalityEngine()
        self.session_messages: list[dict] = []

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

    async def assign_task(self, task_id: int, title: str, description: str):
        self.data.current_task_id = task_id
        self.data.state = AgentState.WORK_SIT
        self.session_messages = [
            {"role": "user", "content": f"Neuer Task: {title}\n\n{description}"}
        ]
        await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, assigned_to=self.data.id)

    async def complete_task(self, result: str):
        if self.data.current_task_id is not None:
            await self.db.update_task_status(self.data.current_task_id, TaskStatus.DONE)
            self.data.traits, self.data.mood = self.personality_engine.apply_event(
                self.data.traits, self.data.mood, PersonalityEvent.TASK_SUCCESS
            )
        self.data.current_task_id = None
        self.data.state = AgentState.IDLE_SIT
        self.session_messages = []

    async def fail_task(self, reason: str):
        if self.data.current_task_id is not None:
            await self.db.update_task_status(self.data.current_task_id, TaskStatus.FAILED)
            self.data.traits, self.data.mood = self.personality_engine.apply_event(
                self.data.traits, self.data.mood, PersonalityEvent.TASK_FAILURE
            )
        self.data.current_task_id = None
        self.data.state = AgentState.IDLE_SIT
        self.session_messages = []

    async def work_step(self) -> dict:
        self.data.state = AgentState.WORK_TYPE
        system_prompt = (
            f"Du bist {self.data.name}, Rolle: {self.data.role.value}. "
            f"{self.personality_description} "
            f"Du hast Zugriff auf Tools. Nutze sie um den Task zu erledigen."
        )
        tool_schemas = self.tools.schemas_for_ollama()
        response = await self.llm.chat_with_tools(
            system_prompt=system_prompt,
            messages=self.session_messages,
            tools=tool_schemas,
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
                return {
                    "type": "tool_use",
                    "agent": self.data.id,
                    "tool": func["name"],
                    "success": result.success,
                    "output_preview": result.output[:100],
                }
        content = response.get("content", "")
        self.session_messages.append({"role": "assistant", "content": content})
        return {
            "type": "work_response",
            "agent": self.data.id,
            "content": content[:200],
        }
