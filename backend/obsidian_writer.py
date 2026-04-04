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

        # Remove existing entry for this task (if moving)
        lines = text.split("\n")
        lines = [l for l in lines if title not in l or l.startswith("## ")]
        text = "\n".join(lines)

        # Insert under target section
        idx = text.index(target_header)
        insert_pos = idx + len(target_header)
        text = text[:insert_pos] + f"\n{entry}" + text[insert_pos:]

        self.kanban_path.write_text(text, encoding="utf-8")

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
