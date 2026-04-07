"""FalkensteinEventBus — bridges CrewAI callbacks to WebSocket, Telegram, and DB."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Tools whose results get streamed to Telegram
STREAM_TO_TELEGRAM: set[str] = {
    "web_search",
    "scrape_website",
    "obsidian_manager",
    "obsidian",
    "shell_runner",
    "system_shell",
    "code_executor",
}

# Maps tool names to Phaser animations
TOOL_TO_ANIMATION: dict[str, str] = {
    "code_executor": "typing",
    "shell_runner": "typing",
    "system_shell": "typing",
    "web_search": "reading",
    "scrape_website": "reading",
    "obsidian": "reading",
    "obsidian_manager": "reading",
    "vision": "thinking",
    "file_read": "thinking",
    "file_write": "typing",
}


class FalkensteinEventBus:
    """Central event hub bridging CrewAI callbacks to WebSocket, Telegram, and DB."""

    def __init__(self, ws_manager, telegram_bot, db):
        self.ws_manager = ws_manager
        self.telegram_bot = telegram_bot
        self.db = db
        self._current_crew_id: str | None = None
        self._current_chat_id: int | str | None = None

    async def on_crew_start(
        self, crew_name: str, task_description: str, chat_id: int | str | None = None
    ) -> str:
        """Called when a crew starts. Creates DB entry, notifies Telegram, broadcasts WS."""
        self._current_chat_id = chat_id

        crew_id = await self.db.create_crew(
            name=crew_name, task_description=task_description
        )
        self._current_crew_id = crew_id

        await self.telegram_bot.send_message(
            f"Crew '{crew_name}' gestartet: {task_description}",
            chat_id=chat_id,
        )

        await self.ws_manager.broadcast(
            {
                "type": "agent_spawn",
                "crew_id": crew_id,
                "crew_name": crew_name,
                "task_description": task_description,
            }
        )

        logger.info("Crew started: %s (id=%s)", crew_name, crew_id)
        return crew_id

    async def on_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        duration_ms: int = 0,
    ) -> None:
        """Called after a tool finishes. Broadcasts WS, optionally streams to Telegram, logs to DB."""
        animation = TOOL_TO_ANIMATION.get(tool_name, "thinking")

        await self.ws_manager.broadcast(
            {
                "type": "tool_use",
                "agent_name": agent_name,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
                "duration_ms": duration_ms,
                "animation": animation,
            }
        )

        if tool_name in STREAM_TO_TELEGRAM:
            output_text = (
                str(tool_output)[:2000]
                if tool_output is not None
                else "(no output)"
            )
            await self.telegram_bot.send_message(
                f"[{agent_name}] {tool_name}:\n{output_text}",
                chat_id=self._current_chat_id,
            )

        await self.db.log_crew_tool(
            crew_id=self._current_crew_id,
            agent_name=agent_name,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            duration_ms=duration_ms,
        )

    async def on_crew_done(
        self, crew_name: str, result: Any, chat_id: int | str | None = None
    ) -> None:
        """Called when a crew finishes successfully."""
        effective_chat_id = chat_id or self._current_chat_id

        result_text = str(result)[:4000] if result is not None else "(kein Ergebnis)"
        await self.telegram_bot.send_message(
            f"Crew '{crew_name}' fertig:\n{result_text}",
            chat_id=effective_chat_id,
        )

        await self.db.update_crew(
            crew_id=self._current_crew_id,
            status="done",
            result=result,
        )

        await self.ws_manager.broadcast(
            {
                "type": "agent_done",
                "crew_name": crew_name,
                "crew_id": self._current_crew_id,
            }
        )

        logger.info("Crew done: %s", crew_name)

    async def on_crew_error(
        self, crew_name: str, error: str | Exception, chat_id: int | str | None = None
    ) -> None:
        """Called when a crew fails."""
        effective_chat_id = chat_id or self._current_chat_id
        error_text = str(error)

        await self.telegram_bot.send_message(
            f"Crew '{crew_name}' Fehler: {error_text}",
            chat_id=effective_chat_id,
        )

        await self.db.update_crew(
            crew_id=self._current_crew_id,
            status="error",
            result=error_text,
        )

        await self.ws_manager.broadcast(
            {
                "type": "agent_error",
                "crew_name": crew_name,
                "crew_id": self._current_crew_id,
                "error": error_text,
            }
        )

        logger.error("Crew error: %s — %s", crew_name, error_text)
