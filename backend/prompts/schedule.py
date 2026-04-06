# backend/prompts/schedule.py
"""Prompts für Schedule-Tasks die der SmartScheduler ausführt."""
from __future__ import annotations
from backend.prompts.subagent import OUTPUT_TEMPLATES, BASE_REQUIREMENTS


def build_schedule_prompt(
    schedule_name: str,
    last_run: str | None,
    result_type: str = "report",
    obsidian_folder: str = "Reports",
) -> str:
    """Build system prompt for a scheduled SubAgent run."""
    template = OUTPUT_TEMPLATES.get(result_type, OUTPUT_TEMPLATES["report"])
    last_run_str = f"Letzter Lauf: {last_run}" if last_run else "Erster Lauf"
    return (
        f"Du bist ein automatischer Schedule-Agent im Falkenstein-System.\n\n"
        f"## Schedule\n"
        f"Name: {schedule_name}\n"
        f"{last_run_str}\n\n"
        f"## Ablage\n"
        f"Speichere das Ergebnis in Obsidian-Ordner: {obsidian_folder}\n\n"
        f"{template}\n\n"
        f"{BASE_REQUIREMENTS}"
    )
