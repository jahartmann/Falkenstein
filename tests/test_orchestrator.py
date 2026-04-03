import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.orchestrator import Orchestrator
from backend.agent_pool import AgentPool
from backend.models import AgentRole, TaskData
from backend.relationships import RelationshipEngine
from backend.models import RelationshipData
from backend.database import Database
import pytest_asyncio


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


@pytest_asyncio.fixture
async def real_db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_orchestrator_assigns_duo_partner(real_db):
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value="coder_1")
    pool = AgentPool(llm=llm, db=real_db, tools=MagicMock())

    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.95, trust=0.8)
    await real_db.upsert_relationship(rel)

    rel_engine = RelationshipEngine(real_db)
    orch = Orchestrator(pool=pool, db=real_db, llm=llm, relationship_engine=rel_engine)

    coder1 = pool.get_agent("coder_1")
    await coder1.assign_task(task_id=99, title="Part A", description="First part")

    real_db.create_task = AsyncMock(return_value=2)
    real_db.get_task = AsyncMock(return_value=TaskData(
        id=2, title="Code part B", description="Code implementieren", project="website"
    ))
    await orch.submit_task("Code part B", "Code implementieren", project="website")
    event = await orch.assign_next_task()
    assert event is not None
    assert event["agent"] == "coder_2"


@pytest.mark.asyncio
async def test_process_work_event_escalation():
    db = AsyncMock()
    db.get_task = AsyncMock(return_value=TaskData(
        id=1, title="Fix bug", description="Debug issue"
    ))
    llm = AsyncMock()
    pool = AgentPool(llm=llm, db=db, tools=MagicMock())
    orch = Orchestrator(pool=pool, db=db, llm=llm)

    agent = pool.get_agent("coder_1")
    event = {"type": "tool_use", "agent": "coder_1", "needs_escalation": True}
    # cli_bridge not registered, so escalation returns empty
    extras = await orch.process_work_event(event)
    # No crash, returns list
    assert isinstance(extras, list)


@pytest.mark.asyncio
async def test_process_work_event_budget_warning():
    from backend.tools.cli_bridge import CLIBudgetTracker
    db = AsyncMock()
    llm = AsyncMock()
    budget = CLIBudgetTracker(daily_budget=1000)
    budget.record_usage(900)  # 90% — over warning threshold
    pool = AgentPool(llm=llm, db=db, tools=MagicMock())
    orch = Orchestrator(pool=pool, db=db, llm=llm, budget_tracker=budget)

    event = {"type": "tool_use", "agent": "coder_1", "needs_escalation": False}
    extras = await orch.process_work_event(event)
    budget_events = [e for e in extras if e.get("type") == "budget_warning"]
    assert len(budget_events) == 1
    assert budget_events[0]["used"] == 900


@pytest.mark.asyncio
async def test_process_work_event_no_escalation():
    db = AsyncMock()
    llm = AsyncMock()
    pool = AgentPool(llm=llm, db=db, tools=MagicMock())
    orch = Orchestrator(pool=pool, db=db, llm=llm)

    event = {"type": "tool_use", "agent": "coder_1", "needs_escalation": False}
    extras = await orch.process_work_event(event)
    assert extras == []
