# backend/obsidian_writer.py
"""Writes knowledge artifacts to Obsidian vault."""

import datetime
import re
from pathlib import Path

VAULT_PREFIX = "KI-Büro"


class ObsidianWriter:
    """Writes results and reports to the Obsidian knowledge base."""

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.wissen_dir = self.vault / VAULT_PREFIX / "Wissen"
        self.projekte_dir = self.vault / VAULT_PREFIX / "Projekte"
        self.reports_dir = self.vault / VAULT_PREFIX / "Reports"

    @staticmethod
    def _slugify(title: str) -> str:
        slug = re.sub(r"[^\w\s-]", "", title.lower())
        return re.sub(r"\s+", "-", slug.strip())[:60]

    def ensure_structure(self) -> None:
        """Create base vault directories if they don't exist."""
        self.wissen_dir.mkdir(parents=True, exist_ok=True)
        self.projekte_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def write_result(self, title: str, typ: str, content: str, project: str | None = None) -> Path:
        """Write a knowledge artifact to Wissen/ or Projekte/<project>/."""
        today = datetime.date.today().isoformat()
        slug = self._slugify(title)
        filename = f"{today}-{slug}.md"

        if project:
            path = self.projekte_dir / project / filename
        else:
            path = self.wissen_dir / filename

        path.parent.mkdir(parents=True, exist_ok=True)

        frontmatter = (
            f"---\n"
            f"typ: {typ}\n"
            f"erstellt: {today}\n"
            f"---\n\n"
        )
        path.write_text(frontmatter + content, encoding="utf-8")
        return path

    def write_report(self, content: str) -> Path:
        """Write or append to today's daily report."""
        today = datetime.date.today().isoformat()
        path = self.reports_dir / f"{today}.md"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        if path.exists():
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n---\n\n" + content)
        else:
            header = f"# Report — {today}\n\n"
            path.write_text(header + content, encoding="utf-8")
        return path
