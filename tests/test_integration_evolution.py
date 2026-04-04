"""Integration tests for the evolved MainAgent wiring (SoulMemory, ReviewGate, IntentEngine, DynamicAgent)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.main_agent import MainAgent
from backend.memory.soul_memory import SoulMemory
from backend.review_gate import ReviewGate, ReviewResult
from backend.intent_engine import IntentEngine, ParsedIntent


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Alles gut!"}')
    return llm


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    db.update_task_status = AsyncMock()
    db.update_task_result = AsyncMock()
    db.get_chat_history = AsyncMock(return_value=[])
    db.append_chat = AsyncMock()
    db.get_open_tasks = AsyncMock(return_value=[])
    db.search_past_tasks = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_soul_memory():
    sm = AsyncMock(spec=SoulMemory)
    sm.get_context_block = AsyncMock(return_value="## User Memory\n- Mag kurze Antworten")
    sm.extract_memories = AsyncMock()
    sm.log_activity = AsyncMock()
    sm.track_tool_usage = AsyncMock()
    sm.compute_daily_profile = AsyncMock(return_value={"wake_up": "07:30"})
    return sm


@pytest.fixture
def mock_review_gate():
    rg = AsyncMock(spec=ReviewGate)
    rg.review = AsyncMock(return_value=ReviewResult(verdict="PASS"))
    return rg


@pytest.fixture
def mock_intent_engine():
    ie = AsyncMock(spec=IntentEngine)
    ie.parse = AsyncMock(return_value=ParsedIntent(
        type="passthrough", enriched_prompt="Test", confidence=0.9,
    ))
    return ie


@pytest.fixture
def agent(mock_llm, mock_db, mock_soul_memory, mock_review_gate, mock_intent_engine):
    return MainAgent(
        llm=mock_llm,
        tools=MagicMock(),
        db=mock_db,
        soul_memory=mock_soul_memory,
        review_gate=mock_review_gate,
        intent_engine=mock_intent_engine,
    )


@pytest.mark.asyncio
async def test_handle_message_uses_intent_engine(agent, mock_intent_engine):
    await agent.handle_message("was ist python?", chat_id="test")
    mock_intent_engine.parse.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_uses_review_gate(agent, mock_llm, mock_review_gate):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Python ist toll"}')
    await agent.handle_message("was ist python?", chat_id="test")
    mock_review_gate.review.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_logs_activity(agent, mock_soul_memory):
    await agent.handle_message("hallo", chat_id="test")
    mock_soul_memory.log_activity.assert_called_once_with("test")


@pytest.mark.asyncio
async def test_handle_message_extracts_soul_memories(agent, mock_soul_memory, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Hi!"}')
    await agent.handle_message("ich mag Python", chat_id="test")
    # extract_memories is fire-and-forget via create_task, so check it was called
    mock_soul_memory.extract_memories.assert_called_once()


@pytest.mark.asyncio
async def test_review_gate_revises_answer(agent, mock_llm, mock_review_gate):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Original"}')
    mock_review_gate.review = AsyncMock(return_value=ReviewResult(
        verdict="REVISE", revised="Verbessert",
    ))
    agent.telegram = AsyncMock()
    agent.telegram.send_message = AsyncMock()
    await agent.handle_message("frage?", chat_id="test")
    # The telegram message should contain the revised answer
    agent.telegram.send_message.assert_called_once()
    sent_text = agent.telegram.send_message.call_args[0][0]
    assert "Verbessert" in sent_text


@pytest.mark.asyncio
async def test_intent_engine_reminder(agent, mock_intent_engine):
    """When intent engine returns 'reminder', we should add a reminder and return early."""
    mock_intent_engine.parse = AsyncMock(return_value=ParsedIntent(
        type="reminder", enriched_prompt="Termin um 14 Uhr",
        confidence=0.95, time_expressions=["2026-04-04T14:00:00"],
    ))
    scheduler = AsyncMock()
    scheduler.add_reminder = AsyncMock()
    agent.scheduler = scheduler
    agent.telegram = AsyncMock()
    agent.telegram.send_message = AsyncMock()

    await agent.handle_message("erinnere mich um 14 Uhr", chat_id="test")

    scheduler.add_reminder.assert_called_once()
    agent.telegram.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_classify_uses_soul_memory(agent, mock_soul_memory, mock_llm):
    """classify() should inject soul memory context block."""
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "ok"}')
    result = await agent.classify("test", chat_id="c1")
    mock_soul_memory.get_context_block.assert_called()


@pytest.mark.asyncio
async def test_legacy_no_new_modules():
    """MainAgent should work fine without any new modules (all None)."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "ok"}')
    db = AsyncMock()
    db.get_chat_history = AsyncMock(return_value=[])
    db.append_chat = AsyncMock()
    db.get_open_tasks = AsyncMock(return_value=[])
    db.search_past_tasks = AsyncMock(return_value=[])

    agent = MainAgent(llm=llm, tools=MagicMock(), db=db)
    await agent.handle_message("hallo", chat_id="test")
    # Should not crash — all new modules are None
    db.append_chat.assert_called()
