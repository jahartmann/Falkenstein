import datetime
import re
from pathlib import Path

VAULT_PREFIX = "KI-Büro"

_RESULT_TYPE_MAP = {
    "recherche": "Recherchen",
    "guide": "Guides",
    "cheat-sheet": "Cheat-Sheets",
    "code": "Code",
    "report": "Reports",
}

_KANBAN_SECTIONS = ["## Backlog", "## In Progress", "## Done", "## Archiv"]


class ObsidianWriter:
    """Manages Kanban board, task notes, and result files in Obsidian vault."""

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.kanban_path = self.vault / VAULT_PREFIX / "Management" / "Kanban.md"
        self.tasks_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Tasks"
        self.results_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Ergebnisse"
        self.reports_dir = self.vault / VAULT_PREFIX / "Falkenstein" / "Daily Reports"

    def map_result_type(self, typ: str) -> str:
        return _RESULT_TYPE_MAP.get(typ, "Reports")

    def create_task_note(self, title: str, typ: str, agent: str) -> Path:
        today = datetime.date.today().isoformat()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug.strip())[:60]
        filename = f"{today}-{slug}.md"
        path = self.tasks_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = (
            f"---\n"
            f"typ: {typ}\n"
            f"status: backlog\n"
            f"agent: {agent}\n"
            f"erstellt: {today}\n"
            f"---\n\n"
            f"# {title}\n"
        )
        path.write_text(frontmatter, encoding="utf-8")
        return path

    def update_task_status(self, path: Path, status: str):
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8")
        content = re.sub(r"status: \w+", f"status: {status}", content, count=1)
        path.write_text(content, encoding="utf-8")

    def kanban_move(self, title: str, target_section: str):
        section_map = {
            "backlog": "## Backlog",
            "in_progress": "## In Progress",
            "done": "## Done",
            "archiv": "## Archiv",
        }
        target_header = section_map.get(target_section, "## Backlog")
        if not self.kanban_path.exists():
            return
        text = self.kanban_path.read_text(encoding="utf-8")

        today = datetime.date.today().isoformat()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug.strip())[:60]
        note_name = f"{today}-{slug}"

        checkbox = "[x]" if target_section == "done" else "[ ]"
        entry = f"- {checkbox} [[Tasks/{note_name}|{title}]]"

        # Remove existing entry for this task (match by wikilink, not substring)
        entry_marker = f"[[Tasks/{note_name}|"
        lines = text.split("\n")
        lines = [l for l in lines if entry_marker not in l]
        text = "\n".join(lines)

        # Insert under target section (create section if missing)
        idx = text.find(target_header)
        if idx == -1:
            text += f"\n{target_header}\n{entry}\n"
        else:
            insert_pos = idx + len(target_header)
            text = text[:insert_pos] + f"\n{entry}" + text[insert_pos:]

        self.kanban_path.write_text(text, encoding="utf-8")

    def remove_from_inbox(self, text: str):
        """Remove or check off a matching todo from Inbox.md."""
        inbox_path = self.kanban_path.parent / "Inbox.md"
        if not inbox_path.exists():
            return
        content = inbox_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        for line in lines:
            # Match unchecked todos that contain the text
            if line.strip().startswith("- [ ]") and text.strip() in line:
                continue  # Remove the line
            new_lines.append(line)
        inbox_path.write_text("\n".join(new_lines), encoding="utf-8")

    def write_result(self, title: str, typ: str, content: str) -> Path:
        subdir = self.map_result_type(typ)
        today = datetime.date.today().isoformat()
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        slug = re.sub(r"\s+", "-", slug.strip())[:60]
        filename = f"{today}-{slug}.md"
        path = self.results_dir / subdir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
