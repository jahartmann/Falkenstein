"""Tests for FalkensteinEventBus."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.event_bus import FalkensteinEventBus, STREAM_TO_TELEGRAM


@pytest.fixture
def mocks():
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()

    telegram_bot = MagicMock()
    telegram_bot.send_message = AsyncMock()

    db = MagicMock()
    db.create_crew = AsyncMock(return_value="crew-123")
    db.update_crew = AsyncMock()
    db.log_crew_tool = AsyncMock()

    return ws_manager, telegram_bot, db


@pytest.fixture
def bus(mocks):
    ws_manager, telegram_bot, db = mocks
    return FalkensteinEventBus(ws_manager, telegram_bot, db)


# ---------------------------------------------------------------------------
# on_crew_start
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_crew_start_broadcasts_agent_spawn(bus, mocks):
    ws_manager, _, _ = mocks
    await bus.on_crew_start("ResearchCrew", "Find facts", chat_id=42)
    ws_manager.broadcast.assert_awaited_once()
    call_data = ws_manager.broadcast.call_args[0][0]
    assert call_data["type"] == "agent_spawn"
    assert call_data["crew_name"] == "ResearchCrew"


@pytest.mark.asyncio
async def test_on_crew_start_sends_telegram_message(bus, mocks):
    _, telegram_bot, _ = mocks
    await bus.on_crew_start("ResearchCrew", "Find facts", chat_id=42)
    telegram_bot.send_message.assert_awaited_once()
    args, kwargs = telegram_bot.send_message.call_args
    assert "ResearchCrew" in args[0]
    assert kwargs.get("chat_id") == 42


@pytest.mark.asyncio
async def test_on_crew_start_creates_db_entry(bus, mocks):
    _, _, db = mocks
    crew_id = await bus.on_crew_start("ResearchCrew", "Find facts", chat_id=42)
    db.create_crew.assert_awaited_once_with(
        name="ResearchCrew", task_description="Find facts"
    )
    assert crew_id == "crew-123"


# ---------------------------------------------------------------------------
# on_tool_call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_tool_call_broadcasts_tool_use(bus, mocks):
    ws_manager, _, _ = mocks
    await bus.on_crew_start("Crew", "task", chat_id=1)
    ws_manager.broadcast.reset_mock()

    await bus.on_tool_call("agent1", "code_executor", {"code": "x=1"}, "ok", 100)
    ws_manager.broadcast.assert_awaited_once()
    call_data = ws_manager.broadcast.call_args[0][0]
    assert call_data["type"] == "tool_use"
    assert call_data["tool_name"] == "code_executor"
    assert call_data["animation"] == "typing"


@pytest.mark.asyncio
async def test_on_tool_call_streams_to_telegram_for_web_search(bus, mocks):
    _, telegram_bot, _ = mocks
    await bus.on_crew_start("Crew", "task", chat_id=7)
    telegram_bot.send_message.reset_mock()

    await bus.on_tool_call("agent1", "web_search", "query", "results", 200)
    telegram_bot.send_message.assert_awaited_once()
    assert "web_search" in STREAM_TO_TELEGRAM


@pytest.mark.asyncio
async def test_on_tool_call_does_not_stream_for_file_read(bus, mocks):
    _, telegram_bot, _ = mocks
    await bus.on_crew_start("Crew", "task", chat_id=7)
    telegram_bot.send_message.reset_mock()

    await bus.on_tool_call("agent1", "file_read", "path.txt", "content", 50)
    telegram_bot.send_message.assert_not_awaited()
    assert "file_read" not in STREAM_TO_TELEGRAM


# ---------------------------------------------------------------------------
# on_crew_done
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_crew_done_sends_final_telegram(bus, mocks):
    _, telegram_bot, _ = mocks
    await bus.on_crew_start("Crew", "task", chat_id=5)
    telegram_bot.send_message.reset_mock()

    await bus.on_crew_done("Crew", "Great result", chat_id=5)
    telegram_bot.send_message.assert_awaited_once()
    args, _ = telegram_bot.send_message.call_args
    assert "Great result" in args[0]


@pytest.mark.asyncio
async def test_on_crew_done_updates_db_status(bus, mocks):
    _, _, db = mocks
    await bus.on_crew_start("Crew", "task", chat_id=5)

    await bus.on_crew_done("Crew", "result", chat_id=5)
    db.update_crew.assert_awaited_once_with(
        crew_id="crew-123", status="done", result="result"
    )


@pytest.mark.asyncio
async def test_on_crew_done_broadcasts_agent_done(bus, mocks):
    ws_manager, _, _ = mocks
    await bus.on_crew_start("Crew", "task", chat_id=5)
    ws_manager.broadcast.reset_mock()

    await bus.on_crew_done("Crew", "result", chat_id=5)
    ws_manager.broadcast.assert_awaited_once()
    call_data = ws_manager.broadcast.call_args[0][0]
    assert call_data["type"] == "agent_done"
    assert call_data["crew_name"] == "Crew"


# ---------------------------------------------------------------------------
# on_crew_error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_crew_error_sends_error_to_telegram(bus, mocks):
    _, telegram_bot, _ = mocks
    await bus.on_crew_start("Crew", "task", chat_id=9)
    telegram_bot.send_message.reset_mock()

    await bus.on_crew_error("Crew", "Something exploded", chat_id=9)
    telegram_bot.send_message.assert_awaited_once()
    args, _ = telegram_bot.send_message.call_args
    assert "Something exploded" in args[0]
