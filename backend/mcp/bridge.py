"""MCPBridge — manages MCP server subprocesses and proxies tool calls.

Each server runs in its own asyncio task that owns the full context-manager
lifecycle (filtered_stdio_client → ClientSession).  This avoids the
cancel-scope nesting bugs that plagued the manual __aenter__/__aexit__ approach.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from mcp import ClientSession, StdioServerParameters
from backend.mcp.filtered_stdio import filtered_stdio_client
from backend.mcp.config import ToolSchema
from backend.mcp.registry import MCPRegistry

log = logging.getLogger(__name__)

@dataclass
class ToolResult:
    success: bool
    output: str

TOOL_CALL_TIMEOUT = 60.0  # seconds before a tool call is considered hung
DEFAULT_START_TIMEOUT = 45.0  # generous timeout for npx first-download


class MCPBridge:
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._sessions: dict[str, ClientSession] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._tool_cache: dict[str, list[ToolSchema]] = {}
        self._start_times: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, server_id: str) -> asyncio.Lock:
        if server_id not in self._locks:
            self._locks[server_id] = asyncio.Lock()
        return self._locks[server_id]

    @property
    def servers(self) -> list[ServerStatus]:
        return self.registry.list_servers()

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(self, timeout: float = DEFAULT_START_TIMEOUT) -> None:
        """Start all enabled servers concurrently."""
        coros = []
        for s in self.registry.list_servers():
            if not s.config.enabled:
                self.registry.update_status(s.config.id, status="disabled")
                continue
            coros.append(self._launch_server(s.config.id, timeout))
        if coros:
            await asyncio.gather(*coros)

    async def stop(self) -> None:
        """Cancel all server tasks (triggers proper context cleanup)."""
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._sessions.clear()
        self._tool_cache.clear()
        self._start_times.clear()

    async def _launch_server(self, server_id: str, timeout: float) -> None:
        """Spawn the background task and wait for it to signal readiness."""
        lock = self._lock_for(server_id)
        if lock.locked():
            log.debug("MCP server %s launch already in progress, skipping", server_id)
            return
        async with lock:
            # Cancel any stale task first
            old_task = self._tasks.pop(server_id, None)
            if old_task and not old_task.done():
                old_task.cancel()
                with _suppress(asyncio.CancelledError):
                    await old_task

            ready: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(
                self._server_task(server_id, ready),
                name=f"mcp-{server_id}",
            )
            self._tasks[server_id] = task
            try:
                success = await asyncio.wait_for(ready, timeout=timeout)
                if not success:
                    log.warning("MCP server %s reported startup failure", server_id)
            except asyncio.TimeoutError:
                log.error("MCP server %s timed out after %.0fs", server_id, timeout)
                self.registry.update_status(
                    server_id, status="error",
                    last_error=f"Timeout after {timeout:.0f}s",
                )
                task.cancel()
                with _suppress(asyncio.CancelledError):
                    await task
                self._tasks.pop(server_id, None)

    async def _server_task(self, server_id: str, ready: asyncio.Future[bool]) -> None:
        """Long-lived task that owns the full context-manager stack."""
        my_task = asyncio.current_task()
        status = self.registry.get(server_id)
        if status is None:
            _set_future(ready, False)
            return
        cfg = status.config
        server_params = StdioServerParameters(
            command=cfg.command, args=cfg.args,
            env=cfg.env if cfg.env else None,
        )
        try:
            async with filtered_stdio_client(server_params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
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
                    self._sessions[server_id] = session
                    self._tool_cache[server_id] = tool_schemas
                    self._start_times[server_id] = time.time()
                    self.registry.update_status(
                        server_id, status="running",
                        pid=None, tools_count=len(tool_schemas),
                    )
                    log.info("MCP server %s started with %d tools", server_id, len(tool_schemas))
                    _set_future(ready, True)

                    # Keep alive until cancelled
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("MCP server %s failed: %s", server_id, e)
            self.registry.update_status(
                server_id, status="error", last_error=str(e),
            )
            _set_future(ready, False)
        finally:
            self._sessions.pop(server_id, None)
            self._tool_cache.pop(server_id, None)
            self._start_times.pop(server_id, None)
            # Only remove task slot if WE still own it (avoid clobbering a newer task)
            if self._tasks.get(server_id) is my_task:
                self._tasks.pop(server_id, None)
            s = self.registry.get(server_id)
            if s and s.status == "running":
                self.registry.update_status(server_id, status="stopped", pid=None, tools_count=0)
                log.info("MCP server %s stopped", server_id)

    # ── Server management ────────────────────────────────────────────

    async def restart_server(self, server_id: str) -> None:
        await self._stop_single(server_id)
        await self._launch_server(server_id, DEFAULT_START_TIMEOUT)

    async def toggle_server(self, server_id: str, enabled: bool) -> None:
        self.registry.toggle(server_id, enabled)
        if not enabled:
            await self._stop_single(server_id)
        elif enabled and server_id not in self._sessions:
            await self._launch_server(server_id, DEFAULT_START_TIMEOUT)

    async def _stop_single(self, server_id: str) -> None:
        task = self._tasks.pop(server_id, None)
        if task:
            task.cancel()
            with _suppress(asyncio.CancelledError):
                await task

    # ── Tool discovery & calls ────────────────────────────────────────

    async def list_tools(self, server_id: str) -> list[ToolSchema]:
        return self._tool_cache.get(server_id, [])

    async def discover_tools(self) -> list[ToolSchema]:
        all_tools: list[ToolSchema] = []
        for sid in list(self._tool_cache):
            status = self.registry.get(sid)
            if status and status.status == "running":
                all_tools.extend(self._tool_cache[sid])
        return all_tools

    async def call_tool(self, server_id: str, tool_name: str, args: dict,
                        timeout: float = TOOL_CALL_TIMEOUT) -> ToolResult:
        session = self._sessions.get(server_id)
        if session is None:
            return ToolResult(success=False, output=f"Server '{server_id}' not connected")
        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=args), timeout=timeout,
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


def _set_future(fut: asyncio.Future, value: object) -> None:
    """Set future result only if not already done (safe against double-signal)."""
    if not fut.done():
        fut.set_result(value)


class _suppress:
    """Minimal async-compatible exception suppressor."""
    def __init__(self, *exceptions):
        self._exceptions = exceptions
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        return exc_type is not None and issubclass(exc_type, self._exceptions)


# Re-export for type hints in other modules
from backend.mcp.config import ServerStatus  # noqa: E402
