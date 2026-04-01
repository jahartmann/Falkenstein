import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.orchestrator import Orchestrator
from backend.agent_pool import AgentPool
from backend.models import AgentRole, TaskData


@pytest.mark.asyncio
async def test_pool_creates_seven_agents():
    pool = AgentPool(llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    assert len(pool.agents) == 7
    roles = {a.data.role for a in pool.agents}
    assert AgentRole.PM in roles
    assert AgentRole.TEAM_LEAD in roles
    assert AgentRole.CODER_1 in roles
    assert AgentRole.CODER_2 in roles
    assert AgentRole.RESEARCHER in roles
    assert AgentRole.WRITER in roles
    assert AgentRole.OPS in roles


@pytest.mark.asyncio
async def test_pool_get_idle_agents():
    pool = AgentPool(llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    idle = pool.get_idle_agents()
    assert len(idle) == 7


@pytest.mark.asyncio
async def test_orchestrator_submit_task():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    pool = AgentPool(llm=AsyncMock(), db=db, tools=MagicMock())
    orch = Orchestrator(pool=pool, db=db, llm=AsyncMock())
    task_id = await orch.submit_task("Build API", "Create REST endpoints")
    assert task_id == 1
    db.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_assign_picks_matching_role():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    db.get_task = AsyncMock(return_value=TaskData(id=1, title="Build API", description="Code implementieren", status="open"))
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value="coder_1")
    pool = AgentPool(llm=llm, db=db, tools=MagicMock())
    orch = Orchestrator(pool=pool, db=db, llm=llm)
    task_id = await orch.submit_task("Build API", "Code implementieren")
    assigned = await orch.assign_next_task()
    assert assigned is not None
