import pytest
import datetime
from pathlib import Path
from backend.tools.obsidian_manager import ObsidianManagerTool


@pytest.fixture
def vault(tmp_path):
    tool = ObsidianManagerTool(vault_path=tmp_path)
    return tmp_path, tool


@pytest.mark.asyncio
async def test_write_task_result_to_project(vault):
    tmp_path, tool = vault
    await tool.execute({"action": "project", "content": "website"})
    result = await tool.write_task_result(
        task_title="Login fixen",
        result="Fixed auth token validation in login.py",
        project="website",
        agent_name="Alex",
    )
    assert result.success
    tasks_path = tmp_path / "Falkenstein" / "Projekte" / "website" / "Tasks.md"
    content = tasks_path.read_text()
    assert "Login fixen" in content
    assert "Alex" in content
    assert "Fixed auth token" in content


@pytest.mark.asyncio
async def test_write_task_result_no_project(vault):
    tmp_path, tool = vault
    result = await tool.write_task_result(
        task_title="General cleanup",
        result="Removed unused imports",
        project=None,
        agent_name="Max",
    )
    assert result.success
    inbox = tmp_path / "Management" / "Inbox.md"
    content = inbox.read_text()
    assert "General cleanup" in content


@pytest.mark.asyncio
async def test_log_escalation(vault):
    tmp_path, tool = vault
    result = await tool.log_escalation(
        agent_name="Bob",
        task_title="Complex refactor",
        details="Claude CLI completed successfully after 3 retries",
    )
    assert result.success
    today = datetime.date.today().isoformat()
    report = tmp_path / "Falkenstein" / "Daily Reports" / f"{today}.md"
    content = report.read_text()
    assert "Eskalation" in content
    assert "Bob" in content


@pytest.mark.asyncio
async def test_write_task_result_long_result_truncated(vault):
    tmp_path, tool = vault
    long_result = "x" * 500
    result = await tool.write_task_result(
        task_title="Big task",
        result=long_result,
        project=None,
        agent_name="Clara",
    )
    assert result.success
    inbox = tmp_path / "Management" / "Inbox.md"
    content = inbox.read_text()
    # Inbox entry should be truncated to 300 chars of result
    assert len(content) < 600  # title + truncated result + overhead
