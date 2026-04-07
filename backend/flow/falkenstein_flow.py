"""FalkensteinFlow — main entry point replacing MainAgent."""

import logging
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
    def __init__(self, event_bus, native_ollama, vault_index, settings, tools: dict):
        self.event_bus = event_bus
        self.ollama = native_ollama
        self.vault_index = vault_index
        self.settings = settings
        self.tools = tools  # dict of crew_type -> list of CrewAI tool instances
        self.rule_engine = RuleEngine()
        self.input_guard = InputGuard()
        self.consolidator = PromptConsolidator()
        self.crew_registry = dict(CREW_CLASSES)

    async def handle_message(self, message: str, chat_id: str | None = None,
                             image_path: str | None = None) -> str:
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
        if route.action == "crew" and route.crew_type:
            crew_type = route.crew_type
        else:
            classification = await self.ollama.classify(message)
            crew_type = classification.get("crew_type", "coder")
            if classification.get("priority") == "premium":
                crew_type = "premium"
        log.info("Routing to crew: %s", crew_type)
        return await self._run_crew(crew_type, message, chat_id)

    async def _run_crew(self, crew_type, task_description, chat_id):
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
        return await crew.run()

    async def handle_scheduled(self, task: dict) -> str:
        description = task.get("prompt", task.get("title", ""))
        chat_id = task.get("chat_id")
        return await self.handle_message(description, chat_id=chat_id)
