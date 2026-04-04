import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.main_agent import MainAgent
from backend.scheduler import ScheduledTask


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


@pytest.mark.asyncio
async def test_classify_quick_reply(agent, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Es geht mir gut!"}')
    result = await agent.classify("Wie geht es dir?")
    assert result["type"] == "quick_reply"


@pytest.mark.asyncio
async def test_classify_task(agent, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "task", "agent": "researcher", "result_type": "recherche", "title": "Docker vs Podman"}')
    result = await agent.classify("Recherchiere Docker vs Podman")
    assert result["type"] == "task"
    assert result["agent"] == "researcher"


@pytest.mark.asyncio
async def test_handle_quick_reply(agent, mock_llm, mock_telegram):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Alles läuft!"}')
    await agent.handle_message("Was ist der Status?", chat_id="123")
    mock_telegram.send_message.assert_called()
    call_args = mock_telegram.send_message.call_args
    assert "Alles läuft!" in call_args[0][0]


@pytest.mark.asyncio
async def test_handle_task_sends_confirmation(agent, mock_llm, mock_telegram, mock_db):
    mock_llm.chat = AsyncMock(return_value='{"type": "task", "agent": "coder", "result_type": "code", "title": "Backup Script"}')
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Script erstellt: rsync ...")
        mock_sub.agent_id = "sub_coder_abc123"
        mock_sub.agent_type = "coder"
        MockSub.return_value = mock_sub
        await agent.handle_message("Schreib ein Backup Script", chat_id="123")
    assert mock_telegram.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_active_agents_tracking(agent, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "task", "agent": "coder", "result_type": "code", "title": "Test"}')
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Done")
        mock_sub.agent_id = "sub_coder_abc123"
        mock_sub.agent_type = "coder"
        mock_sub.done = True
        MockSub.return_value = mock_sub
        assert len(agent.active_agents) == 0
        await agent.handle_message("Test task", chat_id="123")
        assert len(agent.active_agents) == 0


def test_get_status(agent):
    status = agent.get_status()
    assert "active_agents" in status
    assert isinstance(status["active_agents"], list)


def _make_scheduled_task(name="Heartbeat", schedule="stündlich", agent="ops",
                         prompt="Prüfe den Status.") -> ScheduledTask:
    return ScheduledTask(
        name=name,
        schedule_str=schedule,
        agent=agent,
        active=True,
        prompt=prompt,
        file_path=Path("/tmp/test_schedule.md"),
    )


@pytest.mark.asyncio
async def test_handle_scheduled_heartbeat_ok(agent, mock_telegram):
    """HEARTBEAT_OK result suppresses Telegram and Obsidian write."""
    task = _make_scheduled_task()
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="HEARTBEAT_OK")
        mock_sub.agent_id = "sub_ops_hb"
        MockSub.return_value = mock_sub
        await agent.handle_scheduled(task)
    mock_telegram.send_message.assert_not_called()
    agent.obsidian_writer.write_result.assert_not_called()


@pytest.mark.asyncio
async def test_handle_scheduled_with_report(agent, mock_telegram, mock_obsidian_writer):
    """Normal result writes to Obsidian and sends Telegram summary."""
    task = _make_scheduled_task(name="Daily Check", prompt="Prüfe alle offenen Tasks.")
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Systemstatus: Alles OK. 3 Tasks offen.")
        mock_sub.agent_id = "sub_ops_daily"
        MockSub.return_value = mock_sub
        await agent.handle_scheduled(task)
    mock_obsidian_writer.write_result.assert_called_once()
    call_kwargs = mock_obsidian_writer.write_result.call_args
    assert call_kwargs[1]["title"] == "Daily Check" or call_kwargs[0][0] == "Daily Check"
    mock_telegram.send_message.assert_called_once()
    sent_text = mock_telegram.send_message.call_args[0][0]
    assert "Daily Check" in sent_text
    assert "Systemstatus" in sent_text
