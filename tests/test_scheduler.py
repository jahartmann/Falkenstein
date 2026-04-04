import datetime
import pytest
from pathlib import Path

from backend.scheduler import parse_schedule, next_run


def test_parse_taeglich():
    s = parse_schedule("täglich 07:00")
    assert s["type"] == "daily"
    assert s["hour"] == 7
    assert s["minute"] == 0


def test_parse_stuendlich():
    s = parse_schedule("stündlich")
    assert s["type"] == "hourly"


def test_parse_alle_minuten():
    s = parse_schedule("alle 30 Minuten")
    assert s["type"] == "interval_minutes"
    assert s["minutes"] == 30


def test_parse_alle_stunden():
    s = parse_schedule("alle 6 Stunden")
    assert s["type"] == "interval_hours"
    assert s["hours"] == 6


def test_parse_wochentags():
    s = parse_schedule("Mo-Fr 09:00")
    assert s["type"] == "weekdays"
    assert s["hour"] == 9


def test_parse_wochentag():
    s = parse_schedule("montags 08:00")
    assert s["type"] == "weekly"
    assert s["weekday"] == 0  # Monday
    assert s["hour"] == 8


def test_parse_cron():
    s = parse_schedule("cron: 0 7 * * 1-5")
    assert s["type"] == "cron"
    assert s["expr"] == "0 7 * * 1-5"


def test_next_run_daily():
    # If it's 06:00 and task is "täglich 07:00" -> next run today at 07:00
    after = datetime.datetime(2026, 4, 4, 6, 0)
    schedule = parse_schedule("täglich 07:00")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 7, 0)


def test_next_run_daily_past():
    # If it's 08:00 and task is "täglich 07:00" -> next run tomorrow at 07:00
    after = datetime.datetime(2026, 4, 4, 8, 0)
    schedule = parse_schedule("täglich 07:00")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 5, 7, 0)


def test_next_run_hourly():
    after = datetime.datetime(2026, 4, 4, 8, 15)
    schedule = parse_schedule("stündlich")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 9, 0)


def test_next_run_interval_minutes():
    after = datetime.datetime(2026, 4, 4, 8, 0)
    schedule = parse_schedule("alle 30 Minuten")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 8, 30)


def test_next_run_weekdays_on_weekday():
    # Friday 2026-04-03 at 10:00, task is Mo-Fr 09:00 -> already past today, next is Monday
    after = datetime.datetime(2026, 4, 4, 10, 0)  # Saturday
    schedule = parse_schedule("Mo-Fr 09:00")
    nxt = next_run(schedule, after)
    assert nxt.weekday() == 0  # Monday
    assert nxt.hour == 9


def test_next_run_weekly():
    after = datetime.datetime(2026, 4, 4, 10, 0)  # Friday
    schedule = parse_schedule("montags 08:00")
    nxt = next_run(schedule, after)
    assert nxt.weekday() == 0
    assert nxt.hour == 8


# Task 2: Scheduler engine tests

from backend.scheduler import ScheduledTask, Scheduler


@pytest.fixture
def tmp_schedules(tmp_path):
    """Create a Schedules directory with test task files."""
    sched_dir = tmp_path / "KI-Büro" / "Schedules"
    sched_dir.mkdir(parents=True)
    (sched_dir / "test-task.md").write_text(
        "---\n"
        "name: Test Task\n"
        "schedule: täglich 07:00\n"
        "agent: researcher\n"
        "active: true\n"
        "active_hours: 06:00-22:00\n"
        "light_context: true\n"
        "---\n\n"
        "# Test Task\n\n"
        "Recherchiere aktuelle Nachrichten.\n"
    )
    (sched_dir / "inactive.md").write_text(
        "---\n"
        "name: Inactive Task\n"
        "schedule: stündlich\n"
        "active: false\n"
        "---\n\n"
        "Inaktiver Task.\n"
    )
    return tmp_path


def test_load_task_from_file(tmp_schedules):
    sched_dir = tmp_schedules / "KI-Büro" / "Schedules"
    task = ScheduledTask.from_file(sched_dir / "test-task.md")
    assert task.name == "Test Task"
    assert task.agent == "researcher"
    assert task.active is True
    assert task.light_context is True
    assert "Recherchiere" in task.prompt
    assert task.active_hours == (6, 0, 22, 0)


def test_load_inactive_task(tmp_schedules):
    sched_dir = tmp_schedules / "KI-Büro" / "Schedules"
    task = ScheduledTask.from_file(sched_dir / "inactive.md")
    assert task.active is False


def test_scheduler_loads_all_tasks(tmp_schedules):
    scheduler = Scheduler(vault_path=tmp_schedules)
    scheduler.load_tasks()
    # heartbeat.md is always created by load_tasks, so 3 tasks total
    assert len(scheduler.tasks) == 3
    # template _vorlage.md must NOT be loaded
    assert "_vorlage.md" not in scheduler.tasks


def test_scheduler_due_tasks():
    task = ScheduledTask(
        name="Due Task", schedule_str="alle 30 Minuten", agent="ops",
        active=True, prompt="test", file_path=Path("/fake.md"),
    )
    task._parsed = parse_schedule(task.schedule_str)
    # Set last_run to 31 minutes ago
    task.last_run = datetime.datetime.now() - datetime.timedelta(minutes=31)
    task._next_run = next_run(task._parsed, task.last_run)
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.tasks = {"due-task.md": task}
    scheduler._last_run_path = Path("/tmp/.last_run.json")
    due = scheduler.get_due_tasks()
    assert len(due) == 1


def test_scheduler_respects_active_hours():
    task = ScheduledTask(
        name="Night Task", schedule_str="alle 30 Minuten", agent="ops",
        active=True, prompt="test", file_path=Path("/fake.md"),
        active_hours=(8, 0, 20, 0),
    )
    task._parsed = parse_schedule(task.schedule_str)
    task.last_run = datetime.datetime(2026, 4, 4, 3, 0)  # 3 AM
    task._next_run = next_run(task._parsed, task.last_run)
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.tasks = {"night.md": task}
    scheduler._last_run_path = Path("/tmp/.last_run.json")
    # At 4 AM, outside active hours (8-20) -> not due
    due = scheduler.get_due_tasks(now=datetime.datetime(2026, 4, 4, 4, 0))
    assert len(due) == 0


def test_last_run_persistence(tmp_path):
    lr_path = tmp_path / ".last_run.json"
    from backend.scheduler import _save_last_runs, _load_last_runs
    runs = {"test.md": "2026-04-04T07:00:00"}
    _save_last_runs(lr_path, runs)
    loaded = _load_last_runs(lr_path)
    assert loaded["test.md"] == "2026-04-04T07:00:00"
