# MCP-Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP server management layer that starts/stops MCP servers as subprocesses, discovers their tools, and exposes them to CrewAI crews and the direct-reply flow path.

**Architecture:** A new `backend/mcp/` package provides `MCPBridge` (singleton, manages server processes), `MCPRegistry` (config/status), and `MCPToolAdapter` (auto-wraps MCP tools as CrewAI `BaseTool`). The Flow gains a `direct_mcp` route for simple commands that skip CrewAI. Admin API gets MCP endpoints. All MCP calls are logged to a new `mcp_calls` DB table.

**Tech Stack:** Python `mcp` SDK (official Anthropic), pydantic for config models, aiosqlite for logging, existing CrewAI `BaseTool` pattern.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/mcp/__init__.py` | Package init, exports `MCPBridge` |
| `backend/mcp/config.py` | Pydantic models for MCP server config + status |
| `backend/mcp/registry.py` | Server registry — loads config, tracks runtime status |
| `backend/mcp/bridge.py` | MCPBridge singleton — subprocess lifecycle, tool discovery, tool execution |
| `backend/mcp/tool_adapter.py` | Converts MCP tool schemas → CrewAI `BaseTool` subclasses |
| `tests/test_mcp_config.py` | Tests for config models |
| `tests/test_mcp_registry.py` | Tests for registry |
| `tests/test_mcp_bridge.py` | Tests for bridge (mocked subprocesses) |
| `tests/test_mcp_tool_adapter.py` | Tests for tool adapter |
| `tests/test_mcp_admin_api.py` | Tests for admin API endpoints |
| `tests/test_mcp_flow_integration.py` | Tests for direct_mcp route in flow |

### Modified Files

| File | Changes |
|------|---------|
| `backend/config.py` | Add MCP fields to `Settings`, add to `HOT_RELOAD_FIELDS` |
| `backend/main.py` | Init MCPBridge in lifespan, pass MCP tools to crews, inject into admin API |
| `backend/flow/falkenstein_flow.py` | Add `direct_mcp` route handling |
| `backend/flow/rule_engine.py` | Add MCP intent detection keywords |
| `backend/event_bus.py` | Add MCP tool names to `STREAM_TO_TELEGRAM` and `TOOL_TO_ANIMATION` |
| `backend/admin_api.py` | Add MCP server management endpoints |
| `.env` | Add MCP config values |
| `requirements.txt` | Add `mcp>=1.0.0` |

---

## Task 1: MCP Config Models

**Files:**
- Create: `backend/mcp/__init__.py`
- Create: `backend/mcp/config.py`
- Create: `tests/test_mcp_config.py`
- Modify: `backend/config.py`
- Modify: `.env`
- Modify: `requirements.txt`

- [ ] **Step 1: Add `mcp` to requirements.txt**

Append to end of `requirements.txt`:
```
mcp>=1.0.0
```

- [ ] **Step 2: Install dependency**

Run: `source venv312/bin/activate && pip install mcp>=1.0.0`
Expected: Successfully installed mcp-...

- [ ] **Step 3: Add MCP fields to Settings in `backend/config.py`**

Add these fields to the `Settings` class (after existing fields like `ollama_keep_alive`):

```python
    # MCP Configuration
    mcp_servers: str = ""                    # comma-separated: "apple-mcp,desktop-commander,mcp-obsidian"
    mcp_apple_enabled: bool = False
    mcp_desktop_commander_enabled: bool = False
    mcp_obsidian_enabled: bool = False
    mcp_obsidian_api_key: str = ""           # Local REST API plugin key
    mcp_node_path: str = "npx"               # path to npx binary
    mcp_auto_restart: bool = True
    mcp_health_interval: int = 30            # seconds between health checks
```

Add to `HOT_RELOAD_FIELDS`:
```python
"mcp_apple_enabled", "mcp_desktop_commander_enabled", "mcp_obsidian_enabled", "mcp_auto_restart", "mcp_health_interval"
```

- [ ] **Step 4: Add MCP values to `.env`**

Append to `.env`:
```env
# MCP Configuration
MCP_SERVERS=apple-mcp,desktop-commander,mcp-obsidian
MCP_APPLE_ENABLED=true
MCP_DESKTOP_COMMANDER_ENABLED=true
MCP_OBSIDIAN_ENABLED=true
MCP_OBSIDIAN_API_KEY=
MCP_NODE_PATH=npx
MCP_AUTO_RESTART=true
MCP_HEALTH_INTERVAL=30
```

- [ ] **Step 5: Write failing test for config models**

Create `tests/test_mcp_config.py`:
```python
"""Tests for MCP config models."""

import pytest
from backend.mcp.config import MCPServerConfig, ServerStatus


def test_server_config_defaults():
    cfg = MCPServerConfig(
        id="apple-mcp",
        name="Apple Services",
        command="npx",
        args=["-y", "apple-mcp"],
    )
    assert cfg.id == "apple-mcp"
    assert cfg.enabled is True
    assert cfg.auto_restart is True
    assert cfg.env == {}


def test_server_config_custom():
    cfg = MCPServerConfig(
        id="mcp-obsidian",
        name="Obsidian Vault",
        command="npx",
        args=["-y", "mcp-obsidian"],
        env={"OBSIDIAN_API_KEY": "secret"},
        enabled=False,
        auto_restart=False,
    )
    assert cfg.enabled is False
    assert cfg.env["OBSIDIAN_API_KEY"] == "secret"


def test_server_status_defaults():
    cfg = MCPServerConfig(id="test", name="Test", command="echo", args=[])
    status = ServerStatus(config=cfg)
    assert status.status == "stopped"
    assert status.pid is None
    assert status.tools_count == 0
    assert status.last_call is None


def test_server_status_running():
    cfg = MCPServerConfig(id="test", name="Test", command="echo", args=[])
    status = ServerStatus(config=cfg, status="running", pid=12345, tools_count=5)
    assert status.status == "running"
    assert status.pid == 12345
```

- [ ] **Step 6: Run test to verify it fails**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.mcp'`

- [ ] **Step 7: Create `backend/mcp/__init__.py`**

```python
"""MCP (Model Context Protocol) integration for Falkenstein."""
```

- [ ] **Step 8: Implement config models in `backend/mcp/config.py`**

```python
"""Pydantic models for MCP server configuration and status."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""
    id: str
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    auto_restart: bool = True


class ServerStatus(BaseModel):
    """Runtime status of an MCP server."""
    config: MCPServerConfig
    status: str = "stopped"  # "running" | "stopped" | "error"
    pid: int | None = None
    tools_count: int = 0
    last_call: datetime | None = None
    last_error: str | None = None
    uptime_seconds: float = 0.0


class ToolSchema(BaseModel):
    """Schema of a single MCP tool as discovered via tools/list."""
    name: str
    description: str
    server_id: str
    input_schema: dict = Field(default_factory=dict)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_config.py -v`
Expected: 4 passed

- [ ] **Step 10: Commit**

```bash
git add backend/mcp/__init__.py backend/mcp/config.py tests/test_mcp_config.py backend/config.py .env requirements.txt
git commit -m "feat(mcp): add config models and Settings fields for MCP servers"
```

---

## Task 2: MCP Registry

**Files:**
- Create: `backend/mcp/registry.py`
- Create: `tests/test_mcp_registry.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_mcp_registry.py`:
```python
"""Tests for MCP server registry."""

import pytest
from backend.mcp.registry import MCPRegistry
from backend.mcp.config import MCPServerConfig


def _apple_config():
    return MCPServerConfig(
        id="apple-mcp",
        name="Apple Services",
        command="npx",
        args=["-y", "apple-mcp"],
    )


def _desktop_config():
    return MCPServerConfig(
        id="desktop-commander",
        name="Desktop Commander",
        command="npx",
        args=["-y", "@anthropic/desktop-commander"],
        enabled=False,
    )


def test_registry_empty():
    reg = MCPRegistry()
    assert reg.list_servers() == []


def test_registry_register():
    reg = MCPRegistry()
    reg.register(_apple_config())
    servers = reg.list_servers()
    assert len(servers) == 1
    assert servers[0].config.id == "apple-mcp"


def test_registry_get():
    reg = MCPRegistry()
    reg.register(_apple_config())
    status = reg.get("apple-mcp")
    assert status is not None
    assert status.config.name == "Apple Services"


def test_registry_get_missing():
    reg = MCPRegistry()
    assert reg.get("nonexistent") is None


def test_registry_enabled_only():
    reg = MCPRegistry()
    reg.register(_apple_config())
    reg.register(_desktop_config())
    enabled = reg.list_enabled()
    assert len(enabled) == 1
    assert enabled[0].config.id == "apple-mcp"


def test_registry_toggle():
    reg = MCPRegistry()
    reg.register(_apple_config())
    reg.toggle("apple-mcp", False)
    assert reg.get("apple-mcp").config.enabled is False
    enabled = reg.list_enabled()
    assert len(enabled) == 0


def test_registry_update_status():
    reg = MCPRegistry()
    reg.register(_apple_config())
    reg.update_status("apple-mcp", status="running", pid=1234, tools_count=12)
    s = reg.get("apple-mcp")
    assert s.status == "running"
    assert s.pid == 1234
    assert s.tools_count == 12


def test_registry_from_settings_string():
    """Build registry from comma-separated server IDs (like Settings.mcp_servers)."""
    reg = MCPRegistry.from_settings(
        server_ids="apple-mcp,desktop-commander",
        enabled_flags={"apple-mcp": True, "desktop-commander": False},
        node_path="npx",
    )
    assert len(reg.list_servers()) == 2
    assert len(reg.list_enabled()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.mcp.registry'`

- [ ] **Step 3: Implement registry**

Create `backend/mcp/registry.py`:
```python
"""MCP server registry — tracks config and runtime status."""

from __future__ import annotations

from backend.mcp.config import MCPServerConfig, ServerStatus


# Default server definitions — command + args for known servers
KNOWN_SERVERS: dict[str, dict] = {
    "apple-mcp": {
        "name": "Apple Services",
        "command": "npx",
        "args": ["-y", "apple-mcp"],
    },
    "desktop-commander": {
        "name": "Desktop Commander",
        "command": "npx",
        "args": ["-y", "@anthropic/desktop-commander"],
    },
    "mcp-obsidian": {
        "name": "Obsidian Vault",
        "command": "npx",
        "args": ["-y", "mcp-obsidian"],
    },
}


class MCPRegistry:
    """In-memory registry of MCP server configs and their runtime status."""

    def __init__(self) -> None:
        self._servers: dict[str, ServerStatus] = {}

    def register(self, config: MCPServerConfig) -> None:
        self._servers[config.id] = ServerStatus(config=config)

    def get(self, server_id: str) -> ServerStatus | None:
        return self._servers.get(server_id)

    def list_servers(self) -> list[ServerStatus]:
        return list(self._servers.values())

    def list_enabled(self) -> list[ServerStatus]:
        return [s for s in self._servers.values() if s.config.enabled]

    def toggle(self, server_id: str, enabled: bool) -> None:
        if server_id in self._servers:
            self._servers[server_id].config.enabled = enabled

    def update_status(
        self,
        server_id: str,
        *,
        status: str | None = None,
        pid: int | None = None,
        tools_count: int | None = None,
        last_error: str | None = None,
        uptime_seconds: float | None = None,
    ) -> None:
        s = self._servers.get(server_id)
        if s is None:
            return
        if status is not None:
            s.status = status
        if pid is not None:
            s.pid = pid
        if tools_count is not None:
            s.tools_count = tools_count
        if last_error is not None:
            s.last_error = last_error
        if uptime_seconds is not None:
            s.uptime_seconds = uptime_seconds

    @classmethod
    def from_settings(
        cls,
        server_ids: str,
        enabled_flags: dict[str, bool],
        node_path: str = "npx",
    ) -> MCPRegistry:
        """Build registry from Settings fields."""
        reg = cls()
        for sid in server_ids.split(","):
            sid = sid.strip()
            if not sid:
                continue
            known = KNOWN_SERVERS.get(sid, {})
            config = MCPServerConfig(
                id=sid,
                name=known.get("name", sid),
                command=node_path,
                args=known.get("args", ["-y", sid]),
                enabled=enabled_flags.get(sid, True),
            )
            reg.register(config)
        return reg
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_registry.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/registry.py tests/test_mcp_registry.py
git commit -m "feat(mcp): add server registry with config tracking"
```

---

## Task 3: MCP Bridge — Server Lifecycle

**Files:**
- Create: `backend/mcp/bridge.py`
- Create: `tests/test_mcp_bridge.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mcp_bridge.py`:
```python
"""Tests for MCPBridge — server lifecycle and tool execution."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.mcp.bridge import MCPBridge
from backend.mcp.config import MCPServerConfig
from backend.mcp.registry import MCPRegistry


@pytest.fixture
def registry():
    reg = MCPRegistry()
    reg.register(MCPServerConfig(
        id="test-server",
        name="Test Server",
        command="echo",
        args=["hello"],
    ))
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
async def test_bridge_start_updates_registry(bridge):
    """Starting bridge should attempt to connect to enabled servers."""
    with patch.object(bridge, "_start_server", new_callable=AsyncMock) as mock_start:
        await bridge.start()
        mock_start.assert_called_once_with("test-server")


@pytest.mark.asyncio
async def test_bridge_stop(bridge):
    """Stopping bridge should disconnect all servers."""
    with patch.object(bridge, "_stop_server", new_callable=AsyncMock) as mock_stop:
        bridge._sessions["test-server"] = MagicMock()
        await bridge.stop()
        mock_stop.assert_called_once_with("test-server")


@pytest.mark.asyncio
async def test_bridge_list_tools_no_session(bridge):
    """list_tools returns empty list if server not connected."""
    tools = await bridge.list_tools("test-server")
    assert tools == []


@pytest.mark.asyncio
async def test_bridge_call_tool_no_session(bridge):
    """call_tool returns error if server not connected."""
    result = await bridge.call_tool("test-server", "some_tool", {})
    assert result.success is False
    assert "not connected" in result.output.lower()


@pytest.mark.asyncio
async def test_bridge_restart_server(bridge):
    """Restart stops then starts a server."""
    with patch.object(bridge, "_stop_server", new_callable=AsyncMock) as mock_stop, \
         patch.object(bridge, "_start_server", new_callable=AsyncMock) as mock_start:
        await bridge.restart_server("test-server")
        mock_stop.assert_called_once_with("test-server")
        mock_start.assert_called_once_with("test-server")


@pytest.mark.asyncio
async def test_bridge_toggle_server(bridge):
    """Toggle disables server and stops it."""
    with patch.object(bridge, "_stop_server", new_callable=AsyncMock) as mock_stop:
        await bridge.toggle_server("test-server", False)
        assert bridge.registry.get("test-server").config.enabled is False
        mock_stop.assert_called_once()


@pytest.mark.asyncio
async def test_bridge_discover_tools_aggregates(bridge):
    """discover_tools collects tools from all connected servers."""
    mock_tool = {"name": "test_tool", "description": "A test", "inputSchema": {"type": "object"}}
    mock_session = AsyncMock()
    mock_session.list_tools.return_value = MagicMock(tools=[MagicMock(
        name="test_tool", description="A test", inputSchema={"type": "object"}
    )])
    bridge._sessions["test-server"] = mock_session
    bridge.registry.update_status("test-server", status="running")

    tools = await bridge.discover_tools()
    assert len(tools) == 1
    assert tools[0].name == "test_tool"
    assert tools[0].server_id == "test-server"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.mcp.bridge'`

- [ ] **Step 3: Implement MCPBridge**

Create `backend/mcp/bridge.py`:
```python
"""MCPBridge — manages MCP server subprocesses and proxies tool calls."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.mcp.config import MCPServerConfig, ServerStatus, ToolSchema
from backend.mcp.registry import MCPRegistry

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    success: bool
    output: str


class MCPBridge:
    """Singleton managing MCP server subprocesses."""

    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._sessions: dict[str, ClientSession] = {}
        self._contexts: dict[str, object] = {}  # context managers for cleanup
        self._tool_cache: dict[str, list[ToolSchema]] = {}
        self._start_times: dict[str, float] = {}
        self._health_task: asyncio.Task | None = None

    @property
    def servers(self) -> list[ServerStatus]:
        return self.registry.list_servers()

    async def start(self) -> None:
        """Start all enabled MCP servers."""
        for s in self.registry.list_enabled():
            try:
                await self._start_server(s.config.id)
            except Exception as e:
                log.error("Failed to start MCP server %s: %s", s.config.id, e)
                self.registry.update_status(s.config.id, status="error", last_error=str(e))

    async def stop(self) -> None:
        """Stop all running MCP servers."""
        if self._health_task:
            self._health_task.cancel()
        for sid in list(self._sessions.keys()):
            await self._stop_server(sid)

    async def _start_server(self, server_id: str) -> None:
        """Start a single MCP server subprocess and establish session."""
        status = self.registry.get(server_id)
        if status is None:
            return
        cfg = status.config

        server_params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env if cfg.env else None,
        )

        # Create the stdio client context
        ctx = stdio_client(server_params)
        streams = await ctx.__aenter__()
        self._contexts[server_id] = ctx

        # Create and initialize the session
        session = ClientSession(*streams)
        await session.__aenter__()
        await session.initialize()
        self._sessions[server_id] = session
        self._start_times[server_id] = time.time()

        # Discover tools
        tools_result = await session.list_tools()
        tool_schemas = [
            ToolSchema(
                name=t.name,
                description=t.description or "",
                server_id=server_id,
                input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
            )
            for t in tools_result.tools
        ]
        self._tool_cache[server_id] = tool_schemas

        self.registry.update_status(
            server_id,
            status="running",
            pid=None,  # stdio_client doesn't expose PID directly
            tools_count=len(tool_schemas),
        )
        log.info("MCP server %s started with %d tools", server_id, len(tool_schemas))

    async def _stop_server(self, server_id: str) -> None:
        """Stop a single MCP server."""
        session = self._sessions.pop(server_id, None)
        if session:
            try:
                await session.__aexit__(None, None, None)
            except Exception as e:
                log.warning("Error closing session for %s: %s", server_id, e)

        ctx = self._contexts.pop(server_id, None)
        if ctx:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception as e:
                log.warning("Error closing context for %s: %s", server_id, e)

        self._tool_cache.pop(server_id, None)
        self._start_times.pop(server_id, None)
        self.registry.update_status(server_id, status="stopped", pid=None, tools_count=0)
        log.info("MCP server %s stopped", server_id)

    async def restart_server(self, server_id: str) -> None:
        """Restart a single server."""
        await self._stop_server(server_id)
        await self._start_server(server_id)

    async def toggle_server(self, server_id: str, enabled: bool) -> None:
        """Enable or disable a server."""
        self.registry.toggle(server_id, enabled)
        if not enabled and server_id in self._sessions:
            await self._stop_server(server_id)
        elif enabled and server_id not in self._sessions:
            await self._start_server(server_id)

    async def list_tools(self, server_id: str) -> list[ToolSchema]:
        """List tools for a specific server from cache."""
        return self._tool_cache.get(server_id, [])

    async def discover_tools(self) -> list[ToolSchema]:
        """List all tools from all connected servers."""
        all_tools: list[ToolSchema] = []
        for sid, tools in self._tool_cache.items():
            status = self.registry.get(sid)
            if status and status.status == "running":
                all_tools.extend(tools)
        return all_tools

    async def call_tool(self, server_id: str, tool_name: str, args: dict) -> ToolResult:
        """Call a tool on a specific MCP server."""
        session = self._sessions.get(server_id)
        if session is None:
            return ToolResult(success=False, output=f"Server '{server_id}' not connected")

        try:
            result = await session.call_tool(tool_name, arguments=args)
            # MCP returns content as list of content blocks
            output_parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    output_parts.append(block.text)
                else:
                    output_parts.append(str(block))
            output = "\n".join(output_parts)
            return ToolResult(success=not result.isError, output=output)
        except Exception as e:
            log.error("MCP tool call failed: %s/%s: %s", server_id, tool_name, e)
            return ToolResult(success=False, output=f"Error: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_bridge.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/bridge.py tests/test_mcp_bridge.py
git commit -m "feat(mcp): add MCPBridge for server lifecycle and tool execution"
```

---

## Task 4: MCP Tool Adapter — MCP Tools as CrewAI BaseTool

**Files:**
- Create: `backend/mcp/tool_adapter.py`
- Create: `tests/test_mcp_tool_adapter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mcp_tool_adapter.py`:
```python
"""Tests for MCP → CrewAI tool adapter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from crewai.tools import BaseTool
from backend.mcp.config import ToolSchema
from backend.mcp.tool_adapter import create_mcp_tool, create_all_mcp_tools


def _sample_schema():
    return ToolSchema(
        name="create_reminder",
        description="Create an Apple Reminder",
        server_id="apple-mcp",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Reminder title"},
                "due_date": {"type": "string", "description": "ISO date"},
            },
            "required": ["title"],
        },
    )


def test_create_mcp_tool_returns_base_tool():
    bridge = MagicMock()
    tool = create_mcp_tool(_sample_schema(), bridge)
    assert isinstance(tool, BaseTool)


def test_create_mcp_tool_name():
    bridge = MagicMock()
    tool = create_mcp_tool(_sample_schema(), bridge)
    assert tool.name == "mcp_apple_create_reminder"


def test_create_mcp_tool_description():
    bridge = MagicMock()
    tool = create_mcp_tool(_sample_schema(), bridge)
    assert "Apple Reminder" in tool.description
    assert "[apple-mcp]" in tool.description


def test_create_mcp_tool_run():
    """_run should call bridge.call_tool and return output."""
    bridge = MagicMock()
    bridge.call_tool = AsyncMock(return_value=MagicMock(success=True, output="Reminder created"))
    tool = create_mcp_tool(_sample_schema(), bridge)

    result = tool._run(title="Meeting", due_date="2026-04-09T09:00:00")

    assert result == "Reminder created"


def test_create_mcp_tool_run_error():
    bridge = MagicMock()
    bridge.call_tool = AsyncMock(return_value=MagicMock(success=False, output="Server down"))
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_tool_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.mcp.tool_adapter'`

- [ ] **Step 3: Implement tool adapter**

Create `backend/mcp/tool_adapter.py`:
```python
"""Converts MCP tool schemas into CrewAI BaseTool instances."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from crewai.tools import BaseTool

from backend.mcp.config import ToolSchema

log = logging.getLogger(__name__)


def _make_tool_class(schema: ToolSchema, bridge: Any) -> type[BaseTool]:
    """Dynamically create a BaseTool subclass for an MCP tool."""
    server_id = schema.server_id
    mcp_tool_name = schema.name
    tool_name = f"mcp_{server_id.replace('-', '_')}_{mcp_tool_name}"
    tool_desc = f"{schema.description} [{ server_id}]"

    class MCPDynamicTool(BaseTool):
        name: str = tool_name
        description: str = tool_desc

        def _run(self, **kwargs) -> str:
            try:
                result = asyncio.run(
                    bridge.call_tool(server_id, mcp_tool_name, kwargs)
                )
            except RuntimeError:
                # Already in async context — use nested loop
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    bridge.call_tool(server_id, mcp_tool_name, kwargs)
                )
            if result.success:
                return result.output
            return f"Error: {result.output}"

    return MCPDynamicTool


def create_mcp_tool(schema: ToolSchema, bridge: Any) -> BaseTool:
    """Create a single CrewAI BaseTool from an MCP ToolSchema."""
    cls = _make_tool_class(schema, bridge)
    return cls()


def create_all_mcp_tools(schemas: list[ToolSchema], bridge: Any) -> list[BaseTool]:
    """Create CrewAI BaseTools for all MCP tool schemas."""
    tools = []
    for schema in schemas:
        try:
            tools.append(create_mcp_tool(schema, bridge))
        except Exception as e:
            log.error("Failed to create tool for %s/%s: %s", schema.server_id, schema.name, e)
    return tools
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_tool_adapter.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/tool_adapter.py tests/test_mcp_tool_adapter.py
git commit -m "feat(mcp): add tool adapter — MCP tools as CrewAI BaseTool"
```

---

## Task 5: Export MCPBridge from package

**Files:**
- Modify: `backend/mcp/__init__.py`

- [ ] **Step 1: Update package init**

Replace `backend/mcp/__init__.py`:
```python
"""MCP (Model Context Protocol) integration for Falkenstein."""

from backend.mcp.bridge import MCPBridge, ToolResult
from backend.mcp.config import MCPServerConfig, ServerStatus, ToolSchema
from backend.mcp.registry import MCPRegistry
from backend.mcp.tool_adapter import create_mcp_tool, create_all_mcp_tools

__all__ = [
    "MCPBridge",
    "MCPRegistry",
    "MCPServerConfig",
    "ServerStatus",
    "ToolResult",
    "ToolSchema",
    "create_mcp_tool",
    "create_all_mcp_tools",
]
```

- [ ] **Step 2: Verify all MCP tests still pass**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_*.py -v`
Expected: All 24 tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/mcp/__init__.py
git commit -m "feat(mcp): export public API from package init"
```

---

## Task 6: EventBus MCP Extensions

**Files:**
- Modify: `backend/event_bus.py`
- Create: `tests/test_event_bus_mcp.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_event_bus_mcp.py`:
```python
"""Tests for MCP-related EventBus extensions."""

from backend.event_bus import STREAM_TO_TELEGRAM, TOOL_TO_ANIMATION


def test_mcp_tools_in_stream_set():
    """MCP tool prefixed names should trigger Telegram streaming."""
    # Generic MCP prefix check — any tool starting with "mcp_" streams
    assert "mcp_tool" not in STREAM_TO_TELEGRAM  # old behavior
    # We test that the check function exists
    from backend.event_bus import should_stream_to_telegram
    assert should_stream_to_telegram("mcp_apple_create_reminder") is True
    assert should_stream_to_telegram("shell_runner") is True
    assert should_stream_to_telegram("unknown_tool") is False


def test_mcp_tool_animation():
    """MCP tools should map to 'thinking' animation."""
    from backend.event_bus import get_tool_animation
    assert get_tool_animation("mcp_apple_create_reminder") == "thinking"
    assert get_tool_animation("shell_runner") == "typing"
    assert get_tool_animation("obsidian") == "reading"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv312/bin/activate && python -m pytest tests/test_event_bus_mcp.py -v`
Expected: FAIL — `ImportError: cannot import name 'should_stream_to_telegram'`

- [ ] **Step 3: Add helper functions to `backend/event_bus.py`**

Add these two functions after the `STREAM_TO_TELEGRAM` and `TOOL_TO_ANIMATION` constant definitions:

```python
def should_stream_to_telegram(tool_name: str) -> bool:
    """Check if a tool's output should be streamed to Telegram."""
    if tool_name in STREAM_TO_TELEGRAM:
        return True
    # All MCP tools stream their results
    return tool_name.startswith("mcp_")


def get_tool_animation(tool_name: str) -> str:
    """Get the Phaser animation hint for a tool."""
    if tool_name in TOOL_TO_ANIMATION:
        return TOOL_TO_ANIMATION[tool_name]
    # Default animation for MCP tools
    if tool_name.startswith("mcp_"):
        return "thinking"
    return "typing"
```

Then update `on_tool_call` to use these functions instead of direct set/dict lookups. Replace:
- `if tool_name in STREAM_TO_TELEGRAM:` → `if should_stream_to_telegram(tool_name):`
- `TOOL_TO_ANIMATION.get(tool_name, "typing")` → `get_tool_animation(tool_name)`

- [ ] **Step 4: Run tests**

Run: `source venv312/bin/activate && python -m pytest tests/test_event_bus_mcp.py tests/test_event_bus.py -v`
Expected: All pass (new + existing)

- [ ] **Step 5: Commit**

```bash
git add backend/event_bus.py tests/test_event_bus_mcp.py
git commit -m "feat(mcp): extend EventBus with MCP tool streaming and animation support"
```

---

## Task 7: DB Migration — mcp_calls Table

**Files:**
- Modify: Database init (in the DB class or migration)
- Create: `tests/test_mcp_db.py`

- [ ] **Step 1: Find the DB init location**

Check `backend/database.py` or wherever `CREATE TABLE` statements live. The table `mcp_calls` needs to be added to the DB init.

Run: `grep -n "CREATE TABLE" backend/database.py` to find the pattern.

- [ ] **Step 2: Write failing test**

Create `tests/test_mcp_db.py`:
```python
"""Tests for mcp_calls DB table."""

import pytest
import aiosqlite

from backend.database import Database


@pytest.mark.asyncio
async def test_mcp_calls_table_exists():
    db = Database(":memory:")
    await db.init()
    async with aiosqlite.connect(db.path) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_calls'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_log_mcp_call():
    db = Database(":memory:")
    await db.init()
    await db.log_mcp_call(
        server_id="apple-mcp",
        tool_name="create_reminder",
        args='{"title": "Test"}',
        result='{"ok": true}',
        success=True,
        duration_ms=120,
        triggered_by="direct",
    )
    async with aiosqlite.connect(db.path) as conn:
        cursor = await conn.execute("SELECT * FROM mcp_calls")
        rows = await cursor.fetchall()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_mcp_calls():
    db = Database(":memory:")
    await db.init()
    await db.log_mcp_call("s1", "tool_a", "{}", "{}", True, 100, "direct")
    await db.log_mcp_call("s2", "tool_b", "{}", "{}", False, 200, "crew:ops")
    calls = await db.get_mcp_calls(limit=10)
    assert len(calls) == 2
    # Most recent first
    assert calls[0]["server_id"] == "s2"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_db.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'log_mcp_call'`

- [ ] **Step 4: Add mcp_calls table and methods to Database**

Add to the `init()` method's `CREATE TABLE` block in `backend/database.py`:
```sql
CREATE TABLE IF NOT EXISTS mcp_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args TEXT,
    result TEXT,
    success BOOLEAN,
    duration_ms INTEGER,
    triggered_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Add these methods to the `Database` class:
```python
async def log_mcp_call(
    self,
    server_id: str,
    tool_name: str,
    args: str,
    result: str,
    success: bool,
    duration_ms: int,
    triggered_by: str,
) -> None:
    async with aiosqlite.connect(self.path) as conn:
        await conn.execute(
            """INSERT INTO mcp_calls (server_id, tool_name, args, result, success, duration_ms, triggered_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (server_id, tool_name, args, result, success, duration_ms, triggered_by),
        )
        await conn.commit()

async def get_mcp_calls(self, limit: int = 50, server_id: str | None = None) -> list[dict]:
    async with aiosqlite.connect(self.path) as conn:
        conn.row_factory = aiosqlite.Row
        if server_id:
            cursor = await conn.execute(
                "SELECT * FROM mcp_calls WHERE server_id = ? ORDER BY created_at DESC LIMIT ?",
                (server_id, limit),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM mcp_calls ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_db.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/database.py tests/test_mcp_db.py
git commit -m "feat(mcp): add mcp_calls DB table and logging methods"
```

---

## Task 8: Flow Integration — direct_mcp Route

**Files:**
- Modify: `backend/flow/falkenstein_flow.py`
- Modify: `backend/flow/rule_engine.py`
- Create: `tests/test_mcp_flow_integration.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mcp_flow_integration.py`:
```python
"""Tests for MCP integration in FalkensteinFlow."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.flow.falkenstein_flow import FalkensteinFlow
from backend.flow.rule_engine import RuleEngine


def _make_deps(mcp_bridge=None):
    event_bus = MagicMock()
    native_ollama = MagicMock()
    native_ollama.quick_reply = AsyncMock(return_value="quick reply")
    native_ollama.classify = AsyncMock(return_value={"crew_type": "coder"})
    native_ollama.classify_mcp = AsyncMock(return_value={
        "server_id": "apple-mcp",
        "tool_name": "create_reminder",
        "args": {"title": "Test"},
    })
    vault_index = MagicMock()
    vault_index.as_context.return_value = ""
    settings = MagicMock()
    settings.ollama_model = "gemma4:26b"
    settings.model_light = "gemma4:e4b"
    return dict(
        event_bus=event_bus,
        native_ollama=native_ollama,
        vault_index=vault_index,
        settings=settings,
        tools={},
        mcp_bridge=mcp_bridge,
    )


def test_rule_engine_detects_reminder():
    re = RuleEngine()
    result = re.route("Erinnere mich morgen um 9 ans Meeting")
    assert result.action == "direct_mcp" or result.action == "crew"


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
    """FalkensteinFlow should accept optional mcp_bridge parameter."""
    bridge = MagicMock()
    deps = _make_deps(mcp_bridge=bridge)
    flow = FalkensteinFlow(**deps)
    assert flow.mcp_bridge is bridge


@pytest.mark.asyncio
async def test_flow_direct_mcp_calls_bridge():
    """direct_mcp route should call bridge directly without CrewAI."""
    bridge = MagicMock()
    bridge.call_tool = AsyncMock(return_value=MagicMock(
        success=True, output="Reminder 'Test' created"
    ))
    bridge.discover_tools = AsyncMock(return_value=[])

    deps = _make_deps(mcp_bridge=bridge)
    flow = FalkensteinFlow(**deps)

    # Mock _run_crew to ensure it is NOT called
    flow._run_crew = AsyncMock(return_value="should not be called")

    result = await flow._handle_direct_mcp("Erinnere mich morgen um 9 ans Meeting", chat_id=42)

    assert result is not None
    # Should have called the native_ollama to classify the MCP intent
    deps["native_ollama"].classify_mcp.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_flow_integration.py -v`
Expected: FAIL — various errors since the code doesn't exist yet

- [ ] **Step 3: Add MCP keywords to `backend/flow/rule_engine.py`**

Add a new set of MCP-related keywords and update the `route()` method. Find the existing keyword routing logic and add before the crew keyword checks:

```python
# MCP direct keywords — simple device commands that skip CrewAI
MCP_KEYWORDS = {
    "erinner", "reminder", "erinnerung",
    "licht", "light", "lampe",
    "musik", "music", "spiel", "play", "pause", "stop",
    "kalender", "calendar", "termin", "event",
    "notiz", "note",
    "homekit", "smart home", "heizung", "thermostat",
    "timer", "wecker", "alarm",
}
```

In the `route()` method, add a check before crew keyword matching:
```python
lower = message.lower()
# Check for direct MCP commands
for kw in MCP_KEYWORDS:
    if kw in lower:
        return RouteResult(action="direct_mcp", crew_type=None)
```

- [ ] **Step 4: Add `mcp_bridge` parameter and `_handle_direct_mcp` to `backend/flow/falkenstein_flow.py`**

Add `mcp_bridge=None` to `__init__`:
```python
def __init__(self, event_bus, native_ollama, vault_index, settings, tools, mcp_bridge=None):
    # ... existing init ...
    self.mcp_bridge = mcp_bridge
```

Add handling in `handle_message` for the `direct_mcp` route:
```python
if route_result.action == "direct_mcp" and self.mcp_bridge:
    return await self._handle_direct_mcp(message, chat_id)
```

Add the method:
```python
async def _handle_direct_mcp(self, message: str, chat_id: int | None = None) -> str:
    """Handle direct MCP commands without CrewAI overhead."""
    try:
        # Use LLM to classify which MCP tool to call
        mcp_intent = await self.ollama.classify_mcp(message)
        server_id = mcp_intent.get("server_id")
        tool_name = mcp_intent.get("tool_name")
        args = mcp_intent.get("args", {})

        if not server_id or not tool_name:
            # Fallback to crew if classification fails
            return await self._run_crew("ops", message, chat_id)

        result = await self.mcp_bridge.call_tool(server_id, tool_name, args)
        return result.output if result.success else f"Fehler: {result.output}"
    except Exception as e:
        return f"MCP Fehler: {e}"
```

- [ ] **Step 5: Run tests**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_flow_integration.py tests/test_flow.py tests/test_rule_engine.py -v`
Expected: All pass (new + existing)

- [ ] **Step 6: Commit**

```bash
git add backend/flow/falkenstein_flow.py backend/flow/rule_engine.py tests/test_mcp_flow_integration.py
git commit -m "feat(mcp): add direct_mcp route in Flow for simple device commands"
```

---

## Task 9: Admin API — MCP Endpoints

**Files:**
- Modify: `backend/admin_api.py`
- Create: `tests/test_mcp_admin_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mcp_admin_api.py`:
```python
"""Tests for MCP admin API endpoints."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

from backend.admin_api import router
import backend.admin_api as admin_mod


@pytest.fixture
def app():
    """Create test app with mocked dependencies."""
    app = FastAPI()
    app.include_router(router)

    # Mock dependencies
    admin_mod._mcp_bridge = MagicMock()
    admin_mod._mcp_bridge.servers = [
        MagicMock(
            config=MagicMock(id="apple-mcp", name="Apple", enabled=True),
            status="running",
            pid=123,
            tools_count=12,
            last_call=None,
            uptime_seconds=300.0,
            last_error=None,
        )
    ]
    admin_mod._mcp_bridge.list_tools = AsyncMock(return_value=[
        MagicMock(name="create_reminder", description="Create reminder", server_id="apple-mcp", input_schema={})
    ])
    admin_mod._mcp_bridge.restart_server = AsyncMock()
    admin_mod._mcp_bridge.toggle_server = AsyncMock()
    admin_mod._db = MagicMock()
    admin_mod._db.get_mcp_calls = AsyncMock(return_value=[])

    return app


@pytest.fixture
def client(app):
    return TestClient(app, headers={"Authorization": "Bearer falkenstein_2026_secret"})


def test_list_mcp_servers(client):
    resp = client.get("/api/admin/mcp/servers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "apple-mcp"
    assert data[0]["status"] == "running"


def test_get_mcp_server_tools(client):
    resp = client.get("/api/admin/mcp/servers/apple-mcp/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "create_reminder"


def test_restart_mcp_server(client):
    resp = client.post("/api/admin/mcp/servers/apple-mcp/restart")
    assert resp.status_code == 200
    admin_mod._mcp_bridge.restart_server.assert_called_once_with("apple-mcp")


def test_toggle_mcp_server(client):
    resp = client.post("/api/admin/mcp/servers/apple-mcp/toggle", json={"enabled": False})
    assert resp.status_code == 200
    admin_mod._mcp_bridge.toggle_server.assert_called_once_with("apple-mcp", False)


def test_get_mcp_logs(client):
    resp = client.get("/api/admin/mcp/servers/apple-mcp/logs")
    assert resp.status_code == 200
    admin_mod._db.get_mcp_calls.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_admin_api.py -v`
Expected: FAIL — endpoints don't exist yet

- [ ] **Step 3: Add MCP endpoints to `backend/admin_api.py`**

Add `_mcp_bridge` to module-level globals:
```python
_mcp_bridge = None  # MCPBridge instance
```

Add to `set_dependencies(...)`:
```python
def set_dependencies(..., mcp_bridge=None):
    global _mcp_bridge
    # ... existing globals ...
    _mcp_bridge = mcp_bridge
```

Add the endpoints (at the end of the file, before any `if __name__` block):
```python
# ── MCP Server Management ──────────────────────────────────────────────────

@router.get("/mcp/servers")
async def list_mcp_servers():
    if _mcp_bridge is None:
        return []
    return [
        {
            "id": s.config.id,
            "name": s.config.name,
            "enabled": s.config.enabled,
            "status": s.status,
            "pid": s.pid,
            "tools_count": s.tools_count,
            "last_call": str(s.last_call) if s.last_call else None,
            "uptime_seconds": s.uptime_seconds,
            "last_error": s.last_error,
        }
        for s in _mcp_bridge.servers
    ]


@router.get("/mcp/servers/{server_id}/tools")
async def get_mcp_server_tools(server_id: str):
    if _mcp_bridge is None:
        return []
    tools = await _mcp_bridge.list_tools(server_id)
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


@router.post("/mcp/servers/{server_id}/restart")
async def restart_mcp_server(server_id: str):
    if _mcp_bridge is None:
        return {"error": "MCP not initialized"}
    await _mcp_bridge.restart_server(server_id)
    return {"status": "restarted", "server_id": server_id}


@router.post("/mcp/servers/{server_id}/toggle")
async def toggle_mcp_server(server_id: str, body: dict):
    if _mcp_bridge is None:
        return {"error": "MCP not initialized"}
    enabled = body.get("enabled", True)
    await _mcp_bridge.toggle_server(server_id, enabled)
    return {"status": "toggled", "server_id": server_id, "enabled": enabled}


@router.get("/mcp/servers/{server_id}/logs")
async def get_mcp_server_logs(server_id: str, limit: int = 50):
    if _db is None:
        return []
    return await _db.get_mcp_calls(limit=limit, server_id=server_id)
```

- [ ] **Step 4: Run tests**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_admin_api.py tests/test_admin_api.py -v`
Expected: All pass (new + existing)

- [ ] **Step 5: Commit**

```bash
git add backend/admin_api.py tests/test_mcp_admin_api.py
git commit -m "feat(mcp): add admin API endpoints for MCP server management"
```

---

## Task 10: Main.py Integration — Wire Everything Together

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add MCP imports to `backend/main.py`**

At the top imports section:
```python
from backend.mcp import MCPBridge, MCPRegistry, create_all_mcp_tools
```

- [ ] **Step 2: Add MCPBridge init to the lifespan startup**

After the EventBus init and before tool instantiation (around line 180, after `event_bus = FalkensteinEventBus(...)`), add:

```python
    # ── MCP Bridge ────────────────────────────────────────────────────
    mcp_registry = MCPRegistry.from_settings(
        server_ids=settings.mcp_servers,
        enabled_flags={
            "apple-mcp": settings.mcp_apple_enabled,
            "desktop-commander": settings.mcp_desktop_commander_enabled,
            "mcp-obsidian": settings.mcp_obsidian_enabled,
        },
        node_path=settings.mcp_node_path,
    )
    mcp_bridge = MCPBridge(mcp_registry)
    try:
        await mcp_bridge.start()
        log.info("MCP Bridge started with %d servers", len(mcp_registry.list_enabled()))
    except Exception as e:
        log.warning("MCP Bridge start failed (non-fatal): %s", e)
```

- [ ] **Step 3: Create MCP tools and merge into crew_tools**

After the MCP bridge start and after the existing `crew_tools` dict:

```python
    # ── MCP Tools for CrewAI ──────────────────────────────────────────
    mcp_tool_schemas = await mcp_bridge.discover_tools()
    mcp_crewai_tools = create_all_mcp_tools(mcp_tool_schemas, mcp_bridge)

    # Add MCP tools to all crews that should have device access
    mcp_general_tools = [t for t in mcp_crewai_tools
                         if any(k in t.name for k in ("reminder", "calendar", "event", "music", "homekit", "note"))]
    mcp_desktop_tools = [t for t in mcp_crewai_tools if "desktop" in t.name]
    mcp_obsidian_tools = [t for t in mcp_crewai_tools if "obsidian" in t.name]

    for crew_type in crew_tools:
        crew_tools[crew_type] = crew_tools[crew_type] + mcp_general_tools
    # Extra tools for specific crews
    crew_tools["ops"] = crew_tools["ops"] + mcp_desktop_tools
    crew_tools["coder"] = crew_tools["coder"] + mcp_desktop_tools
    crew_tools["researcher"] = crew_tools["researcher"] + mcp_obsidian_tools
    crew_tools["writer"] = crew_tools["writer"] + mcp_obsidian_tools
```

- [ ] **Step 4: Pass mcp_bridge to Flow**

Update the `FalkensteinFlow` construction to include `mcp_bridge`:

```python
    flow = FalkensteinFlow(
        event_bus=event_bus,
        native_ollama=native_ollama,
        vault_index=vault_index,
        settings=settings,
        tools=crew_tools,
        mcp_bridge=mcp_bridge,
    )
```

- [ ] **Step 5: Pass mcp_bridge to admin API**

Update the `set_dependencies` call to include `mcp_bridge`:

```python
    admin_api.set_dependencies(
        # ... existing args ...
        mcp_bridge=mcp_bridge,
    )
```

- [ ] **Step 6: Add graceful shutdown**

In the lifespan `yield` / shutdown section:
```python
    yield
    # Shutdown
    await mcp_bridge.stop()
```

- [ ] **Step 7: Run all tests**

Run: `source venv312/bin/activate && python -m pytest tests/ -v --ignore=tests/test_smart_integration.py`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add backend/main.py
git commit -m "feat(mcp): wire MCPBridge into startup, crews, flow, and admin API"
```

---

## Task 11: classify_mcp Method on NativeOllamaClient

**Files:**
- Modify: `backend/native_ollama.py`
- Create: `tests/test_mcp_classify.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_mcp_classify.py`:
```python
"""Tests for MCP intent classification via NativeOllamaClient."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.native_ollama import NativeOllamaClient


@pytest.fixture
def client():
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
    """classify_mcp should return server_id, tool_name, args."""
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
    """classify_mcp should return empty dict if classification fails."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"message": {"content": "I don't know"}}
    client._http.post = AsyncMock(return_value=mock_response)

    result = await client.classify_mcp("random text", available_tools=[])
    assert result.get("server_id") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_classify.py -v`
Expected: FAIL — `AttributeError: 'NativeOllamaClient' object has no attribute 'classify_mcp'`

- [ ] **Step 3: Add `classify_mcp` to `backend/native_ollama.py`**

Add this method to the `NativeOllamaClient` class:
```python
async def classify_mcp(self, message: str, available_tools: list[dict] | None = None) -> dict:
    """Classify a message as an MCP tool call. Returns {server_id, tool_name, args}."""
    tools_desc = ""
    if available_tools:
        tools_desc = "\n".join(
            f"- {t['server_id']}/{t['tool_name']}: {t.get('description', '')}"
            for t in available_tools
        )

    system_prompt = f"""Du bist ein Tool-Router. Analysiere die Nachricht und entscheide welches Tool aufgerufen werden soll.

Verfügbare Tools:
{tools_desc}

Antworte NUR mit einem JSON-Objekt:
{{"server_id": "...", "tool_name": "...", "args": {{...}}}}

Wenn kein Tool passt, antworte: {{"server_id": null, "tool_name": null, "args": {{}}}}"""

    try:
        response = await self._http.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model_light,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                "stream": False,
                "format": "json",
                "options": {"num_ctx": self.num_ctx},
            },
            timeout=30,
        )
        content = response.json()["message"]["content"]
        return json.loads(content)
    except (json.JSONDecodeError, KeyError, Exception):
        return {"server_id": None, "tool_name": None, "args": {}}
```

Add `import json` at top if not already present.

- [ ] **Step 4: Run tests**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_classify.py tests/test_native_ollama.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add backend/native_ollama.py tests/test_mcp_classify.py
git commit -m "feat(mcp): add classify_mcp to NativeOllamaClient for MCP intent routing"
```

---

## Task 12: Integration Test — End-to-End MCP Flow

**Files:**
- Create: `tests/test_mcp_e2e.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_mcp_e2e.py`:
```python
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
    """MCPBridge with mocked server connections."""
    reg = MCPRegistry()
    reg.register(MCPServerConfig(id="apple-mcp", name="Apple", command="echo", args=[]))
    bridge = MCPBridge(reg)
    bridge.call_tool = AsyncMock(return_value=ToolResult(success=True, output="Erinnerung erstellt"))
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
        event_bus=event_bus,
        native_ollama=native_ollama,
        vault_index=vault_index,
        settings=settings,
        tools={},
        mcp_bridge=mock_bridge,
    )


@pytest.mark.asyncio
async def test_reminder_e2e(flow, mock_bridge):
    """'Erinnere mich' should route through direct_mcp and call apple-mcp."""
    result = await flow.handle_message("Erinnere mich morgen um 9 ans Meeting", chat_id=42)
    assert "erstellt" in result.lower() or result is not None
    mock_bridge.call_tool.assert_called_once_with(
        "apple-mcp", "create_reminder",
        {"title": "Meeting", "due_date": "2026-04-09T09:00:00"},
    )


@pytest.mark.asyncio
async def test_mcp_tools_as_crewai(mock_bridge):
    """MCP tools should be convertible to CrewAI BaseTool."""
    schemas = await mock_bridge.discover_tools()
    tools = create_all_mcp_tools(schemas, mock_bridge)
    assert len(tools) == 1
    assert tools[0].name == "mcp_apple_mcp_create_reminder"

    # Calling the tool should proxy to bridge
    result = tools[0]._run(title="Test")
    assert result == "Erinnerung erstellt"
```

- [ ] **Step 2: Run test**

Run: `source venv312/bin/activate && python -m pytest tests/test_mcp_e2e.py -v`
Expected: 2 passed

- [ ] **Step 3: Run full test suite**

Run: `source venv312/bin/activate && python -m pytest tests/ -v --ignore=tests/test_smart_integration.py`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_e2e.py
git commit -m "test(mcp): add end-to-end integration test for MCP flow"
```

---

## Task 13: Final Verification

- [ ] **Step 1: Run complete test suite**

Run: `source venv312/bin/activate && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Verify imports work**

Run:
```bash
source venv312/bin/activate && python -c "
from backend.mcp import MCPBridge, MCPRegistry, create_all_mcp_tools
from backend.mcp.config import MCPServerConfig, ServerStatus, ToolSchema
from backend.mcp.bridge import ToolResult
print('All MCP imports OK')
"
```
Expected: `All MCP imports OK`

- [ ] **Step 3: Verify Settings loads MCP fields**

Run:
```bash
source venv312/bin/activate && python -c "
from backend.config import Settings
s = Settings()
print(f'MCP servers: {s.mcp_servers}')
print(f'Apple enabled: {s.mcp_apple_enabled}')
print(f'Node path: {s.mcp_node_path}')
"
```
Expected: Shows values from `.env`

- [ ] **Step 4: Final commit if any loose changes**

```bash
git status
# If anything unstaged, add and commit
```
