"""Tests for MCP → CrewAI tool adapter."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from crewai.tools import BaseTool
from backend.mcp.bridge import ToolResult
from backend.mcp.config import ToolSchema
from backend.mcp.tool_adapter import create_mcp_tool, create_all_mcp_tools

def _sample_schema():
    return ToolSchema(
        name="create_reminder",
        description="Create an Apple Reminder",
        server_id="apple-mcp",
        input_schema={"type": "object", "properties": {"title": {"type": "string"}, "due_date": {"type": "string"}}, "required": ["title"]},
    )

def test_create_mcp_tool_returns_base_tool():
    bridge = MagicMock()
    tool = create_mcp_tool(_sample_schema(), bridge)
    assert isinstance(tool, BaseTool)

def test_create_mcp_tool_name():
    bridge = MagicMock()
    tool = create_mcp_tool(_sample_schema(), bridge)
    assert tool.name == "mcp_apple_mcp_create_reminder"

def test_create_mcp_tool_description():
    bridge = MagicMock()
    tool = create_mcp_tool(_sample_schema(), bridge)
    assert "Apple Reminder" in tool.description
    assert "[apple-mcp]" in tool.description

def test_create_mcp_tool_run():
    bridge = MagicMock()
    bridge.call_tool_threadsafe = MagicMock(return_value=ToolResult(success=True, output="Reminder created"))
    tool = create_mcp_tool(_sample_schema(), bridge)
    result = tool._run(title="Meeting", due_date="2026-04-09T09:00:00")
    assert result == "Reminder created"

def test_create_mcp_tool_run_error():
    bridge = MagicMock()
    bridge.call_tool_threadsafe = MagicMock(return_value=ToolResult(success=False, output="Server down"))
    tool = create_mcp_tool(_sample_schema(), bridge)
    result = tool._run(title="Meeting")
    assert "Error" in result

def test_create_all_mcp_tools():
    schemas = [
        ToolSchema(name="tool_a", description="A", server_id="s1", input_schema={}),
        ToolSchema(name="tool_b", description="B", server_id="s2", input_schema={}),
    ]
    bridge = MagicMock()
    tools = create_all_mcp_tools(schemas, bridge)
    assert len(tools) == 2
    assert all(isinstance(t, BaseTool) for t in tools)
    names = {t.name for t in tools}
    assert "mcp_s1_tool_a" in names
    assert "mcp_s2_tool_b" in names
