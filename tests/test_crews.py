"""Tests for YAML config loaders and BaseFalkensteinCrew."""
from unittest.mock import MagicMock

import pytest

from backend.crews.base_crew import (
    BaseFalkensteinCrew,
    create_crewai_agent,
    load_agent_configs,
    load_task_configs,
)


# ── Config loader tests ───────────────────────────────────────────────────────

def test_load_agent_configs():
    configs = load_agent_configs()
    assert "coder" in configs
    assert configs["coder"]["role"] == "Senior Developer"


def test_load_agent_configs_all_keys():
    configs = load_agent_configs()
    expected_keys = {
        "coder", "web_designer", "web_coder", "researcher",
        "swift_dev", "ki_expert", "analyst", "writer", "ops", "premium",
    }
    assert expected_keys.issubset(configs.keys())


def test_load_agent_configs_has_required_fields():
    configs = load_agent_configs()
    for key, cfg in configs.items():
        assert "role" in cfg, f"{key} missing 'role'"
        assert "goal" in cfg, f"{key} missing 'goal'"
        assert "backstory" in cfg, f"{key} missing 'backstory'"


def test_load_task_configs():
    configs = load_task_configs()
    assert "default" in configs
    assert "code_task" in configs
    assert "research_task" in configs


def test_load_task_configs_has_expected_output():
    configs = load_task_configs()
    for key, cfg in configs.items():
        assert "expected_output" in cfg, f"{key} missing 'expected_output'"


# ── Agent factory tests ───────────────────────────────────────────────────────

def test_create_crewai_agent():
    configs = load_agent_configs()
    agent = create_crewai_agent(
        "coder",
        configs["coder"],
        "ollama_chat/gemma4:26b",
        "ollama_chat/gemma4:e4b",
        [],
    )
    assert agent.role == "Senior Developer"


def test_create_crewai_agent_vault_context_appended():
    configs = load_agent_configs()
    agent = create_crewai_agent(
        "researcher",
        configs["researcher"],
        "ollama_chat/gemma4:26b",
        "ollama_chat/gemma4:e4b",
        [],
        vault_context="Use folder: Recherchen",
    )
    assert "Use folder: Recherchen" in agent.backstory


def test_create_crewai_agent_no_vault_context():
    configs = load_agent_configs()
    agent = create_crewai_agent(
        "writer",
        configs["writer"],
        "ollama_chat/gemma4:26b",
        "ollama_chat/gemma4:e4b",
        [],
        vault_context=None,
    )
    assert agent.backstory == configs["writer"]["backstory"]


# ── BaseFalkensteinCrew tests ─────────────────────────────────────────────────

class _StubCrew(BaseFalkensteinCrew):
    """Minimal concrete subclass used only in tests."""

    def build_crew(self):
        return MagicMock()


def test_base_crew_has_event_bus():
    crew = _StubCrew("coder", "Fix bug", MagicMock(), "123")
    assert crew.crew_type == "coder"


def test_base_crew_stores_task_description():
    crew = _StubCrew("coder", "Fix bug", MagicMock(), "123")
    assert crew.task_description == "Fix bug"


def test_base_crew_loads_configs():
    crew = _StubCrew("researcher", "Research topic", MagicMock(), "42")
    assert "coder" in crew.agent_configs
    assert "default" in crew.task_configs


def test_base_crew_is_abstract():
    """BaseFalkensteinCrew cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseFalkensteinCrew("coder", "task", MagicMock(), "123")


def test_base_crew_subclass_can_be_instantiated():
    class ConcreteCrew(BaseFalkensteinCrew):
        def build_crew(self):
            return MagicMock()

    crew = ConcreteCrew("ops", "Deploy app", MagicMock(), "99")
    assert crew.crew_type == "ops"
    assert crew.chat_id == "99"


def test_base_crew_vault_context_stored():
    class ConcreteCrew(BaseFalkensteinCrew):
        def build_crew(self):
            return MagicMock()

    crew = ConcreteCrew("writer", "Write guide", MagicMock(), "1", vault_context="Vault rules")
    assert crew.vault_context == "Vault rules"
