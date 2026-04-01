import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.llm_client import LLMClient


@pytest.mark.asyncio
async def test_chat_returns_response():
    mock_response = {"message": {"content": "Hello from Ollama"}}
    with patch("backend.llm_client.ollama_chat") as mock_chat:
        mock_chat.return_value = mock_response
        client = LLMClient()
        result = await client.chat(
            system_prompt="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert result == "Hello from Ollama"
        mock_chat.assert_called_once()


@pytest.mark.asyncio
async def test_chat_with_tools_returns_tool_call():
    mock_response = {
        "message": {
            "content": "",
            "tool_calls": [
                {"function": {"name": "web_surfer", "arguments": {"query": "python"}}}
            ],
        }
    }
    with patch("backend.llm_client.ollama_chat") as mock_chat:
        mock_chat.return_value = mock_response
        client = LLMClient()
        result = await client.chat_with_tools(
            system_prompt="You have tools.",
            messages=[{"role": "user", "content": "Search for python"}],
            tools=[{"type": "function", "function": {"name": "web_surfer", "parameters": {}}}],
        )
        assert result["tool_calls"][0]["function"]["name"] == "web_surfer"


@pytest.mark.asyncio
async def test_generate_sim_action_returns_string():
    mock_response = {"message": {"content": "wander"}}
    with patch("backend.llm_client.ollama_chat") as mock_chat:
        mock_chat.return_value = mock_response
        client = LLMClient()
        result = await client.generate_sim_action(
            agent_name="Alex",
            personality="social and curious",
            nearby_agents=["Bob", "Amelia"],
        )
        assert isinstance(result, str)
        assert len(result) > 0
