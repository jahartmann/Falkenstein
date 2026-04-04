"""Tests for the DB-backed Scheduler."""
import asyncio
import datetime

import pytest
import pytest_asyncio

from backend.database import Database
from backend.scheduler import Scheduler, parse_schedule, next_run


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.init()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def scheduler(db):
    return Scheduler(db)


# ── load tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_empty(scheduler):
    await scheduler.load_tasks()
    assert scheduler.tasks == []


@pytest.mark.asyncio
async def test_load_with_schedules(db, scheduler):
    await db.create_schedule(
        name="Test Job",
        schedule="täglich 09:00",
        agent_type="researcher",
        prompt="Do stuff",
        active=1,
    )
    await scheduler.load_tasks()
    assert len(scheduler.tasks) == 1
    t = scheduler.tasks[0]
    assert t["name"] == "Test Job"
    assert t["_parsed"]["type"] == "daily"
    assert t["_next_run"] is not None


# ── due tasks ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_due_tasks(db, scheduler):
    await db.create_schedule(
        name="Due Job",
        schedule="alle 5 Minuten",
        agent_type="ops",
        prompt="check",
        active=1,
    )
    await scheduler.load_tasks()
    # Force _next_run into the past
    scheduler.tasks[0]["_next_run"] = datetime.datetime(2020, 1, 1)
    due = scheduler.get_due_tasks()
    assert len(due) == 1
    assert due[0]["name"] == "Due Job"


@pytest.mark.asyncio
async def test_inactive_schedules_not_due(db, scheduler):
    await db.create_schedule(
        name="Inactive",
        schedule="alle 5 Minuten",
        agent_type="ops",
        prompt="nope",
        active=0,
    )
    await scheduler.load_tasks()
    # Even with past _next_run, inactive should never be due
    for t in scheduler.tasks:
        t["_next_run"] = datetime.datetime(2020, 1, 1)
    due = scheduler.get_due_tasks()
    assert len(due) == 0


# ── mark_run ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_run_updates_db(db, scheduler):
    sid = await db.create_schedule(
        name="Run Me",
        schedule="alle 5 Minuten",
        agent_type="ops",
        prompt="go",
        active=1,
    )
    await scheduler.load_tasks()
    task = scheduler.tasks[0]
    # Force next_run far in the past so mark_run produces a different value
    task["_next_run"] = datetime.datetime(2020, 1, 1)
    task["_last_run"] = datetime.datetime(2020, 1, 1)
    await scheduler.mark_run(task)
    # In-memory update
    assert task["_last_run"] is not None
    assert task["_last_run"].year >= 2026
    assert task["_next_run"] > task["_last_run"]
    # DB update
    row = await db.get_schedule(sid)
    assert row["last_run"] is not None


# ── parse_schedule (unchanged functions, sanity check) ──────────

def test_parse_schedule_taeglich():
    p = parse_schedule("täglich 08:30")
    assert p == {"type": "daily", "hour": 8, "minute": 30}


def test_parse_schedule_stuendlich():
    p = parse_schedule("stündlich")
    assert p == {"type": "hourly"}


def test_parse_schedule_interval_minutes():
    p = parse_schedule("alle 15 Minuten")
    assert p == {"type": "interval_minutes", "minutes": 15}
