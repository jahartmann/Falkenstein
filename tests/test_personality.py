import pytest
from backend.personality import PersonalityEngine, PersonalityEvent
from backend.models import AgentTraits, AgentMood


def test_task_success_boosts_confidence():
    traits = AgentTraits(confidence=0.5)
    mood = AgentMood(stress=0.3)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(traits, mood, PersonalityEvent.TASK_SUCCESS)
    assert new_traits.confidence > 0.5
    assert new_mood.stress < 0.3


def test_task_failure_increases_frustration():
    traits = AgentTraits(patience=0.5)
    mood = AgentMood(frustration=0.1)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(traits, mood, PersonalityEvent.TASK_FAILURE)
    assert new_mood.frustration > 0.1


def test_successful_collab_boosts_motivation():
    traits = AgentTraits()
    mood = AgentMood(motivation=0.5)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(traits, mood, PersonalityEvent.SUCCESSFUL_COLLAB)
    assert new_mood.motivation > 0.5


def test_cli_escalation_lowers_confidence():
    traits = AgentTraits(confidence=0.6)
    mood = AgentMood()
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(traits, mood, PersonalityEvent.CLI_ESCALATION)
    assert new_traits.confidence < 0.6


def test_received_praise_boosts_motivation_and_leadership():
    traits = AgentTraits(leadership=0.3)
    mood = AgentMood(motivation=0.5)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(traits, mood, PersonalityEvent.RECEIVED_PRAISE)
    assert new_mood.motivation > 0.5
    assert new_traits.leadership > 0.3


def test_traits_clamp_to_0_1():
    traits = AgentTraits(confidence=0.99)
    mood = AgentMood()
    engine = PersonalityEngine()
    new_traits, _ = engine.apply_event(traits, mood, PersonalityEvent.TASK_SUCCESS)
    assert new_traits.confidence <= 1.0

    traits2 = AgentTraits(confidence=0.01)
    new_traits2, _ = engine.apply_event(traits2, AgentMood(), PersonalityEvent.CLI_ESCALATION)
    assert new_traits2.confidence >= 0.0


def test_mood_decay_towards_baseline():
    mood = AgentMood(stress=0.8, energy=0.3, frustration=0.7)
    engine = PersonalityEngine()
    decayed = engine.decay_mood(mood)
    assert decayed.stress < 0.8
    assert decayed.energy > 0.3
    assert decayed.frustration < 0.7


def test_idle_chat_no_trait_change():
    traits = AgentTraits(social=0.5)
    mood = AgentMood()
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(traits, mood, PersonalityEvent.IDLE_CHAT)
    assert new_traits.social == 0.5
    assert new_mood.energy >= mood.energy
