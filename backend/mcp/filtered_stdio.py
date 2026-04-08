"""Filtered stdio_client that silently drops non-JSON-RPC lines from stdout."""
from __future__ import annotations
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
import anyio.lowlevel
from anyio.streams.text import TextReceiveStream
from dataclasses import dataclass
from mcp import types
from mcp.client.stdio import StdioServerParameters

log = logging.getLogger(__name__)

try:
    from mcp.shared.message import SessionMessage
except ImportError:
    @dataclass
    class SessionMessage:
        message: types.JSONRPCMessage
        metadata: object = None

# Timeout before force-killing the process
PROCESS_TERMINATION_TIMEOUT = 2.0

# Safe env vars to pass to subprocess (matches MCP SDK)
_POSIX_ENV_VARS = ("HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER")


def _get_default_environment() -> dict[str, str]:
    return {k: os.environ[k] for k in _POSIX_ENV_VARS if k in os.environ}


@asynccontextmanager
async def filtered_stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    """Like mcp.client.stdio.stdio_client but drops non-JSON stdout lines
    instead of forwarding parse exceptions to the session."""
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    env = {**_get_default_environment(), **server.env} if server.env is not None else _get_default_environment()
    encoding = getattr(server, "encoding", "utf-8")
    encoding_errors = getattr(server, "encoding_error_handler", "strict")

    try:
        process = await anyio.open_process(
            [server.command, *server.args],
            env=env,
            stderr=errlog,
            cwd=getattr(server, "cwd", None),
            start_new_session=True,
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
                    process.stdout, encoding=encoding, errors=encoding_errors,
                ):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if not line or not line.startswith("{"):
                            if line:
                                log.debug("MCP stdout (non-JSON, dropped): %s", line[:120])
                            continue
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                        except Exception as exc:
                            # Forward parse error so callers unblock with an error
                            # instead of hanging forever on a missing response
                            log.warning("MCP stdout (invalid JSON-RPC): %s", line[:120])
                            await read_stream_writer.send(
                                Exception(f"Invalid JSON-RPC from server: {line[:200]}")
                            )
                            continue
                        await read_stream_writer.send(SessionMessage(message))
                # Process remaining buffer at EOF
                if buffer.strip() and buffer.strip().startswith("{"):
                    try:
                        message = types.JSONRPCMessage.model_validate_json(buffer.strip())
                        await read_stream_writer.send(SessionMessage(message))
                    except Exception:
                        log.debug("MCP stdout (invalid JSON at EOF, dropped): %s", buffer[:120])
        except (anyio.ClosedResourceError, anyio.EndOfStream):
            pass
        except Exception as e:
            log.debug("MCP stdout_reader error: %s", e)

    async def stdin_writer():
        assert process.stdin
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_str = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                    await process.stdin.send(
                        (json_str + "\n").encode(encoding=encoding, errors=encoding_errors)
                    )
        except (anyio.ClosedResourceError, anyio.EndOfStream):
            pass
        except Exception as e:
            log.debug("MCP stdin_writer error: %s", e)

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            tg.cancel_scope.cancel()
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                with anyio.fail_after(PROCESS_TERMINATION_TIMEOUT):
                    await process.wait()
            except (TimeoutError, ProcessLookupError):
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            if process.stdin:
                try:
                    await process.stdin.aclose()
                except Exception:
                    pass
            if process.stdout:
                try:
                    await process.stdout.aclose()
                except Exception:
                    pass
            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()
