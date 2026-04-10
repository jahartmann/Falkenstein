from __future__ import annotations

import datetime
from pathlib import Path
from backend.tools.base import Tool, ToolResult
from backend.obsidian_paths import resolve_falkenstein_root


# Falkenstein structure created on first use
VAULT_STRUCTURE = {
    "Wissen": {},
    "Projekte": {},
    "Reports": {},
}


class ObsidianManagerTool(Tool):
    name = "obsidian_manager"
    mutating = True
    description = (
        "Obsidian Wissensbasis verwalten: Notizen lesen/schreiben, Projekte anlegen, "
        "Daily Reports, Ordner erstellen. "
        "Actions: read, write, append, list, daily_report, project, init_vault."
    )

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.base_dir = resolve_falkenstein_root(self.vault)
        self._ensure_vault_structure()

    def _ensure_vault_structure(self):
        """Create vault folder structure if it doesn't exist."""
        self.vault.mkdir(parents=True, exist_ok=True)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._create_structure(self.base_dir, VAULT_STRUCTURE)

    def _create_structure(self, base: Path, structure: dict):
        for name, content in structure.items():
            path = base / name
            if isinstance(content, dict):
                path.mkdir(parents=True, exist_ok=True)
                self._create_structure(path, content)
            elif isinstance(content, str):
                if not path.exists():
                    path.write_text(content, encoding="utf-8")

    def _resolve_safe(self, path_str: str) -> Path | None:
        target = (self.vault / path_str).resolve()
        if not str(target).startswith(str(self.vault)):
            return None
        return target

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "")
        path_str = params.get("path", "")

        actions = {
            "read": lambda: self._read(path_str),
            "write": lambda: self._write(path_str, params.get("content", "")),
            "append": lambda: self._append(path_str, params.get("content", "")),
            "list": lambda: self._list(path_str or "."),
            "daily_report": lambda: self._daily_report(params.get("content", "")),
            "project": lambda: self._create_project(params.get("content", "")),
            "init_vault": lambda: self._init_vault(),
        }
        handler = actions.get(action)
        if not handler:
            return ToolResult(success=False, output=f"Unbekannte Action: {action}. Verfügbar: {', '.join(actions.keys())}")
        return await handler()

    async def _read(self, path_str: str) -> ToolResult:
        if not path_str:
            return ToolResult(success=False, output="Parameter 'path' fehlt.")
        target = self._resolve_safe(path_str)
        if target is None:
            return ToolResult(success=False, output="Pfad außerhalb des Vaults.")
        if not target.exists():
            return ToolResult(success=False, output=f"Nicht gefunden: {path_str}")
        try:
            return ToolResult(success=True, output=target.read_text(encoding="utf-8")[:10000])
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _write(self, path_str: str, content: str) -> ToolResult:
        if not path_str:
            return ToolResult(success=False, output="Parameter 'path' fehlt.")
        target = self._resolve_safe(path_str)
        if target is None:
            return ToolResult(success=False, output="Pfad außerhalb des Vaults.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Geschrieben: {path_str}")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _append(self, path_str: str, content: str) -> ToolResult:
        if not path_str:
            return ToolResult(success=False, output="Parameter 'path' fehlt.")
        target = self._resolve_safe(path_str)
        if target is None:
            return ToolResult(success=False, output="Pfad außerhalb des Vaults.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write("\n" + content)
            return ToolResult(success=True, output=f"Angehängt an: {path_str}")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _list(self, path_str: str) -> ToolResult:
        target = self._resolve_safe(path_str)
        if target is None:
            return ToolResult(success=False, output="Pfad außerhalb des Vaults.")
        if not target.exists():
            return ToolResult(success=False, output=f"Nicht gefunden: {path_str}")
        try:
            entries = sorted(
                f"{'📁' if p.is_dir() else '📄'} {p.name}"
                for p in target.iterdir()
                if not p.name.startswith(".")
            )
            return ToolResult(success=True, output="\n".join(entries) or "(leer)")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _daily_report(self, content: str) -> ToolResult:
        if not content:
            return ToolResult(success=False, output="Parameter 'content' fehlt.")
        today = datetime.date.today().isoformat()
        report_dir = self.base_dir / "Reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{today}.md"
        header = f"# Daily Report — {today}\n\n"
        try:
            if report_path.exists():
                with open(report_path, "a", encoding="utf-8") as f:
                    f.write("\n---\n\n" + content)
            else:
                report_path.write_text(header + content, encoding="utf-8")
            return ToolResult(success=True, output=f"Daily Report: {report_path.name}")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _create_project(self, name: str) -> ToolResult:
        """Create a new project folder with README."""
        if not name:
            return ToolResult(success=False, output="Projektname fehlt.")
        project_dir = self.base_dir / "Projekte" / name
        if project_dir.exists():
            return ToolResult(success=True, output=f"Projekt '{name}' existiert bereits.")
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.date.today().isoformat()
            (project_dir / "README.md").write_text(
                f"# {name}\n\nErstellt: {today}\n\n## Beschreibung\n\n## Status\n\nIn Arbeit\n",
                encoding="utf-8",
            )
            return ToolResult(success=True, output=f"Projekt '{name}' angelegt.")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _init_vault(self) -> ToolResult:
        """Re-initialize vault structure."""
        self._ensure_vault_structure()
        return ToolResult(success=True, output="Vault-Struktur initialisiert.")

    async def write_task_result(self, task_title: str, result: str,
                                project: str | None, agent_name: str) -> ToolResult:
        """Write a completed task result to the appropriate location."""
        today = datetime.date.today().isoformat()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        slug = task_title.lower().replace(" ", "-")[:40]
        root_name = self.base_dir.name

        if project:
            path_str = f"{root_name}/Projekte/{project}/{today}-{slug}.md"
        else:
            path_str = f"{root_name}/Wissen/{today}-{slug}.md"

        content = f"# {task_title}\n\n*{agent_name}* — {timestamp}\n\n{result}"
        return await self._write(path_str, content)

    async def log_escalation(self, agent_name: str, task_title: str,
                              details: str) -> ToolResult:
        """Log escalation details to the daily report."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"## Eskalation: {task_title}\n*{agent_name}* — {timestamp}\n\n{details}"
        return await self._daily_report(content)

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "append", "list", "daily_report", "project", "init_vault"],
                    "description": "Aktion im Obsidian Vault",
                },
                "path": {
                    "type": "string",
                    "description": "Relativer Pfad im Vault",
                },
                "content": {
                    "type": "string",
                    "description": "Inhalt / Projektname",
                },
                "project": {
                    "type": "string",
                    "description": "Projektname (für write_task_result)",
                },
            },
            "required": ["action"],
        }
