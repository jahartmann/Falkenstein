# tests/test_prompt_consolidator.py
import pytest
from backend.prompt_consolidator import PromptConsolidator, has_numbered_points

def test_has_numbered_points_detects_list():
    text = "1. Recherchiere KI-Trends\n2. Erstelle einen Guide\n3. Speichere in Obsidian"
    assert has_numbered_points(text) is True

def test_has_numbered_points_detects_bullet():
    text = "- Recherchiere X\n- Analysiere Y\n- Schreibe Report"
    assert has_numbered_points(text) is True

def test_has_numbered_points_ignores_single_item():
    text = "1. Recherchiere KI-Trends"
    assert has_numbered_points(text) is False

def test_has_numbered_points_ignores_plain():
    text = "Wie geht es dir?"
    assert has_numbered_points(text) is False

def test_has_numbered_points_detects_mixed():
    text = "Bitte mach folgendes:\n1. Recherchiere X\n2. Erstelle Y"
    assert has_numbered_points(text) is True

def test_consolidator_extracts_points():
    consolidator = PromptConsolidator()
    text = "1. Recherchiere KI-Trends 2026\n2. Erstelle daraus einen Guide\n3. Lege in Obsidian ab"
    points = consolidator.extract_points(text)
    assert len(points) == 3
    assert "KI-Trends" in points[0]
    assert "Guide" in points[1]
    assert "Obsidian" in points[2]

def test_consolidator_builds_single_prompt():
    consolidator = PromptConsolidator()
    points = [
        "Recherchiere KI-Trends 2026",
        "Erstelle daraus einen strukturierten Guide",
        "Speichere in Obsidian",
    ]
    result = consolidator.build_consolidated_prompt(points)
    assert "KI-Trends" in result
    assert "Guide" in result
    # Single prompt, not a list
    assert "\n1." not in result or result.count("\n1.") == 0
