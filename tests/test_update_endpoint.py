# tests/test_update_endpoint.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from backend.admin_api import router

app = FastAPI()
app.include_router(router)


class _AsyncBytesStream:
    def __init__(self, lines):
        self._lines = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._lines)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeProcess:
    def __init__(self, lines: list[bytes], returncode: int = 0):
        self.stdout = _AsyncBytesStream(lines)
        self.returncode = None
        self._returncode = returncode

    async def wait(self):
        self.returncode = self._returncode
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def _fake_subprocess_factory():
    return AsyncMock(
        side_effect=[
            _FakeProcess([b"Already up to date.\n"]),
            _FakeProcess([b"Requirement already satisfied\n"]),
        ]
    )


@pytest.mark.asyncio
async def test_update_endpoint_exists():
    """POST /api/admin/update should return 200 with SSE content-type."""
    with patch("backend.admin_api.asyncio.create_subprocess_exec", _fake_subprocess_factory()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Use stream to avoid waiting for full SSE response
            async with ac.stream("POST", "/api/admin/update") as resp:
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_update_endpoint_streams_lines():
    """Update endpoint should stream at least one data: line."""
    lines = []
    with patch("backend.admin_api.asyncio.create_subprocess_exec", _fake_subprocess_factory()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with ac.stream("POST", "/api/admin/update") as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        lines.append(line)
                    if len(lines) >= 1:
                        break
    assert len(lines) >= 1
