import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from backend.memory.fact_memory import FactMemory, extract_and_store_facts, FACTS_TABLE_SQL


class FakeConn:
    """Minimal async sqlite conn mock."""

    def __init__(self):
        self._rows = []
        self._next_id = 1

    async def execute(self, sql, params=None):
        cursor = MagicMock()
        if "INSERT" in sql:
            cursor.lastrowid = self._next_id
            self._next_id += 1
        elif "SELECT" in sql and "COUNT" in sql:
            cursor.fetchone = AsyncMock(return_value=(len(self._rows),))
        elif "SELECT" in sql:
            cursor.fetchall = AsyncMock(return_value=self._rows)
        return cursor

    async def commit(self):
        pass


class FakeDB:
    def __init__(self):
        self._conn = FakeConn()


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.fixture
def fact_mem(fake_db):
    return FactMemory(fake_db)


@pytest.mark.asyncio
async def test_init_creates_table(fact_mem, fake_db):
    await fact_mem.init()
    assert fact_mem._initialized is True


@pytest.mark.asyncio
async def test_add_fact(fact_mem):
    fid = await fact_mem.add("user", "Janik nutzt FastAPI", "conversation")
    assert fid == 1


@pytest.mark.asyncio
async def test_add_multiple_facts(fact_mem):
    id1 = await fact_mem.add("user", "Fakt 1")
    id2 = await fact_mem.add("project", "Fakt 2")
    assert id1 == 1
    assert id2 == 2


@pytest.mark.asyncio
async def test_get_all_active_empty(fact_mem):
    facts = await fact_mem.get_all_active()
    assert facts == []


@pytest.mark.asyncio
async def test_get_context_block_empty(fact_mem):
    block = await fact_mem.get_context_block()
    assert block == ""


@pytest.mark.asyncio
async def test_count(fact_mem):
    count = await fact_mem.count()
    assert count == 0


@pytest.mark.asyncio
async def test_update_fact(fact_mem):
    # Should not raise
    await fact_mem.update(1, "Updated content")


@pytest.mark.asyncio
async def test_deactivate_fact(fact_mem):
    # Should not raise
    await fact_mem.deactivate(1)


@pytest.mark.asyncio
async def test_search_empty(fact_mem):
    results = await fact_mem.search("anything")
    assert results == []


# ── extract_and_store_facts tests ──


@pytest.mark.asyncio
async def test_extract_adds_facts():
    """LLM returns ADD actions -> facts get added."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='[{"action": "ADD", "category": "user", "content": "Mag Python"}]')

    fm = MagicMock(spec=FactMemory)
    fm.get_all_active = AsyncMock(return_value=[])
    fm.add = AsyncMock(return_value=1)

    await extract_and_store_facts(llm, fm, "Ich mag Python", "Cool!")
    fm.add.assert_called_once_with(category="user", content="Mag Python", source="conversation")


@pytest.mark.asyncio
async def test_extract_noop_on_empty():
    """LLM returns empty array -> nothing happens."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value="[]")

    fm = MagicMock(spec=FactMemory)
    fm.get_all_active = AsyncMock(return_value=[])
    fm.add = AsyncMock()

    await extract_and_store_facts(llm, fm, "Hi", "Hey!")
    fm.add.assert_not_called()


@pytest.mark.asyncio
async def test_extract_handles_bad_json():
    """LLM returns garbage -> no crash."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value="not json at all")

    fm = MagicMock(spec=FactMemory)
    fm.get_all_active = AsyncMock(return_value=[])

    # Should not raise
    await extract_and_store_facts(llm, fm, "test", "test")


@pytest.mark.asyncio
async def test_extract_update_and_delete():
    """LLM returns UPDATE and DELETE actions."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=(
        '[{"action": "UPDATE", "fact_id": 3, "content": "Neuer Inhalt"}, '
        '{"action": "DELETE", "fact_id": 5}]'
    ))

    fm = MagicMock(spec=FactMemory)
    fm.get_all_active = AsyncMock(return_value=[])
    fm.update = AsyncMock()
    fm.deactivate = AsyncMock()

    await extract_and_store_facts(llm, fm, "test", "test")
    fm.update.assert_called_once_with(3, "Neuer Inhalt")
    fm.deactivate.assert_called_once_with(5)
