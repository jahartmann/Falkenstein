from __future__ import annotations

from pathlib import Path
from backend.tools.base import Tool, ToolResult


class FileManagerTool(Tool):
    name = "file_manager"
    mutating = True  # writes/deletes files
    description = (
        "Dateien im Workspace lesen, schreiben, auflisten und löschen. "
        "Actions: read, write, list, delete. "
        "Pfade sind relativ zum Workspace-Verzeichnis."
    )

    def __init__(self, workspace_path: Path):
        self.workspace = workspace_path.resolve()

    def _resolve_safe(self, path_str: str) -> Path | None:
        target = (self.workspace / path_str).resolve()
        if not str(target).startswith(str(self.workspace)):
            return None
        return target

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "")
        path_str = params.get("path", ".")
        target = self._resolve_safe(path_str)
        if target is None:
            return ToolResult(success=False, output="Pfad außerhalb des Workspace nicht erlaubt.")

        if action == "read":
            return await self._read(target)
        elif action == "write":
            content = params.get("content", "")
            return await self._write(target, content)
        elif action == "list":
            return await self._list(target)
        elif action == "delete":
            return await self._delete(target)
        else:
            return ToolResult(success=False, output=f"Unbekannte Action: {action}")

    async def _read(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output=f"Datei nicht gefunden: {path.name}")
        try:
            content = path.read_text(encoding="utf-8")
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _write(self, path: Path, content: str) -> ToolResult:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Geschrieben: {path.name}")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _list(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output=f"Verzeichnis nicht gefunden: {path.name}")
        try:
            entries = sorted(p.name for p in path.iterdir())
            return ToolResult(success=True, output="\n".join(entries))
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _delete(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output=f"Datei nicht gefunden: {path.name}")
        try:
            path.unlink()
            return ToolResult(success=True, output=f"Gelöscht: {path.name}")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "list", "delete"],
                    "description": "Die auszuführende Aktion",
                },
                "path": {
                    "type": "string",
                    "description": "Relativer Pfad im Workspace",
                },
                "content": {
                    "type": "string",
                    "description": "Inhalt zum Schreiben (nur bei action=write)",
                },
            },
            "required": ["action", "path"],
        }
