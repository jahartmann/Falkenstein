"""Tests for MCP intent classification via NativeOllamaClient."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.native_ollama import NativeOllamaClient

@pytest.fixture
def client():
    """Create a NativeOllamaClient with mocked HTTP."""
    c = NativeOllamaClient.__new__(NativeOllamaClient)
    c.host = "http://localhost:11434"
    c.model_light = "test-model"
    c.model_heavy = "test-model"
    c._http = MagicMock()
    c.num_ctx = 4096
    c.num_ctx_extended = 8192
    c.keep_alive = "5m"
    c.stream_tools = False
    c.stream_text = False
    return c

@pytest.mark.asyncio
async def test_classify_mcp_returns_dict(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "content": json.dumps({
                "server_id": "apple-mcp",
                "tool_name": "create_reminder",
                "args": {"title": "Meeting", "due_date": "2026-04-09T09:00:00"}
            })
        }
    }
    client._http.post = AsyncMock(return_value=mock_response)
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
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"message": {"content": "I don't know"}}
    client._http.post = AsyncMock(return_value=mock_response)
    result = await client.classify_mcp("random text", available_tools=[])
    assert result.get("server_id") is None
