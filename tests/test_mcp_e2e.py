"""End-to-end integration test for MCP flow (mocked MCP servers)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.mcp import MCPBridge, MCPRegistry, create_all_mcp_tools
from backend.mcp.config import MCPServerConfig, ToolSchema
from backend.mcp.bridge import ToolResult
from backend.flow.falkenstein_flow import FalkensteinFlow

@pytest.fixture
def mock_bridge():
    from backend.mcp.config import ServerStatus
    reg = MCPRegistry()
    cfg = MCPServerConfig(id="apple-mcp", name="Apple", command="echo", args=[])
    reg._servers["apple-mcp"] = ServerStatus(config=cfg)
    reg._installed["apple-mcp"] = False
    reg._user_configs["apple-mcp"] = {}
    bridge = MCPBridge(reg)
    bridge.call_tool = AsyncMock(return_value=ToolResult(success=True, output="Erinnerung erstellt"))
    bridge.call_tool_threadsafe = MagicMock(return_value=ToolResult(success=True, output="Erinnerung erstellt"))
    bridge.discover_tools = AsyncMock(return_value=[
        ToolSchema(name="create_reminder", description="Create reminder", server_id="apple-mcp",
                   input_schema={"type": "object", "properties": {"title": {"type": "string"}}}),
    ])
    return bridge

@pytest.fixture
def flow(mock_bridge):
    event_bus = MagicMock()
    native_ollama = MagicMock()
    native_ollama.quick_reply = AsyncMock(return_value="ok")
    native_ollama.classify = AsyncMock(return_value={"crew_type": "ops"})
    native_ollama.classify_mcp = AsyncMock(return_value={
        "server_id": "apple-mcp",
        "tool_name": "create_reminder",
        "args": {"title": "Meeting", "due_date": "2026-04-09T09:00:00"},
    })
    vault_index = MagicMock()
    vault_index.as_context.return_value = ""
    settings = MagicMock()
    settings.ollama_model = "test"
    settings.model_light = "test"
    return FalkensteinFlow(
        event_bus=event_bus, native_ollama=native_ollama,
        vault_index=vault_index, settings=settings, tools={},
        mcp_bridge=mock_bridge,
    )

@pytest.mark.asyncio
async def test_reminder_e2e(flow, mock_bridge):
    """'Erinnere mich' should route through direct_mcp and call apple-mcp."""
    result = await flow.handle_message("Erinnere mich morgen um 9 ans Meeting", chat_id=42)
    assert result is not None
    mock_bridge.call_tool.assert_called_once_with(
        "apple-mcp", "create_reminder",
        {"title": "Meeting", "due_date": "2026-04-09T09:00:00"},
    )

def test_mcp_tools_as_crewai(mock_bridge):
    """MCP tools should be convertible to CrewAI BaseTool."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        schemas = loop.run_until_complete(mock_bridge.discover_tools())
        tools = create_all_mcp_tools(schemas, mock_bridge)
        assert len(tools) == 1
        assert tools[0].name == "mcp_apple_mcp_create_reminder"
        result = tools[0]._run(title="Test")
        assert result == "Erinnerung erstellt"
    finally:
        loop.close()
