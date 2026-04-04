import pytest
import pytest_asyncio
from backend.database import Database
from backend.models import TaskData, TaskStatus


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_get_all_tasks_no_filter(db):
    for i in range(5):
        await db.create_task(TaskData(title=f"Task {i}", description="desc", status=TaskStatus.OPEN))
    result = await db.get_all_tasks(limit=50, offset=0)
    assert len(result) == 5
    assert result[0].title == "Task 4"


@pytest.mark.asyncio
async def test_get_all_tasks_filter_status(db):
    await db.create_task(TaskData(title="open1", description="d", status=TaskStatus.OPEN))
    t2 = await db.create_task(TaskData(title="done1", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t2, TaskStatus.DONE)
    result = await db.get_all_tasks(status="done")
    assert len(result) == 1
    assert result[0].title == "done1"


@pytest.mark.asyncio
async def test_get_all_tasks_filter_agent(db):
    t1 = await db.create_task(TaskData(title="t1", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t1, TaskStatus.IN_PROGRESS, "researcher")
    t2 = await db.create_task(TaskData(title="t2", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t2, TaskStatus.IN_PROGRESS, "coder")
    result = await db.get_all_tasks(agent="researcher")
    assert len(result) == 1
    assert result[0].title == "t1"


@pytest.mark.asyncio
async def test_get_all_tasks_search(db):
    await db.create_task(TaskData(title="News recherche", description="daily news", status=TaskStatus.OPEN))
    await db.create_task(TaskData(title="Backup DB", description="run backup", status=TaskStatus.OPEN))
    result = await db.get_all_tasks(search="news")
    assert len(result) == 1
    assert result[0].title == "News recherche"


@pytest.mark.asyncio
async def test_get_all_tasks_pagination(db):
    for i in range(10):
        await db.create_task(TaskData(title=f"Task {i}", description="d", status=TaskStatus.OPEN))
    page1 = await db.get_all_tasks(limit=3, offset=0)
    page2 = await db.get_all_tasks(limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 3
    assert page1[0].id != page2[0].id


@pytest.mark.asyncio
async def test_get_task_count(db):
    await db.create_task(TaskData(title="t1", description="d", status=TaskStatus.OPEN))
    t2 = await db.create_task(TaskData(title="t2", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t2, TaskStatus.DONE)
    assert await db.get_task_count() == 2
    assert await db.get_task_count(status="open") == 1


@pytest.mark.asyncio
async def test_delete_task(db):
    tid = await db.create_task(TaskData(title="del me", description="d", status=TaskStatus.OPEN))
    assert await db.delete_task(tid) is True
    assert await db.get_task(tid) is None
    assert await db.delete_task(999) is False


@pytest.mark.asyncio
async def test_update_task_status_manual(db):
    tid = await db.create_task(TaskData(title="t", description="d", status=TaskStatus.OPEN))
    assert await db.update_task_status_manual(tid, TaskStatus.DONE) is True
    task = await db.get_task(tid)
    assert task.status == TaskStatus.DONE
