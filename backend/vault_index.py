from __future__ import annotations

# backend/vault_index.py
"""Scans an Obsidian vault and provides smart file placement."""

import os
from pathlib import Path
from typing import Optional

CREW_TO_FOLDER = {
    "researcher": "KI-Buero/Recherchen",
    "writer": "KI-Buero/Guides",
    "coder": "KI-Buero/Code",
    "ki_expert": "KI-Buero/Recherchen",
    "analyst": "KI-Buero/Reports",
    "web_design": "KI-Buero/Code",
    "swift": "KI-Buero/Code",
    "ops": "KI-Buero/Reports",
    "premium": "KI-Buero/Recherchen",
}

KNOWLEDGE_FOLDERS = {
    "kontext": "Agenten-Wissensbasis/Kontext",
    "gelerntes": "Agenten-Wissensbasis/Gelerntes",
    "referenz": "Agenten-Wissensbasis/Referenzen",
    "fehler": "Agenten-Wissensbasis/Fehler-Log",
}

# Hidden dirs to skip during scan
_SKIP_DIRS = {".obsidian", ".git", ".trash", "__pycache__"}


class VaultIndex:
    """Indexes an Obsidian vault for smart file placement."""

    def __init__(self, vault_path: str | Path) -> None:
        self._vault = Path(vault_path)
        self._folders: list[str] = []
        # Maps relative note path → filename stem (lowercase, normalised)
        self._notes: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> None:
        """Walk the vault directory and build the folder/notes index."""
        folders: list[str] = []
        notes: dict[str, str] = {}

        for dirpath, dirnames, filenames in os.walk(self._vault):
            # Prune hidden dirs in-place so os.walk won't descend into them
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

            rel_dir = Path(dirpath).relative_to(self._vault)
            rel_str = str(rel_dir)

            if rel_str != ".":
                folders.append(rel_str)

            for fname in filenames:
                if fname.endswith(".md"):
                    rel_note = str(rel_dir / fname) if rel_str != "." else fname
                    # Normalised stem: lowercase, strip separators
                    stem = _normalise(fname[:-3])
                    notes[rel_note] = stem

        self._folders = sorted(folders)
        self._notes = notes

    def list_folders(self) -> list[str]:
        """Return sorted list of relative folder paths."""
        return list(self._folders)

    def list_notes(self, folder: str) -> list[str]:
        """Return .md filenames that live directly in *folder*."""
        results: list[str] = []
        for rel_path in self._notes:
            parent = str(Path(rel_path).parent)
            if parent == folder or (folder == "." and "/" not in rel_path):
                results.append(Path(rel_path).name)
        return sorted(results)

    def find_best_folder(self, crew_type: str, topic: str = "") -> str:  # noqa: ARG002
        """Return the designated output folder for *crew_type*."""
        return CREW_TO_FOLDER.get(crew_type, "KI-Buero/Recherchen")

    def find_related_note(self, topic: str) -> Optional[str]:
        """Find an existing note whose filename matches *topic*.

        Comparison is case-insensitive and ignores separators (-, _, space).
        Returns the relative path (including .md) or None.
        """
        needle = _normalise(topic)
        for rel_path, stem in self._notes.items():
            if needle in stem or stem in needle:
                return rel_path
        return None

    def get_knowledge_folder(self, category: str) -> str:
        """Return the knowledge-base folder for *category*."""
        return KNOWLEDGE_FOLDERS.get(category, "Agenten-Wissensbasis/Kontext")

    def as_context(self) -> str:
        """Return the vault structure as an indented text tree for agent prompts."""
        if not self._folders:
            return "(vault not scanned)"

        lines: list[str] = [f"Vault: {self._vault.name}"]

        # Build a simple depth-indented tree from the sorted folder list
        for folder in self._folders:
            depth = folder.count(os.sep)
            indent = "  " * depth
            name = Path(folder).name
            notes = self.list_notes(folder)
            lines.append(f"{indent}- {name}/")
            for note in notes:
                lines.append(f"{indent}  - {note}")

        return "\n".join(lines)

    def full_path(self, rel_path: str) -> Path:
        """Resolve a relative vault path to an absolute Path."""
        return self._vault / rel_path


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase and remove -, _, space separators."""
    return text.lower().replace("-", "").replace("_", "").replace(" ", "")
