import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
from backend.database import Database

@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()

@pytest.mark.asyncio
async def test_memories_table_exists(db):
    cursor = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
    )
    row = await cursor.fetchone()
    assert row is not None

@pytest.mark.asyncio
async def test_memories_insert_and_query(db):
    await db._conn.execute(
        "INSERT INTO memories (layer, category, key, value, confidence, source, created_at, updated_at) "
        "VALUES ('user', 'preferences', 'tone', 'kurz und direkt', 0.9, 'conversation', datetime('now'), datetime('now'))"
    )
    await db._conn.commit()
    cursor = await db._conn.execute("SELECT * FROM memories WHERE layer='user'")
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["key"] == "tone"

@pytest.mark.asyncio
async def test_activity_log_table_exists(db):
    cursor = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_log'"
    )
    assert (await cursor.fetchone()) is not None

@pytest.mark.asyncio
async def test_reminders_table_exists(db):
    cursor = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'"
    )
    assert (await cursor.fetchone()) is not None

@pytest.mark.asyncio
async def test_planned_tasks_and_steps_tables_exist(db):
    for table in ["planned_tasks", "task_steps"]:
        cursor = await db._conn.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
        )
        assert (await cursor.fetchone()) is not None, f"{table} missing"
