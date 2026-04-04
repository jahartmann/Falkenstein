import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.main_agent import MainAgent
from backend.scheduler import Scheduler


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
    mock_llm.chat = AsyncMock(return_value='{"type": "content", "agent": "coder", "result_type": "code", "title": "Backup Script"}')
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Script erstellt: rsync ...")
        mock_sub.agent_id = "sub_coder_abc123"
        mock_sub.agent_type = "coder"
        MockSub.return_value = mock_sub
        await agent.handle_message("Schreib ein Backup Script", chat_id="123")
        # Background task needs a tick to run
        await asyncio.sleep(0.1)
    assert mock_telegram.send_message.call_count >= 1


@pytest.mark.asyncio
async def test_action_no_obsidian_report(agent, mock_llm, mock_telegram, mock_db, mock_obsidian_writer):
    """Action tasks should NOT write a report to Obsidian."""
    mock_llm.chat = AsyncMock(return_value='{"type": "action", "agent": "ops", "title": "Schedule optimieren"}')
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Schedule-Dateien angepasst.")
        mock_sub.agent_id = "sub_ops_abc123"
        MockSub.return_value = mock_sub
        await agent.handle_message("Optimiere die Schedules", chat_id="123")
        # Background task needs a tick to run
        await asyncio.sleep(0.1)
    mock_obsidian_writer.write_result.assert_not_called()
    mock_obsidian_writer.create_task_note.assert_not_called()
    assert mock_telegram.send_message.call_count >= 1
    sent = mock_telegram.send_message.call_args[0][0]
    assert "Erledigt" in sent


@pytest.mark.asyncio
async def test_active_agents_tracking(agent, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "content", "agent": "coder", "result_type": "code", "title": "Test"}')
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Done")
        mock_sub.agent_id = "sub_coder_abc123"
        mock_sub.agent_type = "coder"
        mock_sub.done = True
        MockSub.return_value = mock_sub
        assert len(agent.active_agents) == 0
        await agent.handle_message("Test task", chat_id="123")
        # Background task needs a tick to run and clean up
        await asyncio.sleep(0.1)
        assert len(agent.active_agents) == 0


def test_get_status(agent):
    status = agent.get_status()
    assert "active_agents" in status
    assert isinstance(status["active_agents"], list)


# ── /command tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cmd_help(agent, mock_telegram):
    await agent.handle_message("/help", chat_id="123")
    mock_telegram.send_message.assert_called_once()
    text = mock_telegram.send_message.call_args[0][0]
    assert "/status" in text
    assert "/help" in text


@pytest.mark.asyncio
async def test_cmd_status_no_agents(agent, mock_telegram, mock_db):
    mock_db.get_open_tasks = AsyncMock(return_value=[])
    await agent.handle_message("/status", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "Keine aktiven Agents" in text


@pytest.mark.asyncio
async def test_cmd_tasks_empty(agent, mock_telegram, mock_db):
    mock_db.get_open_tasks = AsyncMock(return_value=[])
    await agent.handle_message("/tasks", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "Keine offenen Tasks" in text


@pytest.mark.asyncio
async def test_cmd_cancel_no_agents(agent, mock_telegram):
    await agent.handle_message("/cancel", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "Keine aktiven Agents" in text


@pytest.mark.asyncio
async def test_cmd_cancel_removes_agent(agent, mock_telegram, mock_db):
    agent.active_agents["sub_coder_xyz"] = {
        "type": "coder", "task": "Test", "task_id": 1,
    }
    await agent.handle_message("/cancel sub_coder_xyz", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "abgebrochen" in text
    assert "sub_coder_xyz" not in agent.active_agents


@pytest.mark.asyncio
async def test_cmd_does_not_hit_llm(agent, mock_llm, mock_telegram, mock_db):
    """Slash commands should NOT call the LLM."""
    mock_db.get_open_tasks = AsyncMock(return_value=[])
    await agent.handle_message("/status", chat_id="123")
    mock_llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_cmd_falls_through_to_llm(agent, mock_llm, mock_telegram):
    """Unknown /commands are not handled — falls through to classify."""
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Hmm?"}')
    await agent.handle_message("/unknown_xyz", chat_id="123")
    mock_llm.chat.assert_called_once()


def _make_scheduled_task(name="Heartbeat", schedule="stündlich", agent_type="ops",
                         prompt="Prüfe den Status.") -> dict:
    return {
        "id": 1,
        "name": name,
        "schedule": schedule,
        "agent_type": agent_type,
        "active": 1,
        "prompt": prompt,
    }


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


# ── /schedule command tests ──────────────────────────────────


@pytest.fixture
def mock_scheduler(tmp_path):
    sched = MagicMock(spec=Scheduler)
    sched.tasks = []
    sched.get_all_tasks_info = MagicMock(return_value=[])
    sched.reload_tasks = AsyncMock()
    sched.mark_run = AsyncMock()
    return sched


@pytest.fixture
def agent_with_scheduler(mock_llm, mock_tools, mock_db, mock_obsidian_writer, mock_telegram, mock_scheduler):
    return MainAgent(
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
        obsidian_writer=mock_obsidian_writer,
        telegram=mock_telegram,
        scheduler=mock_scheduler,
    )


@pytest.mark.asyncio
async def test_schedule_list_empty(agent_with_scheduler, mock_telegram):
    await agent_with_scheduler.handle_message("/schedule list", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "Keine Schedules" in text


@pytest.mark.asyncio
async def test_schedule_list_with_tasks(agent_with_scheduler, mock_telegram, mock_scheduler):
    mock_scheduler.get_all_tasks_info.return_value = [
        {"name": "Morning Briefing", "schedule": "täglich 08:00", "agent": "researcher",
         "active": True, "next_run": "2026-04-05T08:00:00", "last_run": None, "active_hours": None},
    ]
    await agent_with_scheduler.handle_message("/schedule list", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "Morning Briefing" in text
    assert "täglich 08:00" in text


@pytest.mark.asyncio
async def test_schedule_create(agent_with_scheduler, mock_llm, mock_telegram, mock_scheduler, mock_db):
    # LLM returns metadata and enriched prompt
    mock_llm.chat = AsyncMock(side_effect=[
        '{"schedule": "täglich 09:00", "agent": "researcher", "name": "KI News Analyse", "active_hours": ""}',
        "Analysiere die aktuellen KI-Nachrichten des Tages. Berücksichtige folgende Aspekte:\n"
        "1. Neue Modelle und Releases\n2. Forschungsdurchbrüche\n3. Regulierung und Politik",
    ])
    mock_db.create_schedule = AsyncMock(return_value=1)
    await agent_with_scheduler.handle_message(
        "/schedule create Erstelle täglich eine Analyse der aktuellen KI-News",
        chat_id="123",
    )
    # DB should be called
    mock_db.create_schedule.assert_called_once()
    call_kwargs = mock_db.create_schedule.call_args[1]
    assert call_kwargs["name"] == "KI News Analyse"
    assert call_kwargs["schedule"] == "täglich 09:00"
    assert call_kwargs["agent_type"] == "researcher"
    assert "Analysiere" in call_kwargs["prompt"]
    # Scheduler reloaded
    mock_scheduler.reload_tasks.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_create_empty(agent_with_scheduler, mock_telegram):
    await agent_with_scheduler.handle_message("/schedule create", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "Bitte Beschreibung angeben" in text


@pytest.mark.asyncio
async def test_schedule_toggle(agent_with_scheduler, mock_telegram, mock_scheduler, mock_db):
    mock_scheduler.tasks = [{"id": 1, "name": "Heartbeat", "schedule": "stündlich", "agent_type": "ops", "active": 1}]
    mock_db.toggle_schedule = AsyncMock(return_value=True)
    await agent_with_scheduler.handle_message("/schedule toggle Heartbeat", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "aktiviert" in text or "pausiert" in text


@pytest.mark.asyncio
async def test_schedule_delete(agent_with_scheduler, mock_telegram, mock_scheduler, mock_db):
    mock_scheduler.tasks = [{"id": 1, "name": "Test Task", "schedule": "täglich 09:00", "agent_type": "researcher", "active": 1}]
    mock_db.delete_schedule = AsyncMock()
    await agent_with_scheduler.handle_message("/schedule delete Test Task", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "gelöscht" in text
    mock_db.delete_schedule.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_schedule_no_scheduler(agent, mock_telegram):
    """Agent without scheduler returns error."""
    await agent.handle_message("/schedule list", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "nicht aktiv" in text


@pytest.mark.asyncio
async def test_schedule_unknown_subcommand(agent_with_scheduler, mock_telegram):
    await agent_with_scheduler.handle_message("/schedule xyz", chat_id="123")
    text = mock_telegram.send_message.call_args[0][0]
    assert "Nutzung" in text
