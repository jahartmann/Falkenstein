# backend/intent_prefilter.py
"""Intent-Prefilter — erkennt klare Intents vor dem LLM-Classify-Call."""
from __future__ import annotations
import re
from enum import Enum


class PrefilterResult(str, Enum):
    CREATE_SCHEDULE = "create_schedule"
    CREATE_TASK = "create_task"
    ROUTE_OBSIDIAN = "route_obsidian"
    NONE = "none"


_SCHEDULE_KEYWORDS = {
    "schedule", "täglich", "stündlich", "wöchentlich", "monatlich",
    "briefing", "erinnerung", "reminder", "regelmäßig", "wiederkehrend",
    "automatisch ausführen", "jeden morgen", "jeden abend", "jeden tag",
    "montags", "dienstags", "mittwochs", "donnerstags", "freitags",
    "samstags", "sonntags", "alle stunden", "alle minuten",
}

_TASK_KEYWORDS = {
    "erstelle task", "neuer task", "task anlegen", "aufgabe erstellen",
    "aufgabe anlegen", "neuen task",
}

_SCHEDULE_PATTERNS = [
    re.compile(r"\bich will\s+(täglich|jeden|morgens|abends|wöchentlich|regelmäßig|stündlich)\b", re.IGNORECASE),
    re.compile(r"\bmach\s+(mir|das|bitte|mal)?\s*(täglich|jeden|regelmäßig|automatisch|stündlich)\b", re.IGNORECASE),
    re.compile(r"\b(erstelle|leg\s+an|richte\s+ein|setz\s+auf|starte)\b.{0,40}\b(schedule|briefing|zusammenfassung|report|monitoring|überwachung|check|reminder|erinnerung)\b", re.IGNORECASE),
    re.compile(r"\bum\s+\d{1,2}:\d{2}\b.{0,60}\b(schicke|sende|zeig|mach|erstelle|check|prüfe)\b", re.IGNORECASE),
    re.compile(r"\b(schicke|sende|zeig|mach|erstelle|check|prüfe)\b.{0,60}\bum\s+\d{1,2}:\d{2}\b", re.IGNORECASE),
    re.compile(r"\bjeden\s+(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b", re.IGNORECASE),
    re.compile(r"\balle\s+\d+\s+(minuten|stunden|min|std)\b", re.IGNORECASE),
    re.compile(r"\berinner\s+(mich|uns)\b", re.IGNORECASE),
    re.compile(r"\btäglich\s+(um|morgens|abends|mittags|früh|ab|ab\s+\d)", re.IGNORECASE),
    re.compile(r"\bwöchentlich\s+\w+\s+\d{1,2}:\d{2}\b", re.IGNORECASE),
]

_SCHEDULE_EXCLUSIONS = [
    re.compile(r"\b(zeig|schau|gib|lies|lese)\s+mir\b.{0,30}\b(täglichen|wöchentlichen|aktuellen)\b", re.IGNORECASE),
    re.compile(r"\b(die|den|das)\s+(täglichen|wöchentlichen)\b", re.IGNORECASE),
]

_TASK_PATTERNS = [
    re.compile(r"\b(erstell\w*|leg\s+\w*\s*an|füge\s+\w*\s*hinzu)\b.{0,30}\b(task|aufgabe)\b", re.IGNORECASE),
    re.compile(r"\b(task|aufgabe)\b.{0,20}\b(erstell\w*|anlegen|hinzufügen)\b", re.IGNORECASE),
    re.compile(r"\b(neuen?\s+task|neues?\s+aufgabe)\b", re.IGNORECASE),
]


def _kw_pattern(kw: str) -> re.Pattern:
    """Build a word-boundary pattern for a keyword (handles multi-word phrases too)."""
    escaped = re.escape(kw)
    return re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)


_SCHEDULE_KW_PATTERNS = {kw: _kw_pattern(kw) for kw in _SCHEDULE_KEYWORDS}
_TASK_KW_PATTERNS = {kw: _kw_pattern(kw) for kw in _TASK_KEYWORDS}


class IntentPrefilter:
    def check(self, message: str) -> PrefilterResult:
        msg_lower = message.lower()

        for excl in _SCHEDULE_EXCLUSIONS:
            if excl.search(message):
                return PrefilterResult.NONE

        for keyword, pat in _TASK_KW_PATTERNS.items():
            if pat.search(message):
                return PrefilterResult.CREATE_TASK

        for keyword, pat in _SCHEDULE_KW_PATTERNS.items():
            if pat.search(message):
                if keyword in ("täglich", "wöchentlich", "stündlich"):
                    if re.search(r"\b" + keyword + r"\s+(um|\d|morgens|abends|früh|ab)", msg_lower):
                        return PrefilterResult.CREATE_SCHEDULE
                    if re.search(r"\b(ich will|mach mir|erstelle|leg an)\b", msg_lower):
                        return PrefilterResult.CREATE_SCHEDULE
                    continue
                return PrefilterResult.CREATE_SCHEDULE

        for pattern in _TASK_PATTERNS:
            if pattern.search(message):
                return PrefilterResult.CREATE_TASK

        for pattern in _SCHEDULE_PATTERNS:
            if pattern.search(message):
                return PrefilterResult.CREATE_SCHEDULE

        return PrefilterResult.NONE
