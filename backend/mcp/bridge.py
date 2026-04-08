"""MCPBridge — manages MCP server subprocesses and proxies tool calls."""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
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
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._sessions: dict[str, ClientSession] = {}
        self._contexts: dict[str, object] = {}
        self._tool_cache: dict[str, list[ToolSchema]] = {}
        self._start_times: dict[str, float] = {}
        self._health_task: asyncio.Task | None = None

    @property
    def servers(self) -> list[ServerStatus]:
        return self.registry.list_servers()

    async def start(self) -> None:
        for s in self.registry.list_enabled():
            try:
                await self._start_server(s.config.id)
            except Exception as e:
                log.error("Failed to start MCP server %s: %s", s.config.id, e)
                self.registry.update_status(s.config.id, status="error", last_error=str(e))

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
        for sid in list(self._sessions.keys()):
            await self._stop_server(sid)

    async def _start_server(self, server_id: str) -> None:
        status = self.registry.get(server_id)
        if status is None:
            return
        cfg = status.config
        server_params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env if cfg.env else None)
        ctx = stdio_client(server_params)
        streams = await ctx.__aenter__()
        self._contexts[server_id] = ctx
        session = ClientSession(*streams)
        await session.__aenter__()
        await session.initialize()
        self._sessions[server_id] = session
        self._start_times[server_id] = time.time()
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
        self.registry.update_status(server_id, status="running", pid=None, tools_count=len(tool_schemas))
        log.info("MCP server %s started with %d tools", server_id, len(tool_schemas))

    async def _stop_server(self, server_id: str) -> None:
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
        await self._stop_server(server_id)
        await self._start_server(server_id)

    async def toggle_server(self, server_id: str, enabled: bool) -> None:
        self.registry.toggle(server_id, enabled)
        if not enabled:
            await self._stop_server(server_id)
        elif enabled and server_id not in self._sessions:
            await self._start_server(server_id)

    async def list_tools(self, server_id: str) -> list[ToolSchema]:
        return self._tool_cache.get(server_id, [])

    async def discover_tools(self) -> list[ToolSchema]:
        all_tools: list[ToolSchema] = []
        for sid, session in self._sessions.items():
            status = self.registry.get(sid)
            if status and status.status == "running":
                if sid in self._tool_cache:
                    all_tools.extend(self._tool_cache[sid])
                else:
                    try:
                        tools_result = await session.list_tools()
                        tool_schemas = [
                            ToolSchema(
                                name=t.name,
                                description=t.description or "",
                                server_id=sid,
                                input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
                            )
                            for t in tools_result.tools
                        ]
                        self._tool_cache[sid] = tool_schemas
                        all_tools.extend(tool_schemas)
                    except Exception as e:
                        log.warning("Failed to list tools for %s: %s", sid, e)
        return all_tools

    async def call_tool(self, server_id: str, tool_name: str, args: dict) -> ToolResult:
        session = self._sessions.get(server_id)
        if session is None:
            return ToolResult(success=False, output=f"Server '{server_id}' not connected")
        try:
            result = await session.call_tool(tool_name, arguments=args)
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
