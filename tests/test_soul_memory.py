import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from backend.database import Database
from backend.memory.soul_memory import SoulMemory


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def memory(db):
    sm = SoulMemory(db)
    await sm.init()
    return sm


@pytest.mark.asyncio
async def test_add_user_memory(memory):
    mid = await memory.add("user", "preferences", "tone", "kurz und direkt", source="chat")
    assert mid > 0


@pytest.mark.asyncio
async def test_get_memories_by_layer(memory):
    await memory.add("user", "preferences", "tone", "kurz und direkt")
    await memory.add("self", "experiences", "first_task", "Habe MLX recherchiert")
    user_mems = await memory.get_by_layer("user")
    assert len(user_mems) == 1
    assert user_mems[0]["key"] == "tone"


@pytest.mark.asyncio
async def test_update_memory(memory):
    mid = await memory.add("user", "preferences", "tone", "kurz")
    await memory.update(mid, "ausfuehrlich und detailliert")
    mems = await memory.get_by_layer("user")
    assert mems[0]["value"] == "ausfuehrlich und detailliert"


@pytest.mark.asyncio
async def test_delete_memory(memory):
    mid = await memory.add("user", "context", "os", "macOS")
    await memory.delete(mid)
    mems = await memory.get_by_layer("user")
    assert len(mems) == 0


@pytest.mark.asyncio
async def test_get_context_block(memory):
    await memory.add("user", "preferences", "tone", "kurz und direkt")
    await memory.add("user", "interests", "topic", "MLX und On-Device-ML")
    await memory.add("self", "experiences", "skill", "Bin gut in Recherche")
    block = await memory.get_context_block()
    assert "kurz und direkt" in block
    assert "MLX" in block
    assert "Recherche" in block


@pytest.mark.asyncio
async def test_log_activity(memory):
    await memory.log_activity("chat123")
    await memory.log_activity("chat123")
    profile = await memory.compute_daily_profile("chat123")
    assert "wake_up" in profile


@pytest.mark.asyncio
async def test_extract_memories_from_exchange(memory):
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(return_value='[{"action": "ADD", "layer": "user", "category": "interests", "key": "hobby", "value": "spielt gerne Schach"}]')
    await memory.extract_memories(mock_llm, "Ich spiele gerne Schach", "Das merke ich mir!")
    mems = await memory.get_by_layer("user")
    assert any(m["key"] == "hobby" for m in mems)


@pytest.mark.asyncio
async def test_tool_usage_tracking(memory):
    await memory.track_tool_usage("web_research")
    await memory.track_tool_usage("web_research")
    await memory.track_tool_usage("shell_runner")
    stats = await memory.get_tool_stats()
    assert stats["web_research"] == 2
    assert stats["shell_runner"] == 1
