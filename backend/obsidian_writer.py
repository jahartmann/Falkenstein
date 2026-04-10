from __future__ import annotations

# backend/obsidian_writer.py
"""Writes knowledge artifacts to Obsidian vault."""

import datetime
import re
from pathlib import Path
from backend.obsidian_paths import resolve_falkenstein_root

VAULT_PREFIX = "KI-Büro"


class ObsidianWriter:
    """Writes results and reports to the Obsidian knowledge base."""

    _TEMPLATES = {
        "recherche": (
            "---\n"
            "typ: recherche\n"
            "tags: [ki-recherche, {tag}]\n"
            "erstellt: {date}\n"
            "titel: \"{title}\"\n"
            "---\n\n"
            "# {title}\n\n"
            "{content}\n\n"
            "---\n"
            "*Automatisch erstellt von Falkenstein am {date}*\n"
        ),
        "guide": (
            "---\n"
            "typ: guide\n"
            "tags: [ki-guide, {tag}]\n"
            "erstellt: {date}\n"
            "titel: \"{title}\"\n"
            "---\n\n"
            "# {title}\n\n"
            "{content}\n\n"
            "---\n"
            "*Automatisch erstellt von Falkenstein am {date}*\n"
        ),
        "report": (
            "---\n"
            "typ: report\n"
            "tags: [ki-report, {tag}]\n"
            "erstellt: {date}\n"
            "titel: \"{title}\"\n"
            "---\n\n"
            "# {title}\n\n"
            "{content}\n\n"
            "---\n"
            "*Automatisch erstellt von Falkenstein am {date}*\n"
        ),
        "code": (
            "---\n"
            "typ: code\n"
            "tags: [ki-code, {tag}]\n"
            "erstellt: {date}\n"
            "titel: \"{title}\"\n"
            "---\n\n"
            "# {title}\n\n"
            "{content}\n"
        ),
    }

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.base_dir = resolve_falkenstein_root(self.vault)
        self.wissen_dir = self.base_dir / "Wissen"
        self.projekte_dir = self.base_dir / "Projekte"
        self.reports_dir = self.base_dir / "Reports"

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
        """Write a knowledge artifact with structured template."""
        today = datetime.date.today().isoformat()
        slug = self._slugify(title)
        filename = f"{today}-{slug}.md"

        if project:
            path = self.projekte_dir / project / filename
        else:
            path = self.wissen_dir / filename

        path.parent.mkdir(parents=True, exist_ok=True)

        tag = self._slugify(project or "allgemein")
        template = self._TEMPLATES.get(typ.lower(), self._TEMPLATES["recherche"])
        text = template.format(title=title, date=today, content=content, tag=tag)
        path.write_text(text, encoding="utf-8")
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
