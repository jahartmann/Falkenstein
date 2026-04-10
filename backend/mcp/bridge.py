"""MCPBridge — manages MCP server subprocesses and proxies tool calls.

Uses the MCP SDK's stdio_client transport for reliable server communication.
Each server runs as a background asyncio task managing its own stdio_client
+ ClientSession lifecycle via anyio task groups.
"""
from __future__ import annotations
import asyncio
import concurrent.futures
import json
import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from backend.mcp.config import ServerStatus, ToolSchema
from backend.mcp.registry import MCPRegistry
from backend.mcp.filtered_stdio import filtered_stdio_client

log = logging.getLogger(__name__)

EVENT_LOG_PATH = Path("data/mcp_events.log")
EVENT_LOG_MAX_BYTES = 10 * 1024 * 1024


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
    stderr: deque = field(default_factory=lambda: deque(maxlen=200))


TOOL_CALL_TIMEOUT = 60.0
DEFAULT_START_TIMEOUT = 45.0


class MCPBridge:
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._handles: dict[str, _ServerHandle] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._health_task: asyncio.Task | None = None
        self._resolver = None     # PermissionResolver
        self._approvals = None    # ApprovalStore

    def attach_policy(self, resolver, approval_store) -> None:
        """Wire the permission resolver and approval store into call_tool."""
        self._resolver = resolver
        self._approvals = approval_store

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
        self._health_task = asyncio.create_task(self._health_loop(), name="mcp-health")

    async def stop(self) -> None:
        """Stop all running servers."""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except (asyncio.CancelledError, Exception):
                pass
            self._health_task = None
        for sid in list(self._handles):
            await self._stop_server(sid)

    def _build_args(self, server_id: str, catalog_entry: dict, user_cfg: dict) -> list[str]:
        """Assemble CLI args from catalog + user config."""
        args: list[str] = []
        # mcp-obsidian expects vault_path as positional
        if server_id == "mcp-obsidian" and user_cfg.get("vault_path"):
            args.append(user_cfg["vault_path"])
        # filesystem expects allowed_directories (comma-separated string OR list)
        if server_id == "filesystem":
            dirs = user_cfg.get("allowed_directories", "")
            if isinstance(dirs, str):
                dirs = [d.strip() for d in dirs.split(",") if d.strip()]
            args.extend(dirs)
        return args

    def _build_env(self, catalog_entry: dict, user_cfg: dict) -> dict:
        """Env vars required by this MCP (API keys etc.). Uppercase keys → env."""
        env = {}
        for key in catalog_entry.get("requires_config", []):
            if key.isupper() and key in user_cfg:
                env[key] = str(user_cfg[key])
        return env

    async def _start_server(self, server_id: str, timeout: float) -> None:
        """Start a single MCP server using the SDK's stdio_client."""
        from backend.mcp.catalog import CATALOG
        from backend.mcp import installer

        status = self.registry.get(server_id)
        if status is None:
            return
        cfg = status.config

        # Catalog-driven resolution: require installed binary
        catalog_entry = CATALOG.get(server_id)
        if catalog_entry is None:
            self.registry.update_status(server_id, status="error",
                                        last_error="not in catalog")
            return
        binary = installer.resolve_binary(server_id, catalog_entry["bin"])
        if binary is None:
            self.registry.update_status(server_id, status="not_installed",
                                        last_error=None)
            self._emit_event("start_skipped_not_installed", server_id=server_id)
            return
        # Check required config before attempting start
        user_cfg = self.registry.get_user_config(server_id) if hasattr(self.registry, "get_user_config") else {}
        missing = [
            k for k in catalog_entry.get("requires_config", [])
            if not user_cfg.get(k)
        ]
        if missing:
            err = f"Missing config: {', '.join(missing)}"
            self.registry.update_status(server_id, status="error", last_error=err)
            self._emit_event("start_skipped_missing_config",
                             server_id=server_id, missing=missing)
            log.warning("MCP %s: skipped — %s", server_id, err)
            return

        # Override cfg.command with resolved absolute path; build args + env
        cfg.command = str(binary)
        cfg.args = self._build_args(server_id, catalog_entry, user_cfg)
        cfg.env = self._build_env(catalog_entry, user_cfg)

        self._emit_event("start_attempt", server_id=server_id)

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

            class _StderrCapture:
                """File-like that appends lines to the handle's stderr deque."""
                def __init__(self, buf, tee=sys.stderr):
                    self.buf = buf
                    self.tee = tee
                    self._partial = ""
                def write(self, data):
                    try:
                        if isinstance(data, bytes):
                            data = data.decode("utf-8", errors="replace")
                        self._partial += data
                        while "\n" in self._partial:
                            line, self._partial = self._partial.split("\n", 1)
                            if line:
                                self.buf.append(line)
                        if self.tee:
                            self.tee.write(data)
                    except Exception:
                        pass
                def flush(self):
                    if self.tee:
                        try: self.tee.flush()
                        except Exception: pass
                def fileno(self):
                    return self.tee.fileno() if hasattr(self.tee, "fileno") else -1

            capture = _StderrCapture(handle.stderr)

            try:
                async with filtered_stdio_client(params, errlog=capture) as (read_stream, write_stream):
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
                        self._emit_event("start_ok", server_id=server_id, tools=len(tool_schemas))

                        # Keep alive until shutdown is requested
                        await handle._shutdown.wait()
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                error_box.append(err_msg)
                handle.stderr.append(f"[bridge] {err_msg}")
                self._emit_event("start_failed", server_id=server_id, error=err_msg)
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
        s = self.registry.get(server_id)
        if s is not None:
            s.config.enabled = enabled
        if not enabled:
            await self._stop_server(server_id)
        elif enabled and server_id not in self._handles:
            await self._start_server(server_id, DEFAULT_START_TIMEOUT)

    # ── Tool discovery & calls ────────────────────────────────────────

    async def list_tools(self, server_id: str) -> list[ToolSchema]:
        h = self._handles.get(server_id)
        return h.tools if h else []

    def get_stderr(self, server_id: str) -> list[str]:
        """Return a snapshot of the last ~200 stderr lines for a server."""
        h = self._handles.get(server_id)
        return list(h.stderr) if h else []

    def _emit_event(self, event: str, **fields) -> None:
        """Append a structured JSON line to the MCP event log."""
        try:
            EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if EVENT_LOG_PATH.exists() and EVENT_LOG_PATH.stat().st_size > EVENT_LOG_MAX_BYTES:
                rotated = EVENT_LOG_PATH.with_suffix(".log.1")
                if rotated.exists():
                    rotated.unlink()
                EVENT_LOG_PATH.rename(rotated)
            payload = {"ts": time.time(), "event": event, **fields}
            with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, default=str) + "\n")
        except Exception as e:
            log.debug("event log write failed: %s", e)

    async def _health_tick(self) -> None:
        """One pass of the health check — mark dead tasks as error."""
        for sid, handle in list(self._handles.items()):
            status = self.registry.get(sid)
            if status and status.status == "running" and handle.task and handle.task.done():
                self.registry.update_status(sid, status="error", last_error="task exited")
                self._emit_event("subprocess_exited", server_id=sid)

    async def _health_loop(self, interval: float = 30.0) -> None:
        while True:
            try:
                await asyncio.sleep(interval)
                await self._health_tick()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.warning("health tick failed: %s", e)

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

        # Policy check (if attached)
        if self._resolver is not None:
            decision = await self._resolver.check(server_id, tool_name)
            if decision == "deny":
                self._emit_event("tool_denied", server_id=server_id, tool_name=tool_name)
                return ToolResult(success=False, output="denied by policy")
            if decision == "ask":
                if self._approvals is None:
                    return ToolResult(success=False,
                                      output="approval required but no approval channel")
                self._emit_event("approval_requested", server_id=server_id, tool_name=tool_name)
                approval_result = await self._approvals.request(server_id, tool_name, args)
                if approval_result != "allow":
                    self._emit_event("approval_not_granted",
                                     server_id=server_id, tool_name=tool_name,
                                     result=approval_result)
                    return ToolResult(success=False, output=f"approval {approval_result}")

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
            self._emit_event("tool_call_ok", server_id=server_id, tool_name=tool_name)
            return ToolResult(success=not result.isError, output=output)
        except asyncio.TimeoutError:
            log.error("MCP tool call timed out after %.0fs: %s/%s", timeout, server_id, tool_name)
            self._emit_event("tool_call_timeout", server_id=server_id, tool_name=tool_name)
            return ToolResult(success=False, output=f"Timeout after {timeout}s")
        except Exception as e:
            log.error("MCP tool call failed: %s/%s: %s", server_id, tool_name, e)
            self._emit_event("tool_call_error", server_id=server_id,
                             tool_name=tool_name, error=str(e))
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
