"""Tests for MCPBridge — server lifecycle and tool execution."""
from __future__ import annotations
import asyncio
import concurrent.futures
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.mcp.bridge import MCPBridge, DEFAULT_START_TIMEOUT, ToolResult, _ServerHandle
from backend.mcp.config import MCPServerConfig, ToolSchema
from backend.mcp.registry import MCPRegistry

@pytest.fixture
def registry():
    reg = MCPRegistry()
    reg.register(MCPServerConfig(id="test-server", name="Test Server", command="echo", args=["hello"]))
    return reg

@pytest.fixture
def bridge(registry):
    return MCPBridge(registry)

def test_bridge_creation(bridge):
    assert bridge is not None
    assert bridge.registry is not None

def test_bridge_servers_property(bridge):
    servers = bridge.servers
    assert len(servers) == 1
    assert servers[0].config.id == "test-server"

@pytest.mark.asyncio
async def test_bridge_start_calls_start_server(bridge):
    with patch.object(bridge, "_start_server", new_callable=AsyncMock) as mock_start:
        await bridge.start()
        mock_start.assert_called_once_with("test-server", DEFAULT_START_TIMEOUT)

@pytest.mark.asyncio
async def test_bridge_stop(bridge):
    with patch.object(bridge, "_stop_server", new_callable=AsyncMock) as mock_stop:
        from backend.mcp.bridge import _ServerHandle
        bridge._handles["test-server"] = MagicMock(spec=_ServerHandle)
        await bridge.stop()
        mock_stop.assert_called_once_with("test-server")

@pytest.mark.asyncio
async def test_bridge_list_tools_no_handle(bridge):
    tools = await bridge.list_tools("test-server")
    assert tools == []

@pytest.mark.asyncio
async def test_bridge_call_tool_no_handle(bridge):
    result = await bridge.call_tool("test-server", "some_tool", {})
    assert result.success is False
    assert "not connected" in result.output.lower()

@pytest.mark.asyncio
async def test_bridge_restart_server(bridge):
    with patch.object(bridge, "_stop_server", new_callable=AsyncMock) as mock_stop, \
         patch.object(bridge, "_start_server", new_callable=AsyncMock) as mock_start:
        await bridge.restart_server("test-server")
        mock_stop.assert_called_once_with("test-server")
        mock_start.assert_called_once_with("test-server", DEFAULT_START_TIMEOUT)

@pytest.mark.asyncio
async def test_bridge_toggle_server(bridge):
    with patch.object(bridge, "_stop_server", new_callable=AsyncMock) as mock_stop:
        await bridge.toggle_server("test-server", False)
        assert bridge.registry.get("test-server").config.enabled is False
        mock_stop.assert_called_once()

@pytest.mark.asyncio
async def test_bridge_discover_tools_aggregates(bridge):
    from backend.mcp.bridge import _ServerHandle
    handle = MagicMock(spec=_ServerHandle)
    handle.tools = [
        ToolSchema(name="test_tool", description="A test", server_id="test-server", input_schema={"type": "object"})
    ]
    bridge._handles["test-server"] = handle
    bridge.registry.update_status("test-server", status="running")
    tools = await bridge.discover_tools()
    assert len(tools) == 1
    assert tools[0].name == "test_tool"
    assert tools[0].server_id == "test-server"


class _FakeSessionResult:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.isError = False


@pytest.mark.asyncio
async def test_call_tool_threadsafe_from_other_thread():
    """REGRESSION: CrewAI calls run in a thread pool; the bridge must
    handle calls from threads other than the main loop. Previously this
    created a fresh event loop and died with 'attached to different loop'."""
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=_FakeSessionResult("ok"))
    handle = _ServerHandle(session=fake_session, task=None, start_time=0.0)
    bridge._handles["fakesrv"] = handle

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool,
            lambda: bridge.call_tool_threadsafe("fakesrv", "ping", {"x": 1}),
        )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.output == "ok"
    fake_session.call_tool.assert_awaited_once_with("ping", arguments={"x": 1})


@pytest.mark.asyncio
async def test_call_tool_threadsafe_unknown_server():
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    bridge._main_loop = asyncio.get_running_loop()
    result = bridge.call_tool_threadsafe("nope", "x", {})
    assert result.success is False
    assert "not connected" in result.output.lower()
