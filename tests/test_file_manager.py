import pytest
import pytest_asyncio
from pathlib import Path
from backend.tools.file_manager import FileManagerTool


@pytest_asyncio.fixture
async def tool(tmp_path):
    return FileManagerTool(workspace_path=tmp_path)


@pytest.mark.asyncio
async def test_write_and_read_file(tool, tmp_path):
    result = await tool.execute({"action": "write", "path": "test.txt", "content": "hello world"})
    assert result.success is True
    assert (tmp_path / "test.txt").read_text() == "hello world"
    result = await tool.execute({"action": "read", "path": "test.txt"})
    assert result.success is True
    assert result.output == "hello world"


@pytest.mark.asyncio
async def test_write_creates_subdirectories(tool, tmp_path):
    result = await tool.execute({"action": "write", "path": "sub/dir/file.py", "content": "print('hi')"})
    assert result.success is True
    assert (tmp_path / "sub" / "dir" / "file.py").read_text() == "print('hi')"


@pytest.mark.asyncio
async def test_list_files(tool, tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    result = await tool.execute({"action": "list", "path": "."})
    assert result.success is True
    assert "a.txt" in result.output
    assert "b.txt" in result.output


@pytest.mark.asyncio
async def test_delete_file(tool, tmp_path):
    (tmp_path / "delete_me.txt").write_text("bye")
    result = await tool.execute({"action": "delete", "path": "delete_me.txt"})
    assert result.success is True
    assert not (tmp_path / "delete_me.txt").exists()


@pytest.mark.asyncio
async def test_path_traversal_blocked(tool):
    result = await tool.execute({"action": "read", "path": "../../etc/passwd"})
    assert result.success is False
    assert "outside" in result.output.lower() or "nicht erlaubt" in result.output.lower()


@pytest.mark.asyncio
async def test_read_nonexistent_file(tool):
    result = await tool.execute({"action": "read", "path": "nope.txt"})
    assert result.success is False


@pytest.mark.asyncio
async def test_schema_returns_dict(tool):
    schema = tool.schema()
    assert "properties" in schema
    assert "action" in schema["properties"]
