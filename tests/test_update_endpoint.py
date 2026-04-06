# tests/test_update_endpoint.py
import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from backend.admin_api import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_update_endpoint_exists():
    """POST /api/admin/update should return 200 with SSE content-type."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Use stream to avoid waiting for full SSE response
        async with ac.stream("POST", "/api/admin/update") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_update_endpoint_streams_lines():
    """Update endpoint should stream at least one data: line."""
    lines = []
    async with AsyncClient(app=app, base_url="http://test") as ac:
        async with ac.stream("POST", "/api/admin/update") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    lines.append(line)
                if len(lines) >= 1:
                    break
    assert len(lines) >= 1
