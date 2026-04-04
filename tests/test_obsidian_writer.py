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
    kanban = ki / "Kanban.md"
    kanban.write_text(
        "# Kanban Board\n\n## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
    )
    (ki / "Falkenstein" / "Tasks").mkdir(parents=True)
    (ki / "Ergebnisse").mkdir(parents=True)
    (ki / "Falkenstein" / "Daily Reports").mkdir(parents=True)
    (ki / "Inbox.md").write_text("# Inbox\n\n")
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
    kanban = (tmp_vault / "KI-Büro" / "Kanban.md").read_text()
    assert "Test Task" in kanban
    backlog_pos = kanban.index("## Backlog")
    in_progress_pos = kanban.index("## In Progress")
    task_pos = kanban.index("Test Task")
    assert backlog_pos < task_pos < in_progress_pos


def test_kanban_move_to_in_progress(writer, tmp_vault):
    writer.create_task_note(title="Moving Task", typ="code", agent="coder")
    writer.kanban_move("Moving Task", "backlog")
    writer.kanban_move("Moving Task", "in_progress")
    kanban = (tmp_vault / "KI-Büro" / "Kanban.md").read_text()
    in_progress_pos = kanban.index("## In Progress")
    done_pos = kanban.index("## Done")
    task_pos = kanban.index("Moving Task")
    assert in_progress_pos < task_pos < done_pos


def test_kanban_move_to_done(writer, tmp_vault):
    writer.create_task_note(title="Done Task", typ="recherche", agent="researcher")
    writer.kanban_move("Done Task", "backlog")
    writer.kanban_move("Done Task", "done")
    kanban = (tmp_vault / "KI-Büro" / "Kanban.md").read_text()
    assert "- [x]" in kanban


def test_write_result_recherche(writer, tmp_vault):
    path = writer.write_result(
        title="Docker vs Podman",
        typ="recherche",
        content="# Docker vs Podman\n\nDocker ist...",
    )
    assert "Ergebnisse" in str(path)
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "Docker ist" in content


def test_write_result_guide(writer, tmp_vault):
    path = writer.write_result(
        title="Git Rebase Guide",
        typ="guide",
        content="# Git Rebase\n\nSchritt 1...",
    )
    assert "Ergebnisse" in str(path)
    content = path.read_text()
    assert "typ: guide" in content


def test_write_result_with_project(writer, tmp_vault):
    proj = tmp_vault / "KI-Büro" / "Projekte" / "website"
    proj.mkdir(parents=True)
    path = writer.write_result(
        title="SEO Analyse",
        typ="recherche",
        content="# SEO\n\nErgebnis...",
        project="website",
    )
    assert "Projekte/website/Ergebnisse" in str(path)
    assert path.exists()
    content = path.read_text()
    assert "typ: recherche" in content
    assert "Ergebnis..." in content


def test_write_result_without_project(writer, tmp_vault):
    path = writer.write_result(
        title="Allgemeine Recherche",
        typ="report",
        content="# Report\n\nInhalt...",
    )
    assert "KI-Büro/Ergebnisse" in str(path)
    assert "Projekte" not in str(path)
    assert path.exists()


def test_update_task_note_status(writer, tmp_vault):
    path = writer.create_task_note(title="Status Test", typ="code", agent="coder")
    writer.update_task_status(path, "in_progress")
    content = path.read_text()
    assert "status: in_progress" in content


def test_remove_from_inbox(writer, tmp_vault):
    inbox = tmp_vault / "KI-Büro" / "Inbox.md"
    inbox.write_text("# Inbox\n\n- [ ] Deploy website\n- [ ] Fix bug\n")
    writer.remove_from_inbox("Deploy website")
    content = inbox.read_text()
    assert "Deploy website" not in content
    assert "Fix bug" in content
