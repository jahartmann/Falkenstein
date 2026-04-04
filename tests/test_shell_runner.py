import pytest
from pathlib import Path
from backend.tools.shell_runner import ShellRunnerTool


@pytest.fixture
def tool(tmp_path):
    return ShellRunnerTool(workspace_path=tmp_path, timeout=10)


@pytest.mark.asyncio
async def test_echo_command(tool):
    result = await tool.execute({"command": "echo hello"})
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_empty_command(tool):
    result = await tool.execute({"command": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_no_command(tool):
    result = await tool.execute({})
    assert not result.success


@pytest.mark.asyncio
async def test_blacklisted_rm_rf(tool):
    result = await tool.execute({"command": "rm -rf /"})
    assert not result.success
    assert "blockiert" in result.output.lower() or "Blacklist" in result.output


@pytest.mark.asyncio
async def test_blacklisted_mkfs(tool):
    result = await tool.execute({"command": "mkfs /dev/sda1"})
    assert not result.success


@pytest.mark.asyncio
async def test_blacklisted_shutdown(tool):
    result = await tool.execute({"command": "shutdown -h now"})
    assert not result.success


@pytest.mark.asyncio
async def test_failing_command(tool):
    result = await tool.execute({"command": "false"})
    assert not result.success
    assert "Exit code" in result.output or "exit" in result.output.lower()


@pytest.mark.asyncio
async def test_ls_workspace(tool, tmp_path):
    (tmp_path / "testfile.txt").write_text("hello")
    result = await tool.execute({"command": "ls"})
    assert result.success
    assert "testfile.txt" in result.output


@pytest.mark.asyncio
async def test_timeout(tool):
    tool.timeout = 1
    result = await tool.execute({"command": "sleep 10"})
    assert not result.success
    assert "Timeout" in result.output


@pytest.mark.asyncio
async def test_stderr_captured(tool):
    result = await tool.execute({"command": "ls /nonexistent_dir_12345"})
    assert not result.success


def test_schema(tool):
    schema = tool.schema()
    assert "command" in schema["properties"]
    assert schema["required"] == ["command"]
