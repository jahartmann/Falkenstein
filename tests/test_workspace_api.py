# tests/test_workspace_api.py
import pytest
import os
import tempfile
from httpx import AsyncClient
from fastapi import FastAPI

# Patch dependencies before import
import backend.workspace_api as ws_module
ws_module._sessions = {}

from backend.workspace_api import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_set_workspace_path_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.post("/api/workspace/path", json={"path": tmpdir})
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == tmpdir
        assert data["type"] == "directory"


@pytest.mark.asyncio
async def test_set_workspace_path_invalid():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/api/workspace/path", json={"path": "/nonexistent/path/xyz"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_workspace_empty():
    ws_module._sessions = {}
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/workspace/current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is False


@pytest.mark.asyncio
async def test_delete_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        async with AsyncClient(app=app, base_url="http://test") as ac:
            await ac.post("/api/workspace/path", json={"path": tmpdir})
            resp = await ac.delete("/api/workspace/current")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"
