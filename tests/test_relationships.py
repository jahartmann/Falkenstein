import pytest
import pytest_asyncio
from pathlib import Path
from backend.relationships import RelationshipEngine, RelationshipEvent
from backend.database import Database
from backend.models import RelationshipData


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_collab_success_increases_synergy(db):
    engine = RelationshipEngine(db)
    await engine.record_event("coder_1", "coder_2", RelationshipEvent.COLLAB_SUCCESS)
    rel = await db.get_relationship("coder_1", "coder_2")
    assert rel is not None
    assert rel.synergy > 0.5
    assert rel.trust > 0.5


@pytest.mark.asyncio
async def test_review_clean_increases_respect(db):
    engine = RelationshipEngine(db)
    await engine.record_event("coder_1", "team_lead", RelationshipEvent.REVIEW_CLEAN)
    rel = await db.get_relationship("coder_1", "team_lead")
    assert rel.respect > 0.5


@pytest.mark.asyncio
async def test_idle_chat_increases_friendship(db):
    engine = RelationshipEngine(db)
    await engine.record_event("coder_1", "coder_2", RelationshipEvent.IDLE_CHAT)
    rel = await db.get_relationship("coder_1", "coder_2")
    assert rel.friendship > 0.5


@pytest.mark.asyncio
async def test_duo_detection_at_high_synergy(db):
    engine = RelationshipEngine(db)
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.9, trust=0.8, friendship=0.7, respect=0.8)
    await db.upsert_relationship(rel)
    duos = await engine.detect_duos()
    assert len(duos) == 1
    assert ("coder_1", "coder_2") in duos or ("coder_2", "coder_1") in duos


@pytest.mark.asyncio
async def test_no_duo_at_low_synergy(db):
    engine = RelationshipEngine(db)
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.5)
    await db.upsert_relationship(rel)
    duos = await engine.detect_duos()
    assert len(duos) == 0


@pytest.mark.asyncio
async def test_repeated_events_accumulate(db):
    engine = RelationshipEngine(db)
    for _ in range(5):
        await engine.record_event("coder_1", "coder_2", RelationshipEvent.COLLAB_SUCCESS)
    rel = await db.get_relationship("coder_1", "coder_2")
    assert rel.synergy > 0.7
