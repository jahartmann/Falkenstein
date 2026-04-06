# backend/prompts/subagent.py
"""SubAgent-Prompts mit expliziten Output-Templates."""
from __future__ import annotations

_OUTPUT_TEMPLATES: dict[str, str] = {
    "recherche": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Zusammenfassung\n"
        "(2-3 Sätze: Was ist das Kernresultat?)\n\n"
        "## Kernpunkte\n"
        "(5-10 Bullet-Points mit den wichtigsten Erkenntnissen)\n\n"
        "## Details\n"
        "(Ausführliche Erläuterung der wichtigsten Aspekte)\n\n"
        "## Quellen\n"
        "(URLs oder Quellen wenn vorhanden)"
    ),
    "guide": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Überblick\n"
        "(Was wird erreicht, für wen ist der Guide?)\n\n"
        "## Voraussetzungen\n"
        "(Was muss vorher installiert/bekannt sein?)\n\n"
        "## Schritt-für-Schritt\n"
        "(Nummerierte Schritte mit konkreten Befehlen/Code-Beispielen)\n\n"
        "## Tipps & Fallstricke\n"
        "(Häufige Fehler und wie man sie vermeidet)"
    ),
    "cheat-sheet": (
        "## Format deiner Antwort\n"
        "Erstelle ein kompaktes Cheat-Sheet:\n\n"
        "## Wichtigste Befehle/Konzepte\n"
        "(Tabellarisch oder als Code-Blöcke, sehr kompakt)\n\n"
        "## Häufige Patterns\n"
        "(Kurze Beispiele)"
    ),
    "code": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Problem\n"
        "(Was wird gelöst?)\n\n"
        "## Lösung\n"
        "```\n(vollständiger Code)\n```\n\n"
        "## Erklärung\n"
        "(Wichtige Design-Entscheidungen erklären)"
    ),
    "report": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Executive Summary\n"
        "(3-5 Sätze: Was wurde gefunden, was sind die wichtigsten Erkenntnisse?)\n\n"
        "## Details\n"
        "(Ausführliche Analyse)\n\n"
        "## Empfehlungen\n"
        "(Konkrete nächste Schritte)"
    ),
}

_DEFAULT_TEMPLATE = _OUTPUT_TEMPLATES["recherche"]

_BASE_REQUIREMENTS = """\
## Anforderungen
- Antworte EINMAL mit dem vollständigen, fertigen Ergebnis
- KEIN "Ich habe Punkt 1 erledigt..." — nur das Endergebnis
- KEINE Statusmeldungen während der Arbeit — nur das finale Dokument
- Sprache: Deutsch (Ausnahme: Code-Kommentare auf Englisch)
- Wenn du ein Tool nutzt und es scheitert: kurz erwähnen und weitermachen
"""


def build_subagent_prompt(
    agent_type: str,
    task: str,
    result_type: str = "recherche",
) -> str:
    """Build a SubAgent system prompt with the appropriate output template."""
    template = _OUTPUT_TEMPLATES.get(result_type, _DEFAULT_TEMPLATE)
    return (
        f"Du bist ein {agent_type}-SubAgent im Falkenstein-System.\n\n"
        f"## Deine Aufgabe\n{task}\n\n"
        f"{template}\n\n"
        f"{_BASE_REQUIREMENTS}"
    )
