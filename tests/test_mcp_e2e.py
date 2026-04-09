"""End-to-end integration test for MCP flow (mocked MCP servers)."""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.mcp import MCPBridge, MCPRegistry, create_all_mcp_tools
from backend.mcp.config import MCPServerConfig, ToolSchema
from backend.mcp.bridge import ToolResult
from backend.flow.falkenstein_flow import FalkensteinFlow

@pytest.fixture
def mock_bridge():
    from backend.mcp.config import ServerStatus
    reg = MCPRegistry()
    cfg = MCPServerConfig(id="apple-mcp", name="Apple", command="echo", args=[])
    reg._servers["apple-mcp"] = ServerStatus(config=cfg)
    reg._installed["apple-mcp"] = False
    reg._user_configs["apple-mcp"] = {}
    bridge = MCPBridge(reg)
    bridge.call_tool = AsyncMock(return_value=ToolResult(success=True, output="Erinnerung erstellt"))
    bridge.call_tool_threadsafe = MagicMock(return_value=ToolResult(success=True, output="Erinnerung erstellt"))
    bridge.discover_tools = AsyncMock(return_value=[
        ToolSchema(name="create_reminder", description="Create reminder", server_id="apple-mcp",
                   input_schema={"type": "object", "properties": {"title": {"type": "string"}}}),
    ])
    return bridge

@pytest.fixture
def flow(mock_bridge):
    event_bus = MagicMock()
    native_ollama = MagicMock()
    native_ollama.quick_reply = AsyncMock(return_value="ok")
    native_ollama.classify = AsyncMock(return_value={"crew_type": "ops"})
    native_ollama.classify_mcp = AsyncMock(return_value={
        "server_id": "apple-mcp",
        "tool_name": "create_reminder",
        "args": {"title": "Meeting", "due_date": "2026-04-09T09:00:00"},
    })
    vault_index = MagicMock()
    vault_index.as_context.return_value = ""
    settings = MagicMock()
    settings.ollama_model = "test"
    settings.model_light = "test"
    return FalkensteinFlow(
        event_bus=event_bus, native_ollama=native_ollama,
        vault_index=vault_index, settings=settings, tools={},
        mcp_bridge=mock_bridge,
    )

@pytest.mark.asyncio
async def test_reminder_e2e(flow, mock_bridge):
    """'Erinnere mich' should route through direct_mcp and call apple-mcp."""
    result = await flow.handle_message("Erinnere mich morgen um 9 ans Meeting", chat_id=42)
    assert result is not None
    mock_bridge.call_tool.assert_called_once_with(
        "apple-mcp", "create_reminder",
        {"title": "Meeting", "due_date": "2026-04-09T09:00:00"},
    )

def test_mcp_tools_as_crewai(mock_bridge):
    """MCP tools should be convertible to CrewAI BaseTool."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        schemas = loop.run_until_complete(mock_bridge.discover_tools())
        tools = create_all_mcp_tools(schemas, mock_bridge)
        assert len(tools) == 1
        assert tools[0].name == "mcp_apple_mcp_create_reminder"
        result = tools[0]._run(title="Test")
        assert result == "Erinnerung erstellt"
    finally:
        loop.close()


# ── Task-20 end-to-end tests (mock) ──────────────────────────────────────────

import concurrent.futures

from backend.database import Database
from backend.mcp.registry import MCPRegistry
from backend.mcp.bridge import _ServerHandle
from backend.mcp.permissions import PermissionResolver
from backend.mcp.approvals import ApprovalStore


class _FakeE2EResult:
    """Fake result shaped like a real MCP tool result."""
    def __init__(self, text, error=False):
        self.content = [type("B", (), {"text": text})()]
        self.isError = error


@pytest.mark.asyncio
async def test_e2e_safe_tool_no_approval(tmp_path):
    """A 'get_*' tool is heuristically safe → runs without approval prompt."""
    db = Database(tmp_path / "e2e1.db"); await db.init()
    reg = MCPRegistry(); await reg.load_from_db(db)
    resolver = PermissionResolver(db)
    tg = MagicMock(); tg.enabled = True; tg.send_approval_request = AsyncMock()
    ws = MagicMock(); ws.broadcast = AsyncMock()
    store = ApprovalStore(tg, ws, db, timeout_seconds=3)

    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=store)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=_FakeE2EResult("12 items"))
    bridge._handles["apple-mcp"] = _ServerHandle(
        session=fake_session, task=None, start_time=0.0,
    )

    # Call from a separate thread, just like CrewAI would
    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool,
            lambda: bridge.call_tool_threadsafe("apple-mcp", "get_reminders", {}),
        )

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.output == "12 items"
    # Safe tool: no approval channel hit
    tg.send_approval_request.assert_not_awaited()
    await db.close()


@pytest.mark.asyncio
async def test_e2e_sensitive_tool_with_allow(tmp_path):
    """A 'send_*' tool is heuristically sensitive → requests approval, user allows, call proceeds."""
    db = Database(tmp_path / "e2e2.db"); await db.init()
    reg = MCPRegistry(); await reg.load_from_db(db)
    resolver = PermissionResolver(db)
    tg = MagicMock(); tg.enabled = True; tg.send_approval_request = AsyncMock()
    ws = MagicMock(); ws.broadcast = AsyncMock()
    store = ApprovalStore(tg, ws, db, timeout_seconds=5)

    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=store)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=_FakeE2EResult("sent"))
    bridge._handles["apple-mcp"] = _ServerHandle(
        session=fake_session, task=None, start_time=0.0,
    )

    async def approver():
        """Simulate the user tapping 'Allow' in Telegram after ~50ms."""
        for _ in range(50):
            await asyncio.sleep(0.02)
            pending = store.list_pending()
            if pending:
                store.resolve(pending[0].id, "allow", "test")
                return
        raise RuntimeError("no pending approval appeared within 1s")

    asyncio.create_task(approver())

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool,
            lambda: bridge.call_tool_threadsafe("apple-mcp", "send_message", {"to": "x"}),
        )

    assert result.success is True
    assert result.output == "sent"
    tg.send_approval_request.assert_awaited()
    await db.close()


@pytest.mark.asyncio
async def test_e2e_denied_by_db_override(tmp_path):
    """A safe tool explicitly denied in the DB is refused without touching the session."""
    db = Database(tmp_path / "e2e3.db"); await db.init()
    reg = MCPRegistry(); await reg.load_from_db(db)
    resolver = PermissionResolver(db)
    await resolver.set_override("apple-mcp", "get_reminders", "deny")

    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=None)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock()
    bridge._handles["apple-mcp"] = _ServerHandle(
        session=fake_session, task=None, start_time=0.0,
    )

    result = await bridge.call_tool("apple-mcp", "get_reminders", {})
    assert result.success is False
    assert "denied" in result.output.lower()
    fake_session.call_tool.assert_not_awaited()
    await db.close()
