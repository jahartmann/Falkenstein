"""Tests for schedules + config tables in Database."""

import pytest
import pytest_asyncio

from backend.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


# ------------------------------------------------------------------
# Schedules
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_schedule(db):
    sid = await db.create_schedule(
        name="daily-news",
        schedule="0 8 * * *",
        agent_type="researcher",
        prompt="Finde die neuesten Nachrichten",
    )
    assert isinstance(sid, int)
    assert sid > 0


@pytest.mark.asyncio
async def test_list_schedules(db):
    await db.create_schedule(name="s1", schedule="* * * * *", agent_type="researcher", prompt="p1")
    await db.create_schedule(name="s2", schedule="* * * * *", agent_type="writer", prompt="p2", active=0)

    all_schedules = await db.get_all_schedules()
    assert len(all_schedules) == 2

    active = await db.get_active_schedules()
    assert len(active) == 1
    assert active[0]["name"] == "s1"


@pytest.mark.asyncio
async def test_update_schedule(db):
    sid = await db.create_schedule(name="s1", schedule="0 8 * * *", agent_type="researcher", prompt="p1")
    await db.update_schedule(sid, prompt="new prompt", agent_type="writer")

    s = await db.get_schedule(sid)
    assert s["prompt"] == "new prompt"
    assert s["agent_type"] == "writer"


@pytest.mark.asyncio
async def test_delete_schedule(db):
    sid = await db.create_schedule(name="s1", schedule="* * * * *", agent_type="researcher", prompt="p1")
    await db.delete_schedule(sid)
    assert await db.get_schedule(sid) is None


@pytest.mark.asyncio
async def test_toggle_schedule(db):
    sid = await db.create_schedule(name="s1", schedule="* * * * *", agent_type="researcher", prompt="p1")

    # starts active (1), toggle -> inactive
    new_state = await db.toggle_schedule(sid)
    assert new_state is False
    s = await db.get_schedule(sid)
    assert s["active"] == 0

    # toggle back -> active
    new_state = await db.toggle_schedule(sid)
    assert new_state is True
    s = await db.get_schedule(sid)
    assert s["active"] == 1


@pytest.mark.asyncio
async def test_mark_schedule_run(db):
    sid = await db.create_schedule(name="s1", schedule="* * * * *", agent_type="researcher", prompt="p1")
    await db.mark_schedule_run(sid)

    s = await db.get_schedule(sid)
    assert s["last_run"] is not None


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_and_get_config(db):
    await db.set_config("api_key", "abc123", category="secrets", description="API key")
    val = await db.get_config("api_key")
    assert val == "abc123"


@pytest.mark.asyncio
async def test_get_config_default(db):
    val = await db.get_config("nonexistent", default="fallback")
    assert val == "fallback"

    val2 = await db.get_config("nonexistent")
    assert val2 is None


@pytest.mark.asyncio
async def test_get_config_by_category(db):
    await db.set_config("k1", "v1", category="llm")
    await db.set_config("k2", "v2", category="llm")
    await db.set_config("k3", "v3", category="general")

    llm = await db.get_config_by_category("llm")
    assert len(llm) == 2
    keys = {c["key"] for c in llm}
    assert keys == {"k1", "k2"}


@pytest.mark.asyncio
async def test_get_all_config(db):
    await db.set_config("a", "1", category="x")
    await db.set_config("b", "2", category="y")

    all_cfg = await db.get_all_config()
    assert len(all_cfg) == 2


@pytest.mark.asyncio
async def test_set_config_upsert(db):
    await db.set_config("key", "old", category="general")
    await db.set_config("key", "new", category="general")

    val = await db.get_config("key")
    assert val == "new"

    # should still be only one row
    all_cfg = await db.get_all_config()
    assert len(all_cfg) == 1


# ------------------------------------------------------------------
# MCP tables
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_tables_exist_after_init(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.init()
    async with db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('mcp_servers', 'mcp_tool_permissions', 'mcp_approvals')"
    ) as cur:
        rows = await cur.fetchall()
    names = {r[0] for r in rows}
    assert names == {"mcp_servers", "mcp_tool_permissions", "mcp_approvals"}
    await db.close()

@pytest.mark.asyncio
async def test_mcp_servers_columns(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.init()
    async with db._conn.execute("PRAGMA table_info(mcp_servers)") as cur:
        rows = await cur.fetchall()
    cols = {r[1] for r in rows}
    assert {"id", "installed", "enabled", "config_json", "last_error",
            "installed_at", "updated_at"} <= cols
    await db.close()
