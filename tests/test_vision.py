import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from backend.tools.vision import VisionTool


@pytest.fixture
def tool(tmp_path):
    llm = AsyncMock()
    llm.analyze_image = AsyncMock(return_value="Ein Screenshot mit einer Fehlermeldung")
    return VisionTool(workspace_path=tmp_path, llm=llm)


@pytest.mark.asyncio
async def test_analyze_image(tool, tmp_path):
    img = tmp_path / "screenshot.png"
    img.write_bytes(b"fake png data")
    result = await tool.execute({"image_path": "screenshot.png", "question": "Was ist das?"})
    assert result.success
    assert "Fehlermeldung" in result.output


@pytest.mark.asyncio
async def test_no_image_path(tool):
    result = await tool.execute({"question": "Was?"})
    assert not result.success
    assert "image_path" in result.output.lower()


@pytest.mark.asyncio
async def test_image_not_found(tool):
    result = await tool.execute({"image_path": "nonexistent.png"})
    assert not result.success
    assert "nicht gefunden" in result.output


@pytest.mark.asyncio
async def test_path_traversal_blocked(tool):
    result = await tool.execute({"image_path": "../../etc/passwd.png"})
    assert not result.success


@pytest.mark.asyncio
async def test_wrong_format(tool, tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("not an image")
    result = await tool.execute({"image_path": "data.txt"})
    assert not result.success
    assert "Bildformat" in result.output


@pytest.mark.asyncio
async def test_default_question(tool, tmp_path):
    img = tmp_path / "test.jpg"
    img.write_bytes(b"fake jpg")
    result = await tool.execute({"image_path": "test.jpg"})
    assert result.success
    tool.llm.analyze_image.assert_called_once()


def test_schema(tool):
    schema = tool.schema()
    assert "image_path" in schema["properties"]
    assert "question" in schema["properties"]
