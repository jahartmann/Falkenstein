"""Regex/keyword router — decides quick_reply vs crew vs classify."""

import re
from dataclasses import dataclass


@dataclass
class RouteResult:
    action: str  # "quick_reply", "crew", or "classify"
    crew_type: str | None = None


QUICK_REPLY_PATTERNS = [
    re.compile(r"^(hallo|hi|hey|moin|servus|guten\s*(morgen|tag|abend))[\s!.]*$", re.I),
    re.compile(r"^(danke|vielen\s*dank|thx|thanks|merci)[\s!.]*", re.I),
    re.compile(r"^(ja|nein|ok|alles\s*klar|passt|genau|stimmt)[\s!.]*$", re.I),
    re.compile(r"^was\s+(machst|tust)\s+du\s*(gerade)?", re.I),
    re.compile(r"^wie\s+geht('?s|\s+es)\s*(dir)?", re.I),
    re.compile(r"^(gute\s*nacht|bis\s*(dann|morgen|spaeter)|tschuess|ciao)[\s!.]*$", re.I),
]

CREW_KEYWORDS = {
    "web_design": ["website", "landing page", "html", "css", "tailwind", "responsive", "frontend", "webpage", "webseite"],
    "swift": ["swift", "swiftui", "ios", "macos", "xcode", "app store", "iphone app", "ipad app", "apple app"],
    "ki_expert": ["fine-tun", "training", "embedding", "neural", "ml pipeline", "modell trainier", "prompt engineer", "machine learning", "deep learning"],
    "analyst": ["csv", "statistik", "chart", "visualisier", "datenanalyse", "pandas", "diagramm", "auswert"],
    "ops": ["server", "docker", "deploy", "systemd", "backup", "nginx", "ssh", "kubernetes", "k8s"],
    "researcher": ["recherchier", "herausfind", "vergleich", "zusammenfass", "informier dich", "such mir", "was ist", "erklaer mir"],
    "coder": ["code", "python", "script", "debug", "fix", "implementier", "programmier", "funktion", "klasse", "refactor", "bug"],
    "writer": ["schreib", "text", "doku", "guide", "artikel", "zusammenfassung", "bericht", "notiz"],
}

# Higher priority crew types first (more specific keywords)
CREW_PRIORITY = ["web_design", "swift", "ki_expert", "analyst", "ops", "researcher", "coder", "writer"]

MCP_KEYWORDS = {
    "erinner", "reminder", "erinnerung",
    "licht", "light", "lampe",
    "musik", "music", "spiel", "play", "pause", "stop",
    "kalender", "calendar", "termin", "event",
    "notiz", "note",
    "homekit", "smart home", "heizung", "thermostat",
    "timer", "wecker", "alarm",
}


class RuleEngine:
    def route(self, message: str) -> RouteResult:
        text = message.strip()
        # 1. Quick-reply patterns
        for pattern in QUICK_REPLY_PATTERNS:
            if pattern.search(text):
                return RouteResult(action="quick_reply")
        # 2. MCP keyword matching (before crew, after quick_reply)
        text_lower = text.lower()
        if any(kw in text_lower for kw in MCP_KEYWORDS):
            return RouteResult(action="direct_mcp", crew_type=None)
        # 3. Crew keyword matching
        for crew_type in CREW_PRIORITY:
            for kw in CREW_KEYWORDS[crew_type]:
                if kw in text_lower:
                    return RouteResult(action="crew", crew_type=crew_type)
        # 4. No match
        return RouteResult(action="classify")
