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


def test_consolidate_multi_point_returns_consolidated():
    consolidator = PromptConsolidator()
    text = "1. Recherchiere KI-Trends 2026\n2. Erstelle daraus einen Guide"
    result, was_consolidated = consolidator.consolidate(text)
    assert was_consolidated is True
    assert "KI-Trends" in result
    assert "Guide" in result


def test_consolidate_plain_text_unchanged():
    consolidator = PromptConsolidator()
    text = "Wie geht es dir?"
    result, was_consolidated = consolidator.consolidate(text)
    assert was_consolidated is False
    assert result == text


def test_consolidate_single_item_unchanged():
    consolidator = PromptConsolidator()
    text = "1. Recherchiere KI-Trends"
    result, was_consolidated = consolidator.consolidate(text)
    assert was_consolidated is False
    assert result == text


def test_extract_points_only_captures_first_line_of_multiline_point():
    """Multi-line sub-items are not supported — only the first line per point is extracted."""
    consolidator = PromptConsolidator()
    text = "1. Recherchiere KI-Trends,\n   besonders im Bereich AGI\n2. Erstelle Guide"
    points = consolidator.extract_points(text)
    # Only the first line of point 1 is captured
    assert len(points) == 2
    assert points[0] == "Recherchiere KI-Trends,"
