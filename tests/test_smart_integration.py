"""Smoke tests for the new slim main.py structure."""


def test_app_import():
    from backend.main import app
    assert app.title == "Falkenstein"


def test_app_has_required_routes():
    from backend.main import app
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/ws" in routes
    assert "/api/task" in routes
    assert "/api/agents" in routes
    assert "/api/tasks" in routes
    assert "/api/status" in routes
    assert "/api/budget" in routes
