"""FalkensteinFlow — main entry point replacing MainAgent."""

import logging
import re
from datetime import datetime, timedelta
from backend.flow.rule_engine import RuleEngine
from backend.security.input_guard import InputGuard
from backend.prompt_consolidator import PromptConsolidator

from backend.crews.coder_crew import CoderCrew
from backend.crews.researcher_crew import ResearcherCrew
from backend.crews.writer_crew import WriterCrew
from backend.crews.ops_crew import OpsCrew
from backend.crews.web_design_crew import WebDesignCrew
from backend.crews.swift_crew import SwiftCrew
from backend.crews.ki_expert_crew import KIExpertCrew
from backend.crews.analyst_crew import AnalystCrew
from backend.crews.premium_crew import PremiumCrew

log = logging.getLogger(__name__)

CREW_CLASSES = {
    "coder": CoderCrew,
    "researcher": ResearcherCrew,
    "writer": WriterCrew,
    "ops": OpsCrew,
    "web_design": WebDesignCrew,
    "swift": SwiftCrew,
    "ki_expert": KIExpertCrew,
    "analyst": AnalystCrew,
    "premium": PremiumCrew,
}

class FalkensteinFlow:
    def __init__(self, event_bus, native_ollama, vault_index, settings, tools: dict,
                 mcp_bridge=None):
        self.event_bus = event_bus
        self.ollama = native_ollama
        self.vault_index = vault_index
        self.settings = settings
        self.tools = tools  # dict of crew_type -> list of CrewAI tool instances
        self.mcp_bridge = mcp_bridge
        self.rule_engine = RuleEngine()
        self.input_guard = InputGuard()
        self.consolidator = PromptConsolidator()
        self.crew_registry = dict(CREW_CLASSES)

    async def handle_message(self, message: str, chat_id: str | None = None,
                             image_path: str | None = None,
                             job_id: str | None = None) -> str:
        # 1. Security check
        guard_result = self.input_guard.check_patterns(message)
        if guard_result.action == "BLOCK":
            return "Nachricht blockiert: Sicherheitsfilter."
        # 2. Consolidate — returns (text, was_consolidated)
        consolidated, _ = self.consolidator.consolidate(message)
        message = consolidated
        # 3. Route
        route = self.rule_engine.route(message)
        if route.action == "quick_reply":
            # No vault context for quick replies — keep it fast
            return await self.ollama.quick_reply(message, context="Antworte kurz und direkt auf Deutsch.")
        if route.action == "direct_mcp" and self.mcp_bridge:
            return await self._handle_direct_mcp(message, chat_id, job_id=job_id)
        if route.action == "crew" and route.crew_type:
            crew_type = route.crew_type
        else:
            classification = await self.ollama.classify(message)
            crew_type = classification.get("crew_type", "coder")
            if classification.get("priority") == "premium":
                crew_type = "premium"
        log.info("Routing to crew: %s", crew_type)
        return await self._run_crew(crew_type, message, chat_id, job_id=job_id)

    async def _run_crew(self, crew_type, task_description, chat_id, job_id: str | None = None):
        crew_cls = self.crew_registry.get(crew_type, CoderCrew)
        vault_ctx = self.vault_index.as_context() if self.vault_index else ""
        crew_tools = self.tools.get(crew_type, [])
        llm_model = f"ollama_chat/{self.settings.ollama_model}"
        fc_llm = f"ollama_chat/{self.settings.model_light}"
        if crew_type == "ops":
            llm_model = fc_llm
        crew = crew_cls(
            task_description=task_description, event_bus=self.event_bus,
            chat_id=chat_id, vault_context=vault_ctx, tools=crew_tools,
            llm_model=llm_model, fc_llm=fc_llm if crew_type not in ("writer", "ops", "premium") else None,
        )
        crew.job_id = job_id
        return await crew.run()

    async def _handle_direct_mcp(
        self, message: str, chat_id: int | None = None, job_id: str | None = None,
    ) -> str:
        try:
            # Pass discovered tools so the LLM knows what's available
            tools_info = []
            available_tool_names: set[tuple[str, str]] = set()
            if self.mcp_bridge:
                try:
                    for schema in await self.mcp_bridge.discover_tools():
                        available_tool_names.add((schema.server_id, schema.name))
                        tools_info.append({
                            "server_id": schema.server_id,
                            "tool_name": schema.name,
                            "description": schema.description,
                            "input_schema": schema.input_schema,
                        })
                except Exception:
                    pass
            mcp_intent = await self.ollama.classify_mcp(message, available_tools=tools_info)
            server_id = mcp_intent.get("server_id")
            tool_name = mcp_intent.get("tool_name")
            args = mcp_intent.get("args", {})
            if (
                not server_id
                or not tool_name
                or (available_tool_names and (server_id, tool_name) not in available_tool_names)
            ):
                server_id, tool_name, args = self._heuristic_direct_mcp(message, tools_info)
            if not server_id or not tool_name:
                if self._looks_like_music_request(message):
                    return (
                        "Für Musik ist aktuell kein passendes MCP-Tool aktiv. "
                        "Der installierte Apple-MCP deckt hier offenbar keine Wiedergabe ab."
                    )
                if self._looks_like_reminder_request(message):
                    return (
                        "Ich habe dafür kein startklares Reminder-Tool gefunden. "
                        "Prüfe bitte Apple-MCP und die freigegebenen Werkzeuge im Admin-Bereich."
                    )
                return await self._run_crew("ops", message, chat_id, job_id=job_id)
            result = await self.mcp_bridge.call_tool(server_id, tool_name, args)
            return result.output if result.success else f"Fehler: {result.output}"
        except Exception as e:
            return f"MCP Fehler: {e}"

    @staticmethod
    def _looks_like_music_request(message: str) -> bool:
        text = (message or "").lower()
        return any(token in text for token in ("musik", "music", "playlist", "apple music", "spotify", "play "))

    @staticmethod
    def _looks_like_reminder_request(message: str) -> bool:
        text = (message or "").lower()
        return any(token in text for token in ("erinner", "remind", "reminder", "erinnerung"))

    def _heuristic_direct_mcp(self, message: str, tools_info: list[dict]) -> tuple[str | None, str | None, dict]:
        reminder_tool = self._find_tool_match(
            tools_info,
            include=("reminder", "reminders"),
            prefer=("create", "add", "new"),
            server_hint="apple-mcp",
        )
        if reminder_tool and self._looks_like_reminder_request(message):
            return (
                reminder_tool["server_id"],
                reminder_tool["tool_name"],
                self._build_reminder_args(message, reminder_tool.get("input_schema", {})),
            )

        music_tool = self._find_tool_match(
            tools_info,
            include=("music", "play"),
            prefer=("play_music", "play"),
            server_hint="apple-mcp",
        )
        if music_tool and self._looks_like_music_request(message):
            return (
                music_tool["server_id"],
                music_tool["tool_name"],
                self._build_music_args(message, music_tool.get("input_schema", {})),
            )

        return None, None, {}

    @staticmethod
    def _find_tool_match(
        tools_info: list[dict],
        *,
        include: tuple[str, ...],
        prefer: tuple[str, ...] = (),
        server_hint: str | None = None,
    ) -> dict | None:
        candidates = []
        for tool in tools_info:
            name = str(tool.get("tool_name", "")).lower()
            server_id = str(tool.get("server_id", ""))
            if not any(token in name for token in include):
                continue
            score = 0
            if server_hint and server_id == server_hint:
                score += 4
            score += sum(2 for token in prefer if token in name)
            score += 1 if "create" in name else 0
            candidates.append((score, tool))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _extract_reminder_title(message: str) -> str:
        text = re.sub(r"^[Ee]rinnere?\s+mich\b", "", message).strip(" .")
        text = re.sub(r"\b(morgen|heute|tomorrow|today)\b", "", text, flags=re.I).strip(" .")
        text = re.sub(r"\bum\s+\d{1,2}(?::\d{2})?\b", "", text, flags=re.I).strip(" .")
        match = re.search(r"\b(?:an|für|ueber|über)\b\s+(.+)$", text, flags=re.I)
        if match:
            text = match.group(1).strip(" .")
        return text or message.strip()

    @staticmethod
    def _extract_due_iso(message: str) -> str | None:
        text = (message or "").lower()
        now = datetime.now()
        base = None
        if "morgen" in text or "tomorrow" in text:
            base = now + timedelta(days=1)
        elif "heute" in text or "today" in text:
            base = now
        if base is None:
            return None
        hour = 9
        minute = 0
        match = re.search(r"\bum\s+(\d{1,2})(?::(\d{2}))?", text)
        if match:
            hour = max(0, min(23, int(match.group(1))))
            minute = max(0, min(59, int(match.group(2) or "0")))
        due = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return due.isoformat(timespec="minutes")

    def _build_reminder_args(self, message: str, input_schema: dict) -> dict:
        props = set((input_schema or {}).get("properties", {}).keys())
        tool_name = self._extract_reminder_title(message)
        due_iso = self._extract_due_iso(message)
        args: dict = {}
        if "operation" in props:
            args["operation"] = "create"
        if "name" in props:
            args["name"] = tool_name
        if "title" in props:
            args["title"] = tool_name
        if "text" in props and "name" not in props and "title" not in props:
            args["text"] = tool_name
        if due_iso:
            for due_key in ("dueDate", "due_date", "date", "startDate"):
                if due_key in props:
                    args[due_key] = due_iso
                    break
        return args

    @staticmethod
    def _extract_music_query(message: str) -> str:
        text = re.sub(r"^[Ss]piel(?:e)?\s+", "", message).strip(" .")
        text = re.sub(r"\bauf\s+apple\s+music\b", "", text, flags=re.I).strip(" .")
        return text or message.strip()

    def _build_music_args(self, message: str, input_schema: dict) -> dict:
        props = set((input_schema or {}).get("properties", {}).keys())
        query = self._extract_music_query(message)
        args: dict = {}
        if "operation" in props:
            args["operation"] = "play"
        for key in ("query", "searchText", "text", "term", "name"):
            if key in props:
                args[key] = query
                break
        return args

    async def handle_scheduled(self, task: dict) -> str:
        description = task.get("prompt", task.get("title", ""))
        chat_id = task.get("chat_id")
        return await self.handle_message(description, chat_id=chat_id)
