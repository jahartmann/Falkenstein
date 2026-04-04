import asyncio

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
    mgmt = tmp_path / "KI-Büro" / "Management"
    mgmt.mkdir(parents=True)
    (mgmt / "Inbox.md").write_text("# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n")

    proj = tmp_path / "KI-Büro" / "Falkenstein" / "Projekte" / "website"
    proj.mkdir(parents=True)
    (proj / "Tasks.md").write_text("# Tasks — website\n\n- [ ] [2026-04-01 10:00] Old task\n")
    return tmp_path


@pytest.fixture
def callback():
    return AsyncMock()


def make_watcher(vault, callback=None) -> ObsidianWatcher:
    return ObsidianWatcher(vault_path=vault, on_new_todo=callback, debounce_seconds=0.1)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_detects_new_inbox_todo(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-02 09:00] Brand new todo\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert "Brand new todo" in changes[0]["content"]
    assert changes[0]["project"] is None


def test_ignores_checked_todos(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [x] [2026-04-01 10:00] Done item\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
    )

    changes = watcher.detect_changes()
    assert changes == []


def test_ignores_non_todo_lines(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "## Neue Sektion\n"
        "Just some text here\n"
        "- A bullet without checkbox\n"
    )

    changes = watcher.detect_changes()
    assert changes == []


def test_detects_project_todo(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    tasks = vault / "KI-Büro" / "Falkenstein" / "Projekte" / "website" / "Tasks.md"
    tasks.write_text(
        "# Tasks — website\n\n"
        "- [ ] [2026-04-01 10:00] Old task\n"
        "- [ ] [2026-04-02 11:00] New website feature\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["project"] == "website"
    assert "New website feature" in changes[0]["content"]


def test_no_duplicate_detection(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-02 08:00] Second pass todo\n"
    )

    first = watcher.detect_changes()
    assert len(first) == 1

    second = watcher.detect_changes()
    assert second == []


def test_new_project_tasks_file(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    new_proj = vault / "KI-Büro" / "Falkenstein" / "Projekte" / "newproj"
    new_proj.mkdir(parents=True)
    (new_proj / "Tasks.md").write_text(
        "# Tasks — newproj\n\n"
        "- [ ] [2026-04-02 12:00] First task for newproj\n"
    )

    changes = watcher.detect_changes()
    assert len(changes) == 1
    assert changes[0]["project"] == "newproj"
    assert "First task for newproj" in changes[0]["content"]


def test_multiple_new_todos_at_once(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Management" / "Inbox.md"
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


def test_scan_files_learns_existing(vault, callback):
    watcher = make_watcher(vault, callback)
    watcher.scan_files()

    changes = watcher.detect_changes()
    assert changes == []


def test_watched_files_property(vault, callback):
    watcher = make_watcher(vault, callback)
    files = [str(f) for f in watcher.watched_files]

    assert any("Inbox.md" in f for f in files)
    assert any("website" in f and "Tasks.md" in f for f in files)


def test_project_extraction_from_path(vault, callback):
    watcher = make_watcher(vault, callback)

    tasks_path = vault / "KI-Büro" / "Falkenstein" / "Projekte" / "myproject" / "Tasks.md"
    from backend.obsidian_watcher import _extract_project
    assert _extract_project(tasks_path) == "myproject"

    inbox_path = vault / "KI-Büro" / "Management" / "Inbox.md"
    assert _extract_project(inbox_path) is None


def test_empty_vault_no_crash(tmp_path, callback):
    watcher = ObsidianWatcher(vault_path=tmp_path, on_new_todo=callback)

    watcher.scan_files()
    changes = watcher.detect_changes()
    assert changes == []


@pytest.mark.asyncio
async def test_debounce_calls_callback(vault, callback):
    """_reset_debounce triggers detect_changes and calls on_new_todo callback."""
    watcher = ObsidianWatcher(vault_path=vault, on_new_todo=callback, debounce_seconds=0.1)
    watcher._loop = asyncio.get_running_loop()
    watcher.scan_files()

    inbox = vault / "KI-Büro" / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n"
        "- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-03 15:00] Brand new todo\n"
    )

    watcher._reset_debounce()
    await asyncio.sleep(0.2)

    callback.assert_awaited()
    args = callback.call_args[0]
    assert "Brand new todo" in args[0]  # content
