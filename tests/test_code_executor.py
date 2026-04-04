import pytest
from pathlib import Path
from backend.tools.code_executor import CodeExecutorTool


@pytest.fixture
def tool(tmp_path):
    return CodeExecutorTool(workspace_path=tmp_path, timeout=10)


@pytest.mark.asyncio
async def test_python_hello(tool):
    result = await tool.execute({"code": "print('hello world')", "language": "python"})
    assert result.success
    assert "hello world" in result.output


@pytest.mark.asyncio
async def test_python_default_language(tool):
    result = await tool.execute({"code": "print(2+2)"})
    assert result.success
    assert "4" in result.output


@pytest.mark.asyncio
async def test_python_error(tool):
    result = await tool.execute({"code": "raise ValueError('test error')", "language": "python"})
    assert not result.success
    assert "test error" in result.output


@pytest.mark.asyncio
async def test_python_syntax_error(tool):
    result = await tool.execute({"code": "def foo(", "language": "python"})
    assert not result.success


@pytest.mark.asyncio
async def test_shell_echo(tool):
    result = await tool.execute({"code": "echo shell works", "language": "shell"})
    assert result.success
    assert "shell works" in result.output


@pytest.mark.asyncio
async def test_shell_error(tool):
    result = await tool.execute({"code": "exit 1", "language": "shell"})
    assert not result.success


@pytest.mark.asyncio
async def test_empty_code(tool):
    result = await tool.execute({"code": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_unknown_language(tool):
    result = await tool.execute({"code": "console.log('hi')", "language": "javascript"})
    assert not result.success
    assert "Unbekannte" in result.output


@pytest.mark.asyncio
async def test_python_timeout(tool):
    tool.timeout = 1
    result = await tool.execute({"code": "import time; time.sleep(10)"})
    assert not result.success
    assert "Timeout" in result.output


@pytest.mark.asyncio
async def test_python_file_io_in_workspace(tool, tmp_path):
    code = "with open('output.txt', 'w') as f: f.write('created by agent')"
    result = await tool.execute({"code": code})
    assert result.success
    assert (tmp_path / "output.txt").read_text() == "created by agent"


@pytest.mark.asyncio
async def test_tmp_file_cleaned_up(tool, tmp_path):
    await tool.execute({"code": "print('cleanup test')"})
    assert not (tmp_path / ".tmp_exec.py").exists()


def test_schema(tool):
    schema = tool.schema()
    assert "code" in schema["properties"]
    assert "language" in schema["properties"]
