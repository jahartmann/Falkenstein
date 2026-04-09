"""MCPBridge — manages MCP server subprocesses and proxies tool calls.

Uses the MCP SDK's stdio_client transport for reliable server communication.
Each server runs as a background asyncio task managing its own stdio_client
+ ClientSession lifecycle via anyio task groups.
"""
from __future__ import annotations
import asyncio
import concurrent.futures
import logging
import sys
import time
from dataclasses import dataclass, field
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from backend.mcp.config import ServerStatus, ToolSchema
from backend.mcp.registry import MCPRegistry

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    success: bool
    output: str


@dataclass
class _ServerHandle:
    """All resources for a single running MCP server."""
    session: ClientSession
    task: asyncio.Task
    tools: list[ToolSchema] = field(default_factory=list)
    start_time: float = 0.0
    _shutdown: asyncio.Event = field(default_factory=asyncio.Event)


TOOL_CALL_TIMEOUT = 60.0
DEFAULT_START_TIMEOUT = 45.0


class MCPBridge:
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._handles: dict[str, _ServerHandle] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None

    @property
    def servers(self) -> list[ServerStatus]:
        return self.registry.list_servers()

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self, timeout: float = DEFAULT_START_TIMEOUT) -> None:
        """Start all enabled servers concurrently."""
        self._main_loop = asyncio.get_running_loop()
        coros = []
        for s in self.registry.list_servers():
            if not s.config.enabled:
                self.registry.update_status(s.config.id, status="disabled")
                continue
            coros.append(self._start_server(s.config.id, timeout))
        if coros:
            await asyncio.gather(*coros)

    async def stop(self) -> None:
        """Stop all running servers."""
        for sid in list(self._handles):
            await self._stop_server(sid)

    async def _start_server(self, server_id: str, timeout: float) -> None:
        """Start a single MCP server using the SDK's stdio_client."""
        status = self.registry.get(server_id)
        if status is None:
            return
        cfg = status.config

        # Event signals the background task to shut down
        ready_event = asyncio.Event()
        handle = _ServerHandle(
            session=None,  # type: ignore[arg-type]  # set by background task
            task=None,  # type: ignore[arg-type]
            start_time=time.time(),
        )
        error_box: list[str] = []

        async def _run() -> None:
            params = StdioServerParameters(
                command=cfg.command,
                args=cfg.args,
                env=cfg.env or None,
            )
            try:
                # errlog param added in newer MCP SDK versions
                import inspect
                _sig = inspect.signature(stdio_client)
                _kw = {"errlog": sys.stderr} if "errlog" in _sig.parameters else {}
                async with stdio_client(params, **_kw) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        init_result = await session.initialize()
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

                        handle.session = session
                        handle.tools = tool_schemas
                        self.registry.update_status(
                            server_id, status="running",
                            tools_count=len(tool_schemas),
                        )
                        log.info("MCP server %s started with %d tools",
                                 server_id, len(tool_schemas))
                        ready_event.set()

                        # Keep alive until shutdown is requested
                        await handle._shutdown.wait()
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                error_box.append(err_msg)
                ready_event.set()  # unblock the waiter

        task = asyncio.create_task(_run(), name=f"mcp-server-{server_id}")
        handle.task = task
        self._handles[server_id] = handle

        # Wait for init or timeout
        try:
            await asyncio.wait_for(ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            error_box.append("TimeoutError")

        if error_box:
            err = error_box[0]
            log.error("MCP server %s: init failed: %s", server_id, err)
            self.registry.update_status(server_id, status="error", last_error=err)
            handle._shutdown.set()
            task.cancel()
            self._handles.pop(server_id, None)
            # Give task a moment to clean up
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                pass

    async def _stop_server(self, server_id: str) -> None:
        """Stop a single server by signalling its background task."""
        handle = self._handles.pop(server_id, None)
        if handle is None:
            return
        handle._shutdown.set()
        try:
            await asyncio.wait_for(handle.task, timeout=10.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            handle.task.cancel()
        self.registry.update_status(server_id, status="stopped", pid=None, tools_count=0)
        log.info("MCP server %s stopped", server_id)

    # ── Server management ─────────────────────────────────────────────

    async def restart_server(self, server_id: str) -> None:
        await self._stop_server(server_id)
        await self._start_server(server_id, DEFAULT_START_TIMEOUT)

    async def toggle_server(self, server_id: str, enabled: bool) -> None:
        self.registry.toggle(server_id, enabled)
        if not enabled:
            await self._stop_server(server_id)
        elif enabled and server_id not in self._handles:
            await self._start_server(server_id, DEFAULT_START_TIMEOUT)

    # ── Tool discovery & calls ────────────────────────────────────────

    async def list_tools(self, server_id: str) -> list[ToolSchema]:
        h = self._handles.get(server_id)
        return h.tools if h else []

    async def discover_tools(self) -> list[ToolSchema]:
        all_tools: list[ToolSchema] = []
        for sid, h in list(self._handles.items()):
            status = self.registry.get(sid)
            if status and status.status == "running":
                all_tools.extend(h.tools)
        return all_tools

    async def call_tool(self, server_id: str, tool_name: str, args: dict,
                        timeout: float = TOOL_CALL_TIMEOUT) -> ToolResult:
        handle = self._handles.get(server_id)
        if handle is None or handle.session is None:
            return ToolResult(success=False, output=f"Server '{server_id}' not connected")
        try:
            result = await asyncio.wait_for(
                handle.session.call_tool(tool_name, arguments=args),
                timeout=timeout,
            )
            output_parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    output_parts.append(block.text)
                else:
                    output_parts.append(str(block))
            output = "\n".join(output_parts)
            return ToolResult(success=not result.isError, output=output)
        except asyncio.TimeoutError:
            log.error("MCP tool call timed out after %.0fs: %s/%s", timeout, server_id, tool_name)
            return ToolResult(success=False, output=f"Timeout after {timeout}s")
        except Exception as e:
            log.error("MCP tool call failed: %s/%s: %s", server_id, tool_name, e)
            return ToolResult(success=False, output=f"Error: {e}")

    def call_tool_threadsafe(
        self, server_id: str, tool_name: str, args: dict,
        timeout: float = TOOL_CALL_TIMEOUT,
    ) -> ToolResult:
        """Sync-facing tool call for CrewAI thread pool. Safe from any thread."""
        if self._main_loop is None:
            return ToolResult(success=False, output="Bridge not started")
        if server_id not in self._handles:
            return ToolResult(success=False, output=f"Server '{server_id}' not connected")
        fut = asyncio.run_coroutine_threadsafe(
            self.call_tool(server_id, tool_name, args, timeout),
            self._main_loop,
        )
        try:
            return fut.result(timeout=timeout + 5)
        except concurrent.futures.TimeoutError:
            return ToolResult(success=False, output=f"Timeout after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, output=f"Error: {e}")
