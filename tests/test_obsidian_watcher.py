import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from backend.obsidian_watcher import ObsidianWatcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    """Create minimal vault structure."""
    mgmt = tmp_path / "Management"
    mgmt.mkdir()
    (mgmt / "Inbox.md").write_text("# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n")

    proj = tmp_path / "Falkenstein" / "Projekte" / "website"
    proj.mkdir(parents=True)
    (proj / "Tasks.md").write_text("# Tasks — website\n\n- [ ] [2026-04-01 10:00] Old task\n")
    return tmp_path


@pytest.fixture
def router():
    r = AsyncMock()
    r.route_event = AsyncMock()
    return r


def make_watcher(vault, router) -> ObsidianWatcher:
    return ObsidianWatcher(vault_path=vault, router=router, debounce_seconds=0.1)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_detects_new_inbox_todo(vault, router):
    """Adding a new unchecked todo to Inbox.md is detected."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-02 09:00] Brand new todo\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert "Brand new todo" in changes[0]["content"]
    assert changes[0]["project"] is None


def test_ignores_checked_todos(vault, router):
    """Checked items (- [x]) must never appear in results."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [x] [2026-04-01 10:00] Done item\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"  # already known
    )

    changes = watcher.detect_changes()
    assert changes == []


def test_ignores_non_todo_lines(vault, router):
    """Headings, plain text, and empty lines are not reported."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "## Neue Sektion\n"
        "Just some text here\n"
        "- A bullet without checkbox\n"
    )

    changes = watcher.detect_changes()
    assert changes == []


def test_detects_project_todo(vault, router):
    """New todo added to a project Tasks.md has the correct project name."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    tasks = vault / "Falkenstein" / "Projekte" / "website" / "Tasks.md"
    tasks.write_text(
        "# Tasks — website\n\n"
        "- [ ] [2026-04-01 10:00] Old task\n"
        "- [ ] [2026-04-02 11:00] New website feature\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["project"] == "website"
    assert "New website feature" in changes[0]["content"]


def test_no_duplicate_detection(vault, router):
    """Once a todo is detected, a second call without changes returns nothing."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-02 08:00] Second pass todo\n"
    )

    first = watcher.detect_changes()
    assert len(first) == 1

    # No changes since last detect_changes — must return empty
    second = watcher.detect_changes()
    assert second == []


def test_new_project_tasks_file(vault, router):
    """A freshly created project Tasks.md with new todos is found on detect_changes."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    new_proj = vault / "Falkenstein" / "Projekte" / "newproj"
    new_proj.mkdir(parents=True)
    (new_proj / "Tasks.md").write_text(
        "# Tasks — newproj\n\n"
        "- [ ] [2026-04-02 12:00] First task for newproj\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["project"] == "newproj"
    assert "First task for newproj" in changes[0]["content"]


def test_multiple_new_todos_at_once(vault, router):
    """Adding 3 new todos at once returns all 3."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-02 09:00] Alpha\n"
        "- [ ] [2026-04-02 09:01] Beta\n"
        "- [ ] [2026-04-02 09:02] Gamma\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 3
    contents = {c["content"] for c in changes}
    assert any("Alpha" in c for c in contents)
    assert any("Beta" in c for c in contents)
    assert any("Gamma" in c for c in contents)


def test_scan_files_learns_existing(vault, router):
    """After scan_files, detect_changes on unchanged files returns nothing."""
    watcher = make_watcher(vault, router)
    watcher.scan_files()

    # Files are unchanged — nothing new
    changes = watcher.detect_changes()
    assert changes == []


def test_watched_files_property(vault, router):
    """watched_files returns Inbox.md and the project Tasks.md."""
    watcher = make_watcher(vault, router)
    files = [str(f) for f in watcher.watched_files]

    assert any("Inbox.md" in f for f in files)
    assert any("website" in f and "Tasks.md" in f for f in files)


def test_project_extraction_from_path(vault, router):
    """Project name is extracted from Projekte/{name}/Tasks.md path structure."""
    watcher = make_watcher(vault, router)

    tasks_path = vault / "Falkenstein" / "Projekte" / "myproject" / "Tasks.md"
    from backend.obsidian_watcher import _extract_project
    assert _extract_project(tasks_path) == "myproject"

    inbox_path = vault / "Management" / "Inbox.md"
    assert _extract_project(inbox_path) is None


def test_empty_vault_no_crash(tmp_path, router):
    """An empty vault path does not raise on scan_files or detect_changes."""
    # tmp_path is empty — no Management or Projekte dirs
    watcher = ObsidianWatcher(vault_path=tmp_path, router=router)

    # Must not raise
    watcher.scan_files()
    changes = watcher.detect_changes()
    assert changes == []
