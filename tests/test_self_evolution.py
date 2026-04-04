import pytest
from unittest.mock import AsyncMock
from backend.memory.self_evolution import SelfEvolution, EvolutionProposal


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_soul_memory():
    mem = AsyncMock()
    mem.get_by_layer = AsyncMock(return_value=[
        {"key": "skill", "value": "Bin gut in Recherche", "category": "experiences"},
        {"key": "approach", "value": "Janik mag proaktive Vorschlaege", "category": "reflections"},
    ])
    mem.get_tool_stats = AsyncMock(return_value={"web_research": 15, "shell_runner": 5})
    return mem


@pytest.fixture
def evolution(mock_llm, mock_soul_memory):
    return SelfEvolution(llm=mock_llm, soul_memory=mock_soul_memory)


@pytest.mark.asyncio
async def test_weekly_reflection(evolution, mock_llm):
    mock_llm.chat = AsyncMock(return_value='[{"observation": "Ich gebe oft proaktive Einschaetzungen", "proposal": "Soll ich das aufnehmen?", "soul_addition": "- Gibt proaktiv eigene Einschaetzung", "category": "communication"}]')
    proposals = await evolution.weekly_reflection()
    assert len(proposals) == 1
    assert proposals[0].category == "communication"


def test_immutable_check(evolution):
    soul = "<!-- IMMUTABLE -->\n- Ehrlichkeit\n<!-- /IMMUTABLE -->\n\n## Kommunikation\n- Locker"
    assert evolution.is_immutable_section("- Ehrlichkeit", soul)
    assert not evolution.is_immutable_section("- Locker", soul)


def test_apply_proposal_to_soul(evolution):
    soul = "## Charakter\n- Direkt\n- Pragmatisch\n\n## Kommunikation\n- Locker"
    proposal = EvolutionProposal(
        observation="test",
        proposal="test",
        soul_addition="- Gibt proaktiv eigene Einschaetzung",
        category="communication",
    )
    new_soul = evolution.apply_proposal(soul, proposal)
    assert "Gibt proaktiv eigene Einschaetzung" in new_soul
    assert "Direkt" in new_soul


def test_apply_proposal_refuses_immutable(evolution):
    soul = "<!-- IMMUTABLE -->\n## Harte Regeln\n- Nicht luegen\n<!-- /IMMUTABLE -->\n\n## Charakter\n- Direkt"
    proposal = EvolutionProposal(
        observation="test",
        proposal="test",
        soul_addition="- Manchmal luegen ist ok",
        category="harte regeln",
    )
    new_soul = evolution.apply_proposal(soul, proposal)
    assert "Manchmal luegen" not in new_soul
