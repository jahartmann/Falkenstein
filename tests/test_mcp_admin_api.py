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


# ── Task 14: Read endpoints (/api/mcp/...) ────────────────────────────

@pytest.fixture
def admin_app_client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.admin_api import router as admin_router
    from backend import admin_api as mod
    from backend.database import Database
    from backend.config_service import ConfigService
    from backend.mcp.registry import MCPRegistry
    from backend.mcp.permissions import PermissionResolver
    import asyncio

    from backend.admin_api import mcp_router
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(mcp_router)

    loop = asyncio.new_event_loop()
    db = Database(tmp_path / "t.db")
    loop.run_until_complete(db.init())
    config_service = ConfigService(db)
    loop.run_until_complete(config_service.init())
    loop.run_until_complete(config_service.set("obsidian_vault_path", str(tmp_path / "Vault")))
    loop.run_until_complete(config_service.set("workspace_path", str(tmp_path / "workspace")))
    reg = MCPRegistry()
    loop.run_until_complete(reg.load_from_db(db))
    resolver = PermissionResolver(db)

    class FakeBridge:
        def __init__(self): self.registry = reg
        def get_stderr(self, sid): return ["line a", "line b"] if sid == "apple-mcp" else []
        async def list_tools(self, sid): return []
        async def discover_tools(self): return []

    mod.set_dependencies(
        db=db, scheduler=None, config_service=config_service, flow=None,
        fact_memory=None, soul_memory=None, system_monitor=None,
        mcp_bridge=FakeBridge(),
        permission_resolver=resolver, approval_store=None,
    )
    with TestClient(app) as client:
        yield client
    loop.run_until_complete(db.close())
    loop.close()


def test_api_catalog_returns_entries(admin_app_client):
    r = admin_app_client.get("/api/mcp/catalog")
    assert r.status_code == 200
    data = r.json()
    ids = {x["id"] for x in data}
    assert "apple-mcp" in ids
    for entry in data:
        assert "risk_level" in entry
        assert "installed" in entry
        assert "enabled" in entry
        assert "preflight" in entry


def test_api_servers_returns_installed_only(admin_app_client):
    r = admin_app_client.get("/api/mcp/servers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_logs(admin_app_client):
    r = admin_app_client.get("/api/mcp/servers/apple-mcp/logs")
    assert r.status_code == 200
    assert "stderr" in r.json()


def test_api_approvals_pending_empty(admin_app_client):
    r = admin_app_client.get("/api/mcp/approvals/pending")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_permissions_empty(admin_app_client):
    r = admin_app_client.get("/api/mcp/permissions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Task 15: Mutating endpoints ───────────────────────────────────────

def test_api_install_triggers_installer(admin_app_client, tmp_path, monkeypatch):
    from backend.mcp import installer as inst
    from backend import admin_api as mod
    calls = []
    async def fake_install(sid, pkg, bin_name):
        calls.append((sid, pkg, bin_name))
        from backend.mcp.installer import InstallResult
        return InstallResult(success=True, binary_path=tmp_path / "bin",
                             error=None, stderr="")
    monkeypatch.setattr(inst, "install", fake_install)
    r = admin_app_client.post("/api/mcp/servers/apple-mcp/install",
                              json={"config": {}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert calls == [("apple-mcp", "apple-mcp", "apple-mcp")]
    assert mod._mcp_bridge.registry.get_user_config("apple-mcp") == {}


def test_api_install_backfills_obsidian_vault_path(admin_app_client, tmp_path, monkeypatch):
    from backend.mcp import installer as inst
    from backend import admin_api as mod

    async def fake_install(sid, pkg, bin_name):
        from backend.mcp.installer import InstallResult
        return InstallResult(success=True, binary_path=tmp_path / "bin",
                             error=None, stderr="")

    monkeypatch.setattr(inst, "install", fake_install)
    r = admin_app_client.post("/api/mcp/servers/mcp-obsidian/install", json={"config": {}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert mod._mcp_bridge.registry.get_user_config("mcp-obsidian")["vault_path"].endswith("/Vault")


def test_api_enable_reports_preflight_error_for_invalid_obsidian_path(admin_app_client, tmp_path, monkeypatch):
    from backend.mcp import installer as inst
    from backend import admin_api as mod

    async def fake_install(sid, pkg, bin_name):
        from backend.mcp.installer import InstallResult
        return InstallResult(success=True, binary_path=tmp_path / "bin",
                             error=None, stderr="")

    monkeypatch.setattr(inst, "install", fake_install)
    monkeypatch.setattr(mod._installer, "resolve_binary", lambda sid, bin_name: tmp_path / "bin")

    original_get = mod._config_service.get
    missing_vault = str(tmp_path / "MissingVault")

    def fake_get(key, default=""):
        if key == "obsidian_vault_path":
            return missing_vault
        return original_get(key, default)

    monkeypatch.setattr(mod._config_service, "get", fake_get)

    install_resp = admin_app_client.post("/api/mcp/servers/mcp-obsidian/install", json={"config": {}})
    assert install_resp.status_code == 200
    assert install_resp.json()["status"] == "ok"

    enable_resp = admin_app_client.post("/api/mcp/servers/mcp-obsidian/enable")
    assert enable_resp.status_code == 200
    data = enable_resp.json()
    assert data["status"] == "error"
    assert data["preflight"]["ok"] is False
    assert any(issue["code"] == "path_missing" for issue in data["preflight"]["issues"])


def test_api_enable_sets_flag(admin_app_client):
    r = admin_app_client.post("/api/mcp/servers/apple-mcp/enable")
    assert r.status_code == 200


def test_api_disable_clears_flag(admin_app_client):
    admin_app_client.post("/api/mcp/servers/apple-mcp/enable")
    r = admin_app_client.post("/api/mcp/servers/apple-mcp/disable")
    assert r.status_code == 200


def test_api_permission_put_and_delete(admin_app_client):
    r = admin_app_client.put("/api/mcp/permissions/apple-mcp/some_tool",
                             json={"decision": "deny"})
    assert r.status_code == 200
    r2 = admin_app_client.get("/api/mcp/permissions")
    rows = r2.json()
    assert any(x["server_id"] == "apple-mcp" and x["tool_name"] == "some_tool"
               and x["decision"] == "deny" for x in rows)
    r3 = admin_app_client.delete("/api/mcp/permissions/apple-mcp/some_tool")
    assert r3.status_code == 200
    r4 = admin_app_client.get("/api/mcp/permissions")
    assert not any(x["tool_name"] == "some_tool" for x in r4.json())
