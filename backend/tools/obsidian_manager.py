import datetime
from pathlib import Path
from backend.tools.base import Tool, ToolResult


# Parent folder inside the vault for all Falkenstein content
VAULT_PREFIX = "KI-Büro"

# Vault structure that gets created on first use
VAULT_STRUCTURE = {
    VAULT_PREFIX: {
        "Falkenstein": {
            "Projekte": {},
            "Tasks": {},
            "Daily Reports": {},
            "Notizen": {},
            "Ergebnisse": {
                "Recherchen": {},
                "Guides": {},
                "Cheat-Sheets": {},
                "Reports": {},
                "Code": {},
            },
        },
        "Management": {
            "Inbox.md": "# Inbox\n\nHier landen neue Aufgaben und Ideen.\n",
            "Kanban.md": (
                "# Kanban Board\n\n"
                "## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
            ),
            "Schedules": {},
        },
    },
}


class ObsidianManagerTool(Tool):
    name = "obsidian_manager"
    mutating = True
    description = (
        "Obsidian Vault verwalten: Notizen lesen/schreiben, Projekte anlegen, "
        "Daily Reports, Inbox, Todos, Kanban. "
        "Actions: read, write, append, list, daily_report, inbox, todo, init_vault, project."
    )

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self._ensure_vault_structure()

    def _ensure_vault_structure(self):
        """Create vault folder structure if it doesn't exist."""
        self.vault.mkdir(parents=True, exist_ok=True)
        self._create_structure(self.vault, VAULT_STRUCTURE)

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
            "inbox": lambda: self._inbox(params.get("content", "")),
            "todo": lambda: self._todo(params.get("content", ""), params.get("project")),
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
        report_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Daily Reports"
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

    async def _inbox(self, content: str) -> ToolResult:
        if not content:
            return ToolResult(success=False, output="Parameter 'content' fehlt.")
        inbox_path = self.vault / VAULT_PREFIX / "Management" / "Inbox.md"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n- [ ] [{timestamp}] {content}"
        try:
            if not inbox_path.exists():
                inbox_path.write_text(f"# Inbox\n{entry}", encoding="utf-8")
            else:
                with open(inbox_path, "a", encoding="utf-8") as f:
                    f.write(entry)
            return ToolResult(success=True, output="Inbox-Eintrag hinzugefügt.")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _todo(self, content: str, project: str | None = None) -> ToolResult:
        """Add a todo item to the project's task file or general Kanban."""
        if not content:
            return ToolResult(success=False, output="Parameter 'content' fehlt.")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        if project:
            # Project-specific todo
            todo_path = self.vault / VAULT_PREFIX / "Falkenstein" / "Projekte" / project / "Tasks.md"
            todo_path.parent.mkdir(parents=True, exist_ok=True)
            entry = f"\n- [ ] [{timestamp}] {content}"
            if not todo_path.exists():
                todo_path.write_text(f"# Tasks — {project}\n{entry}", encoding="utf-8")
            else:
                with open(todo_path, "a", encoding="utf-8") as f:
                    f.write(entry)
            return ToolResult(success=True, output=f"Todo hinzugefügt: {project}/Tasks.md")
        else:
            # General Kanban backlog
            kanban_path = self.vault / VAULT_PREFIX / "Management" / "Kanban.md"
            if kanban_path.exists():
                text = kanban_path.read_text(encoding="utf-8")
                # Add under Backlog section
                text = text.replace(
                    "## Backlog\n",
                    f"## Backlog\n\n- [ ] [{timestamp}] {content}\n",
                    1,
                )
                kanban_path.write_text(text, encoding="utf-8")
            else:
                kanban_path.parent.mkdir(parents=True, exist_ok=True)
                kanban_path.write_text(
                    f"# Kanban Board\n\n## Backlog\n\n- [ ] [{timestamp}] {content}\n\n## In Arbeit\n\n## Review\n\n## Fertig\n",
                    encoding="utf-8",
                )
            return ToolResult(success=True, output="Todo zum Kanban-Backlog hinzugefügt.")

    async def _create_project(self, name: str) -> ToolResult:
        """Create a new project folder with template files."""
        if not name:
            return ToolResult(success=False, output="Projektname fehlt.")
        project_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Projekte" / name
        if project_dir.exists():
            return ToolResult(success=True, output=f"Projekt '{name}' existiert bereits.")
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.date.today().isoformat()
            (project_dir / "README.md").write_text(
                f"# {name}\n\nErstellt: {today}\n\n## Beschreibung\n\n## Status\n\nIn Arbeit\n",
                encoding="utf-8",
            )
            (project_dir / "Tasks.md").write_text(
                f"# Tasks — {name}\n\n", encoding="utf-8",
            )
            (project_dir / "Notizen.md").write_text(
                f"# Notizen — {name}\n\n", encoding="utf-8",
            )
            return ToolResult(success=True, output=f"Projekt '{name}' angelegt mit README, Tasks, Notizen.")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _init_vault(self) -> ToolResult:
        """Re-initialize vault structure."""
        self._ensure_vault_structure()
        return ToolResult(success=True, output="Vault-Struktur initialisiert.")

    async def write_task_result(self, task_title: str, result: str,
                                project: str | None, agent_name: str) -> ToolResult:
        """Write a completed task result to the appropriate location."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        if project:
            path_str = f"{VAULT_PREFIX}/Falkenstein/Projekte/{project}/Tasks.md"
            content = f"\n\n### {task_title} ✅\n*{agent_name}* — {timestamp}\n\n{result}"
            return await self._append(path_str, content)
        else:
            content = f"[DONE] {task_title} ({agent_name}): {result[:300]}"
            return await self._inbox(content)

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
                    "enum": ["read", "write", "append", "list", "daily_report", "inbox", "todo", "project", "init_vault"],
                    "description": "Aktion im Obsidian Vault",
                },
                "path": {
                    "type": "string",
                    "description": "Relativer Pfad im Vault",
                },
                "content": {
                    "type": "string",
                    "description": "Inhalt / Projektname / Todo-Text",
                },
                "project": {
                    "type": "string",
                    "description": "Projektname (für todo)",
                },
            },
            "required": ["action"],
        }
