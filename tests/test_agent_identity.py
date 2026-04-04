import pytest
from pathlib import Path
from backend.agent_identity import AgentIdentity, load_agent_pool, select_agent


def test_agent_identity_creation():
    identity = AgentIdentity(
        name="Mira",
        role="Recherche-Analystin",
        personality="Wissensdurstig, strukturiert",
        approach="Deep-Dives mit Quellen",
        tool_priority=["web_research", "cli_bridge"],
    )
    assert identity.name == "Mira"
    assert identity.role == "Recherche-Analystin"
    assert "web_research" in identity.tool_priority


def test_load_agent_pool():
    pool = load_agent_pool()
    assert len(pool) >= 4
    names = [a.name for a in pool]
    assert "Mira" in names
    assert "Rex" in names


def test_select_agent_for_research():
    pool = load_agent_pool()
    agent = select_agent("Recherchiere alles ueber MLX", pool)
    assert agent is not None
    assert agent.name is not None
    assert len(agent.tool_priority) > 0


def test_select_agent_for_coding():
    pool = load_agent_pool()
    agent = select_agent("Schreibe ein Python-Script das X macht", pool)
    assert agent is not None


def test_agent_identity_system_prompt():
    identity = AgentIdentity(
        name="Rex",
        role="Code-Ingenieur",
        personality="Pragmatisch, test-getrieben",
        approach="Liest erstmal, dann schreibt er",
        tool_priority=["shell_runner", "code_executor"],
    )
    prompt = identity.build_system_prompt(soul_content="Ich bin Falki.")
    assert "Rex" in prompt
    assert "Code-Ingenieur" in prompt
    assert "Falki" in prompt
