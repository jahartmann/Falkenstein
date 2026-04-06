import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.llm_router import LLMRouter

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.model = "gemma4:26b"
    llm.model_light = "gemma3:4b"
    llm.model_heavy = "gemma4:26b"
    llm.chat_light = AsyncMock(return_value="light response")
    llm.chat_heavy = AsyncMock(return_value="heavy response")
    return llm

def test_router_has_telegram_type(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    client, size = router.get_client_with_size("telegram")
    assert size == "light"

def test_router_classify_is_light(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("classify")
    assert size == "light"

def test_router_action_is_heavy(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("action")
    assert size == "heavy"

def test_router_scheduled_is_heavy(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("scheduled")
    assert size == "heavy"

def test_router_content_is_heavy(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("content")
    assert size == "heavy"

def test_get_client_with_size_returns_tuple(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    result = router.get_client_with_size("telegram")
    assert isinstance(result, tuple)
    assert len(result) == 2
