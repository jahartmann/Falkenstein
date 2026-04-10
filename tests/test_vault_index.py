"""Tests for VaultIndex."""
from __future__ import annotations

import pytest
from pathlib import Path

from backend.vault_index import VaultIndex, CREW_TO_FOLDER, KNOWLEDGE_FOLDERS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_vault(tmp_path: Path) -> Path:
    """Create a minimal mock Obsidian vault under tmp_path."""
    # KI-Buero structure
    ki_buero = tmp_path / "KI-Buero"
    for sub in ("Recherchen", "Guides", "Code", "Reports", "Ideen", "Daily"):
        (ki_buero / sub).mkdir(parents=True)

    (ki_buero / "Projekte" / "Falkenstein").mkdir(parents=True)

    # Top-level file inside KI-Buero
    (ki_buero / "Kanban.md").write_text("# Kanban")

    # Notes in Recherchen
    (ki_buero / "Recherchen" / "crewai-overview.md").write_text("# CrewAI Overview")
    (ki_buero / "Recherchen" / "ollama-tools.md").write_text("# Ollama Tools")

    # Agenten-Wissensbasis structure
    wissens = tmp_path / "Agenten-Wissensbasis"
    for sub in ("Kontext", "Gelerntes", "Referenzen", "Fehler-Log"):
        (wissens / sub).mkdir(parents=True)

    (wissens / "Kontext" / "user-profil.md").write_text("# User Profil")

    # Hidden dirs that should be skipped
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".git").mkdir()

    return tmp_path


@pytest.fixture()
def index(mock_vault: Path) -> VaultIndex:
    vi = VaultIndex(mock_vault)
    vi.scan()
    return vi


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scan_finds_all_folders(index: VaultIndex) -> None:
    folders = index.list_folders()
    expected = [
        "KI-Buero",
        "KI-Buero/Code",
        "KI-Buero/Daily",
        "KI-Buero/Guides",
        "KI-Buero/Ideen",
        "KI-Buero/Projekte",
        "KI-Buero/Projekte/Falkenstein",
        "KI-Buero/Recherchen",
        "KI-Buero/Reports",
        "Agenten-Wissensbasis",
        "Agenten-Wissensbasis/Fehler-Log",
        "Agenten-Wissensbasis/Gelerntes",
        "Agenten-Wissensbasis/Kontext",
        "Agenten-Wissensbasis/Referenzen",
    ]
    for exp in expected:
        assert exp in folders, f"Expected folder '{exp}' not found in {folders}"

    # Hidden dirs must not appear
    assert not any(".obsidian" in f or ".git" in f for f in folders)


def test_scan_finds_existing_notes(index: VaultIndex) -> None:
    notes = index.list_notes("KI-Buero/Recherchen")
    assert "crewai-overview.md" in notes
    assert "ollama-tools.md" in notes

    kontext_notes = index.list_notes("Agenten-Wissensbasis/Kontext")
    assert "user-profil.md" in kontext_notes


def test_find_best_folder_researcher(index: VaultIndex) -> None:
    assert index.find_best_folder("researcher") == "KI-Buero/Recherchen"


def test_find_best_folder_coder(index: VaultIndex) -> None:
    assert index.find_best_folder("coder") == "KI-Buero/Code"


def test_find_best_folder_writer(index: VaultIndex) -> None:
    assert index.find_best_folder("writer") == "KI-Buero/Guides"


def test_find_best_folder_analyst(index: VaultIndex) -> None:
    assert index.find_best_folder("analyst") == "KI-Buero/Reports"


def test_find_related_note_found(index: VaultIndex) -> None:
    result = index.find_related_note("crewai")
    assert result is not None
    assert "crewai-overview.md" in result


def test_find_related_note_not_found(index: VaultIndex) -> None:
    result = index.find_related_note("quantum")
    assert result is None


def test_as_context_contains_key_folders(index: VaultIndex) -> None:
    ctx = index.as_context()
    assert "KI-Buero" in ctx
    assert "Recherchen" in ctx
    assert "Agenten-Wissensbasis" in ctx
    assert "Kontext" in ctx


def test_get_knowledge_folder_maps_correctly(index: VaultIndex) -> None:
    assert index.get_knowledge_folder("kontext") == "Agenten-Wissensbasis/Kontext"
    assert index.get_knowledge_folder("gelerntes") == "Agenten-Wissensbasis/Gelerntes"
    assert index.get_knowledge_folder("referenz") == "Agenten-Wissensbasis/Referenzen"
    assert index.get_knowledge_folder("fehler") == "Agenten-Wissensbasis/Fehler-Log"


def test_full_path_resolves_correctly(index: VaultIndex, mock_vault: Path) -> None:
    p = index.full_path("KI-Buero/Recherchen/crewai-overview.md")
    assert p == mock_vault / "KI-Buero" / "Recherchen" / "crewai-overview.md"
    assert p.exists()


def test_find_best_folder_prefers_existing_canonical_root(tmp_path: Path) -> None:
    (tmp_path / "KI-Büro" / "Reports").mkdir(parents=True)
    vi = VaultIndex(tmp_path)
    vi.scan()
    assert vi.find_best_folder("analyst") == "KI-Büro/Reports"
