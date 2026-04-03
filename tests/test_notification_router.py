"""Tests for NotificationRouter — routing table, LLM hybrid check, target formatting."""
import pytest
from unittest.mock import AsyncMock

from backend.notification_router import NotificationRouter


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
    l.model_light = "test-model"
    l.chat = AsyncMock(return_value="Ja")
    return l


@pytest.fixture
def router(telegram, obsidian, llm):
    return NotificationRouter(telegram, obsidian, llm)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_assigned_only_telegram(router, telegram, obsidian):
    """task_assigned → only telegram, obsidian not called."""
    await router.route_event("task_assigned", {"agent_name": "coder_1", "task_title": "Build API"})

    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "coder_1" in msg
    assert "Build API" in msg
    obsidian.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_completed_both_targets_long_result(router, telegram, obsidian, llm):
    """task_completed with result > 100 chars → both targets, no LLM check."""
    long_result = "x" * 150
    await router.route_event("task_completed", {
        "agent_name": "coder_1",
        "task_title": "Build API",
        "result": long_result,
        "project": "Falkenstein",
    })

    telegram.send_message.assert_awaited_once()
    obsidian.execute.assert_awaited_once()
    # LLM should NOT have been called — content is long enough
    llm.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_completed_short_result_llm_says_no(router, telegram, obsidian, llm):
    """task_completed with result < 100 chars and LLM says Nein → only telegram."""
    llm.chat.return_value = "Nein"

    await router.route_event("task_completed", {
        "agent_name": "coder_1",
        "task_title": "Fix bug",
        "result": "Done.",
        "project": "Falkenstein",
    })

    telegram.send_message.assert_awaited_once()
    obsidian.execute.assert_not_awaited()
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_completed_short_result_llm_says_yes(router, telegram, obsidian, llm):
    """task_completed with result < 100 chars and LLM says Ja → both targets."""
    llm.chat.return_value = "Ja"

    await router.route_event("task_completed", {
        "agent_name": "coder_1",
        "task_title": "Fix bug",
        "result": "Done.",
        "project": "Falkenstein",
    })

    telegram.send_message.assert_awaited_once()
    obsidian.execute.assert_awaited_once()
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_budget_warning_only_telegram(router, telegram, obsidian):
    """budget_warning → telegram with formatted numbers, obsidian not called."""
    await router.route_event("budget_warning", {"used": 80000, "budget": 100000})

    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "80%" in msg
    assert "80,000" in msg
    assert "100,000" in msg
    obsidian.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_subtask_completed_only_obsidian(router, telegram, obsidian):
    """subtask_completed → only obsidian, telegram not called."""
    await router.route_event("subtask_completed", {
        "task_title": "Write tests",
        "project": "Falkenstein",
    })

    telegram.send_message.assert_not_awaited()
    obsidian.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_todo_from_obsidian_only_telegram(router, telegram, obsidian):
    """todo_from_obsidian → telegram with 'Obsidian' in message, obsidian not called."""
    await router.route_event("todo_from_obsidian", {"content": "Review PR"})

    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "Obsidian" in msg
    obsidian.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalation_success_both_targets(router, telegram, obsidian):
    """escalation_success → telegram + obsidian daily_report action."""
    await router.route_event("escalation_success", {
        "agent_name": "ops",
        "task_title": "Deploy",
        "details": "CLI stepped in and deployed successfully.",
    })

    telegram.send_message.assert_awaited_once()
    obsidian.execute.assert_awaited_once()
    call_params = obsidian.execute.call_args[0][0]
    assert call_params["action"] == "daily_report"


@pytest.mark.asyncio
async def test_unknown_event_type_ignored(router, telegram, obsidian):
    """Unknown event type → neither target called."""
    await router.route_event("this_event_does_not_exist", {"foo": "bar"})

    telegram.send_message.assert_not_awaited()
    obsidian.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_routing_disabled_always_writes_obsidian(telegram, obsidian, llm):
    """llm_routing_enabled=False + short result → both targets, LLM not consulted."""
    router = NotificationRouter(telegram, obsidian, llm, llm_routing_enabled=False)

    await router.route_event("task_completed", {
        "agent_name": "coder_1",
        "task_title": "Fix bug",
        "result": "Done.",
        "project": "Falkenstein",
    })

    telegram.send_message.assert_awaited_once()
    obsidian.execute.assert_awaited_once()
    llm.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_report_both_targets(router, telegram, obsidian):
    """daily_report → telegram + obsidian daily_report action."""
    report = "## Daily Report\n\n- coder_1: completed 3 tasks\n- researcher: found 5 sources"
    await router.route_event("daily_report", {"content": report})

    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "Daily Report" in msg

    obsidian.execute.assert_awaited_once()
    call_params = obsidian.execute.call_args[0][0]
    assert call_params["action"] == "daily_report"
    assert "Daily Report" in call_params["content"]


@pytest.mark.asyncio
async def test_escalation_failed_both_targets(router, telegram, obsidian):
    """escalation_failed → telegram with ❌ emoji + reason, obsidian daily_report action."""
    await router.route_event("escalation_failed", {
        "agent_name": "ops",
        "task_title": "Deploy",
        "reason": "CLI returned non-zero exit code",
        "details": "Deployment failed at step 3.",
    })

    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "❌" in msg
    assert "CLI returned non-zero exit code" in msg

    obsidian.execute.assert_awaited_once()
    call_params = obsidian.execute.call_args[0][0]
    assert call_params["action"] == "daily_report"


@pytest.mark.asyncio
async def test_todo_from_telegram_obsidian_path(router, telegram, obsidian):
    """todo_from_telegram → obsidian called with action=todo and project key."""
    await router.route_event("todo_from_telegram", {
        "content": "Review pull request #42",
        "project": "Falkenstein",
    })

    obsidian.execute.assert_awaited_once()
    call_params = obsidian.execute.call_args[0][0]
    assert call_params["action"] == "todo"
    assert call_params["project"] == "Falkenstein"
    assert "Review pull request #42" in call_params["content"]


@pytest.mark.asyncio
async def test_project_created_both_targets(router, telegram, obsidian):
    """project_created → telegram with 📁 message, obsidian with action=project."""
    await router.route_event("project_created", {"project_name": "NewProject"})

    telegram.send_message.assert_awaited_once()
    msg = telegram.send_message.call_args[0][0]
    assert "📁" in msg
    assert "NewProject" in msg

    obsidian.execute.assert_awaited_once()
    call_params = obsidian.execute.call_args[0][0]
    assert call_params["action"] == "project"
    assert call_params["project_name"] == "NewProject"


@pytest.mark.asyncio
async def test_task_completed_without_project_uses_inbox(router, telegram, obsidian, llm):
    """task_completed without project key → obsidian uses action=inbox instead of append."""
    long_result = "x" * 150  # long enough to skip LLM check

    await router.route_event("task_completed", {
        "agent_name": "coder_1",
        "task_title": "Standalone task",
        "result": long_result,
        # no "project" key
    })

    telegram.send_message.assert_awaited_once()
    obsidian.execute.assert_awaited_once()
    call_params = obsidian.execute.call_args[0][0]
    assert call_params["action"] == "inbox"
    llm.chat.assert_not_awaited()
