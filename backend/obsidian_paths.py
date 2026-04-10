from __future__ import annotations

from pathlib import Path

DEFAULT_FALKENSTEIN_ROOT = "KI-Büro"
LEGACY_FALKENSTEIN_ROOT = "KI-Buero"
KNOWN_FALKENSTEIN_ROOTS = (
    DEFAULT_FALKENSTEIN_ROOT,
    LEGACY_FALKENSTEIN_ROOT,
)


def resolve_falkenstein_root(vault_path: str | Path) -> Path:
    """Return the preferred Falkenstein folder inside an Obsidian vault.

    If an existing folder is already present, reuse it so older installations
    keep working. Otherwise default to the canonical modern name.
    """
    vault = Path(vault_path).expanduser().resolve()
    for name in KNOWN_FALKENSTEIN_ROOTS:
        candidate = vault / name
        if candidate.exists():
            return candidate
    return vault / DEFAULT_FALKENSTEIN_ROOT


def resolve_falkenstein_root_name(vault_path: str | Path) -> str:
    return resolve_falkenstein_root(vault_path).name
