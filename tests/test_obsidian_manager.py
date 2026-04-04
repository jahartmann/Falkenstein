import pytest
import datetime
from pathlib import Path
from backend.tools.obsidian_manager import ObsidianManagerTool


@pytest.fixture
def tool(tmp_path):
    return ObsidianManagerTool(vault_path=tmp_path)


@pytest.mark.asyncio
async def test_write_and_read(tool, tmp_path):
    await tool.execute({"action": "write", "path": "notes/test.md", "content": "Hello Vault"})
    result = await tool.execute({"action": "read", "path": "notes/test.md"})
    assert result.success
    assert "Hello Vault" in result.output


@pytest.mark.asyncio
async def test_append(tool, tmp_path):
    await tool.execute({"action": "write", "path": "log.md", "content": "Line 1"})
    await tool.execute({"action": "append", "path": "log.md", "content": "Line 2"})
    result = await tool.execute({"action": "read", "path": "log.md"})
    assert "Line 1" in result.output
    assert "Line 2" in result.output


@pytest.mark.asyncio
async def test_list(tool, tmp_path):
    (tmp_path / "note1.md").write_text("a")
    (tmp_path / "note2.md").write_text("b")
    (tmp_path / "subdir").mkdir()
    result = await tool.execute({"action": "list", "path": "."})
    assert result.success
    assert "note1.md" in result.output
    assert "subdir" in result.output


@pytest.mark.asyncio
async def test_list_hides_dotfiles(tool, tmp_path):
    (tmp_path / ".hidden").write_text("secret")
    (tmp_path / "visible.md").write_text("public")
    result = await tool.execute({"action": "list", "path": "."})
    assert ".hidden" not in result.output
    assert "visible.md" in result.output


@pytest.mark.asyncio
async def test_read_nonexistent(tool):
    result = await tool.execute({"action": "read", "path": "nope.md"})
    assert not result.success


@pytest.mark.asyncio
async def test_path_traversal_blocked(tool):
    result = await tool.execute({"action": "read", "path": "../../etc/passwd"})
    assert not result.success
    assert "außerhalb" in result.output.lower() or "Vault" in result.output


@pytest.mark.asyncio
async def test_daily_report(tool, tmp_path):
    result = await tool.execute({"action": "daily_report", "content": "Alles erledigt heute."})
    assert result.success
    today = datetime.date.today().isoformat()
    report = (tmp_path / "KI-Büro" / "Falkenstein" / "Daily Reports" / f"{today}.md").read_text()
    assert "Alles erledigt" in report
    assert today in report


@pytest.mark.asyncio
async def test_daily_report_append(tool, tmp_path):
    await tool.execute({"action": "daily_report", "content": "Morgens"})
    await tool.execute({"action": "daily_report", "content": "Abends"})
    today = datetime.date.today().isoformat()
    report = (tmp_path / "KI-Büro" / "Falkenstein" / "Daily Reports" / f"{today}.md").read_text()
    assert "Morgens" in report
    assert "Abends" in report


@pytest.mark.asyncio
async def test_inbox(tool, tmp_path):
    result = await tool.execute({"action": "inbox", "content": "Neue Idee prüfen"})
    assert result.success
    inbox = (tmp_path / "KI-Büro" / "Inbox.md").read_text()
    assert "Neue Idee" in inbox
    assert "- [ ]" in inbox


@pytest.mark.asyncio
async def test_inbox_multiple(tool, tmp_path):
    await tool.execute({"action": "inbox", "content": "Aufgabe 1"})
    await tool.execute({"action": "inbox", "content": "Aufgabe 2"})
    inbox = (tmp_path / "KI-Büro" / "Inbox.md").read_text()
    assert "Aufgabe 1" in inbox
    assert "Aufgabe 2" in inbox


@pytest.mark.asyncio
async def test_write_no_path(tool):
    result = await tool.execute({"action": "write", "content": "no path"})
    assert not result.success


@pytest.mark.asyncio
async def test_daily_report_no_content(tool):
    result = await tool.execute({"action": "daily_report"})
    assert not result.success


@pytest.mark.asyncio
async def test_unknown_action(tool):
    result = await tool.execute({"action": "delete_everything"})
    assert not result.success


def test_schema(tool):
    schema = tool.schema()
    assert "action" in schema["properties"]
    assert "inbox" in schema["properties"]["action"]["enum"]
