"""Tests for NativeOllamaClient — TDD approach."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.native_ollama import NativeOllamaClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(body: dict) -> MagicMock:
    """Build a mock response whose .json() returns body and .raise_for_status() is a no-op."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=body)
    return resp


def _make_client() -> NativeOllamaClient:
    return NativeOllamaClient(
        host="http://localhost:11434",
        model_light="gemma4:e4b",
        model_heavy="gemma4:26b",
    )


# ---------------------------------------------------------------------------
# 1. classify() — structured output, uses light model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_returns_structured_output():
    classify_body = {
        "message": {
            "content": json.dumps({
                "crew_type": "coder",
                "task_description": "Write a Python script",
                "priority": "normal",
            })
        }
    }
    mock_post = AsyncMock(return_value=_make_response(classify_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        result = await client.classify("Write a Python script")

    assert result["crew_type"] == "coder"
    assert result["task_description"] == "Write a Python script"
    assert result["priority"] == "normal"


@pytest.mark.asyncio
async def test_classify_uses_light_model():
    classify_body = {
        "message": {
            "content": json.dumps({
                "crew_type": "researcher",
                "task_description": "Find info",
                "priority": "normal",
            })
        }
    }
    mock_post = AsyncMock(return_value=_make_response(classify_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client.classify("Find some information")

    call_payload = mock_post.call_args[1]["json"]
    assert call_payload["model"] == "gemma4:e4b"


# ---------------------------------------------------------------------------
# 2. quick_reply() — returns plain text string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quick_reply_returns_string():
    reply_body = {"message": {"content": "This is a quick answer."}}
    mock_post = AsyncMock(return_value=_make_response(reply_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        result = await client.quick_reply("What is 2+2?")

    assert result == "This is a quick answer."
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_quick_reply_includes_context_as_system_message():
    reply_body = {"message": {"content": "Sure!"}}
    mock_post = AsyncMock(return_value=_make_response(reply_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client.quick_reply("Help me", context="You are a coding assistant.")

    payload = mock_post.call_args[1]["json"]
    assert payload["messages"][0] == {"role": "system", "content": "You are a coding assistant."}
    assert payload["messages"][1]["role"] == "user"


@pytest.mark.asyncio
async def test_quick_reply_no_context_skips_system_message():
    reply_body = {"message": {"content": "OK"}}
    mock_post = AsyncMock(return_value=_make_response(reply_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client.quick_reply("Hello")

    payload = mock_post.call_args[1]["json"]
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"


# ---------------------------------------------------------------------------
# 3. chat_with_tools() — sends tools param, returns full response dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_with_tools_returns_full_response():
    full_body = {
        "message": {
            "content": "",
            "tool_calls": [
                {"function": {"name": "web_search", "arguments": {"query": "python"}}}
            ],
        }
    }
    mock_post = AsyncMock(return_value=_make_response(full_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
        result = await client.chat_with_tools(
            messages=[{"role": "user", "content": "Search python"}],
            tools=tools,
        )

    assert "message" in result
    assert result["message"]["tool_calls"][0]["function"]["name"] == "web_search"


@pytest.mark.asyncio
async def test_chat_with_tools_sends_tools_param():
    full_body = {"message": {"content": "done", "tool_calls": []}}
    mock_post = AsyncMock(return_value=_make_response(full_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        tools = [{"type": "function", "function": {"name": "my_tool"}}]
        await client.chat_with_tools(
            messages=[{"role": "user", "content": "Use my_tool"}],
            tools=tools,
        )

    payload = mock_post.call_args[1]["json"]
    assert "tools" in payload
    assert payload["tools"] == tools


@pytest.mark.asyncio
async def test_chat_with_tools_uses_heavy_model_by_default():
    full_body = {"message": {"content": "", "tool_calls": []}}
    mock_post = AsyncMock(return_value=_make_response(full_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client.chat_with_tools(
            messages=[{"role": "user", "content": "heavy task"}],
            tools=[],
        )

    payload = mock_post.call_args[1]["json"]
    assert payload["model"] == "gemma4:26b"


@pytest.mark.asyncio
async def test_chat_with_tools_uses_light_model_when_requested():
    full_body = {"message": {"content": "", "tool_calls": []}}
    mock_post = AsyncMock(return_value=_make_response(full_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client.chat_with_tools(
            messages=[{"role": "user", "content": "light task"}],
            tools=[],
            model="light",
        )

    payload = mock_post.call_args[1]["json"]
    assert payload["model"] == "gemma4:e4b"


# ---------------------------------------------------------------------------
# 4. _chat() — sends format param when provided
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_sends_format_param_when_provided():
    body = {"message": {"content": '{"key": "val"}'}}
    mock_post = AsyncMock(return_value=_make_response(body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        schema = {"type": "object", "properties": {"key": {"type": "string"}}}
        await client._chat(
            model="gemma4:e4b",
            messages=[{"role": "user", "content": "test"}],
            format=schema,
        )

    payload = mock_post.call_args[1]["json"]
    assert "format" in payload
    assert payload["format"] == schema


@pytest.mark.asyncio
async def test_chat_omits_format_param_when_not_provided():
    body = {"message": {"content": "plain text"}}
    mock_post = AsyncMock(return_value=_make_response(body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client._chat(
            model="gemma4:e4b",
            messages=[{"role": "user", "content": "test"}],
        )

    payload = mock_post.call_args[1]["json"]
    assert "format" not in payload


# ---------------------------------------------------------------------------
# 5. stream: False always
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_always_uses_stream_false():
    body = {"message": {"content": "ok"}}
    mock_post = AsyncMock(return_value=_make_response(body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client._chat(
            model="gemma4:e4b",
            messages=[{"role": "user", "content": "hi"}],
        )

    payload = mock_post.call_args[1]["json"]
    assert payload["stream"] is False


@pytest.mark.asyncio
async def test_chat_with_tools_always_uses_stream_false():
    full_body = {"message": {"content": "", "tool_calls": []}}
    mock_post = AsyncMock(return_value=_make_response(full_body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = _make_client()
        await client.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )

    payload = mock_post.call_args[1]["json"]
    assert payload["stream"] is False


# ---------------------------------------------------------------------------
# 6. keep_alive and host trailing-slash cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keep_alive_sent_in_payload():
    body = {"message": {"content": "ok"}}
    mock_post = AsyncMock(return_value=_make_response(body))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = MagicMock(post=mock_post)
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_ctx

        client = NativeOllamaClient(
            host="http://localhost:11434/",
            model_light="gemma4:e4b",
            model_heavy="gemma4:26b",
            keep_alive="10m",
        )
        await client._chat(model="gemma4:e4b", messages=[{"role": "user", "content": "hi"}])

    payload = mock_post.call_args[1]["json"]
    assert payload["keep_alive"] == "10m"

    url = mock_post.call_args[0][0]
    assert url == "http://localhost:11434/api/chat"
