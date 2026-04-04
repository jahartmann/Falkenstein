"""Tests for task dependency system."""
import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path

from backend.database import Database
from backend.models import TaskData, TaskStatus


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_create_task_with_depends_on(db):
    t1 = await db.create_task(TaskData(title="Step 1", description="First"))
    t2 = await db.create_task(TaskData(title="Step 2", description="Second", depends_on=[t1]))
    task = await db.get_task(t2)
    assert task.depends_on == [t1]


@pytest.mark.asyncio
async def test_create_task_no_deps(db):
    t1 = await db.create_task(TaskData(title="Solo", description="No deps"))
    task = await db.get_task(t1)
    assert task.depends_on == []


@pytest.mark.asyncio
async def test_dependencies_met_all_done(db):
    t1 = await db.create_task(TaskData(title="A", description="a"))
    t2 = await db.create_task(TaskData(title="B", description="b"))
    t3 = await db.create_task(TaskData(title="C", description="c", depends_on=[t1, t2]))

    task3 = await db.get_task(t3)
    assert not await db.dependencies_met(task3)

    await db.update_task_status(t1, TaskStatus.DONE)
    assert not await db.dependencies_met(task3)

    await db.update_task_status(t2, TaskStatus.DONE)
    assert await db.dependencies_met(task3)


@pytest.mark.asyncio
async def test_dependencies_met_empty(db):
    t1 = await db.create_task(TaskData(title="No deps", description="x"))
    task = await db.get_task(t1)
    assert await db.dependencies_met(task)


@pytest.mark.asyncio
async def test_get_blocked_tasks(db):
    t1 = await db.create_task(TaskData(title="A", description="a"))
    t2 = await db.create_task(TaskData(title="B", description="b", depends_on=[t1]))
    t3 = await db.create_task(TaskData(title="C", description="c"))

    blocked = await db.get_blocked_tasks()
    assert len(blocked) == 1
    assert blocked[0].id == t2


@pytest.mark.asyncio
async def test_get_dependency_results(db):
    t1 = await db.create_task(TaskData(title="Research", description="Do research"))
    await db.update_task_result(t1, "Found interesting data about X")
    t2 = await db.create_task(TaskData(title="Write Report", description="Write it", depends_on=[t1]))

    task2 = await db.get_task(t2)
    context = await db.get_dependency_results(task2)
    assert "Research" in context
    assert "Found interesting data" in context


@pytest.mark.asyncio
async def test_dependency_chain(db):
    """Test a chain: A → B → C. C should only unblock when B is done."""
    t_a = await db.create_task(TaskData(title="A", description="first"))
    t_b = await db.create_task(TaskData(title="B", description="second", depends_on=[t_a]))
    t_c = await db.create_task(TaskData(title="C", description="third", depends_on=[t_b]))

    task_c = await db.get_task(t_c)
    assert not await db.dependencies_met(task_c)

    await db.update_task_status(t_a, TaskStatus.DONE)
    assert not await db.dependencies_met(task_c)  # B still open

    await db.update_task_status(t_b, TaskStatus.DONE)
    assert await db.dependencies_met(task_c)


@pytest.mark.asyncio
async def test_migration_adds_depends_on(tmp_path):
    """Simulate an old DB without depends_on column and verify migration."""
    db_path = tmp_path / "old.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                assigned_to TEXT,
                project TEXT,
                parent_task_id INTEGER,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO tasks (title, description) VALUES ('Old task', 'from before');
        """)
        await conn.commit()
    # Now open with new Database which runs migration
    db = Database(db_path)
    await db.init()
    task = await db.get_task(1)
    assert task is not None
    assert task.depends_on == []
    await db.close()
