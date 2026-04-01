import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from backend.ws_manager import WSManager


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    mgr = WSManager()
    ws = AsyncMock()
    await mgr.connect(ws)
    assert len(mgr.connections) == 1
    mgr.disconnect(ws)
    assert len(mgr.connections) == 0


@pytest.mark.asyncio
async def test_broadcast_sends_to_all():
    mgr = WSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    await mgr.connect(ws1)
    await mgr.connect(ws2)
    await mgr.broadcast({"type": "move", "agent": "coder_1", "x": 10, "y": 20})
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()
    sent = json.loads(ws1.send_text.call_args[0][0])
    assert sent["type"] == "move"


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections():
    mgr = WSManager()
    ws_alive = AsyncMock()
    ws_dead = AsyncMock()
    ws_dead.send_text.side_effect = Exception("connection closed")
    await mgr.connect(ws_alive)
    await mgr.connect(ws_dead)
    await mgr.broadcast({"type": "test"})
    assert ws_dead not in mgr.connections
    assert ws_alive in mgr.connections
