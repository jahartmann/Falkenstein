import pytest
import datetime
from unittest.mock import AsyncMock
from backend.scheduler import Scheduler, parse_schedule, next_run


@pytest.mark.asyncio
async def test_reload_preserves_next_run():
    """reload_tasks should preserve _next_run for unchanged schedules."""
    db = AsyncMock()
    sched = Scheduler(db)
    db.get_all_schedules.return_value = [
        {"id": 1, "name": "Test", "schedule": "täglich 09:00", "agent_type": "ops",
         "prompt": "do stuff", "active": 1, "active_hours": None, "light_context": 0,
         "last_run": None, "last_status": None, "last_error": None}
    ]
    await sched.load_tasks()
    original_next_run = sched.tasks[0]["_next_run"]
    await sched.reload_tasks()
    assert sched.tasks[0]["_next_run"] == original_next_run


@pytest.mark.asyncio
async def test_cron_syntax_sets_error():
    """cron: prefix should skip schedule and set error."""
    db = AsyncMock()
    sched = Scheduler(db)
    db.get_all_schedules.return_value = [
        {"id": 1, "name": "Cron", "schedule": "cron: 0 9 * * 1-5", "agent_type": "ops",
         "prompt": "do stuff", "active": 1, "active_hours": None, "light_context": 0,
         "last_run": None, "last_status": None, "last_error": None}
    ]
    await sched.load_tasks()
    db.update_schedule_result.assert_called_once()
    call_args = db.update_schedule_result.call_args
    assert call_args[0][1] == "error"
    assert "cron" in call_args[0][2].lower() or "nicht unterstützt" in call_args[0][2].lower()
    # Cron schedule should NOT be in tasks
    assert len(sched.tasks) == 0


def test_get_next_runs():
    """get_next_runs should return N future run times."""
    from backend.scheduler import get_next_runs
    sched_dict = parse_schedule("täglich 09:00")
    now = datetime.datetime(2026, 4, 4, 10, 0)
    runs = get_next_runs(sched_dict, count=3, after=now)
    assert len(runs) == 3
    assert runs[0] == datetime.datetime(2026, 4, 5, 9, 0)
    assert runs[1] == datetime.datetime(2026, 4, 6, 9, 0)
    assert runs[2] == datetime.datetime(2026, 4, 7, 9, 0)


def test_tasks_info_includes_full_prompt():
    """get_all_tasks_info should include full prompt, not just preview."""
    sched = Scheduler.__new__(Scheduler)
    sched.tasks = [
        {"id": 1, "name": "T", "schedule": "stündlich", "agent_type": "ops",
         "prompt": "A" * 500, "active": 1, "active_hours": None,
         "_next_run": datetime.datetime.now(), "_last_run": None,
         "last_status": None, "last_error": None}
    ]
    info = sched.get_all_tasks_info()
    assert len(info[0]["prompt"]) == 500
