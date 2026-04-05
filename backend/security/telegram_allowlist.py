"""Allowlist for Telegram chat IDs — only permitted users can interact with the bot."""
from __future__ import annotations


class TelegramAllowlist:
    """Manages which Telegram chat IDs are allowed to interact with the bot.

    The owner is always allowed and cannot be removed.
    Additional IDs can be added/removed at runtime.
    """

    def __init__(self, owner_chat_id: str, allowed_ids_csv: str = ""):
        self._owner = str(owner_chat_id).strip()
        # Parse CSV, filter empties, exclude owner (added separately)
        extra = [
            str(cid).strip()
            for cid in allowed_ids_csv.split(",")
            if cid.strip() and str(cid).strip() != self._owner
        ]
        # Use ordered set via dict keys to preserve insertion order
        self._allowed: dict[str, None] = {cid: None for cid in extra}

    # ── Queries ──────────────────────────────────────────────────────────────

    def is_owner(self, chat_id: str) -> bool:
        """Return True if chat_id is the bot owner."""
        return str(chat_id).strip() == self._owner

    def is_allowed(self, chat_id: str) -> bool:
        """Return True if chat_id is permitted (owner is always permitted)."""
        cid = str(chat_id).strip()
        return cid == self._owner or cid in self._allowed

    def list_allowed(self) -> list[str]:
        """Return all permitted chat IDs (owner first, then extras)."""
        return [self._owner] + list(self._allowed.keys())

    def to_csv(self) -> str:
        """Serialize extra allowed IDs (not the owner) as a comma-separated string."""
        return ",".join(self._allowed.keys())

    # ── Mutations ─────────────────────────────────────────────────────────────

    def add(self, chat_id: str) -> None:
        """Add chat_id to the allowlist. No-op if already present or is owner."""
        cid = str(chat_id).strip()
        if cid and cid != self._owner:
            self._allowed[cid] = None

    def remove(self, chat_id: str) -> None:
        """Remove chat_id from the allowlist. Raises ValueError if chat_id is the owner."""
        cid = str(chat_id).strip()
        if cid == self._owner:
            raise ValueError("Cannot remove the owner from the allowlist.")
        self._allowed.pop(cid, None)
