import asyncio
import httpx
from backend.config import settings


class TelegramBot:
    """Telegram Bot — thin transport layer. All logic is in MainAgent."""

    def __init__(self):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
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
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={"chat_id": target, "text": text, "parse_mode": "Markdown"},
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

