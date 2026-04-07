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

    async def _tg_send(self, text: str, chat_id=None):
        """Send to Telegram only if bot is configured and enabled."""
        if self.telegram_bot and getattr(self.telegram_bot, "enabled", False):
            cid = chat_id or self._current_chat_id
            if cid:
                try:
                    await self.telegram_bot.send_message(text, chat_id=cid)
                except Exception as e:
                    logger.warning("Telegram send failed: %s", e)

    async def on_crew_start(
        self, crew_name: str, task_description: str, chat_id: int | str | None = None
    ) -> str:
        """Called when a crew starts. Creates DB entry, notifies Telegram, broadcasts WS."""
        self._current_chat_id = chat_id

        crew_id = await self.db.create_crew(
            crew_type=crew_name,
            trigger_source="telegram" if chat_id else "api",
            chat_id=str(chat_id) if chat_id else None,
            task_description=task_description,
        )
        self._current_crew_id = crew_id

        await self._tg_send(f"{crew_name} arbeitet: {task_description}", chat_id)

        await self.ws_manager.broadcast(
            {
                "type": "agent_spawn",
                "crew": crew_name,
                "crew_id": crew_id,
                "task": task_description,
            }
        )

        logger.info("Crew started: %s (id=%s)", crew_name, crew_id)
        return crew_id

    async def on_tool_call(
        self,
        agent_name: str,
        tool_name: str,
        tool_input: Any = "",
        tool_output: Any = "",
        duration_ms: int = 0,
    ) -> None:
        """Called after a tool finishes. Broadcasts WS, optionally streams to Telegram, logs to DB."""
        animation = TOOL_TO_ANIMATION.get(tool_name, "thinking")

        await self.ws_manager.broadcast(
            {
                "type": "tool_use",
                "agent": agent_name,
                "tool": tool_name,
                "animation": animation,
                "crew_id": self._current_crew_id,
            }
        )

        if tool_name in STREAM_TO_TELEGRAM and tool_output:
            truncated = str(tool_output)[:500]
            await self._tg_send(f"🔧 {tool_name}: {truncated}")

        if self._current_crew_id:
            try:
                await self.db.log_crew_tool(
                    crew_id=self._current_crew_id,
                    agent_name=str(agent_name),
                    tool_name=str(tool_name),
                    tool_input=str(tool_input)[:2000] if tool_input else "",
                    tool_output=str(tool_output)[:2000] if tool_output else "",
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning("Failed to log tool use: %s", e)

    async def on_crew_done(
        self, crew_name: str, result: Any, chat_id: int | str | None = None
    ) -> None:
        """Called when a crew finishes successfully."""
        result_text = str(result)[:4000] if result else "(kein Ergebnis)"
        await self._tg_send(result_text, chat_id)

        if self._current_crew_id:
            await self.db.update_crew(self._current_crew_id, status="done")

        await self.ws_manager.broadcast(
            {
                "type": "agent_done",
                "crew": crew_name,
                "crew_id": self._current_crew_id,
            }
        )

        logger.info("Crew done: %s", crew_name)
        self._current_crew_id = None
        self._current_chat_id = None

    async def on_crew_error(
        self, crew_name: str, error: str | Exception, chat_id: int | str | None = None
    ) -> None:
        """Called when a crew fails."""
        error_text = str(error)

        await self._tg_send(f"❌ {crew_name} Fehler: {error_text}", chat_id)

        if self._current_crew_id:
            await self.db.update_crew(self._current_crew_id, status="error")

        await self.ws_manager.broadcast(
            {
                "type": "agent_error",
                "crew": crew_name,
                "crew_id": self._current_crew_id,
                "error": error_text,
            }
        )

        logger.error("Crew error: %s — %s", crew_name, error_text)
        self._current_crew_id = None
        self._current_chat_id = None
