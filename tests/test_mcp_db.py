"""Tests for mcp_calls DB table."""
import pytest
import aiosqlite
from backend.database import Database


@pytest.mark.asyncio
async def test_mcp_calls_table_exists():
    db = Database(":memory:")
    await db.init()
    cursor = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_calls'"
    )
    row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_log_mcp_call():
    db = Database(":memory:")
    await db.init()
    await db.log_mcp_call(
        server_id="apple-mcp", tool_name="create_reminder",
        args='{"title": "Test"}', result='{"ok": true}',
        success=True, duration_ms=120, triggered_by="direct",
    )
    cursor = await db._conn.execute("SELECT * FROM mcp_calls")
    rows = await cursor.fetchall()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_mcp_calls():
    db = Database(":memory:")
    await db.init()
    await db.log_mcp_call("s1", "tool_a", "{}", "{}", True, 100, "direct")
    await db.log_mcp_call("s2", "tool_b", "{}", "{}", False, 200, "crew:ops")
    calls = await db.get_mcp_calls(limit=10)
    assert len(calls) == 2
    assert calls[0]["server_id"] == "s2"  # most recent first
