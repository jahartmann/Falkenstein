import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.agent import Agent
from backend.models import AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position


def make_agent_data(**overrides) -> AgentData:
    defaults = dict(
        id="coder_1", name="Alex", role=AgentRole.CODER_1,
        state=AgentState.IDLE_SIT, position=Position(x=5, y=5),
        traits=AgentTraits(social=0.7, focus=0.8),
        mood=AgentMood(energy=0.9),
    )
    defaults.update(overrides)
    return AgentData(**defaults)


@pytest.mark.asyncio
async def test_agent_starts_idle():
    data = make_agent_data()
    agent = Agent(data=data, llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    assert agent.is_idle


@pytest.mark.asyncio
async def test_assign_task_switches_to_work():
    data = make_agent_data()
    db = AsyncMock()
    agent = Agent(data=data, llm=AsyncMock(), db=db, tools=MagicMock())
    await agent.assign_task(task_id=1, title="Build API", description="REST endpoints")
    assert agent.data.state == AgentState.WORK_SIT
    assert agent.data.current_task_id == 1


@pytest.mark.asyncio
async def test_complete_task_returns_to_idle():
    data = make_agent_data(state=AgentState.WORK_TYPE, current_task_id=1)
    db = AsyncMock()
    agent = Agent(data=data, llm=AsyncMock(), db=db, tools=MagicMock())
    await agent.complete_task(result="Done")
    assert agent.is_idle
    assert agent.data.current_task_id is None
    db.update_task_status.assert_called_once()


@pytest.mark.asyncio
async def test_personality_description():
    data = make_agent_data(traits=AgentTraits(social=0.9, focus=0.3, curiosity=0.8))
    agent = Agent(data=data, llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    desc = agent.personality_description
    assert "Alex" in desc
    assert isinstance(desc, str)
    assert len(desc) > 10


from backend.personality import PersonalityEngine


@pytest.mark.asyncio
async def test_complete_task_triggers_personality_event():
    data = make_agent_data(state=AgentState.WORK_TYPE, current_task_id=1)
    data.traits = AgentTraits(confidence=0.5)
    data.mood = AgentMood(stress=0.3)
    db = AsyncMock()
    agent = Agent(data=data, llm=AsyncMock(), db=db, tools=MagicMock(),
                  personality_engine=PersonalityEngine())
    await agent.complete_task(result="Done")
    assert agent.data.traits.confidence > 0.5
    assert agent.data.mood.stress < 0.3
