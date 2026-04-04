import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.tools.ollama_manager import OllamaManagerTool


@pytest.fixture
def tool():
    return OllamaManagerTool(timeout=10)


@pytest.mark.asyncio
async def test_list_models(tool):
    with patch("backend.tools.ollama_manager.asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"NAME\ngemma4:26b\n", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        result = await tool.execute({"action": "list"})
        assert result.success
        assert "gemma4" in result.output


@pytest.mark.asyncio
async def test_pull_no_model(tool):
    result = await tool.execute({"action": "pull"})
    assert not result.success
    assert "Kein Modell" in result.output


@pytest.mark.asyncio
async def test_pull_model(tool):
    with patch("backend.tools.ollama_manager.asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"pulling gemma4:26b\n", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        result = await tool.execute({"action": "pull", "model": "gemma4:26b"})
        assert result.success


@pytest.mark.asyncio
async def test_remove_no_model(tool):
    result = await tool.execute({"action": "remove"})
    assert not result.success


@pytest.mark.asyncio
async def test_ps(tool):
    with patch("backend.tools.ollama_manager.asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"NAME\n", b""))
        proc.returncode = 0
        mock_exec.return_value = proc

        result = await tool.execute({"action": "ps"})
        assert result.success


@pytest.mark.asyncio
async def test_unknown_action(tool):
    result = await tool.execute({"action": "restart"})
    assert not result.success
    assert "Unbekannte Action" in result.output


@pytest.mark.asyncio
async def test_ollama_not_found(tool):
    with patch("backend.tools.ollama_manager.asyncio.create_subprocess_exec",
               side_effect=FileNotFoundError):
        result = await tool.execute({"action": "list"})
        assert not result.success
        assert "nicht gefunden" in result.output


def test_schema(tool):
    s = tool.schema()
    assert "action" in s["properties"]
    assert "model" in s["properties"]
