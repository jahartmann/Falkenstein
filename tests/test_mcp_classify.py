"""Tests for MCP intent classification via NativeOllamaClient."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.native_ollama import NativeOllamaClient

@pytest.fixture
def client():
    """Create a NativeOllamaClient with proper init."""
    c = NativeOllamaClient(
        host="http://localhost:11434",
        model_light="test-model",
        model_heavy="test-model",
        keep_alive="5m",
        timeout=30.0,
    )
    return c


def _mock_response(content_dict):
    """Create a mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": json.dumps(content_dict) if isinstance(content_dict, dict) else content_dict}
    }
    return mock_resp


@pytest.mark.asyncio
async def test_classify_mcp_returns_dict(client):
    mock_response = _mock_response({
        "server_id": "apple-mcp",
        "tool_name": "create_reminder",
        "args": {"title": "Meeting", "due_date": "2026-04-09T09:00:00"}
    })

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    with pytest.MonkeyPatch.context() as mp:
        import httpx
        mp.setattr(httpx, "AsyncClient", lambda **kwargs: mock_http)

        result = await client.classify_mcp(
            "Erinnere mich morgen um 9 ans Meeting",
            available_tools=[
                {"server_id": "apple-mcp", "tool_name": "create_reminder", "description": "Create reminder"},
            ],
        )
    assert result["server_id"] == "apple-mcp"
    assert result["tool_name"] == "create_reminder"
    assert "title" in result["args"]

@pytest.mark.asyncio
async def test_classify_mcp_returns_none_on_failure(client):
    mock_response = _mock_response("I don't know")

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)

    with pytest.MonkeyPatch.context() as mp:
        import httpx
        mp.setattr(httpx, "AsyncClient", lambda **kwargs: mock_http)

        result = await client.classify_mcp("random text", available_tools=[])
    assert result.get("server_id") is None
