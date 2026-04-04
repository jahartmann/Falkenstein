from __future__ import annotations

"""
SelfConfigTool — Falki can read/edit its own configuration files.
Covers: .env, SOUL.md, CLAUDE.md, config files in the project directory.
"""

from pathlib import Path
from backend.tools.base import Tool, ToolResult


# Files Falki is allowed to read and write
ALLOWED_FILES = {
    ".env", "SOUL.md", "CLAUDE.md", "AGENTS.md",
    "requirements.txt", "start.sh",
}

# Files that are read-only (can read but not write)
READ_ONLY_FILES = {
    "CLAUDE.md",  # managed externally
}


class SelfConfigTool(Tool):
    name = "self_config"
    mutating = True
    description = (
        "Eigene Konfigurationsdateien lesen und bearbeiten. "
        "Dateien: .env, SOUL.md, AGENTS.md, requirements.txt, start.sh. "
        "Actions: read, write, list, env_get, env_set."
    )

    def __init__(self, project_path: Path):
        self.project = project_path.resolve()

    def _resolve_safe(self, filename: str) -> tuple[Path | None, str | None]:
        """Resolve filename, return (path, error) tuple."""
        # Prevent path traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            return None, "Pfad-Traversal nicht erlaubt. Nur Dateinamen angeben."
        if filename not in ALLOWED_FILES:
            return None, f"Datei '{filename}' nicht erlaubt. Erlaubt: {', '.join(sorted(ALLOWED_FILES))}"
        return self.project / filename, None

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "").strip().lower()

        if action == "list":
            return self._list_configs()
        elif action == "read":
            return self._read(params.get("file", ""))
        elif action == "write":
            return self._write(params.get("file", ""), params.get("content", ""))
        elif action == "env_get":
            return self._env_get(params.get("key", ""))
        elif action == "env_set":
            return self._env_set(params.get("key", ""), params.get("value", ""))
        else:
            return ToolResult(
                success=False,
                output=f"Unbekannte Action: {action}. Verfügbar: list, read, write, env_get, env_set"
            )

    def _list_configs(self) -> ToolResult:
        lines = []
        for fname in sorted(ALLOWED_FILES):
            fpath = self.project / fname
            exists = fpath.exists()
            ro = " (read-only)" if fname in READ_ONLY_FILES else ""
            status = "vorhanden" if exists else "nicht vorhanden"
            lines.append(f"• {fname} — {status}{ro}")
        return ToolResult(success=True, output="\n".join(lines))

    def _read(self, filename: str) -> ToolResult:
        if not filename:
            return ToolResult(success=False, output="Kein Dateiname angegeben.")
        path, err = self._resolve_safe(filename)
        if err:
            return ToolResult(success=False, output=err)
        if not path.exists():
            return ToolResult(success=False, output=f"{filename} existiert nicht.")
        try:
            content = path.read_text(encoding="utf-8")
            return ToolResult(success=True, output=content[:10000])
        except Exception as e:
            return ToolResult(success=False, output=f"Lesefehler: {e}")

    def _write(self, filename: str, content: str) -> ToolResult:
        if not filename:
            return ToolResult(success=False, output="Kein Dateiname angegeben.")
        if filename in READ_ONLY_FILES:
            return ToolResult(success=False, output=f"{filename} ist read-only.")
        if not content:
            return ToolResult(success=False, output="Kein Inhalt angegeben.")
        path, err = self._resolve_safe(filename)
        if err:
            return ToolResult(success=False, output=err)
        try:
            path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"{filename} geschrieben ({len(content)} Zeichen).")
        except Exception as e:
            return ToolResult(success=False, output=f"Schreibfehler: {e}")

    def _env_get(self, key: str) -> ToolResult:
        if not key:
            return ToolResult(success=False, output="Kein Key angegeben.")
        env_path = self.project / ".env"
        if not env_path.exists():
            return ToolResult(success=False, output=".env existiert nicht.")
        key_upper = key.upper()
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            if k.strip().upper() == key_upper:
                # Mask sensitive values
                if any(s in k.upper() for s in ("TOKEN", "SECRET", "PASSWORD", "KEY")):
                    return ToolResult(success=True, output=f"{k.strip()}=*****(gesetzt)")
                return ToolResult(success=True, output=f"{k.strip()}={v.strip()}")
        return ToolResult(success=False, output=f"Key '{key}' nicht in .env gefunden.")

    def _env_set(self, key: str, value: str) -> ToolResult:
        if not key:
            return ToolResult(success=False, output="Kein Key angegeben.")
        env_path = self.project / ".env"
        key_upper = key.upper()

        lines = []
        found = False
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    k, _, _ = stripped.partition("=")
                    if k.strip().upper() == key_upper:
                        lines.append(f"{key_upper}={value}")
                        found = True
                        continue
                lines.append(line)

        if not found:
            lines.append(f"{key_upper}={value}")

        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return ToolResult(success=True, output=f"{key_upper}={value} gesetzt. Neustart nötig für Übernahme.")

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "read", "write", "env_get", "env_set"],
                    "description": "Aktion: list/read/write/env_get/env_set",
                },
                "file": {
                    "type": "string",
                    "description": "Dateiname (z.B. .env, SOUL.md)",
                },
                "content": {
                    "type": "string",
                    "description": "Inhalt zum Schreiben (nur bei action=write)",
                },
                "key": {
                    "type": "string",
                    "description": "ENV-Variable (nur bei env_get/env_set)",
                },
                "value": {
                    "type": "string",
                    "description": "Neuer Wert (nur bei env_set)",
                },
            },
            "required": ["action"],
        }
