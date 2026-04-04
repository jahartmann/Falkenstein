"""Test that handle_message returns quickly when dispatching background agents."""
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.main_agent import MainAgent


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_tools():
    return MagicMock()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    db.update_task_status = AsyncMock()
    db.update_task_result = AsyncMock()
    return db


@pytest.fixture
def mock_obsidian_writer():
    writer = MagicMock()
    writer.create_task_note = MagicMock(return_value=MagicMock())
    writer.kanban_move = MagicMock()
    writer.write_result = MagicMock(return_value=MagicMock())
    writer.update_task_status = MagicMock()
    writer.remove_from_inbox = MagicMock()
    return writer


@pytest.fixture
def mock_telegram():
    tg = AsyncMock()
    tg.send_message = AsyncMock(return_value=True)
    return tg


@pytest.fixture
def agent(mock_llm, mock_tools, mock_db, mock_obsidian_writer, mock_telegram):
    return MainAgent(
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
        obsidian_writer=mock_obsidian_writer,
        telegram=mock_telegram,
    )


async def _slow_run():
    """Simulate a SubAgent.run() that takes 10 seconds."""
    await asyncio.sleep(10)
    return "done"


@pytest.mark.asyncio
async def test_handle_message_returns_quickly_for_action(agent, mock_llm):
    """handle_message should return in under 2s even if SubAgent.run takes 10s."""
    classification = {
        "type": "action",
        "agent": "ops",
        "title": "Slow task",
    }
    mock_llm.chat = AsyncMock(return_value=json.dumps(classification))

    with patch("backend.main_agent.DynamicAgent") as MockSub:
        instance = AsyncMock()
        instance.run = _slow_run
        instance.agent_id = "test-123"
        MockSub.return_value = instance

        start = time.monotonic()
        await agent.handle_message("do something slow", chat_id="123")
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"handle_message took {elapsed:.1f}s, should be < 2s"


@pytest.mark.asyncio
async def test_handle_message_returns_quickly_for_content(agent, mock_llm):
    """handle_message should return in under 2s for content tasks too."""
    classification = {
        "type": "content",
        "agent": "researcher",
        "title": "Long research",
        "result_type": "report",
    }
    mock_llm.chat = AsyncMock(return_value=json.dumps(classification))

    with patch("backend.main_agent.DynamicAgent") as MockSub:
        instance = AsyncMock()
        instance.run = _slow_run
        instance.agent_id = "test-456"
        MockSub.return_value = instance

        start = time.monotonic()
        await agent.handle_message("research something complex", chat_id="123")
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"handle_message took {elapsed:.1f}s, should be < 2s"


@pytest.mark.asyncio
async def test_background_task_error_sends_telegram(agent, mock_llm, mock_telegram):
    """Errors in background tasks should be reported via Telegram."""
    classification = {
        "type": "action",
        "agent": "ops",
        "title": "Failing task",
    }
    mock_llm.chat = AsyncMock(return_value=json.dumps(classification))

    async def _failing_run():
        raise RuntimeError("boom")

    with patch("backend.main_agent.DynamicAgent") as MockSub:
        instance = AsyncMock()
        instance.run = _failing_run
        instance.agent_id = "test-err"
        MockSub.return_value = instance

        await agent.handle_message("do something broken", chat_id="123")
        # Give background task time to complete
        await asyncio.sleep(0.3)

        # The error should have triggered a Telegram message with the error
        calls = [str(c) for c in mock_telegram.send_message.call_args_list]
        error_sent = any("Fehler" in c for c in calls)
        assert error_sent, f"Expected error message via Telegram, got: {calls}"
