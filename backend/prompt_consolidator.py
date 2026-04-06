"""Konsolidiert nummerierte/aufgezählte Prompts zu einem einzigen kohärenten Prompt.

Beispiel:
    "1. Recherchiere KI-Trends\n2. Erstelle Guide\n3. Speichere in Obsidian"
    ->  "Recherchiere aktuelle KI-Trends 2026 und dann erstelle daraus einen
        strukturierten guide. anschließend lege in obsidian ab."
"""
from __future__ import annotations
import re


# Mindestanzahl Punkte für Konsolidierung
_MIN_POINTS = 2

_NUMBERED_RE = re.compile(r"^\s*(\d+[\.\):]|\-|\•|\*)\s+(.+)", re.MULTILINE)


def has_numbered_points(text: str) -> bool:
    """Return True if text contains 2+ numbered/bulleted points."""
    matches = _NUMBERED_RE.findall(text)
    return len(matches) >= _MIN_POINTS


class PromptConsolidator:
    """Turns multi-point prompts into a single consolidated task prompt."""

    def extract_points(self, text: str) -> list[str]:
        """Extract individual points from a numbered/bulleted list."""
        matches = _NUMBERED_RE.findall(text)
        return [m[1].strip() for m in matches]

    def build_consolidated_prompt(self, points: list[str]) -> str:
        """Merge points into one fluid prompt.

        Simple approach: join with connective words.
        The LLM will interpret this as one coherent task.
        """
        if not points:
            return ""
        if len(points) == 1:
            return points[0]

        # Join points into a single flowing instruction.
        # Only single-line points are supported — multi-line sub-items are not extracted.
        # connectors[0] applies to the 2nd point (i=1), connectors[1] to the 3rd, etc.
        connectors = [" und dann ", " anschließend ", " zuletzt ", " außerdem "]
        parts = []
        for i, point in enumerate(points):
            if i == 0:
                parts.append(point)
            elif i - 1 < len(connectors):
                parts.append(connectors[i - 1] + point)
            else:
                parts.append(" sowie " + point)

        return "".join(parts) + "."

    def consolidate(self, text: str) -> tuple[str, bool]:
        """Consolidate a message if it contains multiple points.

        Returns:
            (consolidated_text, was_consolidated)
        """
        if not has_numbered_points(text):
            return text, False
        points = self.extract_points(text)
        if len(points) < _MIN_POINTS:
            return text, False
        consolidated = self.build_consolidated_prompt(points)
        return consolidated, True
