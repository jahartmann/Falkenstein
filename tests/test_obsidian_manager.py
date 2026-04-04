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
    report = (tmp_path / "KI-Büro" / "Reports" / f"{today}.md").read_text()
    assert "Alles erledigt" in report
    assert today in report


@pytest.mark.asyncio
async def test_daily_report_append(tool, tmp_path):
    await tool.execute({"action": "daily_report", "content": "Morgens"})
    await tool.execute({"action": "daily_report", "content": "Abends"})
    today = datetime.date.today().isoformat()
    report = (tmp_path / "KI-Büro" / "Reports" / f"{today}.md").read_text()
    assert "Morgens" in report
    assert "Abends" in report


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
    assert "daily_report" in schema["properties"]["action"]["enum"]
    assert "inbox" not in schema["properties"]["action"]["enum"]
    assert "todo" not in schema["properties"]["action"]["enum"]


@pytest.mark.asyncio
async def test_create_project(tool, tmp_path):
    result = await tool.execute({"action": "project", "content": "TestProjekt"})
    assert result.success
    project_dir = tmp_path / "KI-Büro" / "Projekte" / "TestProjekt"
    assert project_dir.exists()
    readme = (project_dir / "README.md").read_text()
    assert "TestProjekt" in readme
    assert "In Arbeit" in readme
    # No Tasks.md or Ergebnisse subfolder
    assert not (project_dir / "Tasks.md").exists()
    assert not (project_dir / "Ergebnisse").exists()


@pytest.mark.asyncio
async def test_create_project_already_exists(tool, tmp_path):
    await tool.execute({"action": "project", "content": "Doppelt"})
    result = await tool.execute({"action": "project", "content": "Doppelt"})
    assert result.success
    assert "existiert" in result.output


@pytest.mark.asyncio
async def test_create_project_no_name(tool):
    result = await tool.execute({"action": "project", "content": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_write_task_result_with_project(tool, tmp_path):
    # Create project first
    await tool.execute({"action": "project", "content": "MyProject"})
    result = await tool.write_task_result("Test Task", "Some result", "MyProject", "coder-1")
    assert result.success
    # Check file was written in project folder
    projekte = tmp_path / "KI-Büro" / "Projekte" / "MyProject"
    md_files = [f for f in projekte.iterdir() if f.suffix == ".md" and f.name != "README.md"]
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert "Test Task" in content
    assert "coder-1" in content


@pytest.mark.asyncio
async def test_write_task_result_without_project(tool, tmp_path):
    result = await tool.write_task_result("General Task", "Result text", None, "writer-1")
    assert result.success
    wissen = tmp_path / "KI-Büro" / "Wissen"
    md_files = list(wissen.glob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert "General Task" in content
    assert "writer-1" in content


@pytest.mark.asyncio
async def test_log_escalation(tool, tmp_path):
    result = await tool.log_escalation("ops-1", "Deploy failed", "Timeout after 30s")
    assert result.success
    today = datetime.date.today().isoformat()
    report = (tmp_path / "KI-Büro" / "Reports" / f"{today}.md").read_text()
    assert "Eskalation" in report
    assert "Deploy failed" in report


@pytest.mark.asyncio
async def test_init_vault(tool, tmp_path):
    result = await tool.execute({"action": "init_vault"})
    assert result.success
    assert (tmp_path / "KI-Büro" / "Wissen").is_dir()
    assert (tmp_path / "KI-Büro" / "Projekte").is_dir()
    assert (tmp_path / "KI-Büro" / "Reports").is_dir()


@pytest.mark.asyncio
async def test_vault_structure_no_legacy_folders(tool, tmp_path):
    """Ensure old structure artifacts are not created."""
    assert not (tmp_path / "KI-Büro" / "Inbox.md").exists()
    assert not (tmp_path / "KI-Büro" / "Kanban.md").exists()
    assert not (tmp_path / "KI-Büro" / "Schedules").exists()
    assert not (tmp_path / "KI-Büro" / "Falkenstein").exists()
    assert not (tmp_path / "KI-Büro" / "Ergebnisse").exists()
