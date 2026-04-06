# tests/test_output_router.py
import pytest
from unittest.mock import AsyncMock
from backend.output_router import OutputRouter, OutputDestination

@pytest.fixture
def router():
    mock_llm = AsyncMock()
    mock_llm.chat_light = AsyncMock(return_value="obsidian")
    return OutputRouter(llm=mock_llm)

def test_explicit_obsidian_keyword(router):
    dest = router.check_explicit("schreib das in obsidian", "recherche")
    assert dest == OutputDestination.OBSIDIAN

def test_explicit_task_keyword(router):
    dest = router.check_explicit("erstelle einen task daraus", "code")
    assert dest == OutputDestination.TASK

def test_explicit_schedule_keyword(router):
    dest = router.check_explicit("als schedule anlegen", "report")
    assert dest == OutputDestination.SCHEDULE

def test_explicit_reply_keyword(router):
    dest = router.check_explicit("zeig mir das hier", "recherche")
    assert dest == OutputDestination.REPLY

def test_no_explicit_returns_none(router):
    dest = router.check_explicit("recherchiere KI-Trends", "recherche")
    assert dest is None

def test_default_content_goes_to_obsidian(router):
    dest = router.get_default_destination("content", "recherche")
    assert dest == OutputDestination.OBSIDIAN

def test_default_action_goes_to_reply(router):
    dest = router.get_default_destination("action", None)
    assert dest == OutputDestination.REPLY

def test_default_multi_step_goes_to_obsidian(router):
    dest = router.get_default_destination("multi_step", "recherche")
    assert dest == OutputDestination.OBSIDIAN

def test_obsidian_folder_for_result_type(router):
    assert router.get_obsidian_folder("recherche") == "Recherchen"
    assert router.get_obsidian_folder("guide") == "Guides"
    assert router.get_obsidian_folder("code") == "Code"
    assert router.get_obsidian_folder("report") == "Reports"
    assert router.get_obsidian_folder("cheat-sheet") == "Cheat-Sheets"
