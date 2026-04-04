import pytest
from pathlib import Path
from backend.tools.self_config import SelfConfigTool


@pytest.fixture
def tool(tmp_path):
    # Create minimal project structure
    (tmp_path / ".env").write_text("OLLAMA_MODEL=gemma4:26b\nTELEGRAM_BOT_TOKEN=secret123\n")
    (tmp_path / "SOUL.md").write_text("# Falki\nIch bin Falki.")
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\nInstructions here.")
    return SelfConfigTool(project_path=tmp_path)


@pytest.mark.asyncio
async def test_list_configs(tool):
    result = await tool.execute({"action": "list"})
    assert result.success
    assert "SOUL.md" in result.output
    assert ".env" in result.output


@pytest.mark.asyncio
async def test_read_soul(tool):
    result = await tool.execute({"action": "read", "file": "SOUL.md"})
    assert result.success
    assert "Falki" in result.output


@pytest.mark.asyncio
async def test_read_env(tool):
    result = await tool.execute({"action": "read", "file": ".env"})
    assert result.success
    assert "OLLAMA_MODEL" in result.output


@pytest.mark.asyncio
async def test_read_nonexistent(tool):
    result = await tool.execute({"action": "read", "file": "AGENTS.md"})
    assert not result.success
    assert "existiert nicht" in result.output


@pytest.mark.asyncio
async def test_write_soul(tool, tmp_path):
    result = await tool.execute({"action": "write", "file": "SOUL.md", "content": "# Falki v2"})
    assert result.success
    assert "SOUL.md geschrieben" in result.output
    assert (tmp_path / "SOUL.md").read_text() == "# Falki v2"


@pytest.mark.asyncio
async def test_write_claude_md_blocked(tool):
    result = await tool.execute({"action": "write", "file": "CLAUDE.md", "content": "hack"})
    assert not result.success
    assert "read-only" in result.output


@pytest.mark.asyncio
async def test_path_traversal_blocked(tool):
    result = await tool.execute({"action": "read", "file": "../../../etc/passwd"})
    assert not result.success
    assert "Traversal" in result.output


@pytest.mark.asyncio
async def test_disallowed_file(tool):
    result = await tool.execute({"action": "read", "file": "secrets.json"})
    assert not result.success
    assert "nicht erlaubt" in result.output


@pytest.mark.asyncio
async def test_env_get(tool):
    result = await tool.execute({"action": "env_get", "key": "OLLAMA_MODEL"})
    assert result.success
    assert "gemma4:26b" in result.output


@pytest.mark.asyncio
async def test_env_get_masks_token(tool):
    result = await tool.execute({"action": "env_get", "key": "TELEGRAM_BOT_TOKEN"})
    assert result.success
    assert "secret123" not in result.output
    assert "*****" in result.output


@pytest.mark.asyncio
async def test_env_get_missing_key(tool):
    result = await tool.execute({"action": "env_get", "key": "NONEXISTENT"})
    assert not result.success


@pytest.mark.asyncio
async def test_env_set_new(tool, tmp_path):
    result = await tool.execute({"action": "env_set", "key": "NEW_VAR", "value": "hello"})
    assert result.success
    content = (tmp_path / ".env").read_text()
    assert "NEW_VAR=hello" in content


@pytest.mark.asyncio
async def test_env_set_update(tool, tmp_path):
    result = await tool.execute({"action": "env_set", "key": "OLLAMA_MODEL", "value": "llama3:8b"})
    assert result.success
    content = (tmp_path / ".env").read_text()
    assert "OLLAMA_MODEL=llama3:8b" in content
    # Old value should be gone
    assert "gemma4:26b" not in content


@pytest.mark.asyncio
async def test_unknown_action(tool):
    result = await tool.execute({"action": "delete"})
    assert not result.success
    assert "Unbekannte Action" in result.output


def test_schema(tool):
    s = tool.schema()
    assert "action" in s["properties"]
    assert "file" in s["properties"]
    assert "key" in s["properties"]
