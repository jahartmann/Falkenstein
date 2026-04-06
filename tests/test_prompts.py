import pytest
from backend.prompts.classify import build_classify_prompt
from backend.prompts.subagent import build_subagent_prompt
from backend.prompts.schedule import build_schedule_prompt


def test_classify_prompt_contains_kern_identitaet():
    prompt = build_classify_prompt()
    assert "Falki" in prompt
    assert "NIEMALS" in prompt
    assert "ops_command" in prompt


def test_classify_prompt_with_context():
    prompt = build_classify_prompt(
        active_agents="sub_researcher_abc: Recherche läuft",
        open_tasks="- [open] Task #1 Analyse",
        workspace="~/Buchprojekt",
    )
    assert "sub_researcher_abc" in prompt
    assert "~/Buchprojekt" in prompt


def test_classify_prompt_without_context():
    prompt = build_classify_prompt()
    assert "Aktive Agents:" not in prompt  # section omitted when empty


def test_subagent_prompt_researcher():
    prompt = build_subagent_prompt("researcher", "Analysiere KI-Trends", "recherche")
    assert "researcher" in prompt.lower()
    assert "## Zusammenfassung" in prompt
    assert "## Quellen" in prompt
    assert "Analysiere KI-Trends" in prompt


def test_subagent_prompt_coder():
    prompt = build_subagent_prompt("coder", "Refactore auth.py", "code")
    assert "## Problem" in prompt
    assert "## Lösung" in prompt


def test_subagent_prompt_writer():
    prompt = build_subagent_prompt("writer", "Schreibe Guide", "guide")
    assert "## Voraussetzungen" in prompt
    assert "## Schritt-für-Schritt" in prompt


def test_subagent_prompt_report():
    prompt = build_subagent_prompt("ops", "Analysiere Server-Logs", "report")
    assert "## Executive Summary" in prompt
    assert "## Empfehlungen" in prompt


def test_schedule_prompt():
    prompt = build_schedule_prompt(
        schedule_name="Morning Briefing",
        last_run="2026-04-06T08:00",
        result_type="report",
        obsidian_folder="Reports",
    )
    assert "Morning Briefing" in prompt
    assert "Reports" in prompt
    assert "## Executive Summary" in prompt
