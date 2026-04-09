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
    """Build a registry with a test-server pre-seeded (no DB needed)."""
    from backend.mcp.config import ServerStatus
    reg = MCPRegistry()
    cfg = MCPServerConfig(id="test-server", name="Test Server", command="echo", args=["hello"])
    reg._servers["test-server"] = ServerStatus(config=cfg)
    reg._installed["test-server"] = False
    reg._user_configs["test-server"] = {}
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


import collections

@pytest.mark.asyncio
async def test_stderr_ring_buffer_capture():
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    handle = _ServerHandle(session=None, task=None, start_time=0.0)
    assert isinstance(handle.stderr, collections.deque)
    assert handle.stderr.maxlen == 200
    for i in range(250):
        handle.stderr.append(f"line {i}")
    assert len(handle.stderr) == 200
    assert handle.stderr[0] == "line 50"


@pytest.mark.asyncio
async def test_get_stderr_returns_snapshot():
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    handle = _ServerHandle(session=None, task=None, start_time=0.0)
    handle.stderr.extend(["a", "b", "c"])
    bridge._handles["srv"] = handle
    lines = bridge.get_stderr("srv")
    assert lines == ["a", "b", "c"]
    assert bridge.get_stderr("missing") == []


@pytest.mark.asyncio
async def test_bridge_emits_event_log(tmp_path, monkeypatch):
    from backend.mcp import bridge as bmod
    monkeypatch.setattr(bmod, "EVENT_LOG_PATH", tmp_path / "mcp_events.log")
    reg = MCPRegistry()
    b = MCPBridge(reg)
    b._emit_event("start_attempt", server_id="apple-mcp")
    log_text = (tmp_path / "mcp_events.log").read_text()
    assert '"event": "start_attempt"' in log_text
    assert '"server_id": "apple-mcp"' in log_text


@pytest.mark.asyncio
async def test_start_skips_when_not_installed(tmp_path, monkeypatch):
    from backend.mcp import installer as inst
    monkeypatch.setattr(inst, "INSTALL_ROOT", tmp_path)
    from backend.mcp.registry import MCPRegistry
    from backend.database import Database
    db = Database(tmp_path / "t.db"); await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    await reg.set_enabled(db, "apple-mcp", True)
    b = MCPBridge(reg)
    await b.start(timeout=2)
    # apple-mcp is enabled but not installed → status=not_installed, no handle
    assert reg.get("apple-mcp").status == "not_installed"
    assert "apple-mcp" not in b._handles
    await b.stop()
    await db.close()


@pytest.mark.asyncio
async def test_bridge_health_check_marks_dead_task():
    from backend.mcp.config import MCPServerConfig, ServerStatus
    reg = MCPRegistry()
    cfg = MCPServerConfig(id="x", name="X", command="nope", args=[])
    reg._servers["x"] = ServerStatus(config=cfg)
    reg._installed["x"] = False
    reg._user_configs["x"] = {}
    b = MCPBridge(reg)
    reg.update_status("x", status="running")

    async def _done():
        return None
    task = asyncio.create_task(_done())
    await task
    handle = _ServerHandle(session=MagicMock(), task=task, start_time=0.0)
    b._handles["x"] = handle
    await b._health_tick()
    assert reg.get("x").status == "error"
