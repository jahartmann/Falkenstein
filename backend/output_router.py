# backend/output_router.py
"""Output-Router — entscheidet wohin ein SubAgent-Ergebnis gelangt.

3-Stufen-Check:
  1. Explizite Keyword-Anweisung im Original-Prompt (0 Token)
  2. Kontext-Inferenz via model_light (wenn kein expliziter Hinweis)
  3. Default basierend auf Intent-Typ
"""
from __future__ import annotations
import re
from enum import Enum


class OutputDestination(str, Enum):
    OBSIDIAN = "obsidian"
    TASK = "task"
    SCHEDULE = "schedule"
    REPLY = "reply"


_OBSIDIAN_KEYWORDS = [
    "in obsidian", "obsidian ablegen", "speichere in", "leg ab in",
    "in die vault", "in vault", "abspeichern",
]
_TASK_KEYWORDS = [
    "als task", "in tasks", "task erstellen", "aufgabe anlegen",
    "task anlegen", "als aufgabe", "einen task", "daraus task",
]
_SCHEDULE_KEYWORDS = [
    "als schedule", "schedule anlegen", "täglich ausführen",
    "als wiederkehrende", "automatisch wiederholen",
]
_REPLY_KEYWORDS = [
    "hier antworten", "zeig mir", "sag mir", "schick mir", "schreib mir",
    "antworte hier", "nur hier",
]

_OBSIDIAN_FOLDERS: dict[str, str] = {
    "recherche": "Recherchen",
    "guide": "Guides",
    "cheat-sheet": "Cheat-Sheets",
    "code": "Code",
    "report": "Reports",
}


class OutputRouter:
    """Routes agent output to the correct destination."""

    def __init__(self, llm=None):
        self._llm = llm

    def check_explicit(self, original_prompt: str, result_type: str | None) -> OutputDestination | None:
        """Check for explicit routing keywords in the original prompt.

        Returns None if no explicit destination found.
        """
        text = original_prompt.lower()
        for kw in _OBSIDIAN_KEYWORDS:
            if kw in text:
                return OutputDestination.OBSIDIAN
        for kw in _TASK_KEYWORDS:
            if kw in text:
                return OutputDestination.TASK
        for kw in _SCHEDULE_KEYWORDS:
            if kw in text:
                return OutputDestination.SCHEDULE
        for kw in _REPLY_KEYWORDS:
            if kw in text:
                return OutputDestination.REPLY
        return None

    def get_default_destination(self, intent_type: str, result_type: str | None) -> OutputDestination:
        """Get the default destination based on intent type.

        content → obsidian (has a document result)
        action/ops_command/quick_reply → reply (just confirm what was done)
        """
        if intent_type == "content":
            return OutputDestination.OBSIDIAN
        if intent_type == "multi_step":
            return OutputDestination.OBSIDIAN
        return OutputDestination.REPLY

    def get_obsidian_folder(self, result_type: str | None) -> str:
        """Map result_type to the correct Obsidian folder."""
        return _OBSIDIAN_FOLDERS.get(result_type or "", "Recherchen")

    async def resolve(
        self,
        original_prompt: str,
        intent_type: str,
        result_type: str | None,
        conversation_history: list[dict] | None = None,
    ) -> OutputDestination:
        """Determine output destination using the 3-step check.

        Step 1: Explicit keyword in prompt → immediate routing
        Step 2: Context inference via LLM (if llm available and history present)
        Step 3: Fall back to default
        """
        # Step 1: explicit keyword
        explicit = self.check_explicit(original_prompt, result_type)
        if explicit is not None:
            return explicit

        # Step 2: LLM context inference (only if history available and LLM configured)
        if self._llm and conversation_history and len(conversation_history) >= 2:
            history_text = "\n".join(
                f"{m['role']}: {m['content'][:200]}"
                for m in conversation_history[-5:]
            )
            try:
                resp = await self._llm.chat_light(
                    system_prompt=(
                        "Analysiere diesen Gesprächsverlauf und bestimme wohin das Ergebnis soll. "
                        "Antworte NUR mit einem Wort: obsidian / task / schedule / reply"
                    ),
                    messages=[{"role": "user", "content": f"Kontext:\n{history_text}\n\nAufgabe: {original_prompt[:300]}"}],
                    temperature=0.0,
                )
                dest_str = resp.strip().lower()
                if dest_str in ("obsidian", "task", "schedule", "reply"):
                    return OutputDestination(dest_str)
            except Exception:
                pass

        # Step 3: Default based on intent type
        return self.get_default_destination(intent_type, result_type)
