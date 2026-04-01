import pytest
import pytest_asyncio
from pathlib import Path
from backend.database import Database
from backend.models import (
    AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position,
    TaskData, TaskStatus, MessageData, MessageType, RelationshipData,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    tables = await db.get_tables()
    assert "agents" in tables
    assert "tasks" in tables
    assert "messages" in tables
    assert "relationships" in tables
    assert "tool_log" in tables
    assert "personality_log" in tables


@pytest.mark.asyncio
async def test_upsert_and_get_agent(db):
    agent = AgentData(
        id="coder_1", name="Alex", role=AgentRole.CODER_1,
        state=AgentState.IDLE_SIT, position=Position(x=10, y=20),
        traits=AgentTraits(social=0.7, focus=0.8),
        mood=AgentMood(energy=0.9),
    )
    await db.upsert_agent(agent)
    loaded = await db.get_agent("coder_1")
    assert loaded is not None
    assert loaded.name == "Alex"
    assert loaded.traits.social == 0.7
    assert loaded.position.x == 10


@pytest.mark.asyncio
async def test_create_and_get_task(db):
    task = TaskData(title="Build API", description="REST endpoints", project="website")
    task_id = await db.create_task(task)
    loaded = await db.get_task(task_id)
    assert loaded is not None
    assert loaded.title == "Build API"
    assert loaded.status == TaskStatus.OPEN


@pytest.mark.asyncio
async def test_update_task_status(db):
    task = TaskData(title="Test", description="desc")
    task_id = await db.create_task(task)
    await db.update_task_status(task_id, TaskStatus.IN_PROGRESS, assigned_to="coder_1")
    loaded = await db.get_task(task_id)
    assert loaded.status == TaskStatus.IN_PROGRESS
    assert loaded.assigned_to == "coder_1"


@pytest.mark.asyncio
async def test_create_and_get_messages(db):
    msg = MessageData(
        from_agent="researcher", to_agent="coder_1",
        type=MessageType.HANDOFF, content="API docs found",
    )
    await db.create_message(msg)
    msgs = await db.get_messages_for("coder_1")
    assert len(msgs) == 1
    assert msgs[0].content == "API docs found"


@pytest.mark.asyncio
async def test_upsert_and_get_relationship(db):
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.9)
    await db.upsert_relationship(rel)
    loaded = await db.get_relationship("coder_1", "coder_2")
    assert loaded is not None
    assert loaded.synergy == 0.9
    loaded_rev = await db.get_relationship("coder_2", "coder_1")
    assert loaded_rev is not None
    assert loaded_rev.synergy == 0.9
