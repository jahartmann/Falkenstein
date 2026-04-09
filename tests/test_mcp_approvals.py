import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.mcp.approvals import ApprovalStore, PendingApproval


class _FakeDb:
    def __init__(self):
        self._conn = self
        self.rows = []
        self.committed = False
    async def execute(self, sql, params=None):
        self.rows.append((sql, params))
    async def commit(self):
        self.committed = True


def _make_store():
    tg = MagicMock()
    tg.enabled = True
    tg.send_approval_request = AsyncMock()
    ws = MagicMock()
    ws.broadcast = AsyncMock()
    db = _FakeDb()
    return ApprovalStore(tg, ws, db, timeout_seconds=1), tg, ws, db


@pytest.mark.asyncio
async def test_request_and_resolve_allow():
    store, tg, ws, db = _make_store()
    async def resolver():
        await asyncio.sleep(0.05)
        pending = list(store._pending.values())[0]
        store.resolve(pending.id, "allow", "telegram")
    asyncio.create_task(resolver())
    result = await store.request("apple-mcp", "send_message", {"to": "x"})
    assert result == "allow"
    tg.send_approval_request.assert_awaited_once()
    ws.broadcast.assert_awaited()


@pytest.mark.asyncio
async def test_request_timeout():
    store, tg, ws, db = _make_store()
    store._timeout_seconds = 0.1
    result = await store.request("srv", "tool", {})
    assert result == "timeout"


@pytest.mark.asyncio
async def test_first_resolve_wins():
    store, *_ = _make_store()
    async def req():
        return await store.request("srv", "tool", {})
    task = asyncio.create_task(req())
    await asyncio.sleep(0.02)
    pending = list(store._pending.values())[0]
    r1 = store.resolve(pending.id, "allow", "telegram")
    r2 = store.resolve(pending.id, "deny", "ws")
    assert r1 is True
    assert r2 is False
    result = await task
    assert result == "allow"


@pytest.mark.asyncio
async def test_dedup_within_window():
    store, *_ = _make_store()
    store._dedup_window_seconds = 30
    async def first():
        return await store.request("srv", "tool", {"k": 1})
    t1 = asyncio.create_task(first())
    await asyncio.sleep(0.02)
    pending = list(store._pending.values())[0]
    store.resolve(pending.id, "allow", "telegram")
    r1 = await t1
    # identical request within dedup window should auto-allow
    r2 = await store.request("srv", "tool", {"k": 1})
    assert r1 == "allow"
    assert r2 == "allow"


@pytest.mark.asyncio
async def test_list_pending():
    store, *_ = _make_store()
    task = asyncio.create_task(store.request("srv", "t", {}))
    await asyncio.sleep(0.02)
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].server_id == "srv"
    # cleanup
    store.resolve(pending[0].id, "deny", "test")
    await task
