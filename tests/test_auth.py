"""Tests for BearerAuthMiddleware."""
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from backend.security.auth import BearerAuthMiddleware


def make_app(api_token: str = "") -> FastAPI:
    """Create a minimal FastAPI app with BearerAuthMiddleware for testing."""
    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware, api_token=api_token)

    @app.get("/")
    def root():
        return {"status": "ok"}

    @app.get("/api/status")
    def api_status():
        return {"status": "ok"}

    @app.get("/api/agents")
    def api_agents():
        return {"agents": []}

    @app.get("/static/style.css")
    def static_file():
        return {"content": "css"}

    @app.get("/office")
    def office():
        return {"page": "office"}

    return app


class TestNoTokenConfigured:
    """When no API_TOKEN is set, all routes pass through (backward compat)."""

    def setup_method(self):
        self.client = TestClient(make_app(api_token=""), raise_server_exceptions=True)

    def test_root_allowed(self):
        r = self.client.get("/")
        assert r.status_code == 200

    def test_api_allowed_without_auth(self):
        r = self.client.get("/api/status")
        assert r.status_code == 200

    def test_api_allowed_with_any_token(self):
        r = self.client.get("/api/status", headers={"Authorization": "Bearer whatever"})
        assert r.status_code == 200


class TestPublicRoutes:
    """Public routes never need auth, even when a token is configured."""

    def setup_method(self):
        self.client = TestClient(make_app(api_token="secret123"), raise_server_exceptions=True)

    def test_root_no_auth(self):
        r = self.client.get("/")
        assert r.status_code == 200

    def test_static_no_auth(self):
        r = self.client.get("/static/style.css")
        assert r.status_code == 200

    def test_office_no_auth(self):
        r = self.client.get("/office")
        assert r.status_code == 200


class TestProtectedRoutes:
    """When a token is configured, /api/* requires Bearer auth."""

    def setup_method(self):
        self.client = TestClient(make_app(api_token="secret123"), raise_server_exceptions=True)

    def test_api_blocked_without_token(self):
        r = self.client.get("/api/status")
        assert r.status_code == 401

    def test_api_blocked_wrong_token(self):
        r = self.client.get("/api/status", headers={"Authorization": "Bearer wrongtoken"})
        assert r.status_code == 401

    def test_api_allowed_correct_bearer(self):
        r = self.client.get("/api/status", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200

    def test_api_blocked_missing_bearer_prefix(self):
        r = self.client.get("/api/status", headers={"Authorization": "secret123"})
        assert r.status_code == 401

    def test_api_allowed_query_param_token(self):
        r = self.client.get("/api/status?token=secret123")
        assert r.status_code == 200

    def test_api_blocked_wrong_query_param(self):
        r = self.client.get("/api/status?token=badtoken")
        assert r.status_code == 401

    def test_401_returns_json(self):
        r = self.client.get("/api/agents")
        assert r.status_code == 401
        body = r.json()
        assert "detail" in body

    def test_api_agents_allowed_correct_token(self):
        r = self.client.get("/api/agents", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200


class TestTokenWithWhitespace:
    """Token configured with surrounding whitespace is stripped."""

    def setup_method(self):
        self.client = TestClient(make_app(api_token="  mytoken  "), raise_server_exceptions=True)

    def test_stripped_token_works(self):
        r = self.client.get("/api/status", headers={"Authorization": "Bearer mytoken"})
        assert r.status_code == 200
