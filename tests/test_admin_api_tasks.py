import pytest
from unittest.mock import AsyncMock
from backend.models import TaskData, TaskStatus


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_all_tasks = AsyncMock(return_value=[
        TaskData(id=1, title="T1", description="d", status=TaskStatus.DONE, assigned_to="researcher", result="result text"),
    ])
    db.get_task_count = AsyncMock(return_value=1)
    db.get_task = AsyncMock(return_value=TaskData(id=1, title="T1", description="d", status=TaskStatus.DONE, result="full result"))
    db.delete_task = AsyncMock(return_value=True)
    db.update_task_status_manual = AsyncMock(return_value=True)
    return db


@pytest.mark.asyncio
async def test_get_tasks_filtered(mock_db):
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.get_tasks(status="done", agent="researcher", search="T1", limit=50, offset=0)
    mock_db.get_all_tasks.assert_called_once_with(limit=50, offset=0, status="done", agent="researcher", search="T1")
    assert result["total"] == 1
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["result"] == "result text"


@pytest.mark.asyncio
async def test_get_single_task(mock_db):
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.get_single_task(1)
    assert result["title"] == "T1"
    assert result["result"] == "full result"


@pytest.mark.asyncio
async def test_patch_task_status(mock_db):
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.patch_task(1, admin_api.TaskPatch(status="done"))
    mock_db.update_task_status_manual.assert_called_once()
    assert result["updated"] is True


@pytest.mark.asyncio
async def test_delete_task_endpoint(mock_db):
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.delete_task(1)
    mock_db.delete_task.assert_called_once_with(1)
    assert result["deleted"] is True
