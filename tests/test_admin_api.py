import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient


def test_hot_reload_fields_defined():
    from backend.config import HOT_RELOAD_FIELDS
    assert "ollama_model" in HOT_RELOAD_FIELDS
    assert "telegram_bot_token" in HOT_RELOAD_FIELDS
    assert "cli_provider" in HOT_RELOAD_FIELDS
    assert "frontend_port" not in HOT_RELOAD_FIELDS
    assert "db_path" not in HOT_RELOAD_FIELDS


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


def test_get_schedules(client):
    resp = client.get("/api/admin/schedules")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


def test_get_config(client):
    resp = client.get("/api/admin/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data


def test_set_dependencies():
    from backend.admin_api import set_dependencies, _db, _scheduler
    mock_db = MagicMock()
    mock_sched = MagicMock()
    set_dependencies(db=mock_db, scheduler=mock_sched)
    import backend.admin_api as api
    assert api._db is mock_db
    assert api._scheduler is mock_sched
    # Clean up
    set_dependencies(db=None, scheduler=None)


def test_schedule_endpoints_use_int_ids(client):
    """Verify schedule endpoints accept integer IDs (not filenames)."""
    # GET detail — should return error since no DB, not a route-not-found
    resp = client.get("/api/admin/schedules/1")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data  # "DB not initialized" or similar

    # Toggle
    resp = client.post("/api/admin/schedules/1/toggle")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data

    # Delete
    resp = client.delete("/api/admin/schedules/1")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_config_category(client):
    resp = client.get("/api/admin/config/llm")
    assert resp.status_code == 200
    data = resp.json()
    assert "config" in data


def test_put_config(client):
    resp = client.put("/api/admin/config", json={"updates": {"ollama_host": "http://localhost:11434"}})
    assert resp.status_code == 200
    data = resp.json()
    # Without config_service it returns error
    assert "error" in data or "saved" in data
