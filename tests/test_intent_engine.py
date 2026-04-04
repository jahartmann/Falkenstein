import pytest
from unittest.mock import AsyncMock
from datetime import datetime
from backend.intent_engine import IntentEngine, ParsedIntent


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def engine(mock_llm):
    return IntentEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_parse_reminder(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "reminder", "text": "Meeting vorbereiten", "time_expr": "2026-04-05T09:00", "confidence": 0.95}')
    result = await engine.parse(
        "erinnere mich morgen um 9 an das Meeting",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.type == "reminder"
    assert result.confidence >= 0.8


@pytest.mark.asyncio
async def test_parse_research_task(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "content", "enriched_prompt": "Recherchiere aktuelle Entwicklungen zu MLX Framework. Fokus auf neue Releases und Performance.", "confidence": 0.9}')
    result = await engine.parse(
        "schau mal was es neues zu MLX gibt",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.type == "content"
    assert len(result.enriched_prompt) > len("schau mal was es neues zu MLX gibt")


@pytest.mark.asyncio
async def test_parse_scheduled_task(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "planned_task", "steps": [{"prompt": "Recherchiere MLX", "scheduled_at": "2026-04-04T20:00"}, {"prompt": "Fasse zusammen", "scheduled_at": "2026-04-05T07:30"}], "confidence": 0.85}')
    result = await engine.parse(
        "recherchiere heute abend was es neues zu MLX gibt und schick mir morgen frueh ne zusammenfassung",
        current_time=datetime(2026, 4, 4, 15, 0),
        daily_profile={"wake_up": "07:30"},
    )
    assert result.type == "planned_task"
    assert result.steps is not None
    assert len(result.steps) == 2


@pytest.mark.asyncio
async def test_parse_low_confidence_asks_clarification(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "content", "enriched_prompt": "...", "confidence": 0.3, "needs_clarification": true, "clarification_question": "Meinst du MLX allgemein oder speziell auf iOS?"}')
    result = await engine.parse(
        "mach mal was zu dem Thema",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.needs_clarification
    assert result.clarification_question is not None


@pytest.mark.asyncio
async def test_parse_with_daily_profile(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "reminder", "text": "Zusammenfassung schicken", "time_expr": "2026-04-05T07:45", "confidence": 0.9}')
    result = await engine.parse(
        "schick mir morgen frueh eine zusammenfassung",
        current_time=datetime(2026, 4, 4, 22, 0),
        daily_profile={"wake_up": "07:45"},
    )
    assert result.type == "reminder"
    assert result.confidence > 0.8


@pytest.mark.asyncio
async def test_parse_simple_question(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick", "enriched_prompt": "Was ist Python?", "confidence": 0.95}')
    result = await engine.parse(
        "was ist python?",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.type == "quick"
    assert not result.needs_clarification


@pytest.mark.asyncio
async def test_parse_fallback_on_llm_error(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value="broken json")
    result = await engine.parse(
        "mach irgendwas",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.type == "passthrough"
    assert result.enriched_prompt == "mach irgendwas"
