from __future__ import annotations

import asyncio
import httpx


class TelegramBot:
    """Telegram Bot — thin transport layer. All logic is in MainAgent."""

    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._offset: int = 0
        self._handlers: list = []
        self._started: bool = False  # Skip old messages on first poll

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def on_message(self, handler):
        """Register a handler for incoming messages."""
        self._handlers.append(handler)

    async def send_message(self, text: str, chat_id: str | None = None) -> bool:
        if not self.enabled:
            return False
        target = chat_id or self.chat_id
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Try with Markdown first
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": target, "text": text, "parse_mode": "Markdown"},
                )
                if resp.status_code == 200:
                    return True
                # Markdown parse error — retry without formatting
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": target, "text": text},
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def send_message_with_buttons(self, text: str, buttons: list[list[dict]],
                                         chat_id: str | None = None) -> bool:
        """Send message with inline keyboard. buttons: [[{"text": "Label", "callback_data": "data"}]]"""
        if not self.enabled:
            return False
        target = chat_id or self.chat_id
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Try with Markdown first
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": target,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": {"inline_keyboard": buttons},
                    },
                )
                if resp.status_code == 200:
                    return True
                # Markdown parse error — retry without formatting
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": target,
                        "text": text,
                        "reply_markup": {"inline_keyboard": buttons},
                    },
                )
                if resp.status_code == 200:
                    return True
                # Fallback without buttons
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": target, "text": text},
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def poll_updates(self) -> list[dict]:
        """Long-poll for new messages. Returns list of message dicts."""
        if not self.enabled:
            return []
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                resp = await client.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": self._offset, "timeout": 30},
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                results = data.get("result", [])
                messages = []
                for update in results:
                    self._offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    if text:
                        messages.append({
                            "text": text,
                            "chat_id": str(msg["chat"]["id"]),
                            "from": msg.get("from", {}).get("first_name", "Unknown"),
                        })
                    # Handle callback queries (inline button presses)
                    callback = update.get("callback_query", {})
                    if callback:
                        cb_data = callback.get("data", "")
                        cb_chat = str(callback.get("message", {}).get("chat", {}).get("id", ""))
                        if cb_data:
                            messages.append({
                                "text": cb_data,
                                "chat_id": cb_chat,
                                "from": callback.get("from", {}).get("first_name", "Unknown"),
                                "is_callback": True,
                            })
                        # Answer callback to remove loading state
                        cb_id = callback.get("id")
                        if cb_id:
                            try:
                                await client.post(
                                    f"{self.base_url}/answerCallbackQuery",
                                    json={"callback_query_id": cb_id},
                                )
                            except Exception:
                                pass
                return messages
        except Exception:
            return []

    async def poll_loop(self):
        """Continuous polling loop — run as asyncio task."""
        # First poll: skip all old messages (just advance offset)
        if not self._started:
            await self.poll_updates()
            self._started = True
            print("Telegram: old messages skipped, listening for new ones")

        while True:
            try:
                messages = await self.poll_updates()
                for msg in messages:
                    for handler in self._handlers:
                        asyncio.create_task(handler(msg))
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

