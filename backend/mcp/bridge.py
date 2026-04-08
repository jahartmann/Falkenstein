"""MCPBridge — manages MCP server subprocesses and proxies tool calls.

Uses direct subprocess + stream management instead of nested async context
managers.  This avoids anyio cancel-scope nesting issues that caused hangs
when asyncio.create_task() was mixed with anyio task groups inside uvicorn.
"""
from __future__ import annotations
import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from mcp import ClientSession, StdioServerParameters
from mcp import types
from backend.mcp.config import ServerStatus, ToolSchema
from backend.mcp.registry import MCPRegistry

import anyio
from anyio.streams.text import TextReceiveStream

log = logging.getLogger(__name__)

try:
    from mcp.shared.message import SessionMessage
except ImportError:
    @dataclass
    class SessionMessage:
        message: types.JSONRPCMessage
        metadata: object = None


@dataclass
class ToolResult:
    success: bool
    output: str


@dataclass
class _ServerHandle:
    """All resources for a single running MCP server."""
    process: anyio.abc.Process
    session: ClientSession
    reader_task: asyncio.Task
    writer_task: asyncio.Task
    tools: list[ToolSchema] = field(default_factory=list)
    start_time: float = 0.0


TOOL_CALL_TIMEOUT = 60.0
DEFAULT_START_TIMEOUT = 45.0
_POSIX_ENV_VARS = ("HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER")


def _get_default_environment() -> dict[str, str]:
    import os
    return {k: os.environ[k] for k in _POSIX_ENV_VARS if k in os.environ}


class MCPBridge:
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._handles: dict[str, _ServerHandle] = {}

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
            coros.append(self._start_server(s.config.id, timeout))
        if coros:
            await asyncio.gather(*coros)

    async def stop(self) -> None:
        """Stop all running servers."""
        coros = [self._stop_server(sid) for sid in list(self._handles)]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def _start_server(self, server_id: str, timeout: float) -> None:
        """Start a single MCP server with timeout."""
        status = self.registry.get(server_id)
        if status is None:
            return
        cfg = status.config
        env = {**_get_default_environment(), **(cfg.env or {})}

        try:
            process = await asyncio.wait_for(
                anyio.open_process(
                    [cfg.command, *cfg.args],
                    env=env, stderr=sys.stderr,
                    start_new_session=True,
                ),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, OSError) as e:
            log.error("MCP server %s: process start failed: %s", server_id, e)
            self.registry.update_status(server_id, status="error", last_error=str(e))
            return

        # Memory streams for MCP JSON-RPC framing
        read_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](32)
        write_stream, write_reader = anyio.create_memory_object_stream[SessionMessage](32)

        reader_task = asyncio.create_task(
            self._stdout_reader(process, read_writer, server_id),
            name=f"mcp-read-{server_id}",
        )
        writer_task = asyncio.create_task(
            self._stdin_writer(process, write_reader, server_id),
            name=f"mcp-write-{server_id}",
        )

        # Initialize session
        try:
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            init_result = await asyncio.wait_for(session.initialize(), timeout=timeout)
            tools_result = await asyncio.wait_for(session.list_tools(), timeout=timeout)
        except Exception as e:
            log.error("MCP server %s: session init failed: %s", server_id, e)
            self.registry.update_status(server_id, status="error", last_error=str(e))
            reader_task.cancel()
            writer_task.cancel()
            _terminate(process)
            return

        tool_schemas = [
            ToolSchema(
                name=t.name,
                description=t.description or "",
                server_id=server_id,
                input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
            )
            for t in tools_result.tools
        ]

        self._handles[server_id] = _ServerHandle(
            process=process, session=session,
            reader_task=reader_task, writer_task=writer_task,
            tools=tool_schemas, start_time=time.time(),
        )
        self.registry.update_status(
            server_id, status="running",
            pid=process.pid, tools_count=len(tool_schemas),
        )
        log.info("MCP server %s started with %d tools (pid %s)",
                 server_id, len(tool_schemas), process.pid)

    async def _stop_server(self, server_id: str) -> None:
        """Stop a single server and clean up all resources."""
        handle = self._handles.pop(server_id, None)
        if handle is None:
            return
        # Cancel reader/writer tasks
        handle.reader_task.cancel()
        handle.writer_task.cancel()
        # Close session (ignore errors — session may already be dead)
        try:
            await handle.session.__aexit__(None, None, None)
        except Exception as e:
            log.debug("Session close for %s: %s", server_id, e)
        # Terminate subprocess
        _terminate(handle.process)
        try:
            await asyncio.wait_for(handle.process.wait(), timeout=3.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                handle.process.kill()
            except ProcessLookupError:
                pass
        self.registry.update_status(server_id, status="stopped", pid=None, tools_count=0)
        log.info("MCP server %s stopped", server_id)

    # ── stdio reader/writer tasks ─────────────────────────────────────

    @staticmethod
    async def _stdout_reader(
        process: anyio.abc.Process,
        writer: anyio.streams.memory.MemoryObjectSendStream,
        server_id: str,
    ) -> None:
        """Read stdout lines, drop non-JSON, forward valid JSON-RPC."""
        assert process.stdout
        try:
            buffer = ""
            async for chunk in TextReceiveStream(process.stdout):
                lines = (buffer + chunk).split("\n")
                buffer = lines.pop()
                for line in lines:
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        if line:
                            log.debug("MCP %s stdout (non-JSON): %s", server_id, line[:120])
                        continue
                    try:
                        message = types.JSONRPCMessage.model_validate_json(line)
                    except Exception:
                        log.warning("MCP %s stdout (bad JSON-RPC): %s", server_id, line[:120])
                        await writer.send(Exception(f"Invalid JSON-RPC: {line[:200]}"))
                        continue
                    await writer.send(SessionMessage(message))
            # EOF: flush buffer
            if buffer.strip() and buffer.strip().startswith("{"):
                try:
                    msg = types.JSONRPCMessage.model_validate_json(buffer.strip())
                    await writer.send(SessionMessage(msg))
                except Exception:
                    pass
        except (anyio.ClosedResourceError, anyio.EndOfStream, asyncio.CancelledError):
            pass
        except Exception as e:
            log.debug("MCP %s stdout_reader error: %s", server_id, e)
        finally:
            await writer.aclose()

    @staticmethod
    async def _stdin_writer(
        process: anyio.abc.Process,
        reader: anyio.streams.memory.MemoryObjectReceiveStream,
        server_id: str,
    ) -> None:
        """Forward SessionMessage objects to subprocess stdin as JSON-RPC."""
        assert process.stdin
        try:
            async for session_message in reader:
                json_str = session_message.message.model_dump_json(
                    by_alias=True, exclude_none=True,
                )
                await process.stdin.send((json_str + "\n").encode())
        except (anyio.ClosedResourceError, anyio.EndOfStream, asyncio.CancelledError):
            pass
        except Exception as e:
            log.debug("MCP %s stdin_writer error: %s", server_id, e)

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
        if handle is None:
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


def _terminate(process: anyio.abc.Process) -> None:
    try:
        process.terminate()
    except ProcessLookupError:
        pass
