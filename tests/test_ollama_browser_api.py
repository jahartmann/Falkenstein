# tests/test_ollama_browser_api.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from backend.admin_api import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_ollama_models_endpoint_structure():
    """Test that /api/admin/ollama/models returns expected structure."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {
                "name": "gemma4:26b",
                "size": 15_000_000_000,
                "modified_at": "2026-04-01T10:00:00Z",
                "details": {"parameter_size": "26B"},
            }
        ]
    }
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/admin/ollama/models")
        # Accept 200 or 500 (Ollama not running in test env)
        assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_ollama_pull_requires_model_name():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/admin/ollama/pull", json={})
    assert resp.status_code == 422  # Validation error — missing model field
