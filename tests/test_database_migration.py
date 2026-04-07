"""Tests for crews table, knowledge_log table, and new DB methods."""
from __future__ import annotations

import pytest
import pytest_asyncio
from pathlib import Path

from backend.database import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_crews_table_exists(db: Database):
    tables = await db.get_tables()
    assert "crews" in tables


@pytest.mark.asyncio
async def test_knowledge_log_table_exists(db: Database):
    tables = await db.get_tables()
    assert "knowledge_log" in tables


@pytest.mark.asyncio
async def test_create_crew(db: Database):
    crew_id = await db.create_crew(
        crew_type="researcher",
        trigger_source="telegram",
        chat_id="12345",
        task_description="Research AI trends",
    )
    assert crew_id is not None
    assert len(crew_id) == 8


@pytest.mark.asyncio
async def test_get_crew(db: Database):
    crew_id = await db.create_crew(
        crew_type="coder",
        trigger_source="api",
        chat_id=None,
        task_description="Build feature X",
    )
    crew = await db.get_crew(crew_id)
    assert crew is not None
    assert crew["id"] == crew_id
    assert crew["crew_type"] == "coder"
    assert crew["trigger_source"] == "api"
    assert crew["chat_id"] is None
    assert crew["task_description"] == "Build feature X"
    assert crew["status"] == "active"
    assert crew["token_count"] == 0


@pytest.mark.asyncio
async def test_get_crew_not_found(db: Database):
    result = await db.get_crew("nonexist")
    assert result is None


@pytest.mark.asyncio
async def test_update_crew_status(db: Database):
    crew_id = await db.create_crew(
        crew_type="writer",
        trigger_source="schedule",
        chat_id="99",
        task_description="Write report",
    )
    await db.update_crew(crew_id, status="done", token_count=1500)
    crew = await db.get_crew(crew_id)
    assert crew["status"] == "done"
    assert crew["token_count"] == 1500


@pytest.mark.asyncio
async def test_update_crew_result_path(db: Database):
    crew_id = await db.create_crew(
        crew_type="ops",
        trigger_source="telegram",
        chat_id="42",
        task_description="Deploy service",
    )
    await db.update_crew(crew_id, result_path="Reports/deploy_result.md")
    crew = await db.get_crew(crew_id)
    assert crew["result_path"] == "Reports/deploy_result.md"


@pytest.mark.asyncio
async def test_update_crew_ignores_unknown_fields(db: Database):
    crew_id = await db.create_crew(
        crew_type="coder",
        trigger_source="api",
        chat_id=None,
        task_description="Task",
    )
    # Should not raise even with unknown field
    await db.update_crew(crew_id, unknown_field="bad")
    crew = await db.get_crew(crew_id)
    assert crew is not None


@pytest.mark.asyncio
async def test_log_crew_tool(db: Database):
    crew_id = await db.create_crew(
        crew_type="coder",
        trigger_source="api",
        chat_id=None,
        task_description="Task",
    )
    # Should not raise
    await db.log_crew_tool(
        crew_id=crew_id,
        agent_name="coder_agent",
        tool_name="write_file",
        tool_input={"path": "foo.py", "content": "print('hi')"},
        tool_output="ok",
        duration_ms=123,
    )
    # Verify it landed in tool_log
    cursor = await db._conn.execute(
        "SELECT * FROM tool_log WHERE crew_id = ?", (crew_id,)
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["tool_name"] == "write_file"
    assert row["agent_name"] == "coder_agent"
    assert row["duration_ms"] == 123


@pytest.mark.asyncio
async def test_log_knowledge(db: Database):
    crew_id = await db.create_crew(
        crew_type="researcher",
        trigger_source="telegram",
        chat_id="1",
        task_description="Research",
    )
    await db.log_knowledge(
        crew_id=crew_id,
        vault_path="Recherchen/AI_Trends.md",
        knowledge_type="research",
        topic="AI Trends 2026",
    )
    cursor = await db._conn.execute(
        "SELECT * FROM knowledge_log WHERE crew_id = ?", (crew_id,)
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["vault_path"] == "Recherchen/AI_Trends.md"
    assert row["knowledge_type"] == "research"
    assert row["topic"] == "AI Trends 2026"


@pytest.mark.asyncio
async def test_get_active_crews(db: Database):
    id1 = await db.create_crew("coder", "api", None, "Task A")
    id2 = await db.create_crew("writer", "telegram", "1", "Task B")
    id3 = await db.create_crew("ops", "schedule", "2", "Task C")

    # Mark one as done
    await db.update_crew(id2, status="done")

    active = await db.get_active_crews()
    active_ids = [c["id"] for c in active]
    assert id1 in active_ids
    assert id3 in active_ids
    assert id2 not in active_ids


@pytest.mark.asyncio
async def test_tool_log_migration_columns(db: Database):
    """tool_log must have crew_id, agent_name, duration_ms columns after migration."""
    cursor = await db._conn.execute("PRAGMA table_info(tool_log)")
    rows = await cursor.fetchall()
    col_names = {dict(r)["name"] for r in rows}
    assert "crew_id" in col_names
    assert "agent_name" in col_names
    assert "duration_ms" in col_names
