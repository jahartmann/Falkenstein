import pytest
from pathlib import Path
from backend.tools.system_shell import SystemShellTool


@pytest.fixture
def tool(tmp_path):
    return SystemShellTool(home_path=tmp_path, timeout=10)


@pytest.mark.asyncio
async def test_echo(tool):
    result = await tool.execute({"command": "echo hello"})
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_empty_command(tool):
    result = await tool.execute({"command": ""})
    assert not result.success
    assert "Kein Befehl" in result.output


@pytest.mark.asyncio
async def test_blacklisted_rm_rf(tool):
    result = await tool.execute({"command": "rm -rf /"})
    assert not result.success
    assert "Blockiert" in result.output


@pytest.mark.asyncio
async def test_blacklisted_mkfs(tool):
    result = await tool.execute({"command": "mkfs.ext4 /dev/sda"})
    assert not result.success


@pytest.mark.asyncio
async def test_blacklisted_shutdown(tool):
    result = await tool.execute({"command": "shutdown -h now"})
    assert not result.success


@pytest.mark.asyncio
async def test_custom_cwd(tool, tmp_path):
    result = await tool.execute({"command": "pwd", "cwd": str(tmp_path)})
    assert result.success
    assert str(tmp_path) in result.output


@pytest.mark.asyncio
async def test_nonexistent_cwd(tool):
    result = await tool.execute({"command": "ls", "cwd": "/nonexistent_dir_xyz"})
    assert not result.success
    assert "existiert nicht" in result.output


@pytest.mark.asyncio
async def test_failing_command(tool):
    result = await tool.execute({"command": "false"})
    assert not result.success


@pytest.mark.asyncio
async def test_ls_home(tool, tmp_path):
    # Create a file in the home dir
    (tmp_path / "testfile.txt").write_text("hi")
    result = await tool.execute({"command": "ls"})
    assert result.success
    assert "testfile.txt" in result.output


@pytest.mark.asyncio
async def test_protected_dir_rm(tool):
    result = await tool.execute({"command": "rm -rf /System/Library"})
    assert not result.success
    assert "Blockiert" in result.output


def test_schema(tool):
    s = tool.schema()
    assert "command" in s["properties"]
    assert "cwd" in s["properties"]
