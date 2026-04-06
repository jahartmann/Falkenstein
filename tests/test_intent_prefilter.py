import pytest
from backend.intent_prefilter import IntentPrefilter, PrefilterResult

@pytest.fixture
def prefilter():
    return IntentPrefilter()

def test_schedule_keyword_direct(prefilter):
    result = prefilter.check("erstelle einen Schedule für tägliche News")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_natural_briefing(prefilter):
    result = prefilter.check("ich will täglich ein Briefing")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_natural_morgens(prefilter):
    result = prefilter.check("mach mir jeden morgen eine Zusammenfassung")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_with_time(prefilter):
    result = prefilter.check("schicke mir um 8:00 einen Report")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_reminder(prefilter):
    result = prefilter.check("erinner mich morgen früh an das Meeting")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_weekly(prefilter):
    result = prefilter.check("wöchentlich montags Server-Status prüfen")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_regelmassig(prefilter):
    result = prefilter.check("überwache regelmäßig die CPU-Auslastung")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_task_create(prefilter):
    result = prefilter.check("erstelle einen Task: Website redesign")
    assert result == PrefilterResult.CREATE_TASK

def test_task_anlegen(prefilter):
    result = prefilter.check("leg einen neuen Task an")
    assert result == PrefilterResult.CREATE_TASK

def test_no_match_simple_question(prefilter):
    result = prefilter.check("wie geht es dir?")
    assert result == PrefilterResult.NONE

def test_no_match_research(prefilter):
    result = prefilter.check("recherchiere KI-Trends 2026")
    assert result == PrefilterResult.NONE

def test_no_match_ops(prefilter):
    result = prefilter.check("pull den code und starte den server")
    assert result == PrefilterResult.NONE

def test_no_schedule_for_shell(prefilter):
    result = prefilter.check("zeig mir die täglichen Logs von heute")
    assert result == PrefilterResult.NONE
