import pytest
from unittest.mock import AsyncMock
from backend.review_gate import ReviewGate, ReviewResult


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def gate(mock_llm):
    return ReviewGate(llm=mock_llm)


@pytest.mark.asyncio
async def test_review_pass(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"verdict": "PASS", "feedback": ""}')
    result = await gate.review(
        answer="Python ist eine Programmiersprache.",
        original_request="Was ist Python?",
    )
    assert result.verdict == "PASS"


@pytest.mark.asyncio
async def test_review_revise(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"verdict": "REVISE", "feedback": "Antwort ist zu vage", "revised": "Python ist eine interpretierte, dynamisch typisierte Programmiersprache."}')
    result = await gate.review(
        answer="Python ist cool.",
        original_request="Was ist Python?",
    )
    assert result.verdict == "REVISE"
    assert result.revised != ""


@pytest.mark.asyncio
async def test_review_fallback_on_parse_error(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value="invalid json response")
    result = await gate.review(
        answer="Test answer",
        original_request="Test request",
    )
    assert result.verdict == "PASS"


@pytest.mark.asyncio
async def test_review_light_mode(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"verdict": "PASS", "feedback": ""}')
    result = await gate.review(
        answer="Mir geht es gut!",
        original_request="Wie geht es dir?",
        review_level="light",
    )
    assert result.verdict == "PASS"
    call_args = mock_llm.chat.call_args
    system_prompt = call_args.kwargs.get("system_prompt", "")
    assert len(system_prompt) < 1000
