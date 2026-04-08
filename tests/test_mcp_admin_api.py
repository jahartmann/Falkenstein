"""Tests for MCP admin API endpoints."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.admin_api import router
import backend.admin_api as admin_mod

@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(router)
    admin_mod._mcp_bridge = MagicMock()
    admin_mod._mcp_bridge.servers = [
        MagicMock(
            config=MagicMock(id="apple-mcp", name="Apple", enabled=True),
            status="running", pid=123, tools_count=12,
            last_call=None, uptime_seconds=300.0, last_error=None,
        )
    ]
    tool = MagicMock()
    tool.name = "create_reminder"
    tool.description = "Create reminder"
    tool.server_id = "apple-mcp"
    tool.input_schema = {}
    admin_mod._mcp_bridge.list_tools = AsyncMock(return_value=[tool])
    admin_mod._mcp_bridge.restart_server = AsyncMock()
    admin_mod._mcp_bridge.toggle_server = AsyncMock()
    admin_mod._db = MagicMock()
    admin_mod._db.get_mcp_calls = AsyncMock(return_value=[])
    return app

@pytest.fixture
def client(app):
    return TestClient(app, headers={"Authorization": "Bearer falkenstein_2026_secret"})

def test_list_mcp_servers(client):
    resp = client.get("/api/admin/mcp/servers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["bridge_initialized"] is True
    assert len(data["servers"]) == 1
    assert data["servers"][0]["id"] == "apple-mcp"

def test_get_mcp_server_tools(client):
    resp = client.get("/api/admin/mcp/servers/apple-mcp/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "create_reminder"

def test_restart_mcp_server(client):
    resp = client.post("/api/admin/mcp/servers/apple-mcp/restart")
    assert resp.status_code == 200
    admin_mod._mcp_bridge.restart_server.assert_called_once_with("apple-mcp")

def test_toggle_mcp_server(client):
    resp = client.post("/api/admin/mcp/servers/apple-mcp/toggle", json={"enabled": False})
    assert resp.status_code == 200
    admin_mod._mcp_bridge.toggle_server.assert_called_once_with("apple-mcp", False)

def test_get_mcp_logs(client):
    resp = client.get("/api/admin/mcp/servers/apple-mcp/logs")
    assert resp.status_code == 200
    admin_mod._db.get_mcp_calls.assert_called_once()
