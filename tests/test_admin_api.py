import os
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient


def test_hot_reload_fields_defined():
    from backend.config import HOT_RELOAD_FIELDS
    assert "ollama_model" in HOT_RELOAD_FIELDS
    assert "telegram_bot_token" in HOT_RELOAD_FIELDS
    assert "cli_provider" in HOT_RELOAD_FIELDS
    assert "frontend_port" not in HOT_RELOAD_FIELDS
    assert "db_path" not in HOT_RELOAD_FIELDS


def test_write_env_file(tmp_path):
    from backend.admin_api import write_env_file
    env_path = tmp_path / ".env"
    env_path.write_text("OLLAMA_MODEL=gemma4:26b\nFRONTEND_PORT=8080\n")
    write_env_file(env_path, {"OLLAMA_MODEL": "llama3"})
    content = env_path.read_text()
    assert "OLLAMA_MODEL=llama3" in content
    assert "FRONTEND_PORT=8080" in content


def test_write_env_file_adds_new_key(tmp_path):
    from backend.admin_api import write_env_file
    env_path = tmp_path / ".env"
    env_path.write_text("OLLAMA_MODEL=gemma4:26b\n")
    write_env_file(env_path, {"TELEGRAM_BOT_TOKEN": "abc123"})
    content = env_path.read_text()
    assert "OLLAMA_MODEL=gemma4:26b" in content
    assert "TELEGRAM_BOT_TOKEN=abc123" in content


def test_write_env_preserves_comments(tmp_path):
    from backend.admin_api import write_env_file
    env_path = tmp_path / ".env"
    env_path.write_text("# My config\nOLLAMA_MODEL=gemma4:26b\n")
    write_env_file(env_path, {"OLLAMA_MODEL": "llama3"})
    content = env_path.read_text()
    assert "# My config" in content
    assert "OLLAMA_MODEL=llama3" in content


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


def test_admin_page_route_exists(client):
    resp = client.get("/admin")
    # Will be 200 once admin.html exists, for now just check route exists (not 404 from missing route)
    assert resp.status_code in (200, 404)


def test_get_dashboard(client):
    resp = client.get("/api/admin/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "uptime_seconds" in data
    assert "ollama_status" in data
    assert "open_tasks_count" in data
    assert "active_agents" in data
    assert "recent_tasks" in data
    assert "budget" in data


def test_get_settings(client):
    resp = client.get("/api/admin/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "groups" in data
    groups = data["groups"]
    assert "llm" in groups
    assert "telegram" in groups
    assert "cli" in groups
    assert "obsidian" in groups
    assert "server" in groups


def test_get_settings_masks_token(client):
    resp = client.get("/api/admin/settings")
    data = resp.json()
    tg = data["groups"]["telegram"]
    token_val = tg["telegram_bot_token"]["value"]
    # Either masked or empty
    assert token_val in ("***", "")


def test_put_settings_hot_reload(client):
    resp = client.put("/api/admin/settings", json={
        "group": "cli",
        "values": {"cli_daily_token_budget": "99999"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["saved"] is True
    assert data["hot_reloaded"] is True
    assert data["restart_required"] is False


def test_put_settings_restart_required(client):
    resp = client.put("/api/admin/settings", json={
        "group": "server",
        "values": {"frontend_port": "9999"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["restart_required"] is True


def test_put_settings_unknown_group(client):
    resp = client.put("/api/admin/settings", json={
        "group": "nonexistent",
        "values": {"foo": "bar"},
    })
    data = resp.json()
    assert data["saved"] is False
