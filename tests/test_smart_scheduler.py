import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from datetime import datetime
from backend.database import Database
from backend.smart_scheduler import SmartScheduler


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.fixture
def scheduler(db):
    return SmartScheduler(db)


@pytest.mark.asyncio
async def test_add_reminder(scheduler):
    rid = await scheduler.add_reminder(
        chat_id="test",
        text="Meeting vorbereiten",
        due_at="2026-04-05T09:00:00",
    )
    assert rid > 0


@pytest.mark.asyncio
async def test_get_due_reminders(scheduler):
    await scheduler.add_reminder(chat_id="test", text="Meeting", due_at="2026-04-04T08:00:00")
    await scheduler.add_reminder(chat_id="test", text="Spaeter", due_at="2026-04-06T08:00:00")
    due = await scheduler.get_due_reminders(now=datetime(2026, 4, 4, 9, 0))
    assert len(due) == 1
    assert due[0]["text"] == "Meeting"


@pytest.mark.asyncio
async def test_mark_reminder_delivered(scheduler):
    rid = await scheduler.add_reminder(chat_id="test", text="Test", due_at="2026-04-04T08:00:00")
    await scheduler.mark_reminder_delivered(rid)
    due = await scheduler.get_due_reminders(now=datetime(2026, 4, 4, 9, 0))
    assert len(due) == 0


@pytest.mark.asyncio
async def test_add_planned_task_with_steps(scheduler):
    ptid = await scheduler.add_planned_task(
        name="MLX Recherche + Summary",
        chat_id="test",
        steps=[
            {"agent_prompt": "Recherchiere MLX", "scheduled_at": "2026-04-04T20:00"},
            {"agent_prompt": "Fasse zusammen", "scheduled_at": "2026-04-05T07:30"},
        ],
    )
    assert ptid > 0
    steps = await scheduler.get_planned_task_steps(ptid)
    assert len(steps) == 2
    assert steps[0]["step_order"] == 1
    assert steps[1]["step_order"] == 2


@pytest.mark.asyncio
async def test_get_due_steps(scheduler):
    ptid = await scheduler.add_planned_task(
        name="Test Plan",
        chat_id="test",
        steps=[
            {"agent_prompt": "Step 1", "scheduled_at": "2026-04-04T08:00"},
            {"agent_prompt": "Step 2", "scheduled_at": "2026-04-05T08:00"},
        ],
    )
    due = await scheduler.get_due_steps(now=datetime(2026, 4, 4, 9, 0))
    assert len(due) == 1
    assert due[0]["agent_prompt"] == "Step 1"


@pytest.mark.asyncio
async def test_mark_step_completed(scheduler):
    ptid = await scheduler.add_planned_task(
        name="Test",
        chat_id="test",
        steps=[{"agent_prompt": "Step 1", "scheduled_at": "2026-04-04T08:00"}],
    )
    steps = await scheduler.get_planned_task_steps(ptid)
    await scheduler.mark_step_completed(steps[0]["id"], "Ergebnis hier")
    updated = await scheduler.get_planned_task_steps(ptid)
    assert updated[0]["status"] == "completed"
    assert updated[0]["result"] == "Ergebnis hier"
