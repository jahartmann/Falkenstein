"""MCP tool-call approval store — pending approvals, Telegram + WS notification."""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    id: str
    server_id: str
    tool_name: str
    args: dict
    crew_id: str | None
    chat_id: str | None
    created_at: float
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: str | None = None
    decided_by: str | None = None


class ApprovalStore:
    def __init__(self, telegram_bot, ws_manager, db,
                 timeout_seconds: int = 600,
                 dedup_window_seconds: int = 30) -> None:
        self._telegram = telegram_bot
        self._ws = ws_manager
        self._db = db
        self._timeout_seconds = timeout_seconds
        self._dedup_window_seconds = dedup_window_seconds
        self._pending: dict[str, PendingApproval] = {}
        self._recent: dict[tuple, tuple[float, str]] = {}

    def _dedup_key(self, server_id: str, tool_name: str, args: dict) -> tuple:
        return (server_id, tool_name, json.dumps(args, sort_keys=True, default=str))

    async def request(
        self, server_id: str, tool_name: str, args: dict,
        crew_id: str | None = None, chat_id: str | None = None,
    ) -> str:
        """Register a pending approval, notify channels, block until resolved.
        Returns 'allow' | 'deny' | 'timeout'."""
        key = self._dedup_key(server_id, tool_name, args)
        now = time.time()
        cached = self._recent.get(key)
        if cached and (now - cached[0]) < self._dedup_window_seconds:
            log.info("approval dedup hit: %s/%s → %s", server_id, tool_name, cached[1])
            return cached[1]

        approval = PendingApproval(
            id=str(uuid.uuid4()),
            server_id=server_id, tool_name=tool_name, args=dict(args),
            crew_id=crew_id, chat_id=chat_id, created_at=now,
        )
        self._pending[approval.id] = approval

        # Persist request
        try:
            await self._db._conn.execute(
                """INSERT INTO mcp_approvals (id, server_id, tool_name, args_json,
                                              requested_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (approval.id, server_id, tool_name,
                 json.dumps(args, default=str),
                 datetime.now(timezone.utc).isoformat()),
            )
            await self._db._conn.commit()
        except Exception as e:
            log.warning("approval DB insert failed: %s", e)

        # Notify channels
        try:
            if self._telegram and getattr(self._telegram, "enabled", True):
                await self._telegram.send_approval_request(approval)
        except Exception as e:
            log.warning("telegram approval notify failed: %s", e)
        try:
            if self._ws:
                await self._ws.broadcast({
                    "type": "approval_pending",
                    "id": approval.id,
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "args": args,
                    "created_at": approval.created_at,
                })
        except Exception as e:
            log.warning("ws approval broadcast failed: %s", e)

        # Block until resolved or timeout
        try:
            await asyncio.wait_for(approval.event.wait(),
                                   timeout=self._timeout_seconds)
            result = approval.result or "deny"
        except asyncio.TimeoutError:
            result = "timeout"
            approval.result = "timeout"
            approval.decided_by = "auto"

        # Persist resolution
        try:
            await self._db._conn.execute(
                """UPDATE mcp_approvals
                   SET decision=?, decided_by=?, decided_at=?
                   WHERE id=?""",
                (result, approval.decided_by or "auto",
                 datetime.now(timezone.utc).isoformat(), approval.id),
            )
            await self._db._conn.commit()
        except Exception as e:
            log.warning("approval DB update failed: %s", e)

        # Broadcast resolution
        try:
            if self._ws:
                await self._ws.broadcast({
                    "type": "approval_resolved",
                    "id": approval.id,
                    "decision": result,
                })
        except Exception:
            pass

        # Cache for dedup
        self._recent[key] = (now, result)
        self._pending.pop(approval.id, None)

        # GC old dedup entries
        cutoff = now - self._dedup_window_seconds * 2
        self._recent = {k: v for k, v in self._recent.items() if v[0] > cutoff}

        return result

    def resolve(self, approval_id: str, decision: str, decided_by: str) -> bool:
        """Resolve a pending approval. First resolve wins. Returns True if
        this call actually resolved it, False if it was already resolved."""
        approval = self._pending.get(approval_id)
        if approval is None or approval.result is not None:
            return False
        if decision not in ("allow", "deny", "allow_once"):
            return False
        effective = "allow" if decision == "allow_once" else decision
        approval.result = effective
        approval.decided_by = decided_by
        approval.event.set()
        return True

    def list_pending(self) -> list[PendingApproval]:
        return list(self._pending.values())
