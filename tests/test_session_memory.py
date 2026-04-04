import time
import pytest
from backend.memory.session import SessionMemory


@pytest.fixture
def mem():
    return SessionMemory(max_messages=5, timeout_seconds=2)


def test_add_and_get(mem):
    mem.add("agent1", {"role": "user", "content": "hello"})
    msgs = mem.get("agent1")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "hello"


def test_get_empty(mem):
    assert mem.get("nonexistent") == []


def test_max_messages_trimmed(mem):
    for i in range(20):
        mem.add("agent1", {"role": "user", "content": f"msg {i}"})
    msgs = mem.get("agent1")
    assert len(msgs) <= mem.max_messages * 2


def test_clear(mem):
    mem.add("agent1", {"role": "user", "content": "hello"})
    mem.clear("agent1")
    assert mem.get("agent1") == []


def test_timeout(mem):
    mem.add("agent1", {"role": "user", "content": "hello"})
    # Manually set last_active to past
    mem._last_active["agent1"] = time.time() - 10
    assert mem.get("agent1") == []


def test_touch_resets_timeout(mem):
    mem.add("agent1", {"role": "user", "content": "hello"})
    mem._last_active["agent1"] = time.time() - 1
    mem.touch("agent1")
    assert len(mem.get("agent1")) == 1


def test_active_agents(mem):
    mem.add("agent1", {"role": "user", "content": "a"})
    mem.add("agent2", {"role": "user", "content": "b"})
    assert set(mem.active_agents()) == {"agent1", "agent2"}


def test_active_agents_excludes_timed_out(mem):
    mem.add("agent1", {"role": "user", "content": "a"})
    mem._last_active["agent1"] = time.time() - 10
    assert "agent1" not in mem.active_agents()


def test_multiple_agents_isolated(mem):
    mem.add("a", {"role": "user", "content": "for a"})
    mem.add("b", {"role": "user", "content": "for b"})
    assert mem.get("a")[0]["content"] == "for a"
    assert mem.get("b")[0]["content"] == "for b"
