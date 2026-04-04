"""Smoke test: DB init -> ConfigService -> Scheduler -> MainAgent flow."""

import asyncio
import datetime
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend.database import Database
from backend.config_service import ConfigService
from backend.scheduler import Scheduler


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_full_lifecycle(db):
    """DB -> ConfigService -> Scheduler -> create schedule -> get due."""
    # Config
    cfg = ConfigService(db)
    await cfg.init()
    assert cfg.get("ollama_model") is not None

    # Scheduler
    sched = Scheduler(db)
    await sched.load_tasks()
    assert sched.tasks == []

    # Create schedule
    sid = await db.create_schedule(
        name="Test Schedule",
        schedule="alle 1 Minuten",
        agent_type="researcher",
        prompt="Do a thing",
    )
    await sched.reload_tasks()
    assert len(sched.tasks) == 1

    # Should be due when checked far enough in the future
    future = datetime.datetime.now() + datetime.timedelta(minutes=5)
    due = sched.get_due_tasks(now=future)
    assert len(due) == 1
    assert due[0]["name"] == "Test Schedule"

    # Mark run
    await sched.mark_run(due[0])
    due2 = sched.get_due_tasks()
    assert len(due2) == 0  # just ran, not due yet


@pytest.mark.asyncio
async def test_config_persistence(db):
    """Config changes persist across service instances."""
    cfg1 = ConfigService(db)
    await cfg1.init()
    await cfg1.set("ollama_model", "test_model")

    cfg2 = ConfigService(db)
    await cfg2.init()
    assert cfg2.get("ollama_model") == "test_model"


@pytest.mark.asyncio
async def test_schedule_crud_lifecycle(db):
    """Full CRUD on schedules through DB."""
    # Create
    sid = await db.create_schedule(
        name="CRUD Test", schedule="täglich 09:00", agent_type="ops", prompt="test"
    )
    assert sid > 0

    # Read
    s = await db.get_schedule(sid)
    assert s["name"] == "CRUD Test"

    # Update
    await db.update_schedule(sid, name="Updated", schedule="stündlich")
    s = await db.get_schedule(sid)
    assert s["name"] == "Updated"
    assert s["schedule"] == "stündlich"

    # Toggle
    new_state = await db.toggle_schedule(sid)
    assert new_state is False
    s = await db.get_schedule(sid)
    assert s["active"] == 0

    # Delete
    await db.delete_schedule(sid)
    s = await db.get_schedule(sid)
    assert s is None


@pytest.mark.asyncio
async def test_config_categories(db):
    """Config service correctly groups by category."""
    cfg = ConfigService(db)
    await cfg.init()

    llm = cfg.get_category("llm")
    assert "ollama_model" in llm

    paths = cfg.get_category("paths")
    assert "obsidian_vault_path" in paths

    all_config = cfg.get_all()
    assert len(all_config) > 0
