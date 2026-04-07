"""BaseFalkensteinCrew — parent class for all specialized CrewAI crews."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml
from crewai import Agent, Crew, Task

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).parent.parent / "config"


# ── Config loaders ────────────────────────────────────────────────────────────

def load_agent_configs() -> dict[str, dict]:
    """Load agent definitions from backend/config/agents.yaml."""
    path = _CONFIG_DIR / "agents.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_task_configs() -> dict[str, dict]:
    """Load task templates from backend/config/tasks.yaml."""
    path = _CONFIG_DIR / "tasks.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Agent factory ─────────────────────────────────────────────────────────────

def create_crewai_agent(
    agent_key: str,
    config: dict,
    llm_model: str,
    function_calling_llm: str,
    tools: list,
    vault_context: str | None = None,
) -> Agent:
    """Create a CrewAI Agent from a YAML config dict.

    If vault_context is provided, it is appended to the backstory so the agent
    is aware of Obsidian vault rules and structure.
    """
    backstory: str = config.get("backstory", "")
    if vault_context:
        backstory = f"{backstory}\n\nVault context:\n{vault_context}"

    return Agent(
        role=config["role"],
        goal=config["goal"],
        backstory=backstory,
        llm=llm_model,
        function_calling_llm=function_calling_llm,
        tools=tools,
        max_iter=config.get("max_iter", 10),
        verbose=config.get("verbose", True),
    )


# ── Base crew ─────────────────────────────────────────────────────────────────

class BaseFalkensteinCrew(ABC):
    """Abstract base class for all Falkenstein CrewAI crews.

    Subclasses must implement ``build_crew()`` which returns a configured
    :class:`crewai.Crew` instance ready to kick off.
    """

    def __init__(
        self,
        crew_type: str,
        task_description: str,
        event_bus: Any,
        chat_id: int | str | None = None,
        vault_context: str | None = None,
    ) -> None:
        self.crew_type = crew_type
        self.task_description = task_description
        self.event_bus = event_bus
        self.chat_id = chat_id
        self.vault_context = vault_context

        self.agent_configs = load_agent_configs()
        self.task_configs = load_task_configs()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_agent(
        self,
        agent_key: str,
        llm_model: str,
        fc_llm: str,
        tools: list,
    ) -> Agent:
        """Convenience wrapper around :func:`create_crewai_agent`."""
        config = self.agent_configs[agent_key]
        return create_crewai_agent(
            agent_key=agent_key,
            config=config,
            llm_model=llm_model,
            function_calling_llm=fc_llm,
            tools=tools,
            vault_context=self.vault_context,
        )

    def _step_callback(self, step_output: Any) -> None:
        """CrewAI step callback — bridges sync callback to async EventBus.

        CrewAI calls this synchronously after each agent step. We schedule the
        async ``on_tool_call`` coroutine onto the running event loop without
        blocking the calling thread.
        """
        try:
            # Extract tool info when available; fall back to generic values.
            agent_name: str = getattr(step_output, "agent", self.crew_type)
            tool_name: str = getattr(step_output, "tool", "unknown")
            tool_input: Any = getattr(step_output, "tool_input", None)
            tool_output: Any = getattr(step_output, "result", str(step_output))

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self.event_bus.on_tool_call(
                        agent_name=str(agent_name),
                        tool_name=str(tool_name),
                        tool_input=tool_input,
                        tool_output=tool_output,
                    )
                )
            else:
                loop.run_until_complete(
                    self.event_bus.on_tool_call(
                        agent_name=str(agent_name),
                        tool_name=str(tool_name),
                        tool_input=tool_input,
                        tool_output=tool_output,
                    )
                )
        except Exception as exc:  # never crash the crew over a callback error
            logger.warning("_step_callback error: %s", exc)

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def build_crew(self) -> Crew:
        """Build and return the configured :class:`crewai.Crew`.

        Subclasses create agents/tasks here and pass ``self._step_callback``
        as the ``step_callback`` to the Crew.
        """

    # ── Async entry point ─────────────────────────────────────────────────────

    async def run(self) -> str:
        """Start the crew, await its result, and fire EventBus lifecycle events.

        Returns the final crew result as a string.
        """
        await self.event_bus.on_crew_start(
            crew_name=self.crew_type,
            task_description=self.task_description,
            chat_id=self.chat_id,
        )

        try:
            crew = self.build_crew()
            # kickoff is synchronous in CrewAI; run in executor to avoid blocking.
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: crew.kickoff(inputs={"task": self.task_description})
            )
            result_str = str(result)
            await self.event_bus.on_crew_done(
                crew_name=self.crew_type,
                result=result_str,
                chat_id=self.chat_id,
            )
            return result_str
        except Exception as exc:
            logger.error("Crew '%s' failed: %s", self.crew_type, exc)
            await self.event_bus.on_crew_error(
                crew_name=self.crew_type,
                error=exc,
                chat_id=self.chat_id,
            )
            raise
