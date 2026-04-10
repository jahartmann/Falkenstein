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


def should_stream_to_telegram(tool_name: str) -> bool:
    """Check if a tool's output should be streamed to Telegram."""
    if tool_name in STREAM_TO_TELEGRAM:
        return True
    return tool_name.startswith("mcp_")


def get_tool_animation(tool_name: str) -> str:
    """Get the Phaser animation hint for a tool."""
    if tool_name in TOOL_TO_ANIMATION:
        return TOOL_TO_ANIMATION[tool_name]
    if tool_name.startswith("mcp_"):
        return "thinking"
    return "typing"


class FalkensteinEventBus:
    """Central event hub bridging CrewAI callbacks to WebSocket, Telegram, and DB."""

    def __init__(self, ws_manager, telegram_bot, db, telegram_jobs=None):
        self.ws_manager = ws_manager
        self.telegram_bot = telegram_bot
        self.db = db
        self.telegram_jobs = telegram_jobs
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
        self,
        crew_name: str,
        task_description: str,
        chat_id: int | str | None = None,
        job_id: str | None = None,
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
        if self.telegram_jobs and job_id:
            self.telegram_jobs.mark_started(job_id, crew_type=crew_name, crew_id=crew_id)

        if job_id:
            await self._tg_send(f"🧠 Job {job_id} läuft jetzt mit {crew_name}.", chat_id)
        else:
            await self._tg_send(f"{crew_name} arbeitet: {task_description}", chat_id)

        await self.ws_manager.broadcast(
            {
                "type": "agent_spawn",
                "crew": crew_name,
                "crew_id": crew_id,
                "task": task_description,
                "job_id": job_id,
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
        crew_id: str | None = None,
        chat_id: int | str | None = None,
        job_id: str | None = None,
    ) -> None:
        """Called after a tool finishes. Broadcasts WS, optionally streams to Telegram, logs to DB."""
        animation = get_tool_animation(tool_name)
        resolved_crew_id = crew_id or self._current_crew_id
        resolved_chat_id = chat_id or self._current_chat_id
        progress = None
        if self.telegram_jobs and job_id:
            progress = self.telegram_jobs.note_progress(job_id, str(tool_name))

        await self.ws_manager.broadcast(
            {
                "type": "tool_use",
                "agent": agent_name,
                "tool": tool_name,
                "animation": animation,
                "crew_id": resolved_crew_id,
                "job_id": job_id,
                "step": progress["step"] if progress else None,
                "label": progress["label"] if progress else str(tool_name),
            }
        )

        if job_id and progress:
            if should_stream_to_telegram(tool_name) and tool_output:
                truncated = str(tool_output)[:500]
                await self._tg_send(
                    f"🔄 Job {job_id} • Schritt {progress['step']} • {tool_name}\n{truncated}",
                    resolved_chat_id,
                )
            else:
                await self._tg_send(
                    f"🔄 Job {job_id} • Schritt {progress['step']} • {tool_name}",
                    resolved_chat_id,
                )
        elif should_stream_to_telegram(tool_name) and tool_output:
            truncated = str(tool_output)[:500]
            await self._tg_send(f"🔧 {tool_name}: {truncated}", resolved_chat_id)

        if resolved_crew_id:
            try:
                await self.db.log_crew_tool(
                    crew_id=resolved_crew_id,
                    agent_name=str(agent_name),
                    tool_name=str(tool_name),
                    tool_input=str(tool_input)[:2000] if tool_input else "",
                    tool_output=str(tool_output)[:2000] if tool_output else "",
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning("Failed to log tool use: %s", e)

    async def on_crew_done(
        self,
        crew_name: str,
        result: Any,
        chat_id: int | str | None = None,
        crew_id: str | None = None,
        job_id: str | None = None,
    ) -> None:
        """Called when a crew finishes successfully."""
        result_text = str(result)[:4000] if result else "(kein Ergebnis)"
        resolved_crew_id = crew_id or self._current_crew_id
        resolved_chat_id = chat_id or self._current_chat_id
        if self.telegram_jobs and job_id:
            self.telegram_jobs.complete(job_id, status="done", result_preview=result_text)
            await self._tg_send(f"✅ Job {job_id} fertig\n\n{result_text}", resolved_chat_id)
        else:
            await self._tg_send(result_text, resolved_chat_id)

        if resolved_crew_id:
            await self.db.update_crew(resolved_crew_id, status="done")

        await self.ws_manager.broadcast(
            {
                "type": "agent_done",
                "crew": crew_name,
                "crew_id": resolved_crew_id,
                "job_id": job_id,
            }
        )

        logger.info("Crew done: %s", crew_name)
        self._current_crew_id = None
        self._current_chat_id = None

    async def on_crew_error(
        self,
        crew_name: str,
        error: str | Exception,
        chat_id: int | str | None = None,
        crew_id: str | None = None,
        job_id: str | None = None,
    ) -> None:
        """Called when a crew fails."""
        error_text = str(error)
        resolved_crew_id = crew_id or self._current_crew_id
        resolved_chat_id = chat_id or self._current_chat_id

        if self.telegram_jobs and job_id:
            self.telegram_jobs.complete(job_id, status="error", result_preview=error_text)
            await self._tg_send(f"❌ Job {job_id} Fehler: {error_text}", resolved_chat_id)
        else:
            await self._tg_send(f"❌ {crew_name} Fehler: {error_text}", resolved_chat_id)

        if resolved_crew_id:
            await self.db.update_crew(resolved_crew_id, status="error")

        await self.ws_manager.broadcast(
            {
                "type": "agent_error",
                "crew": crew_name,
                "crew_id": resolved_crew_id,
                "job_id": job_id,
                "error": error_text,
            }
        )

        logger.error("Crew error: %s — %s", crew_name, error_text)
        self._current_crew_id = None
        self._current_chat_id = None
