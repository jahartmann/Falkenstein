"""End-to-end integration tests for NotificationRouter + ObsidianWatcher."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from backend.notification_router import NotificationRouter
from backend.obsidian_watcher import ObsidianWatcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def telegram():
    t = AsyncMock()
    t.enabled = True
    t.send_message = AsyncMock(return_value=True)
    return t


@pytest.fixture
def obsidian():
    o = AsyncMock()
    o.execute = AsyncMock()
    return o


@pytest.fixture
def llm():
    l = AsyncMock()
    l.model_light = "test"
    l.chat = AsyncMock(return_value="Ja")
    return l


@pytest.fixture
def router(telegram, obsidian, llm):
    from backend.notification_router import NotificationRouter
    return NotificationRouter(telegram=telegram, obsidian=obsidian, llm=llm)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_task_lifecycle(router, telegram, obsidian, llm):
    """Task assigned → completed → both targets get correct messages."""
    # Step 1: task_assigned — only Telegram
    await router.route_event("task_assigned", {
        "agent_name": "coder_1",
        "task_title": "Build login API",
    })

    telegram.send_message.assert_awaited_once()
    assign_msg = telegram.send_message.call_args[0][0]
    assert "coder_1" in assign_msg
    assert "Build login API" in assign_msg
    obsidian.execute.assert_not_awaited()

    # Reset mocks for next step
    telegram.send_message.reset_mock()
    obsidian.execute.reset_mock()

    # Step 2: task_completed with long result and project — both targets, no LLM check
    long_result = "Implemented JWT-based authentication with refresh tokens, added tests, " \
                  "updated swagger docs and integrated with the existing user service."
    await router.route_event("task_completed", {
        "agent_name": "coder_1",
        "task_title": "Build login API",
        "result": long_result,
        "project": "falkenstein",
    })

    telegram.send_message.assert_awaited_once()
    complete_msg = telegram.send_message.call_args[0][0]
    assert "coder_1" in complete_msg
    assert "Build login API" in complete_msg

    obsidian.execute.assert_awaited_once()
    obsidian_call = obsidian.execute.call_args[0][0]
    assert obsidian_call["action"] == "append"
    assert "falkenstein" in obsidian_call["path"]

    # LLM not called — result is long enough
    llm.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_obsidian_todo_triggers_telegram(tmp_path, telegram, obsidian, llm):
    """Todo added in Obsidian vault → Telegram notified via router."""
    # Create vault with Inbox.md
    mgmt = tmp_path / "Management"
    mgmt.mkdir()
    inbox = mgmt / "Inbox.md"
    inbox.write_text("# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n")

    router = NotificationRouter(telegram=telegram, obsidian=obsidian, llm=llm)
    watcher = ObsidianWatcher(vault_path=tmp_path, router=router, debounce_seconds=0.1)

    # Snapshot initial state
    watcher.scan_files()

    # Add new todo to Inbox.md
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-03 09:00] Review neue Feature-Requests\n"
    )

    # detect_changes returns the new todo
    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert "Review neue Feature-Requests" in changes[0]["content"]

    # Route the change via the router
    for change in changes:
        await router.route_event("todo_from_obsidian", change)

    # Telegram must be notified with Obsidian reference
    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "Obsidian" in msg
    assert "Review neue Feature-Requests" in msg

    # Obsidian must NOT be called — todo is already in Obsidian
    obsidian.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalation_full_flow(router, telegram, obsidian):
    """Escalation success → Telegram warning + Obsidian daily report."""
    await router.route_event("escalation_success", {
        "agent_name": "ops",
        "task_title": "Deploy to production",
        "details": "CLI stepped in and executed docker-compose up successfully.",
    })

    # Telegram must mention escalation
    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "Eskalation" in msg

    # Obsidian must be called with daily_report action
    obsidian.execute.assert_awaited_once()
    obsidian_call = obsidian.execute.call_args[0][0]
    assert obsidian_call["action"] == "daily_report"


@pytest.mark.asyncio
async def test_budget_warning_telegram_only(router, telegram, obsidian):
    """Budget warning → only Telegram with percentage formatting."""
    await router.route_event("budget_warning", {
        "used": 75000,
        "budget": 100000,
    })

    # Telegram must receive percentage-formatted message
    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "75%" in msg
    assert "75,000" in msg
    assert "100,000" in msg

    # Obsidian must NOT be called
    obsidian.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_todo_from_obsidian(tmp_path, telegram, obsidian, llm):
    """New todo in project Tasks.md → Telegram notified with project info."""
    # Create vault with project structure
    proj_dir = tmp_path / "Falkenstein" / "Projekte" / "website"
    proj_dir.mkdir(parents=True)
    tasks_file = proj_dir / "Tasks.md"
    tasks_file.write_text("# Tasks — website\n\n- [ ] [2026-04-01 10:00] Old task\n")

    router = NotificationRouter(telegram=telegram, obsidian=obsidian, llm=llm)
    watcher = ObsidianWatcher(vault_path=tmp_path, router=router, debounce_seconds=0.1)

    # Snapshot initial state
    watcher.scan_files()

    # Add todo to project Tasks.md
    tasks_file.write_text(
        "# Tasks — website\n\n"
        "- [ ] [2026-04-01 10:00] Old task\n"
        "- [ ] [2026-04-03 11:00] Implement dark mode\n"
    )

    # detect_changes must find the new todo with correct project
    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["project"] == "website"
    assert "Implement dark mode" in changes[0]["content"]

    # Route via router
    for change in changes:
        await router.route_event("todo_from_obsidian", change)

    # Telegram must be notified
    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "Obsidian" in msg
    assert "Implement dark mode" in msg

    # Obsidian must NOT be called
    obsidian.execute.assert_not_awaited()
