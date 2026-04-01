import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.sim_engine import SimEngine
from backend.agent import Agent
from backend.models import (
    AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position,
)
from backend.relationships import RelationshipEngine
from backend.database import Database
from backend.models import RelationshipData
import pytest_asyncio


def make_agent(agent_id: str, name: str, role: AgentRole, x: int, y: int, **trait_overrides) -> Agent:
    traits = AgentTraits(**{**{"social": 0.5, "focus": 0.5}, **trait_overrides})
    data = AgentData(
        id=agent_id, name=name, role=role,
        state=AgentState.IDLE_SIT, position=Position(x=x, y=y),
        traits=traits, mood=AgentMood(),
    )
    return Agent(data=data, llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())


@pytest.mark.asyncio
async def test_tick_idle_agent_gets_action():
    agent = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5, social=0.9)
    agent.llm.generate_sim_action = AsyncMock(return_value="wander")
    sim = SimEngine(agents=[agent], llm=agent.llm)
    events = await sim.tick()
    assert len(events) >= 1
    assert events[0]["agent"] == "coder_1"


@pytest.mark.asyncio
async def test_tick_skips_working_agents():
    agent = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5)
    agent.data.state = AgentState.WORK_TYPE
    sim = SimEngine(agents=[agent], llm=AsyncMock())
    events = await sim.tick()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_talk_action_generates_chat_message():
    alex = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5, social=0.9)
    bob = make_agent("coder_2", "Bob", AgentRole.CODER_2, 6, 5)
    alex.llm.generate_sim_action = AsyncMock(return_value="talk")
    alex.llm.generate_chat_message = AsyncMock(return_value="Hey Bob, wie läuft's?")
    bob.llm.generate_sim_action = AsyncMock(return_value="sit")
    sim = SimEngine(agents=[alex, bob], llm=alex.llm)
    events = await sim.tick()
    talk_events = [e for e in events if e.get("type") == "talk"]
    assert len(talk_events) >= 1
    assert "Hey Bob" in talk_events[0]["message"]


@pytest_asyncio.fixture
async def sim_db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_talk_prefers_friends(sim_db):
    from backend.models import AgentState as AS
    alex = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5, social=0.9)
    bob = make_agent("coder_2", "Bob", AgentRole.CODER_2, 6, 5)
    clara = make_agent("writer", "Clara", AgentRole.WRITER, 6, 6)

    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", friendship=0.9, synergy=0.8)
    await sim_db.upsert_relationship(rel)

    rel_engine = RelationshipEngine(sim_db)
    alex.llm.generate_sim_action = AsyncMock(return_value="talk")
    alex.llm.generate_chat_message = AsyncMock(return_value="Hey!")
    bob.llm.generate_sim_action = AsyncMock(return_value="sit")
    clara.llm.generate_sim_action = AsyncMock(return_value="sit")

    sim = SimEngine(agents=[alex, bob, clara], llm=alex.llm, relationship_engine=rel_engine)
    bob_count = 0
    for _ in range(20):
        events = await sim.tick()
        for e in events:
            if e.get("type") == "talk" and e.get("agent") == "coder_1":
                if e.get("partner") == "coder_2":
                    bob_count += 1
        alex.data.state = AS.IDLE_SIT
        bob.data.state = AS.IDLE_SIT
        clara.data.state = AS.IDLE_SIT

    assert bob_count >= 10


@pytest.mark.asyncio
async def test_mood_decay_applied_each_tick():
    agent = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5)
    agent.data.mood.stress = 0.8
    agent.llm.generate_sim_action = AsyncMock(return_value="sit")
    sim = SimEngine(agents=[agent], llm=agent.llm)
    await sim.tick()
    assert agent.data.mood.stress < 0.8
