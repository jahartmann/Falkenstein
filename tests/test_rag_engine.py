import pytest
from backend.memory.rag_engine import RAGEngine


@pytest.fixture
def rag_engine(tmp_path):
    """Create RAGEngine - init must be called in async tests."""
    return RAGEngine(persist_path=tmp_path / "chroma_test")


@pytest.mark.asyncio
async def test_available(rag_engine):
    assert rag_engine.available


@pytest.mark.asyncio
async def test_store_and_query(rag_engine):
    await rag_engine.init()
    await rag_engine.store_episode("Alex hat die REST API implementiert", {"agent_id": "coder_1"})
    await rag_engine.store_episode("Bob hat Tests geschrieben", {"agent_id": "coder_2"})
    results = await rag_engine.query("API Implementierung")
    assert len(results) > 0
    assert "Alex" in results[0]["text"]


@pytest.mark.asyncio
async def test_store_task_completion(rag_engine):
    await rag_engine.init()
    await rag_engine.store_task_completion(
        agent_id="coder_1", task_title="API bauen",
        task_description="REST API für Users", result="Endpoint /api/users fertig",
        success=True,
    )
    results = await rag_engine.query("API Users")
    assert len(results) > 0
    assert "erfolgreich" in results[0]["text"]


@pytest.mark.asyncio
async def test_get_context_for_task(rag_engine):
    await rag_engine.init()
    await rag_engine.store_episode("Researcher hat DuckDuckGo API recherchiert")
    context = await rag_engine.get_context_for_task("Websuche implementieren")
    assert "DuckDuckGo" in context or context == ""


@pytest.mark.asyncio
async def test_empty_query(rag_engine):
    await rag_engine.init()
    results = await rag_engine.query("something random")
    assert results == []


@pytest.mark.asyncio
async def test_count(rag_engine):
    await rag_engine.init()
    assert await rag_engine.count() == 0
    await rag_engine.store_episode("Episode 1")
    assert await rag_engine.count() == 1


@pytest.mark.asyncio
async def test_upsert_no_duplicates(rag_engine):
    await rag_engine.init()
    await rag_engine.store_episode("Same text twice")
    await rag_engine.store_episode("Same text twice")
    assert await rag_engine.count() == 1


@pytest.mark.asyncio
async def test_metadata_stored(rag_engine):
    await rag_engine.init()
    await rag_engine.store_episode("Task done", {"agent_id": "ops", "type": "task"})
    results = await rag_engine.query("Task done")
    assert results[0]["metadata"]["agent_id"] == "ops"


@pytest.mark.asyncio
async def test_no_chromadb_graceful():
    """RAGEngine works gracefully without ChromaDB."""
    engine = RAGEngine.__new__(RAGEngine)
    engine._available = False
    engine._client = None
    engine._collection = None
    engine._persist_path = None
    await engine.init()
    await engine.store_episode("test")
    results = await engine.query("test")
    assert results == []
    assert await engine.count() == 0
