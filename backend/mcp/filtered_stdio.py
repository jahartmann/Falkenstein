"""Filtered stdio_client that silently drops non-JSON-RPC lines from stdout."""
from __future__ import annotations
import logging
import sys
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
import anyio.lowlevel
from anyio.streams.text import TextReceiveStream
from mcp import types
from mcp.client.stdio import (
    StdioServerParameters,
    _create_platform_compatible_process,
    _get_executable_command,
    _terminate_process_tree,
    PROCESS_TERMINATION_TIMEOUT,
    get_default_environment,
)
from mcp.shared.message import SessionMessage

log = logging.getLogger(__name__)


@asynccontextmanager
async def filtered_stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    """Like mcp.client.stdio.stdio_client but drops non-JSON stdout lines
    instead of forwarding parse exceptions to the session."""
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    try:
        command = _get_executable_command(server.command)
        process = await _create_platform_compatible_process(
            command=command,
            args=server.args,
            env=({**get_default_environment(), **server.env} if server.env is not None else get_default_environment()),
            errlog=errlog,
            cwd=server.cwd,
        )
    except OSError:
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise

    async def stdout_reader():
        assert process.stdout
        try:
            async with read_stream_writer:
                buffer = ""
                async for chunk in TextReceiveStream(
                    process.stdout,
                    encoding=server.encoding,
                    errors=server.encoding_error_handler,
                ):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if not line or not line.startswith("{"):
                            # Non-JSON line — log and skip instead of sending exception
                            if line:
                                log.debug("MCP stdout (non-JSON, dropped): %s", line[:120])
                            continue
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                        except Exception:
                            log.debug("MCP stdout (invalid JSON, dropped): %s", line[:120])
                            continue
                        await read_stream_writer.send(SessionMessage(message))
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdin_writer():
        assert process.stdin
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_str = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                    await process.stdin.send(
                        (json_str + "\n").encode(
                            encoding=server.encoding,
                            errors=server.encoding_error_handler,
                        )
                    )
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg, process:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            if process.stdin:
                try:
                    await process.stdin.aclose()
                except Exception:
                    pass
            try:
                with anyio.fail_after(PROCESS_TERMINATION_TIMEOUT):
                    await process.wait()
            except TimeoutError:
                await _terminate_process_tree(process)
            except ProcessLookupError:
                pass
            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()
