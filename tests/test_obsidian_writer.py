import datetime
from pathlib import Path
import pytest

from backend.obsidian_writer import ObsidianWriter


@pytest.fixture
def tmp_vault(tmp_path):
    vault = tmp_path / "TestVault"
    vault.mkdir()
    ki = vault / "KI-Büro"
    ki.mkdir()
    mgmt = ki / "Management"
    mgmt.mkdir()
    kanban = mgmt / "Kanban.md"
    kanban.write_text(
        "# Kanban Board\n\n## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
    )
    tasks = ki / "Falkenstein" / "Tasks"
    tasks.mkdir(parents=True)
    for sub in ["Recherchen", "Guides", "Cheat-Sheets", "Reports", "Code"]:
        (ki / "Falkenstein" / "Ergebnisse" / sub).mkdir(parents=True)
    (ki / "Falkenstein" / "Daily Reports").mkdir(parents=True)
    return vault


@pytest.fixture
def writer(tmp_vault):
    return ObsidianWriter(vault_path=tmp_vault)


def test_create_task_note(writer, tmp_vault):
    path = writer.create_task_note(
        title="Docker vs Podman recherchieren",
        typ="recherche",
        agent="researcher",
    )
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "status: backlog" in content
    assert "agent: researcher" in content
    assert "# Docker vs Podman recherchieren" in content


def test_kanban_add_backlog(writer, tmp_vault):
    writer.create_task_note(title="Test Task", typ="code", agent="coder")
    writer.kanban_move("Test Task", "backlog")
    kanban = (tmp_vault / "KI-Büro" / "Management" / "Kanban.md").read_text()
    assert "Test Task" in kanban
    backlog_pos = kanban.index("## Backlog")
    in_progress_pos = kanban.index("## In Progress")
    task_pos = kanban.index("Test Task")
    assert backlog_pos < task_pos < in_progress_pos


def test_kanban_move_to_in_progress(writer, tmp_vault):
    writer.create_task_note(title="Moving Task", typ="code", agent="coder")
    writer.kanban_move("Moving Task", "backlog")
    writer.kanban_move("Moving Task", "in_progress")
    kanban = (tmp_vault / "KI-Büro" / "Management" / "Kanban.md").read_text()
    in_progress_pos = kanban.index("## In Progress")
    done_pos = kanban.index("## Done")
    task_pos = kanban.index("Moving Task")
    assert in_progress_pos < task_pos < done_pos


def test_kanban_move_to_done(writer, tmp_vault):
    writer.create_task_note(title="Done Task", typ="recherche", agent="researcher")
    writer.kanban_move("Done Task", "backlog")
    writer.kanban_move("Done Task", "done")
    kanban = (tmp_vault / "KI-Büro" / "Management" / "Kanban.md").read_text()
    assert "- [x]" in kanban


def test_write_result_recherche(writer, tmp_vault):
    path = writer.write_result(
        title="Docker vs Podman",
        typ="recherche",
        content="# Docker vs Podman\n\nDocker ist...",
    )
    assert "Recherchen" in str(path)
    assert path.exists()
    assert "Docker ist" in path.read_text()


def test_write_result_guide(writer, tmp_vault):
    path = writer.write_result(
        title="Git Rebase Guide",
        typ="guide",
        content="# Git Rebase\n\nSchritt 1...",
    )
    assert "Guides" in str(path)


def test_write_result_cheat_sheet(writer, tmp_vault):
    path = writer.write_result(
        title="Docker Commands",
        typ="cheat-sheet",
        content="# Docker Cheat Sheet",
    )
    assert "Cheat-Sheets" in str(path)


def test_write_result_code(writer, tmp_vault):
    path = writer.write_result(
        title="Backup Script",
        typ="code",
        content="# Backup Script\n\n```bash\nrsync...\n```",
    )
    assert "Code" in str(path)


def test_update_task_note_status(writer, tmp_vault):
    path = writer.create_task_note(title="Status Test", typ="code", agent="coder")
    writer.update_task_status(path, "in_progress")
    content = path.read_text()
    assert "status: in_progress" in content


def test_result_type_mapping(writer):
    assert writer.map_result_type("recherche") == "Recherchen"
    assert writer.map_result_type("guide") == "Guides"
    assert writer.map_result_type("cheat-sheet") == "Cheat-Sheets"
    assert writer.map_result_type("code") == "Code"
    assert writer.map_result_type("report") == "Reports"
