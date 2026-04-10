"""Tests for MCP integration in FalkensteinFlow."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.flow.falkenstein_flow import FalkensteinFlow
from backend.flow.rule_engine import RuleEngine
from backend.mcp.config import ToolSchema

def _make_deps(mcp_bridge=None):
    event_bus = MagicMock()
    native_ollama = MagicMock()
    native_ollama.quick_reply = AsyncMock(return_value="quick reply")
    native_ollama.classify = AsyncMock(return_value={"crew_type": "coder"})
    native_ollama.classify_mcp = AsyncMock(return_value={
        "server_id": "apple-mcp",
        "tool_name": "create_reminder",
        "args": {"title": "Meeting", "due_date": "2026-04-09T09:00:00"},
    })
    vault_index = MagicMock()
    vault_index.as_context.return_value = ""
    settings = MagicMock()
    settings.ollama_model = "gemma4:26b"
    settings.model_light = "gemma4:e4b"
    return dict(
        event_bus=event_bus, native_ollama=native_ollama,
        vault_index=vault_index, settings=settings, tools={},
        mcp_bridge=mcp_bridge,
    )

def test_rule_engine_detects_reminder():
    re = RuleEngine()
    result = re.route("Erinnere mich morgen um 9 ans Meeting")
    assert result.action == "direct_mcp"

def test_rule_engine_detects_light_control():
    re = RuleEngine()
    result = re.route("Mach das Licht im Wohnzimmer aus")
    assert result.action == "direct_mcp"

def test_rule_engine_detects_music():
    re = RuleEngine()
    result = re.route("Spiel etwas Jazz Musik")
    assert result.action == "direct_mcp"

@pytest.mark.asyncio
async def test_flow_accepts_mcp_bridge():
    bridge = MagicMock()
    deps = _make_deps(mcp_bridge=bridge)
    flow = FalkensteinFlow(**deps)
    assert flow.mcp_bridge is bridge

@pytest.mark.asyncio
async def test_flow_direct_mcp_calls_bridge():
    bridge = MagicMock()
    bridge.call_tool = AsyncMock(return_value=MagicMock(success=True, output="Reminder created"))
    deps = _make_deps(mcp_bridge=bridge)
    flow = FalkensteinFlow(**deps)
    flow._run_crew = AsyncMock(return_value="should not be called")
    result = await flow._handle_direct_mcp("Erinnere mich morgen um 9", chat_id=42)
    assert result is not None
    deps["native_ollama"].classify_mcp.assert_called_once()


@pytest.mark.asyncio
async def test_flow_direct_mcp_uses_heuristic_reminder_fallback():
    bridge = MagicMock()
    bridge.discover_tools = AsyncMock(return_value=[
        ToolSchema(
            name="reminders",
            description="Search, create, and open reminders",
            server_id="apple-mcp",
            input_schema={"type": "object", "properties": {"operation": {"type": "string"}, "name": {"type": "string"}, "dueDate": {"type": "string"}}},
        ),
    ])
    bridge.call_tool = AsyncMock(return_value=MagicMock(success=True, output="Reminder created"))
    deps = _make_deps(mcp_bridge=bridge)
    deps["native_ollama"].classify_mcp = AsyncMock(return_value={"server_id": None, "tool_name": None, "args": {}})
    flow = FalkensteinFlow(**deps)

    result = await flow._handle_direct_mcp("Erinnere mich morgen an Test", chat_id=42)

    assert result == "Reminder created"
    bridge.call_tool.assert_awaited_once()
    args = bridge.call_tool.await_args.args[2]
    assert args["operation"] == "create"
    assert args["name"] == "Test"
    assert "dueDate" in args


@pytest.mark.asyncio
async def test_flow_direct_mcp_music_without_tool_returns_clear_message():
    bridge = MagicMock()
    bridge.discover_tools = AsyncMock(return_value=[])
    deps = _make_deps(mcp_bridge=bridge)
    deps["native_ollama"].classify_mcp = AsyncMock(return_value={"server_id": None, "tool_name": None, "args": {}})
    flow = FalkensteinFlow(**deps)

    result = await flow._handle_direct_mcp('Spiel "lofi beats chill" auf Apple Music', chat_id=42)

    assert "kein passendes MCP-Tool" in result
