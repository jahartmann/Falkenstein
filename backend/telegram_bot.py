from __future__ import annotations

import asyncio
import httpx
import tempfile
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from backend.security.telegram_allowlist import TelegramAllowlist


class TelegramBot:
    """Telegram Bot — thin transport layer. All logic is in MainAgent."""

    def __init__(self, token: str = "", chat_id: str = "",
                 allowlist: "TelegramAllowlist | None" = None,
                 download_dir: Path | None = None):
        self.token = token
        self.chat_id = chat_id
        self.allowlist = allowlist
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.file_url = f"https://api.telegram.org/file/bot{self.token}"
        self.download_dir = download_dir or Path(tempfile.gettempdir()) / "falkenstein_media"
        self.download_dir.mkdir(parents=True, exist_ok=True)
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

    async def download_file(self, file_id: str, suffix: str = "") -> Path | None:
        """Download a file from Telegram by file_id. Returns local path."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.base_url}/getFile",
                    params={"file_id": file_id},
                )
                if resp.status_code != 200:
                    return None
                file_path = resp.json().get("result", {}).get("file_path", "")
                if not file_path:
                    return None
                # Download the actual file
                file_resp = await client.get(f"{self.file_url}/{file_path}")
                if file_resp.status_code != 200:
                    return None
                ext = suffix or Path(file_path).suffix or ".bin"
                local_path = self.download_dir / f"{file_id}{ext}"
                local_path.write_bytes(file_resp.content)
                return local_path
        except Exception:
            return None

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
                    msg_chat_id = str(msg.get("chat", {}).get("id", ""))
                    from_name = msg.get("from", {}).get("first_name", "Unknown")

                    # Allowlist check
                    if msg_chat_id and self.allowlist and not self.allowlist.is_allowed(msg_chat_id):
                        # Still process callback queries below
                        if not update.get("callback_query"):
                            continue

                    text = msg.get("text", "")
                    caption = msg.get("caption", "")

                    # Voice messages
                    voice = msg.get("voice") or msg.get("audio")
                    if voice and msg_chat_id:
                        file_id = voice.get("file_id", "")
                        if file_id:
                            local_path = await self.download_file(file_id, ".ogg")
                            if local_path:
                                messages.append({
                                    "text": caption or "",
                                    "chat_id": msg_chat_id,
                                    "from": from_name,
                                    "voice_path": str(local_path),
                                })
                                continue

                    # Photo messages (take largest photo)
                    photos = msg.get("photo")
                    if photos and msg_chat_id:
                        # Telegram sends multiple sizes, last is largest
                        best = photos[-1]
                        file_id = best.get("file_id", "")
                        if file_id:
                            local_path = await self.download_file(file_id, ".jpg")
                            if local_path:
                                messages.append({
                                    "text": caption or "",
                                    "chat_id": msg_chat_id,
                                    "from": from_name,
                                    "image_path": str(local_path),
                                })
                                continue

                    # Document (images sent as file)
                    doc = msg.get("document")
                    if doc and msg_chat_id:
                        mime = doc.get("mime_type", "")
                        if mime.startswith("image/"):
                            file_id = doc.get("file_id", "")
                            ext = {"image/png": ".png", "image/jpeg": ".jpg",
                                   "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".jpg")
                            if file_id:
                                local_path = await self.download_file(file_id, ext)
                                if local_path:
                                    messages.append({
                                        "text": caption or "",
                                        "chat_id": msg_chat_id,
                                        "from": from_name,
                                        "image_path": str(local_path),
                                    })
                                    continue

                    # Plain text messages
                    if text and msg_chat_id:
                        messages.append({
                            "text": text,
                            "chat_id": msg_chat_id,
                            "from": from_name,
                        })
                    # Handle callback queries (inline button presses)
                    callback = update.get("callback_query", {})
                    if callback:
                        cb_data = callback.get("data", "")
                        cb_chat = str(callback.get("message", {}).get("chat", {}).get("id", ""))
                        # Silently ignore callbacks from non-allowed chat IDs
                        if self.allowlist and not self.allowlist.is_allowed(cb_chat):
                            # Still answer the callback to remove the loading spinner
                            cb_id = callback.get("id")
                            if cb_id:
                                try:
                                    await client.post(
                                        f"{self.base_url}/answerCallbackQuery",
                                        json={"callback_query_id": cb_id},
                                    )
                                except Exception:
                                    pass
                            continue
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

