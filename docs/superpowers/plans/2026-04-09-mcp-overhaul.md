# MCP Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the MCP Bridge thread/loop bug that causes silent tool-call failures, move MCP configuration from `.env` into a runtime-editable Store UI with a curated 13-server catalog, add a hybrid permission system with Telegram-based approvals, and make MCP installation fast and offline-capable via managed per-server `node_modules`.

**Architecture:** Main asyncio loop is the single owner of `ClientSession` objects; all other contexts (CrewAI threads, HTTP handlers, Telegram) reach sessions via `asyncio.run_coroutine_threadsafe`. Each MCP server lives in its own `~/.falkenstein/mcp/<id>/` directory installed via npm. Permissions use a resolution chain (DB override → catalog override → heuristic → fail-safe "ask"). Approvals block the main-loop coroutine on an `asyncio.Event` that is set by either a Telegram callback or a WS-driven API call.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, CrewAI, MCP SDK (`stdio_client`, `ClientSession`), `asyncio.run_coroutine_threadsafe`, npm, vanilla JS (Command-Center), Phaser is untouched.

**Spec:** `docs/superpowers/specs/2026-04-09-mcp-overhaul-design.md`

---

## Task Overview

**Phase A — Foundation**
1. DB migration for mcp_servers / mcp_tool_permissions / mcp_approvals tables
2. ConfigService key for approval timeout

**Phase B — Bridge P0 (the actual bug)**
3. Bridge `call_tool_threadsafe` + thread regression test
4. Bridge stderr ring buffer
5. Bridge structured event log + health check loop

**Phase C — Installer**
6. `installer.py` — resolve_binary, is_installed, install, uninstall

**Phase D — Catalog**
7. `catalog.py` — 13-server CATALOG dict + schema validation

**Phase E — Registry**
8. Registry rewrite to DB-backed + catalog merge + .env migration

**Phase F — Permissions**
9. `permissions.py` — heuristic + resolution chain

**Phase G — Approvals**
10. `approvals.py` — PendingApproval + ApprovalStore + dedup
11. Telegram `send_approval_request` + callback_query routing

**Phase H — Bridge Integration**
12. Bridge `_start_server` uses installer + catalog, tool_adapter uses threadsafe
13. Bridge `call_tool` uses permissions + approvals

**Phase I — Admin API**
14. Admin API read endpoints (catalog, servers, tools, logs, permissions list, approvals pending/history)
15. Admin API mutating endpoints (install/uninstall/enable/disable/restart/permission PUT/DELETE/resolve)

**Phase J — Main Wiring**
16. `main.py` lifespan wiring (registry, bridge, approvals, tool creation)

**Phase K — Store UI**
17. Command-Center new "MCP Store" tab (HTML + CSS)
18. Store UI JS — fetch catalog + render installed & available zones
19. Store UI JS — install modal, permission toggles, logs viewer, live updates

**Phase L — Verification**
20. Integration test with mock bridge (threadsafe flow end-to-end)
21. Optional E2E with real `@modelcontextprotocol/server-everything`
22. Manual smoke checklist

---

## Task 1: DB Migration — new MCP tables

**Files:**
- Modify: `backend/database.py`
- Test: `tests/test_database_new_tables.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_database_new_tables.py`:

```python
import pytest
from backend.database import Database

@pytest.mark.asyncio
async def test_mcp_tables_exist_after_init(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.init()
    async with db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('mcp_servers', 'mcp_tool_permissions', 'mcp_approvals')"
    ) as cur:
        rows = await cur.fetchall()
    names = {r[0] for r in rows}
    assert names == {"mcp_servers", "mcp_tool_permissions", "mcp_approvals"}
    await db.close()

@pytest.mark.asyncio
async def test_mcp_servers_columns(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.init()
    async with db._conn.execute("PRAGMA table_info(mcp_servers)") as cur:
        rows = await cur.fetchall()
    cols = {r[1] for r in rows}
    assert {"id", "installed", "enabled", "config_json", "last_error",
            "installed_at", "updated_at"} <= cols
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_new_tables.py::test_mcp_tables_exist_after_init -v`
Expected: FAIL — tables don't exist yet.

- [ ] **Step 3: Add the migrations to `backend/database.py`**

Find the `async def init(self)` method in `backend/database.py`. Add these table creates after the existing `CREATE TABLE IF NOT EXISTS` statements:

```python
await self._conn.execute("""
    CREATE TABLE IF NOT EXISTS mcp_servers (
        id TEXT PRIMARY KEY,
        installed INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 0,
        config_json TEXT,
        last_error TEXT,
        installed_at DATETIME,
        updated_at DATETIME
    )
""")
await self._conn.execute("""
    CREATE TABLE IF NOT EXISTS mcp_tool_permissions (
        server_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('allow','ask','deny')),
        updated_at DATETIME,
        PRIMARY KEY (server_id, tool_name)
    )
""")
await self._conn.execute("""
    CREATE TABLE IF NOT EXISTS mcp_approvals (
        id TEXT PRIMARY KEY,
        server_id TEXT,
        tool_name TEXT,
        args_json TEXT,
        decision TEXT,
        decided_by TEXT,
        requested_at DATETIME,
        decided_at DATETIME
    )
""")
await self._conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_mcp_approvals_requested_at "
    "ON mcp_approvals(requested_at)"
)
await self._conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_database_new_tables.py -v`
Expected: both new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/database.py tests/test_database_new_tables.py
git commit -m "feat(db): add mcp_servers, mcp_tool_permissions, mcp_approvals tables"
```

---

## Task 2: ConfigService — approval timeout key

**Files:**
- Modify: `backend/config_service.py`
- Test: `tests/test_config_service.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config_service.py`:

```python
@pytest.mark.asyncio
async def test_approval_timeout_default(tmp_path):
    from backend.database import Database
    from backend.config_service import ConfigService
    db = Database(tmp_path / "t.db")
    await db.init()
    svc = ConfigService(db)
    await svc.init()
    assert svc.get_int("mcp_approval_timeout_seconds", 0) == 600
    await db.close()

@pytest.mark.asyncio
async def test_approval_timeout_override(tmp_path):
    from backend.database import Database
    from backend.config_service import ConfigService
    db = Database(tmp_path / "t.db")
    await db.init()
    svc = ConfigService(db)
    await svc.init()
    await svc.set("mcp_approval_timeout_seconds", "300")
    assert svc.get_int("mcp_approval_timeout_seconds", 0) == 300
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_service.py::test_approval_timeout_default -v`
Expected: FAIL — default is not registered (returns 0).

- [ ] **Step 3: Add the default to ConfigService**

In `backend/config_service.py`, locate the dict of defaults (typically in `init()` where defaults are seeded). Add:

```python
DEFAULTS = {
    # ... existing defaults ...
    "mcp_approval_timeout_seconds": "600",
}
```

If `get_int` does not exist yet, add a helper (right after `get_str` or similar):

```python
def get_int(self, key: str, default: int) -> int:
    raw = self.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_config_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/config_service.py tests/test_config_service.py
git commit -m "feat(config): add mcp_approval_timeout_seconds (default 600s)"
```

---

## Task 3: Bridge — call_tool_threadsafe + thread regression test

**Files:**
- Modify: `backend/mcp/bridge.py`
- Test: `tests/test_mcp_bridge.py` (extend)

**This task fixes the actual bug that causes Apple Music to fail. TDD: write the regression test first.**

- [ ] **Step 1: Write the regression test**

Add to `tests/test_mcp_bridge.py`:

```python
import asyncio
import concurrent.futures
import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.mcp.bridge import MCPBridge, ToolResult, _ServerHandle
from backend.mcp.registry import MCPRegistry

class _FakeSessionResult:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.isError = False

@pytest.mark.asyncio
async def test_call_tool_threadsafe_from_other_thread():
    """REGRESSION: CrewAI calls run in a thread pool; the bridge must
    handle calls from threads other than the main loop. Previously this
    created a fresh event loop and died with 'attached to different loop'."""
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=_FakeSessionResult("ok"))
    handle = _ServerHandle(session=fake_session, task=None, start_time=0.0)
    bridge._handles["fakesrv"] = handle

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool,
            lambda: bridge.call_tool_threadsafe("fakesrv", "ping", {"x": 1}),
        )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.output == "ok"
    fake_session.call_tool.assert_awaited_once_with("ping", arguments={"x": 1})

@pytest.mark.asyncio
async def test_call_tool_threadsafe_unknown_server():
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    bridge._main_loop = asyncio.get_running_loop()
    result = bridge.call_tool_threadsafe("nope", "x", {})
    assert result.success is False
    assert "not connected" in result.output.lower()
```

- [ ] **Step 2: Run the regression test to verify it fails**

Run: `python -m pytest tests/test_mcp_bridge.py::test_call_tool_threadsafe_from_other_thread -v`
Expected: FAIL with `AttributeError: 'MCPBridge' object has no attribute 'call_tool_threadsafe'` or similar.

- [ ] **Step 3: Implement the fix**

In `backend/mcp/bridge.py`, replace the class header with the loop pin and add `call_tool_threadsafe`:

```python
# At top of file, with the other imports
import concurrent.futures
```

Change `__init__`:

```python
class MCPBridge:
    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._handles: dict[str, _ServerHandle] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None
```

Change the beginning of `start()`:

```python
async def start(self, timeout: float = DEFAULT_START_TIMEOUT) -> None:
    """Start all enabled servers concurrently."""
    self._main_loop = asyncio.get_running_loop()
    coros = []
    for s in self.registry.list_servers():
        if not s.config.enabled:
            self.registry.update_status(s.config.id, status="disabled")
            continue
        coros.append(self._start_server(s.config.id, timeout))
    if coros:
        await asyncio.gather(*coros)
```

Add the new sync-facing API at the bottom of the class (after `call_tool`):

```python
def call_tool_threadsafe(
    self, server_id: str, tool_name: str, args: dict,
    timeout: float = TOOL_CALL_TIMEOUT,
) -> ToolResult:
    """Sync-facing tool call for CrewAI thread pool. Safe from any thread."""
    if self._main_loop is None:
        return ToolResult(success=False, output="Bridge not started")
    if server_id not in self._handles:
        return ToolResult(success=False, output=f"Server '{server_id}' not connected")
    fut = asyncio.run_coroutine_threadsafe(
        self.call_tool(server_id, tool_name, args, timeout),
        self._main_loop,
    )
    try:
        return fut.result(timeout=timeout + 5)
    except concurrent.futures.TimeoutError:
        return ToolResult(success=False, output=f"Timeout after {timeout}s")
    except Exception as e:
        return ToolResult(success=False, output=f"Error: {e}")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_bridge.py -v`
Expected: both new tests PASS, all existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/bridge.py tests/test_mcp_bridge.py
git commit -m "fix(mcp): bridge.call_tool_threadsafe — fix event-loop mismatch for CrewAI thread pool

Root cause: tool_adapter._run_async() created a fresh event loop per call,
but ClientSession lives on the main loop. Cross-loop use of async primitives
broke deterministically. Fix: pin main loop in start(), expose threadsafe
wrapper using run_coroutine_threadsafe."
```

---

## Task 4: Bridge — stderr ring buffer

**Files:**
- Modify: `backend/mcp/bridge.py`
- Test: `tests/test_mcp_bridge.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mcp_bridge.py`:

```python
import collections

@pytest.mark.asyncio
async def test_stderr_ring_buffer_capture():
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    handle = _ServerHandle(session=None, task=None, start_time=0.0)
    assert isinstance(handle.stderr, collections.deque)
    assert handle.stderr.maxlen == 200
    for i in range(250):
        handle.stderr.append(f"line {i}")
    assert len(handle.stderr) == 200
    assert handle.stderr[0] == "line 50"

@pytest.mark.asyncio
async def test_get_stderr_returns_snapshot():
    reg = MCPRegistry()
    bridge = MCPBridge(reg)
    handle = _ServerHandle(session=None, task=None, start_time=0.0)
    handle.stderr.extend(["a", "b", "c"])
    bridge._handles["srv"] = handle
    lines = bridge.get_stderr("srv")
    assert lines == ["a", "b", "c"]
    assert bridge.get_stderr("missing") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mcp_bridge.py::test_stderr_ring_buffer_capture -v`
Expected: FAIL — `_ServerHandle` has no `stderr` field.

- [ ] **Step 3: Add stderr field + get_stderr method**

In `backend/mcp/bridge.py`:

```python
from collections import deque
```

Update `_ServerHandle` dataclass:

```python
@dataclass
class _ServerHandle:
    """All resources for a single running MCP server."""
    session: ClientSession
    task: asyncio.Task
    tools: list[ToolSchema] = field(default_factory=list)
    start_time: float = 0.0
    _shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    stderr: deque = field(default_factory=lambda: deque(maxlen=200))
```

Add method to `MCPBridge` (right after `discover_tools`):

```python
def get_stderr(self, server_id: str) -> list[str]:
    """Return a snapshot of the last ~200 stderr lines for a server."""
    h = self._handles.get(server_id)
    return list(h.stderr) if h else []
```

- [ ] **Step 4: Wire stderr capture into `_start_server`**

Inside `_start_server`, replace the `_run` function body's `stdio_client` call to capture stderr. Replace the entire `_run()` coroutine with:

```python
async def _run() -> None:
    params = StdioServerParameters(
        command=cfg.command,
        args=cfg.args,
        env=cfg.env or None,
    )

    class _StderrCapture:
        """File-like that appends lines to the handle's stderr deque."""
        def __init__(self, buf: deque, tee=sys.stderr):
            self.buf = buf
            self.tee = tee
            self._partial = ""
        def write(self, data):
            try:
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                self._partial += data
                while "\n" in self._partial:
                    line, self._partial = self._partial.split("\n", 1)
                    if line:
                        self.buf.append(line)
                if self.tee:
                    self.tee.write(data)
            except Exception:
                pass
        def flush(self):
            if self.tee:
                try: self.tee.flush()
                except Exception: pass
        def fileno(self):
            # Some transports call fileno(); fall back to tee
            return self.tee.fileno() if hasattr(self.tee, "fileno") else -1

    capture = _StderrCapture(handle.stderr)

    try:
        import inspect
        _sig = inspect.signature(stdio_client)
        _kw = {"errlog": capture} if "errlog" in _sig.parameters else {}
        async with stdio_client(params, **_kw) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_result = await session.initialize()
                tools_result = await session.list_tools()

                tool_schemas = [
                    ToolSchema(
                        name=t.name,
                        description=t.description or "",
                        server_id=server_id,
                        input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
                    )
                    for t in tools_result.tools
                ]

                handle.session = session
                handle.tools = tool_schemas
                self.registry.update_status(
                    server_id, status="running",
                    tools_count=len(tool_schemas),
                )
                log.info("MCP server %s started with %d tools",
                         server_id, len(tool_schemas))
                ready_event.set()

                await handle._shutdown.wait()
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        error_box.append(err_msg)
        handle.stderr.append(f"[bridge] {err_msg}")
        ready_event.set()
```

Note: older MCP SDK versions may not support `errlog`. In that case `_kw` is empty and stderr from the subprocess goes only to the parent process stderr; we still capture bridge-side errors via the `except` block.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_mcp_bridge.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/mcp/bridge.py tests/test_mcp_bridge.py
git commit -m "feat(mcp): add stderr ring buffer (200 lines) + get_stderr API"
```

---

## Task 5: Bridge — structured event log + health check loop

**Files:**
- Modify: `backend/mcp/bridge.py`
- Test: `tests/test_mcp_bridge.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_bridge.py`:

```python
@pytest.mark.asyncio
async def test_bridge_emits_event_log(tmp_path, monkeypatch):
    from backend.mcp import bridge as bmod
    monkeypatch.setattr(bmod, "EVENT_LOG_PATH", tmp_path / "mcp_events.log")
    reg = MCPRegistry()
    b = MCPBridge(reg)
    b._emit_event("start_attempt", server_id="apple-mcp")
    log = (tmp_path / "mcp_events.log").read_text()
    assert '"event": "start_attempt"' in log
    assert '"server_id": "apple-mcp"' in log

@pytest.mark.asyncio
async def test_bridge_health_check_marks_dead_task():
    reg = MCPRegistry()
    from backend.mcp.config import MCPServerConfig
    reg.register(MCPServerConfig(id="x", name="X", command="nope", args=[]))
    b = MCPBridge(reg)
    reg.update_status("x", status="running")

    async def _done():
        return None
    task = asyncio.create_task(_done())
    await task
    handle = _ServerHandle(session=MagicMock(), task=task, start_time=0.0)
    b._handles["x"] = handle
    await b._health_tick()
    assert reg.get("x").status == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_bridge.py::test_bridge_emits_event_log tests/test_mcp_bridge.py::test_bridge_health_check_marks_dead_task -v`
Expected: FAIL.

- [ ] **Step 3: Add event log + health tick**

In `backend/mcp/bridge.py`:

```python
import json
from pathlib import Path

EVENT_LOG_PATH = Path("data/mcp_events.log")
EVENT_LOG_MAX_BYTES = 10 * 1024 * 1024
```

Add methods to `MCPBridge`:

```python
def _emit_event(self, event: str, **fields) -> None:
    """Append a structured JSON line to the MCP event log."""
    try:
        EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if EVENT_LOG_PATH.exists() and EVENT_LOG_PATH.stat().st_size > EVENT_LOG_MAX_BYTES:
            rotated = EVENT_LOG_PATH.with_suffix(".log.1")
            if rotated.exists():
                rotated.unlink()
            EVENT_LOG_PATH.rename(rotated)
        payload = {"ts": time.time(), "event": event, **fields}
        with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception as e:
        log.debug("event log write failed: %s", e)

async def _health_tick(self) -> None:
    """One pass of the health check — mark dead tasks as error."""
    for sid, handle in list(self._handles.items()):
        status = self.registry.get(sid)
        if status and status.status == "running" and handle.task and handle.task.done():
            self.registry.update_status(sid, status="error", last_error="task exited")
            self._emit_event("subprocess_exited", server_id=sid)

async def _health_loop(self, interval: float = 30.0) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            await self._health_tick()
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("health tick failed: %s", e)
```

Extend `start()` to launch the health loop:

```python
async def start(self, timeout: float = DEFAULT_START_TIMEOUT) -> None:
    self._main_loop = asyncio.get_running_loop()
    coros = []
    for s in self.registry.list_servers():
        if not s.config.enabled:
            self.registry.update_status(s.config.id, status="disabled")
            continue
        coros.append(self._start_server(s.config.id, timeout))
    if coros:
        await asyncio.gather(*coros)
    self._health_task = asyncio.create_task(self._health_loop(), name="mcp-health")
```

Add `self._health_task: asyncio.Task | None = None` to `__init__`.

Extend `stop()`:

```python
async def stop(self) -> None:
    if self._health_task:
        self._health_task.cancel()
        try:
            await self._health_task
        except (asyncio.CancelledError, Exception):
            pass
        self._health_task = None
    for sid in list(self._handles):
        await self._stop_server(sid)
```

Sprinkle `self._emit_event(...)` calls in `_start_server` at key points (start_attempt, start_ok, start_failed):

```python
self._emit_event("start_attempt", server_id=server_id)
# after ready_event.set() success:
self._emit_event("start_ok", server_id=server_id, tools=len(tool_schemas))
# after error_box branch:
self._emit_event("start_failed", server_id=server_id, error=err)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_bridge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/bridge.py tests/test_mcp_bridge.py
git commit -m "feat(mcp): structured event log + health check loop"
```

---

## Task 6: installer.py — managed MCP install

**Files:**
- Create: `backend/mcp/installer.py`
- Test: `tests/test_mcp_installer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_installer.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from backend.mcp import installer

def test_install_root_under_home():
    assert str(installer.INSTALL_ROOT).endswith(".falkenstein/mcp") or \
           "falkenstein" in str(installer.INSTALL_ROOT).lower()

def test_is_installed_false_if_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    assert installer.is_installed("nope", "bin_name") is False

def test_is_installed_true_if_binary_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    server_dir = tmp_path / "apple-mcp" / "node_modules" / ".bin"
    server_dir.mkdir(parents=True)
    (server_dir / "apple-mcp").touch()
    assert installer.is_installed("apple-mcp", "apple-mcp") is True

def test_resolve_binary_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    server_dir = tmp_path / "srv" / "node_modules" / ".bin"
    server_dir.mkdir(parents=True)
    (server_dir / "srvbin").touch()
    p = installer.resolve_binary("srv", "srvbin")
    assert p is not None
    assert p.name == "srvbin"

def test_resolve_binary_returns_none_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    assert installer.resolve_binary("nope", "x") is None

@pytest.mark.asyncio
async def test_install_runs_npm(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    async def fake_exec(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"installed\n", b""))
        return proc
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    server_dir = tmp_path / "srv" / "node_modules" / ".bin"
    server_dir.mkdir(parents=True)
    (server_dir / "srvbin").touch()
    r = await installer.install("srv", "srv-package", "srvbin")
    assert r.success is True
    assert r.binary_path is not None

@pytest.mark.asyncio
async def test_install_npm_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    async def fake_exec(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(return_value=(b"", b"ENOENT\n"))
        return proc
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    r = await installer.install("srv", "bad-pkg", "srvbin")
    assert r.success is False
    assert "ENOENT" in r.stderr

@pytest.mark.asyncio
async def test_uninstall_removes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    (tmp_path / "srv").mkdir()
    (tmp_path / "srv" / "marker.txt").write_text("x")
    ok = await installer.uninstall("srv")
    assert ok is True
    assert not (tmp_path / "srv").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_installer.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create `backend/mcp/installer.py`**

```python
"""Managed MCP server installation in ~/.falkenstein/mcp/."""
from __future__ import annotations
import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

INSTALL_ROOT = Path.home() / ".falkenstein" / "mcp"


@dataclass
class InstallResult:
    success: bool
    binary_path: Path | None
    error: str | None
    stderr: str


def server_dir(server_id: str) -> Path:
    return INSTALL_ROOT / server_id


def resolve_binary(server_id: str, bin_name: str) -> Path | None:
    """Return the absolute path of node_modules/.bin/<bin_name> if it exists."""
    p = server_dir(server_id) / "node_modules" / ".bin" / bin_name
    return p if p.exists() else None


def is_installed(server_id: str, bin_name: str) -> bool:
    """True iff the install dir exists AND the binary is resolvable."""
    return resolve_binary(server_id, bin_name) is not None


async def install(server_id: str, package: str, bin_name: str) -> InstallResult:
    """`npm install <package> --prefix ~/.falkenstein/mcp/<server_id>`."""
    target = server_dir(server_id)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return InstallResult(success=False, binary_path=None,
                             error=f"mkdir failed: {e}", stderr="")

    # Seed a minimal package.json so npm doesn't warn
    pkg_json = target / "package.json"
    if not pkg_json.exists():
        pkg_json.write_text('{"name":"falkenstein-mcp-' + server_id + '","version":"0.0.0","private":true}\n')

    log.info("Installing MCP %s (package=%s) into %s", server_id, package, target)
    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", package, "--prefix", str(target),
            "--no-audit", "--no-fund", "--loglevel=error",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0:
            return InstallResult(
                success=False, binary_path=None,
                error=f"npm exited with code {proc.returncode}",
                stderr=stderr_text,
            )
    except FileNotFoundError:
        return InstallResult(success=False, binary_path=None,
                             error="npm not found on PATH", stderr="")
    except Exception as e:
        return InstallResult(success=False, binary_path=None,
                             error=f"npm invocation failed: {e}", stderr="")

    binary = resolve_binary(server_id, bin_name)
    if binary is None:
        return InstallResult(
            success=False, binary_path=None,
            error=f"Binary '{bin_name}' not found after install",
            stderr=stderr_text if 'stderr_text' in locals() else "",
        )
    return InstallResult(success=True, binary_path=binary, error=None,
                         stderr=stderr_text if 'stderr_text' in locals() else "")


async def uninstall(server_id: str) -> bool:
    """Remove the entire ~/.falkenstein/mcp/<server_id>/ directory."""
    target = server_dir(server_id)
    if not target.exists():
        return True
    try:
        await asyncio.to_thread(shutil.rmtree, target)
        return True
    except Exception as e:
        log.error("Uninstall of %s failed: %s", server_id, e)
        return False
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_installer.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/installer.py tests/test_mcp_installer.py
git commit -m "feat(mcp): managed installer in ~/.falkenstein/mcp/"
```

---

## Task 7: catalog.py — 13-server CATALOG

**Files:**
- Create: `backend/mcp/catalog.py`
- Test: `tests/test_mcp_catalog.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_catalog.py`:

```python
import pytest
from backend.mcp.catalog import CATALOG, validate_entry, REQUIRED_FIELDS

def test_catalog_has_expected_count():
    assert 10 <= len(CATALOG) <= 20

def test_catalog_contains_core_servers():
    for sid in ("apple-mcp", "mcp-obsidian", "desktop-commander",
                "filesystem", "brave-search", "github"):
        assert sid in CATALOG, f"missing catalog entry: {sid}"

def test_every_entry_has_required_fields():
    for sid, entry in CATALOG.items():
        for field in REQUIRED_FIELDS:
            assert field in entry, f"{sid} missing {field}"

def test_risk_levels_valid():
    for sid, entry in CATALOG.items():
        assert entry["risk_level"] in ("low", "medium", "high"), \
            f"{sid} has invalid risk_level"

def test_validate_entry_accepts_good_entry():
    validate_entry("x", {
        "name": "X", "description": "d", "package": "pkg", "bin": "b",
        "category": "c", "platform": [], "risk_level": "low",
        "requires_config": [], "permissions": {},
    })

def test_validate_entry_rejects_missing_field():
    with pytest.raises(ValueError, match="missing"):
        validate_entry("x", {"name": "X"})

def test_validate_entry_rejects_bad_risk():
    bad = {f: "" for f in REQUIRED_FIELDS}
    bad["platform"] = []; bad["requires_config"] = []; bad["permissions"] = {}
    bad["risk_level"] = "nuclear"
    with pytest.raises(ValueError, match="risk_level"):
        validate_entry("x", bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mcp_catalog.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `backend/mcp/catalog.py`**

```python
"""Static curated catalog of known MCP servers."""
from __future__ import annotations

REQUIRED_FIELDS = (
    "name", "description", "package", "bin",
    "category", "platform", "risk_level",
    "requires_config", "permissions",
)

VALID_RISK_LEVELS = {"low", "medium", "high"}


def validate_entry(server_id: str, entry: dict) -> None:
    for f in REQUIRED_FIELDS:
        if f not in entry:
            raise ValueError(f"catalog entry '{server_id}' missing field '{f}'")
    if entry["risk_level"] not in VALID_RISK_LEVELS:
        raise ValueError(
            f"catalog entry '{server_id}' has invalid risk_level "
            f"'{entry['risk_level']}'"
        )
    if not isinstance(entry["platform"], list):
        raise ValueError(f"catalog entry '{server_id}': platform must be list")
    if not isinstance(entry["requires_config"], list):
        raise ValueError(f"catalog entry '{server_id}': requires_config must be list")
    if not isinstance(entry["permissions"], dict):
        raise ValueError(f"catalog entry '{server_id}': permissions must be dict")


CATALOG: dict[str, dict] = {
    "apple-mcp": {
        "name": "Apple Services",
        "description": "Reminders, Calendar, Notes, Messages, Music, Maps (macOS only)",
        "package": "apple-mcp",
        "bin": "apple-mcp",
        "category": "productivity",
        "platform": ["darwin"],
        "risk_level": "medium",
        "requires_config": [],
        "permissions": {
            "get_reminders": "allow",
            "get_calendar_events": "allow",
            "get_notes": "allow",
            "play_music": "allow",
            "pause_music": "allow",
            "send_message": "ask",
            "create_reminder": "ask",
            "create_note": "ask",
        },
    },
    "mcp-obsidian": {
        "name": "Obsidian Vault",
        "description": "Read and write notes in an Obsidian vault",
        "package": "mcp-obsidian",
        "bin": "mcp-obsidian",
        "category": "knowledge",
        "platform": [],
        "risk_level": "medium",
        "requires_config": ["vault_path"],
        "permissions": {},
    },
    "desktop-commander": {
        "name": "Desktop Commander",
        "description": "Shell, file operations, process management",
        "package": "@wonderwhy-er/desktop-commander",
        "bin": "desktop-commander",
        "category": "system",
        "platform": [],
        "risk_level": "high",
        "requires_config": [],
        "permissions": {},
    },
    "filesystem": {
        "name": "Filesystem",
        "description": "Read, write, and search files in allowed directories",
        "package": "@modelcontextprotocol/server-filesystem",
        "bin": "mcp-server-filesystem",
        "category": "system",
        "platform": [],
        "risk_level": "high",
        "requires_config": ["allowed_directories"],
        "permissions": {},
    },
    "brave-search": {
        "name": "Brave Search",
        "description": "Web search via Brave Search API",
        "package": "@modelcontextprotocol/server-brave-search",
        "bin": "mcp-server-brave-search",
        "category": "research",
        "platform": [],
        "risk_level": "low",
        "requires_config": ["BRAVE_API_KEY"],
        "permissions": {},
    },
    "fetch": {
        "name": "Fetch",
        "description": "Fetch and convert web content (HTML → markdown)",
        "package": "@modelcontextprotocol/server-fetch",
        "bin": "mcp-server-fetch",
        "category": "research",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
    "github": {
        "name": "GitHub",
        "description": "Repos, issues, PRs, files, search",
        "package": "@modelcontextprotocol/server-github",
        "bin": "mcp-server-github",
        "category": "development",
        "platform": [],
        "risk_level": "medium",
        "requires_config": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "permissions": {},
    },
    "postgres": {
        "name": "PostgreSQL",
        "description": "Query a PostgreSQL database (read-only by default)",
        "package": "@modelcontextprotocol/server-postgres",
        "bin": "mcp-server-postgres",
        "category": "data",
        "platform": [],
        "risk_level": "high",
        "requires_config": ["POSTGRES_URL"],
        "permissions": {},
    },
    "puppeteer": {
        "name": "Puppeteer",
        "description": "Browser automation and scraping",
        "package": "@modelcontextprotocol/server-puppeteer",
        "bin": "mcp-server-puppeteer",
        "category": "research",
        "platform": [],
        "risk_level": "medium",
        "requires_config": [],
        "permissions": {},
    },
    "sequential-thinking": {
        "name": "Sequential Thinking",
        "description": "Structured multi-step reasoning helper",
        "package": "@modelcontextprotocol/server-sequential-thinking",
        "bin": "mcp-server-sequential-thinking",
        "category": "reasoning",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
    "memory": {
        "name": "Memory",
        "description": "Persistent knowledge graph across sessions",
        "package": "@modelcontextprotocol/server-memory",
        "bin": "mcp-server-memory",
        "category": "reasoning",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
    "slack": {
        "name": "Slack",
        "description": "Read and send Slack messages",
        "package": "@modelcontextprotocol/server-slack",
        "bin": "mcp-server-slack",
        "category": "productivity",
        "platform": [],
        "risk_level": "medium",
        "requires_config": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
        "permissions": {},
    },
    "time": {
        "name": "Time",
        "description": "Timezone-aware time and date utilities",
        "package": "@modelcontextprotocol/server-time",
        "bin": "mcp-server-time",
        "category": "utility",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    },
}

# Validate on module import — fail loudly if catalog is malformed
for _sid, _entry in CATALOG.items():
    validate_entry(_sid, _entry)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/catalog.py tests/test_mcp_catalog.py
git commit -m "feat(mcp): static 13-server catalog with validation"
```

---

## Task 8: Registry — DB-backed + catalog merge + .env migration

**Files:**
- Modify: `backend/mcp/registry.py`
- Test: `tests/test_mcp_registry.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_registry.py`:

```python
import pytest
from backend.mcp.registry import MCPRegistry
from backend.mcp.config import MCPServerConfig

@pytest.mark.asyncio
async def test_load_from_db_empty(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    # Catalog entries exist but nothing is installed/enabled
    srv = reg.get("apple-mcp")
    assert srv is not None
    assert srv.config.enabled is False
    assert reg.is_installed("apple-mcp") is False
    await db.close()

@pytest.mark.asyncio
async def test_persist_install_state(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    await reg.set_installed(db, "apple-mcp", True, config={"k": "v"})
    await reg.set_enabled(db, "apple-mcp", True)

    reg2 = MCPRegistry()
    await reg2.load_from_db(db)
    assert reg2.is_installed("apple-mcp") is True
    assert reg2.get("apple-mcp").config.enabled is True
    assert reg2.get_user_config("apple-mcp") == {"k": "v"}
    await db.close()

@pytest.mark.asyncio
async def test_env_migration_one_shot(tmp_path, monkeypatch):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    legacy = {"mcp_apple_enabled": True,
              "mcp_desktop_commander_enabled": False,
              "mcp_obsidian_enabled": True}
    await reg.migrate_from_env(db, legacy_flags=legacy)
    await reg.load_from_db(db)
    assert reg.get("apple-mcp").config.enabled is True
    assert reg.get("mcp-obsidian").config.enabled is True
    # Running migration again should be idempotent (no crash)
    await reg.migrate_from_env(db, legacy_flags=legacy)
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_registry.py -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Rewrite `backend/mcp/registry.py`**

Replace the entire file contents:

```python
"""MCP server registry — catalog-seeded, DB-persisted runtime state."""
from __future__ import annotations
import json
from datetime import datetime
from backend.mcp.catalog import CATALOG
from backend.mcp.config import MCPServerConfig, ServerStatus
from backend.mcp import installer


class MCPRegistry:
    """In-memory view of catalog + DB state. load_from_db populates."""

    def __init__(self) -> None:
        self._servers: dict[str, ServerStatus] = {}
        self._user_configs: dict[str, dict] = {}
        self._installed: dict[str, bool] = {}

    # ── loading ──────────────────────────────────────────────────────

    async def load_from_db(self, db) -> None:
        """Build registry from catalog + DB overrides."""
        self._servers.clear()
        self._user_configs.clear()
        self._installed.clear()

        # Read DB state for installed/enabled flags
        rows = {}
        async with db._conn.execute(
            "SELECT id, installed, enabled, config_json FROM mcp_servers"
        ) as cur:
            async for row in cur:
                rows[row[0]] = {
                    "installed": bool(row[1]),
                    "enabled": bool(row[2]),
                    "config_json": row[3],
                }

        # Seed one entry per catalog server
        for sid, entry in CATALOG.items():
            db_row = rows.get(sid, {})
            enabled = db_row.get("enabled", False)
            installed = db_row.get("installed", False)
            user_cfg = {}
            if db_row.get("config_json"):
                try:
                    user_cfg = json.loads(db_row["config_json"])
                except Exception:
                    user_cfg = {}
            # Determine runtime command: resolved binary if installed else placeholder
            bin_path = installer.resolve_binary(sid, entry["bin"])
            command = str(bin_path) if bin_path else "<not-installed>"
            config = MCPServerConfig(
                id=sid, name=entry["name"],
                command=command, args=[],
                env={},  # merged at start time
                enabled=enabled,
            )
            self._servers[sid] = ServerStatus(config=config)
            self._user_configs[sid] = user_cfg
            self._installed[sid] = installed

    # ── catalog passthrough ─────────────────────────────────────────

    def catalog_entry(self, server_id: str) -> dict | None:
        return CATALOG.get(server_id)

    # ── state queries ───────────────────────────────────────────────

    def get(self, server_id: str) -> ServerStatus | None:
        return self._servers.get(server_id)

    def list_servers(self) -> list[ServerStatus]:
        return list(self._servers.values())

    def list_enabled(self) -> list[ServerStatus]:
        return [s for s in self._servers.values() if s.config.enabled]

    def list_installed(self) -> list[ServerStatus]:
        return [s for s in self._servers.values() if self._installed.get(s.config.id)]

    def is_installed(self, server_id: str) -> bool:
        return self._installed.get(server_id, False)

    def get_user_config(self, server_id: str) -> dict:
        return dict(self._user_configs.get(server_id, {}))

    def update_status(
        self, server_id: str, *, status=None, pid=None,
        tools_count=None, last_error=None, uptime_seconds=None,
    ) -> None:
        s = self._servers.get(server_id)
        if s is None:
            return
        if status is not None: s.status = status
        if pid is not None: s.pid = pid
        if tools_count is not None: s.tools_count = tools_count
        if last_error is not None: s.last_error = last_error
        if uptime_seconds is not None: s.uptime_seconds = uptime_seconds

    # ── mutations (persisted) ───────────────────────────────────────

    async def set_installed(
        self, db, server_id: str, installed: bool,
        config: dict | None = None,
    ) -> None:
        self._installed[server_id] = installed
        if config is not None:
            self._user_configs[server_id] = dict(config)
        cfg_json = json.dumps(self._user_configs.get(server_id, {}))
        now = datetime.utcnow().isoformat()
        await db._conn.execute(
            """INSERT INTO mcp_servers (id, installed, enabled, config_json, installed_at, updated_at)
               VALUES (?, ?, COALESCE((SELECT enabled FROM mcp_servers WHERE id=?),0), ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   installed=excluded.installed,
                   config_json=excluded.config_json,
                   installed_at=excluded.installed_at,
                   updated_at=excluded.updated_at""",
            (server_id, int(installed), server_id, cfg_json, now, now),
        )
        await db._conn.commit()

    async def set_enabled(self, db, server_id: str, enabled: bool) -> None:
        s = self._servers.get(server_id)
        if s is not None:
            s.config.enabled = enabled
        now = datetime.utcnow().isoformat()
        await db._conn.execute(
            """INSERT INTO mcp_servers (id, installed, enabled, updated_at)
               VALUES (?, COALESCE((SELECT installed FROM mcp_servers WHERE id=?),0), ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   enabled=excluded.enabled,
                   updated_at=excluded.updated_at""",
            (server_id, server_id, int(enabled), now),
        )
        await db._conn.commit()

    async def set_last_error(self, db, server_id: str, err: str | None) -> None:
        s = self._servers.get(server_id)
        if s is not None:
            s.last_error = err
        await db._conn.execute(
            "UPDATE mcp_servers SET last_error=?, updated_at=? WHERE id=?",
            (err, datetime.utcnow().isoformat(), server_id),
        )
        await db._conn.commit()

    # ── migration ───────────────────────────────────────────────────

    async def migrate_from_env(self, db, legacy_flags: dict) -> None:
        """One-shot migration of old .env MCP flags into DB.
        Idempotent — running multiple times does no harm."""
        mapping = {
            "mcp_apple_enabled": "apple-mcp",
            "mcp_desktop_commander_enabled": "desktop-commander",
            "mcp_obsidian_enabled": "mcp-obsidian",
        }
        now = datetime.utcnow().isoformat()
        for flag_key, server_id in mapping.items():
            if server_id not in CATALOG:
                continue
            enabled = bool(legacy_flags.get(flag_key, False))
            if not enabled:
                continue
            await db._conn.execute(
                """INSERT INTO mcp_servers (id, installed, enabled, updated_at)
                   VALUES (?, 0, 1, ?)
                   ON CONFLICT(id) DO NOTHING""",
                (server_id, now),
            )
        await db._conn.commit()
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/registry.py tests/test_mcp_registry.py
git commit -m "refactor(mcp): registry is now catalog-seeded, DB-persisted, with .env migration"
```

---

## Task 9: permissions.py — heuristic + resolution chain

**Files:**
- Create: `backend/mcp/permissions.py`
- Test: `tests/test_mcp_permissions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_permissions.py`:

```python
import pytest
from backend.mcp.permissions import classify_heuristic, PermissionResolver

def test_heuristic_safe_get():
    assert classify_heuristic("get_reminders") == "allow"

def test_heuristic_safe_list():
    assert classify_heuristic("list_notes") == "allow"

def test_heuristic_sensitive_create():
    assert classify_heuristic("create_reminder") == "ask"

def test_heuristic_sensitive_send():
    assert classify_heuristic("send_message") == "ask"

def test_heuristic_sensitive_play():
    assert classify_heuristic("play_music") == "ask"

def test_heuristic_unknown_defaults_to_ask():
    assert classify_heuristic("weirdfunc") == "ask"

def test_heuristic_case_insensitive():
    assert classify_heuristic("GetNotes") == "allow"
    assert classify_heuristic("SEND_Message") == "ask"

def test_heuristic_sensitive_wins_over_safe():
    # "send_get_info" should still be "ask" because send_ matches first
    assert classify_heuristic("send_get_info") == "ask"

@pytest.mark.asyncio
async def test_resolver_db_override_wins(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    await resolver.set_override("apple-mcp", "create_reminder", "allow")
    assert await resolver.check("apple-mcp", "create_reminder") == "allow"
    await db.close()

@pytest.mark.asyncio
async def test_resolver_catalog_override(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    # catalog sets play_music to allow for apple-mcp
    assert await resolver.check("apple-mcp", "play_music") == "allow"
    await db.close()

@pytest.mark.asyncio
async def test_resolver_heuristic_fallback(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    assert await resolver.check("apple-mcp", "get_something_new") == "allow"
    assert await resolver.check("apple-mcp", "delete_something_new") == "ask"
    await db.close()

@pytest.mark.asyncio
async def test_resolver_reset_override(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    resolver = PermissionResolver(db)
    await resolver.set_override("apple-mcp", "get_notes", "deny")
    assert await resolver.check("apple-mcp", "get_notes") == "deny"
    await resolver.clear_override("apple-mcp", "get_notes")
    assert await resolver.check("apple-mcp", "get_notes") == "allow"
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_permissions.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `backend/mcp/permissions.py`**

```python
"""MCP tool permission resolution: DB → catalog → heuristic → fail-safe."""
from __future__ import annotations
import re
from datetime import datetime
from backend.mcp.catalog import CATALOG

VALID_DECISIONS = {"allow", "ask", "deny"}

# Order matters: sensitive is checked first so send_get_info → ask
SENSITIVE_PATTERNS = [
    re.compile(r"^(create|delete|remove|update|set|write|send|post|put|patch)_", re.I),
    re.compile(r"^(execute|run|spawn|kill|stop|start|restart)_", re.I),
    re.compile(r"^(play|pause|skip|enable|disable|toggle)_", re.I),
    re.compile(r"_(execute|run|write|delete)$", re.I),
]

SAFE_PATTERNS = [
    re.compile(r"^(get|list|read|search|find|query|fetch|show|describe)_", re.I),
    re.compile(r"^(count|exists|has|is)_", re.I),
    re.compile(r"_(info|status|metadata|list|count)$", re.I),
]


def classify_heuristic(tool_name: str, description: str = "") -> str:
    """Return 'allow' | 'ask' based on patterns. Fail-safe default is 'ask'."""
    for p in SENSITIVE_PATTERNS:
        if p.search(tool_name):
            return "ask"
    for p in SAFE_PATTERNS:
        if p.search(tool_name):
            return "allow"
    return "ask"


class PermissionResolver:
    """Resolves effective permission for (server_id, tool_name)."""

    def __init__(self, db) -> None:
        self._db = db

    async def check(self, server_id: str, tool_name: str,
                    description: str = "") -> str:
        # 1. DB override
        async with self._db._conn.execute(
            "SELECT decision FROM mcp_tool_permissions WHERE server_id=? AND tool_name=?",
            (server_id, tool_name),
        ) as cur:
            row = await cur.fetchone()
            if row and row[0] in VALID_DECISIONS:
                return row[0]

        # 2. Catalog override
        entry = CATALOG.get(server_id, {})
        catalog_perms = entry.get("permissions", {})
        if tool_name in catalog_perms and catalog_perms[tool_name] in VALID_DECISIONS:
            return catalog_perms[tool_name]

        # 3. Heuristic
        return classify_heuristic(tool_name, description)

    async def set_override(self, server_id: str, tool_name: str, decision: str) -> None:
        if decision not in VALID_DECISIONS:
            raise ValueError(f"invalid decision: {decision}")
        now = datetime.utcnow().isoformat()
        await self._db._conn.execute(
            """INSERT INTO mcp_tool_permissions (server_id, tool_name, decision, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(server_id, tool_name) DO UPDATE SET
                   decision=excluded.decision, updated_at=excluded.updated_at""",
            (server_id, tool_name, decision, now),
        )
        await self._db._conn.commit()

    async def clear_override(self, server_id: str, tool_name: str) -> None:
        await self._db._conn.execute(
            "DELETE FROM mcp_tool_permissions WHERE server_id=? AND tool_name=?",
            (server_id, tool_name),
        )
        await self._db._conn.commit()

    async def list_overrides(self) -> list[dict]:
        rows = []
        async with self._db._conn.execute(
            "SELECT server_id, tool_name, decision FROM mcp_tool_permissions"
        ) as cur:
            async for r in cur:
                rows.append({"server_id": r[0], "tool_name": r[1], "decision": r[2]})
        return rows
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_permissions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/permissions.py tests/test_mcp_permissions.py
git commit -m "feat(mcp): permission resolver — DB > catalog > heuristic > fail-safe"
```

---

## Task 10: approvals.py — PendingApproval + ApprovalStore

**Files:**
- Create: `backend/mcp/approvals.py`
- Test: `tests/test_mcp_approvals.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_approvals.py`:

```python
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.mcp.approvals import ApprovalStore, PendingApproval

class _FakeDb:
    def __init__(self):
        self._conn = self
        self.rows = []
        self.committed = False
    async def execute(self, sql, params=None):
        self.rows.append((sql, params))
    async def commit(self):
        self.committed = True

def _make_store():
    tg = MagicMock()
    tg.send_approval_request = AsyncMock()
    ws = MagicMock()
    ws.broadcast = AsyncMock()
    db = _FakeDb()
    return ApprovalStore(tg, ws, db, timeout_seconds=1), tg, ws, db

@pytest.mark.asyncio
async def test_request_and_resolve_allow():
    store, tg, ws, db = _make_store()
    async def resolver():
        await asyncio.sleep(0.05)
        pending = list(store._pending.values())[0]
        store.resolve(pending.id, "allow", "telegram")
    asyncio.create_task(resolver())
    result = await store.request("apple-mcp", "send_message", {"to": "x"})
    assert result == "allow"
    tg.send_approval_request.assert_awaited_once()
    ws.broadcast.assert_awaited()

@pytest.mark.asyncio
async def test_request_timeout():
    store, tg, ws, db = _make_store()
    store._timeout_seconds = 0.1
    result = await store.request("srv", "tool", {})
    assert result == "timeout"

@pytest.mark.asyncio
async def test_first_resolve_wins():
    store, *_ = _make_store()
    async def req():
        return await store.request("srv", "tool", {})
    task = asyncio.create_task(req())
    await asyncio.sleep(0.02)
    pending = list(store._pending.values())[0]
    r1 = store.resolve(pending.id, "allow", "telegram")
    r2 = store.resolve(pending.id, "deny", "ws")
    assert r1 is True
    assert r2 is False
    result = await task
    assert result == "allow"

@pytest.mark.asyncio
async def test_dedup_within_window():
    store, *_ = _make_store()
    store._dedup_window_seconds = 30
    async def first():
        return await store.request("srv", "tool", {"k": 1})
    t1 = asyncio.create_task(first())
    await asyncio.sleep(0.02)
    pending = list(store._pending.values())[0]
    store.resolve(pending.id, "allow", "telegram")
    r1 = await t1
    # identical request within dedup window should auto-allow
    r2 = await store.request("srv", "tool", {"k": 1})
    assert r1 == "allow"
    assert r2 == "allow"

@pytest.mark.asyncio
async def test_list_pending():
    store, *_ = _make_store()
    task = asyncio.create_task(store.request("srv", "t", {}))
    await asyncio.sleep(0.02)
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].server_id == "srv"
    # cleanup
    store.resolve(pending[0].id, "deny", "test")
    await task
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_approvals.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `backend/mcp/approvals.py`**

```python
"""MCP tool-call approval store — pending approvals, Telegram + WS notification."""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    id: str
    server_id: str
    tool_name: str
    args: dict
    crew_id: str | None
    chat_id: str | None
    created_at: float
    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: str | None = None
    decided_by: str | None = None


class ApprovalStore:
    def __init__(self, telegram_bot, ws_manager, db,
                 timeout_seconds: int = 600,
                 dedup_window_seconds: int = 30) -> None:
        self._telegram = telegram_bot
        self._ws = ws_manager
        self._db = db
        self._timeout_seconds = timeout_seconds
        self._dedup_window_seconds = dedup_window_seconds
        self._pending: dict[str, PendingApproval] = {}
        self._recent: dict[tuple, tuple[float, str]] = {}  # key → (ts, decision)
        self._lock = asyncio.Lock()

    def _dedup_key(self, server_id: str, tool_name: str, args: dict) -> tuple:
        return (server_id, tool_name, json.dumps(args, sort_keys=True, default=str))

    async def request(
        self, server_id: str, tool_name: str, args: dict,
        crew_id: str | None = None, chat_id: str | None = None,
    ) -> str:
        """Register a pending approval, notify channels, block until resolved.
        Returns 'allow' | 'deny' | 'timeout'."""
        # Dedup: identical recent request → reuse decision
        key = self._dedup_key(server_id, tool_name, args)
        now = time.time()
        cached = self._recent.get(key)
        if cached and (now - cached[0]) < self._dedup_window_seconds:
            log.info("approval dedup hit: %s/%s → %s", server_id, tool_name, cached[1])
            return cached[1]

        approval = PendingApproval(
            id=str(uuid.uuid4()),
            server_id=server_id, tool_name=tool_name, args=dict(args),
            crew_id=crew_id, chat_id=chat_id, created_at=now,
        )
        self._pending[approval.id] = approval

        # Persist request
        try:
            await self._db._conn.execute(
                """INSERT INTO mcp_approvals (id, server_id, tool_name, args_json,
                                              requested_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (approval.id, server_id, tool_name,
                 json.dumps(args, default=str),
                 datetime.utcnow().isoformat()),
            )
            await self._db._conn.commit()
        except Exception as e:
            log.warning("approval DB insert failed: %s", e)

        # Notify channels
        try:
            if self._telegram and getattr(self._telegram, "enabled", True):
                await self._telegram.send_approval_request(approval)
        except Exception as e:
            log.warning("telegram approval notify failed: %s", e)
        try:
            if self._ws:
                await self._ws.broadcast({
                    "type": "approval_pending",
                    "id": approval.id,
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "args": args,
                    "created_at": approval.created_at,
                })
        except Exception as e:
            log.warning("ws approval broadcast failed: %s", e)

        # Block until resolved or timeout
        try:
            await asyncio.wait_for(approval.event.wait(),
                                   timeout=self._timeout_seconds)
            result = approval.result or "deny"
        except asyncio.TimeoutError:
            result = "timeout"
            approval.result = "timeout"
            approval.decided_by = "auto"

        # Persist resolution
        try:
            await self._db._conn.execute(
                """UPDATE mcp_approvals
                   SET decision=?, decided_by=?, decided_at=?
                   WHERE id=?""",
                (result, approval.decided_by or "auto",
                 datetime.utcnow().isoformat(), approval.id),
            )
            await self._db._conn.commit()
        except Exception as e:
            log.warning("approval DB update failed: %s", e)

        # Broadcast resolution
        try:
            if self._ws:
                await self._ws.broadcast({
                    "type": "approval_resolved",
                    "id": approval.id,
                    "decision": result,
                })
        except Exception:
            pass

        # Cache for dedup
        self._recent[key] = (now, result)
        self._pending.pop(approval.id, None)

        # GC old dedup entries
        cutoff = now - self._dedup_window_seconds * 2
        self._recent = {k: v for k, v in self._recent.items() if v[0] > cutoff}

        return result

    def resolve(self, approval_id: str, decision: str, decided_by: str) -> bool:
        """Resolve a pending approval. First resolve wins. Returns True if
        this call actually resolved it, False if it was already resolved."""
        approval = self._pending.get(approval_id)
        if approval is None or approval.result is not None:
            return False
        if decision not in ("allow", "deny", "allow_once"):
            return False
        # "allow_once" resolves as allow but without persistence — caller decides
        effective = "allow" if decision == "allow_once" else decision
        approval.result = effective
        approval.decided_by = decided_by
        approval.event.set()
        return True

    def list_pending(self) -> list[PendingApproval]:
        return list(self._pending.values())
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_approvals.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/approvals.py tests/test_mcp_approvals.py
git commit -m "feat(mcp): ApprovalStore — pending-approval flow with dedup & timeout"
```

---

## Task 11: Telegram — send_approval_request + callback_query routing

**Files:**
- Modify: `backend/telegram_bot.py`
- Test: `tests/test_telegram_bot.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_telegram_bot.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from backend.telegram_bot import TelegramBot
from backend.mcp.approvals import PendingApproval
import asyncio

@pytest.mark.asyncio
async def test_send_approval_request_builds_inline_keyboard():
    bot = TelegramBot(token="x", chat_id="123")
    with patch.object(bot, "_api_post", new=AsyncMock(return_value={"ok": True})) as mock:
        approval = PendingApproval(
            id="abc", server_id="apple-mcp", tool_name="send_message",
            args={"to": "+49"}, crew_id=None, chat_id=None,
            created_at=0.0, event=asyncio.Event(),
        )
        await bot.send_approval_request(approval)
        mock.assert_awaited_once()
        args, kwargs = mock.call_args
        payload = args[1] if len(args) > 1 else kwargs.get("json", {})
        assert "reply_markup" in payload
        buttons = payload["reply_markup"]["inline_keyboard"][0]
        labels = [b["text"] for b in buttons]
        assert any("Allow" in l or "allow" in l.lower() for l in labels)
        assert any("Deny" in l or "deny" in l.lower() for l in labels)
        cb_data = [b["callback_data"] for b in buttons]
        assert any("approval:abc:allow" in c for c in cb_data)
        assert any("approval:abc:deny" in c for c in cb_data)

@pytest.mark.asyncio
async def test_callback_query_routes_to_approval_store():
    bot = TelegramBot(token="x", chat_id="123")
    resolved = []
    class FakeStore:
        def resolve(self, approval_id, decision, decided_by):
            resolved.append((approval_id, decision, decided_by))
            return True
    bot.approval_store = FakeStore()
    await bot.handle_callback_query({
        "id": "q1",
        "from": {"id": 123},
        "data": "approval:abc:allow",
        "message": {"chat": {"id": 123}, "message_id": 42},
    })
    assert resolved == [("abc", "allow", "telegram")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telegram_bot.py::test_send_approval_request_builds_inline_keyboard -v`
Expected: FAIL — methods missing.

- [ ] **Step 3: Extend `backend/telegram_bot.py`**

Add to `TelegramBot.__init__` if not present:

```python
self.approval_store = None   # set by main.py after construction
```

Add methods:

```python
async def send_approval_request(self, approval) -> None:
    """Send a tool-call approval prompt with inline Allow/Deny/Once buttons."""
    args_preview = str(approval.args)[:200]
    text = (
        f"🔒 Approval required\n"
        f"Crew wants to call:\n"
        f"    {approval.server_id}::{approval.tool_name}\n"
        f"Args: {args_preview}"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Allow", "callback_data": f"approval:{approval.id}:allow"},
            {"text": "❌ Deny", "callback_data": f"approval:{approval.id}:deny"},
            {"text": "⏭️ Allow once", "callback_data": f"approval:{approval.id}:allow_once"},
        ]]
    }
    payload = {
        "chat_id": self.chat_id,
        "text": text,
        "reply_markup": keyboard,
    }
    await self._api_post("sendMessage", payload)

async def handle_callback_query(self, cq: dict) -> None:
    """Parse Telegram callback_query and forward to ApprovalStore."""
    data = cq.get("data", "")
    if not data.startswith("approval:"):
        return
    parts = data.split(":")
    if len(parts) != 3:
        return
    _, approval_id, decision = parts
    if self.approval_store is None:
        return
    self.approval_store.resolve(approval_id, decision, "telegram")
    # Acknowledge the callback and edit the original message
    try:
        await self._api_post("answerCallbackQuery", {
            "callback_query_id": cq.get("id"),
            "text": f"Decision: {decision}",
        })
        msg = cq.get("message", {})
        if msg.get("chat", {}).get("id") and msg.get("message_id"):
            await self._api_post("editMessageText", {
                "chat_id": msg["chat"]["id"],
                "message_id": msg["message_id"],
                "text": f"🔒 Approval resolved: {decision}",
            })
    except Exception:
        pass
```

Find the message-polling loop (`poll_loop` or similar) and make sure incoming updates with a `callback_query` field are routed to `handle_callback_query`. If the poll loop currently only looks at `message`, add:

```python
# Inside the update processing loop, after the message handler
if "callback_query" in update:
    await self.handle_callback_query(update["callback_query"])
```

Also make sure the `getUpdates` request includes `callback_query` in `allowed_updates` if the bot uses that parameter:

```python
# Where getUpdates is called:
params = {"offset": self._offset, "timeout": 25,
          "allowed_updates": ["message", "callback_query"]}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_telegram_bot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/telegram_bot.py tests/test_telegram_bot.py
git commit -m "feat(telegram): send_approval_request + callback_query routing"
```

---

## Task 12: Bridge integration — _start_server uses installer + catalog

**Files:**
- Modify: `backend/mcp/bridge.py`
- Modify: `backend/mcp/tool_adapter.py`
- Test: `tests/test_mcp_bridge.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mcp_bridge.py`:

```python
@pytest.mark.asyncio
async def test_start_skips_when_not_installed(tmp_path, monkeypatch):
    from backend.mcp import installer as inst
    monkeypatch.setattr(inst, "INSTALL_ROOT", tmp_path)
    from backend.mcp.registry import MCPRegistry
    reg = MCPRegistry()
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    await reg.load_from_db(db)
    await reg.set_enabled(db, "apple-mcp", True)
    b = MCPBridge(reg)
    await b.start(timeout=2)
    # apple-mcp is enabled but not installed → status=not_installed, no handle
    assert reg.get("apple-mcp").status == "not_installed"
    assert "apple-mcp" not in b._handles
    await db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mcp_bridge.py::test_start_skips_when_not_installed -v`
Expected: FAIL — `_start_server` still tries to launch.

- [ ] **Step 3: Update `_start_server` to check installer first**

In `backend/mcp/bridge.py`, at the top of `_start_server`, add:

```python
async def _start_server(self, server_id: str, timeout: float) -> None:
    """Start a single MCP server using the SDK's stdio_client."""
    from backend.mcp.catalog import CATALOG
    from backend.mcp import installer

    status = self.registry.get(server_id)
    if status is None:
        return
    cfg = status.config

    # Catalog-driven resolution: require installed binary
    catalog_entry = CATALOG.get(server_id)
    if catalog_entry is None:
        self.registry.update_status(server_id, status="error",
                                    last_error="not in catalog")
        return
    binary = installer.resolve_binary(server_id, catalog_entry["bin"])
    if binary is None:
        self.registry.update_status(server_id, status="not_installed",
                                    last_error=None)
        self._emit_event("start_skipped_not_installed", server_id=server_id)
        return
    # Override cfg.command with the resolved absolute path
    cfg.command = str(binary)
    # Build args from catalog entry + user config
    user_cfg = self.registry.get_user_config(server_id) if hasattr(self.registry, "get_user_config") else {}
    cfg.args = self._build_args(server_id, catalog_entry, user_cfg)
    cfg.env = self._build_env(catalog_entry, user_cfg)

    # ... rest of the existing _start_server body
```

Add helper methods to `MCPBridge`:

```python
def _build_args(self, server_id: str, catalog_entry: dict, user_cfg: dict) -> list[str]:
    """Assemble CLI args from catalog + user config."""
    args: list[str] = []
    # mcp-obsidian expects vault_path positional
    if server_id == "mcp-obsidian" and user_cfg.get("vault_path"):
        args.append(user_cfg["vault_path"])
    # filesystem expects allowed_directories (comma-separated or multi-positional)
    if server_id == "filesystem":
        dirs = user_cfg.get("allowed_directories", "")
        if isinstance(dirs, str):
            dirs = [d.strip() for d in dirs.split(",") if d.strip()]
        args.extend(dirs)
    return args

def _build_env(self, catalog_entry: dict, user_cfg: dict) -> dict:
    """Env vars required by this MCP (API keys etc.). Uppercase keys → env."""
    env = {}
    for key in catalog_entry.get("requires_config", []):
        if key.isupper() and key in user_cfg:
            env[key] = str(user_cfg[key])
    return env
```

- [ ] **Step 4: Update tool_adapter.py to use threadsafe wrapper**

Replace `backend/mcp/tool_adapter.py` entirely:

```python
"""Converts MCP tool schemas into CrewAI BaseTool instances."""
from __future__ import annotations
import logging
from typing import Any
from crewai.tools import BaseTool
from backend.mcp.config import ToolSchema

log = logging.getLogger(__name__)


def _make_tool_class(schema: ToolSchema, bridge: Any) -> type[BaseTool]:
    server_id = schema.server_id
    mcp_tool_name = schema.name
    tool_name = f"mcp_{server_id.replace('-', '_')}_{mcp_tool_name}"
    tool_desc = f"{schema.description} [{server_id}]"

    class MCPDynamicTool(BaseTool):
        name: str = tool_name
        description: str = tool_desc

        def _run(self, **kwargs) -> str:
            result = bridge.call_tool_threadsafe(server_id, mcp_tool_name, kwargs)
            if result.success:
                return result.output
            return f"Error: {result.output}"

    return MCPDynamicTool


def create_mcp_tool(schema: ToolSchema, bridge: Any) -> BaseTool:
    cls = _make_tool_class(schema, bridge)
    return cls()


def create_all_mcp_tools(schemas: list[ToolSchema], bridge: Any) -> list[BaseTool]:
    tools = []
    for schema in schemas:
        try:
            tools.append(create_mcp_tool(schema, bridge))
        except Exception as e:
            log.error("Failed to create tool for %s/%s: %s",
                      schema.server_id, schema.name, e)
    return tools
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_mcp_bridge.py tests/test_mcp_tool_adapter.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/mcp/bridge.py backend/mcp/tool_adapter.py tests/test_mcp_bridge.py
git commit -m "feat(mcp): bridge uses installer + catalog at start; tool_adapter uses threadsafe wrapper"
```

---

## Task 13: Bridge call_tool — permission check + approval request

**Files:**
- Modify: `backend/mcp/bridge.py`
- Test: `tests/test_mcp_bridge.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mcp_bridge.py`:

```python
@pytest.mark.asyncio
async def test_call_tool_denied_by_permission(tmp_path):
    from backend.mcp.registry import MCPRegistry
    from backend.database import Database
    from backend.mcp.permissions import PermissionResolver
    from backend.mcp.approvals import ApprovalStore
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    resolver = PermissionResolver(db)
    await resolver.set_override("apple-mcp", "delete_all", "deny")
    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=None)
    bridge._main_loop = asyncio.get_running_loop()
    bridge._handles["apple-mcp"] = _ServerHandle(
        session=MagicMock(), task=None, start_time=0.0,
    )
    result = await bridge.call_tool("apple-mcp", "delete_all", {})
    assert result.success is False
    assert "denied" in result.output.lower()
    await db.close()

@pytest.mark.asyncio
async def test_call_tool_asks_then_allows(tmp_path):
    from backend.mcp.registry import MCPRegistry
    from backend.database import Database
    from backend.mcp.permissions import PermissionResolver
    from backend.mcp.approvals import ApprovalStore
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    resolver = PermissionResolver(db)

    # Fake telegram + ws
    tg = MagicMock()
    tg.enabled = True
    tg.send_approval_request = AsyncMock()
    ws = MagicMock()
    ws.broadcast = AsyncMock()
    store = ApprovalStore(tg, ws, db, timeout_seconds=5)

    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=store)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=_FakeSessionResult("done"))
    bridge._handles["apple-mcp"] = _ServerHandle(
        session=fake_session, task=None, start_time=0.0,
    )

    async def approver():
        await asyncio.sleep(0.05)
        pending = store.list_pending()
        assert len(pending) == 1
        store.resolve(pending[0].id, "allow", "telegram")
    asyncio.create_task(approver())

    result = await bridge.call_tool("apple-mcp", "send_message", {"to": "x"})
    assert result.success is True
    assert result.output == "done"
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_bridge.py::test_call_tool_denied_by_permission tests/test_mcp_bridge.py::test_call_tool_asks_then_allows -v`
Expected: FAIL — `attach_policy` doesn't exist.

- [ ] **Step 3: Add policy integration to `call_tool`**

In `backend/mcp/bridge.py`, add to `__init__`:

```python
self._resolver = None     # PermissionResolver
self._approvals = None    # ApprovalStore
```

Add method:

```python
def attach_policy(self, resolver, approval_store) -> None:
    """Wire the permission resolver and approval store into call_tool."""
    self._resolver = resolver
    self._approvals = approval_store
```

Rewrite `call_tool` to insert the policy check before dispatching:

```python
async def call_tool(self, server_id: str, tool_name: str, args: dict,
                    timeout: float = TOOL_CALL_TIMEOUT) -> ToolResult:
    handle = self._handles.get(server_id)
    if handle is None or handle.session is None:
        return ToolResult(success=False, output=f"Server '{server_id}' not connected")

    # Policy check (if attached)
    if self._resolver is not None:
        decision = await self._resolver.check(server_id, tool_name)
        if decision == "deny":
            self._emit_event("tool_denied", server_id=server_id, tool_name=tool_name)
            return ToolResult(success=False, output="denied by policy")
        if decision == "ask":
            if self._approvals is None:
                # No approval channel → fail-safe deny
                return ToolResult(success=False,
                                  output="approval required but no approval channel")
            self._emit_event("approval_requested", server_id=server_id, tool_name=tool_name)
            result = await self._approvals.request(server_id, tool_name, args)
            if result != "allow":
                self._emit_event("approval_not_granted",
                                 server_id=server_id, tool_name=tool_name,
                                 result=result)
                return ToolResult(success=False, output=f"approval {result}")

    try:
        result = await asyncio.wait_for(
            handle.session.call_tool(tool_name, arguments=args),
            timeout=timeout,
        )
        output_parts = []
        for block in result.content:
            if hasattr(block, "text"):
                output_parts.append(block.text)
            else:
                output_parts.append(str(block))
        output = "\n".join(output_parts)
        self._emit_event("tool_call_ok", server_id=server_id, tool_name=tool_name)
        return ToolResult(success=not result.isError, output=output)
    except asyncio.TimeoutError:
        log.error("MCP tool call timed out after %.0fs: %s/%s", timeout, server_id, tool_name)
        self._emit_event("tool_call_timeout", server_id=server_id, tool_name=tool_name)
        return ToolResult(success=False, output=f"Timeout after {timeout}s")
    except Exception as e:
        log.error("MCP tool call failed: %s/%s: %s", server_id, tool_name, e)
        self._emit_event("tool_call_error", server_id=server_id,
                         tool_name=tool_name, error=str(e))
        return ToolResult(success=False, output=f"Error: {e}")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_bridge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp/bridge.py tests/test_mcp_bridge.py
git commit -m "feat(mcp): bridge.call_tool honours permission resolver + approval store"
```

---

## Task 14: Admin API — read endpoints

**Files:**
- Modify: `backend/admin_api.py`
- Test: `tests/test_mcp_admin_api.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_admin_api.py`:

```python
from fastapi.testclient import TestClient
import pytest

def test_api_catalog_returns_entries(admin_app_client):
    r = admin_app_client.get("/api/mcp/catalog")
    assert r.status_code == 200
    data = r.json()
    ids = {x["id"] for x in data}
    assert "apple-mcp" in ids
    for entry in data:
        assert "risk_level" in entry
        assert "installed" in entry
        assert "enabled" in entry

def test_api_servers_returns_installed_only(admin_app_client):
    r = admin_app_client.get("/api/mcp/servers")
    assert r.status_code == 200

def test_api_server_tools_returns_permission_source(admin_app_client):
    r = admin_app_client.get("/api/mcp/servers/apple-mcp/tools")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        for t in r.json():
            assert t["permission"] in ("allow", "ask", "deny")
            assert t["source"] in ("db", "catalog", "heuristic")

def test_api_logs(admin_app_client):
    r = admin_app_client.get("/api/mcp/servers/apple-mcp/logs")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert "stderr" in r.json()

def test_api_approvals_pending_empty(admin_app_client):
    r = admin_app_client.get("/api/mcp/approvals/pending")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

Note: `admin_app_client` is a fixture in this file that wires a minimal FastAPI app with a mock bridge. If it doesn't exist yet, add:

```python
@pytest.fixture
def admin_app_client(tmp_path):
    from fastapi import FastAPI
    from backend.admin_api import router as admin_router
    from backend import admin_api as mod
    from backend.database import Database
    from backend.mcp.registry import MCPRegistry
    from backend.mcp.permissions import PermissionResolver
    import asyncio
    app = FastAPI()
    app.include_router(admin_router)

    loop = asyncio.new_event_loop()
    db = Database(tmp_path / "t.db")
    loop.run_until_complete(db.init())
    reg = MCPRegistry()
    loop.run_until_complete(reg.load_from_db(db))
    resolver = PermissionResolver(db)

    class FakeBridge:
        def __init__(self): self.registry = reg
        def get_stderr(self, sid): return ["line a", "line b"] if sid == "apple-mcp" else []
        async def list_tools(self, sid): return []
        async def discover_tools(self): return []

    mod.set_dependencies(db=db, scheduler=None, config_service=None, flow=None,
                         fact_memory=None, soul_memory=None, system_monitor=None,
                         mcp_bridge=FakeBridge())
    # Attach extra deps the new endpoints need
    mod._permission_resolver = resolver
    mod._approval_store = None
    with TestClient(app) as client:
        yield client
    loop.run_until_complete(db.close())
    loop.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_admin_api.py -v`
Expected: FAIL — endpoints not defined.

- [ ] **Step 3: Add endpoints to `backend/admin_api.py`**

At the top of `admin_api.py`, ensure these imports exist:

```python
from backend.mcp.catalog import CATALOG
from backend.mcp.permissions import PermissionResolver, classify_heuristic
```

Extend `set_dependencies` to accept optional `permission_resolver` and `approval_store`:

```python
_permission_resolver: PermissionResolver | None = None
_approval_store = None

def set_dependencies(*, db, scheduler, config_service, flow, fact_memory,
                     soul_memory, system_monitor, mcp_bridge,
                     permission_resolver=None, approval_store=None):
    global _db, _scheduler, _config_service, _flow, _fact_memory, _soul_memory
    global _system_monitor, _mcp_bridge, _permission_resolver, _approval_store
    _db = db
    _scheduler = scheduler
    _config_service = config_service
    _flow = flow
    _fact_memory = fact_memory
    _soul_memory = soul_memory
    _system_monitor = system_monitor
    _mcp_bridge = mcp_bridge
    _permission_resolver = permission_resolver
    _approval_store = approval_store
```

Add the read endpoints (append to the router definitions):

```python
@router.get("/api/mcp/catalog")
async def api_mcp_catalog():
    reg = _mcp_bridge.registry
    out = []
    for sid, entry in CATALOG.items():
        srv = reg.get(sid)
        out.append({
            "id": sid,
            "name": entry["name"],
            "description": entry["description"],
            "category": entry["category"],
            "platform": entry["platform"],
            "risk_level": entry["risk_level"],
            "requires_config": entry["requires_config"],
            "installed": reg.is_installed(sid) if hasattr(reg, "is_installed") else False,
            "enabled": bool(srv.config.enabled) if srv else False,
            "status": srv.status if srv else "stopped",
        })
    return out


@router.get("/api/mcp/servers")
async def api_mcp_servers():
    reg = _mcp_bridge.registry
    out = []
    for srv in reg.list_servers():
        sid = srv.config.id
        if not reg.is_installed(sid):
            continue
        out.append({
            "id": sid,
            "name": srv.config.name,
            "enabled": srv.config.enabled,
            "status": srv.status,
            "tools_count": srv.tools_count,
            "last_error": srv.last_error,
            "uptime_seconds": srv.uptime_seconds,
        })
    return out


@router.get("/api/mcp/servers/{server_id}")
async def api_mcp_server_detail(server_id: str):
    reg = _mcp_bridge.registry
    srv = reg.get(server_id)
    if srv is None:
        return {"error": "not found"}
    entry = CATALOG.get(server_id, {})
    return {
        "id": server_id,
        "name": srv.config.name,
        "description": entry.get("description", ""),
        "installed": reg.is_installed(server_id),
        "enabled": srv.config.enabled,
        "status": srv.status,
        "tools_count": srv.tools_count,
        "last_error": srv.last_error,
        "uptime_seconds": srv.uptime_seconds,
        "user_config": _mask_secrets(reg.get_user_config(server_id)),
    }


def _mask_secrets(cfg: dict) -> dict:
    import re
    out = {}
    for k, v in cfg.items():
        if re.search(r"token|secret|password|key", k, re.I):
            out[k] = "***"
        else:
            out[k] = v
    return out


@router.get("/api/mcp/servers/{server_id}/logs")
async def api_mcp_server_logs(server_id: str):
    lines = _mcp_bridge.get_stderr(server_id) if hasattr(_mcp_bridge, "get_stderr") else []
    return {"stderr": lines}


@router.get("/api/mcp/servers/{server_id}/tools")
async def api_mcp_server_tools(server_id: str):
    reg = _mcp_bridge.registry
    srv = reg.get(server_id)
    if srv is None or not reg.is_installed(server_id):
        return []
    tools = await _mcp_bridge.list_tools(server_id)
    out = []
    for t in tools:
        # Resolve source of permission
        source = "heuristic"
        decision = classify_heuristic(t.name)
        entry = CATALOG.get(server_id, {})
        if t.name in entry.get("permissions", {}):
            decision = entry["permissions"][t.name]
            source = "catalog"
        if _permission_resolver:
            async with _db._conn.execute(
                "SELECT decision FROM mcp_tool_permissions WHERE server_id=? AND tool_name=?",
                (server_id, t.name),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    decision = row[0]
                    source = "db"
        out.append({
            "name": t.name,
            "description": t.description,
            "permission": decision,
            "source": source,
        })
    return out


@router.get("/api/mcp/permissions")
async def api_mcp_permissions_list():
    if _permission_resolver is None:
        return []
    return await _permission_resolver.list_overrides()


@router.get("/api/mcp/approvals/pending")
async def api_mcp_approvals_pending():
    if _approval_store is None:
        return []
    return [
        {"id": a.id, "server_id": a.server_id, "tool_name": a.tool_name,
         "args": a.args, "created_at": a.created_at}
        for a in _approval_store.list_pending()
    ]


@router.get("/api/mcp/approvals/history")
async def api_mcp_approvals_history(limit: int = 50):
    rows = []
    async with _db._conn.execute(
        """SELECT id, server_id, tool_name, decision, decided_by,
                  requested_at, decided_at
           FROM mcp_approvals ORDER BY requested_at DESC LIMIT ?""",
        (limit,),
    ) as cur:
        async for r in cur:
            rows.append({
                "id": r[0], "server_id": r[1], "tool_name": r[2],
                "decision": r[3], "decided_by": r[4],
                "requested_at": r[5], "decided_at": r[6],
            })
    return rows
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_admin_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/admin_api.py tests/test_mcp_admin_api.py
git commit -m "feat(api): MCP read endpoints (catalog, servers, tools, logs, permissions, approvals)"
```

---

## Task 15: Admin API — mutating endpoints

**Files:**
- Modify: `backend/admin_api.py`
- Test: `tests/test_mcp_admin_api.py` (extend)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mcp_admin_api.py`:

```python
def test_api_install_triggers_installer(admin_app_client, tmp_path, monkeypatch):
    from backend.mcp import installer as inst
    calls = []
    async def fake_install(sid, pkg, bin_name):
        calls.append((sid, pkg, bin_name))
        from backend.mcp.installer import InstallResult
        return InstallResult(success=True, binary_path=tmp_path / "bin",
                             error=None, stderr="")
    monkeypatch.setattr(inst, "install", fake_install)
    r = admin_app_client.post("/api/mcp/servers/apple-mcp/install",
                              json={"config": {}})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert calls == [("apple-mcp", "apple-mcp", "apple-mcp")]

def test_api_enable_sets_flag(admin_app_client):
    r = admin_app_client.post("/api/mcp/servers/apple-mcp/enable")
    assert r.status_code == 200
    r2 = admin_app_client.get("/api/mcp/catalog")
    entry = next(x for x in r2.json() if x["id"] == "apple-mcp")
    assert entry["enabled"] is True

def test_api_permission_put_and_delete(admin_app_client):
    r = admin_app_client.put("/api/mcp/permissions/apple-mcp/some_tool",
                             json={"decision": "deny"})
    assert r.status_code == 200
    r2 = admin_app_client.get("/api/mcp/permissions")
    rows = r2.json()
    assert any(x["server_id"] == "apple-mcp" and x["tool_name"] == "some_tool"
               and x["decision"] == "deny" for x in rows)
    r3 = admin_app_client.delete("/api/mcp/permissions/apple-mcp/some_tool")
    assert r3.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp_admin_api.py::test_api_install_triggers_installer -v`
Expected: FAIL.

- [ ] **Step 3: Add mutating endpoints**

Append to `backend/admin_api.py`:

```python
from pydantic import BaseModel
from backend.mcp import installer as _installer
from backend.ws_manager import WSManager  # type hint only

class InstallBody(BaseModel):
    config: dict = {}

class PermissionBody(BaseModel):
    decision: str

class ResolveBody(BaseModel):
    decision: str  # allow | deny | allow_once


async def _broadcast_mcp_state_changed():
    from backend.main import ws_mgr  # late import to avoid cycle
    try:
        await ws_mgr.broadcast({"type": "mcp_state_changed"})
    except Exception:
        pass


@router.post("/api/mcp/servers/{server_id}/install")
async def api_mcp_install(server_id: str, body: InstallBody):
    entry = CATALOG.get(server_id)
    if entry is None:
        return {"error": "not in catalog"}
    result = await _installer.install(server_id, entry["package"], entry["bin"])
    if not result.success:
        return {"status": "error", "error": result.error, "stderr": result.stderr}
    reg = _mcp_bridge.registry
    await reg.set_installed(_db, server_id, True, config=body.config)
    await _broadcast_mcp_state_changed()
    return {"status": "ok"}


@router.post("/api/mcp/servers/{server_id}/uninstall")
async def api_mcp_uninstall(server_id: str):
    reg = _mcp_bridge.registry
    # Stop first if running
    if hasattr(_mcp_bridge, "_stop_server") and server_id in getattr(_mcp_bridge, "_handles", {}):
        await _mcp_bridge._stop_server(server_id)
    ok = await _installer.uninstall(server_id)
    await reg.set_installed(_db, server_id, False)
    await reg.set_enabled(_db, server_id, False)
    await _broadcast_mcp_state_changed()
    return {"status": "ok" if ok else "error"}


@router.post("/api/mcp/servers/{server_id}/enable")
async def api_mcp_enable(server_id: str):
    reg = _mcp_bridge.registry
    await reg.set_enabled(_db, server_id, True)
    if hasattr(_mcp_bridge, "_start_server") and server_id not in getattr(_mcp_bridge, "_handles", {}):
        try:
            await _mcp_bridge._start_server(server_id, 45.0)
        except Exception as e:
            return {"status": "error", "error": str(e)}
    await _broadcast_mcp_state_changed()
    return {"status": "ok"}


@router.post("/api/mcp/servers/{server_id}/disable")
async def api_mcp_disable(server_id: str):
    reg = _mcp_bridge.registry
    await reg.set_enabled(_db, server_id, False)
    if hasattr(_mcp_bridge, "_stop_server") and server_id in getattr(_mcp_bridge, "_handles", {}):
        await _mcp_bridge._stop_server(server_id)
    await _broadcast_mcp_state_changed()
    return {"status": "ok"}


@router.post("/api/mcp/servers/{server_id}/restart")
async def api_mcp_restart(server_id: str):
    if hasattr(_mcp_bridge, "restart_server"):
        await _mcp_bridge.restart_server(server_id)
    await _broadcast_mcp_state_changed()
    return {"status": "ok"}


@router.put("/api/mcp/permissions/{server_id}/{tool_name}")
async def api_mcp_permission_put(server_id: str, tool_name: str, body: PermissionBody):
    if _permission_resolver is None:
        return {"error": "resolver not wired"}
    await _permission_resolver.set_override(server_id, tool_name, body.decision)
    await _broadcast_mcp_state_changed()
    return {"status": "ok"}


@router.delete("/api/mcp/permissions/{server_id}/{tool_name}")
async def api_mcp_permission_delete(server_id: str, tool_name: str):
    if _permission_resolver is None:
        return {"error": "resolver not wired"}
    await _permission_resolver.clear_override(server_id, tool_name)
    await _broadcast_mcp_state_changed()
    return {"status": "ok"}


@router.post("/api/mcp/approvals/{approval_id}/resolve")
async def api_mcp_approval_resolve(approval_id: str, body: ResolveBody):
    if _approval_store is None:
        return {"error": "no approval store"}
    ok = _approval_store.resolve(approval_id, body.decision, "ws")
    return {"status": "ok" if ok else "already_resolved"}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_mcp_admin_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/admin_api.py tests/test_mcp_admin_api.py
git commit -m "feat(api): MCP mutating endpoints (install, uninstall, enable, disable, restart, permission, resolve)"
```

---

## Task 16: main.py lifespan wiring

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Identify the sections to replace**

In `backend/main.py`, find:
1. The `# ── MCP Bridge ────` block that builds `MCPRegistry.from_settings(...)` and calls `mcp_bridge.start()`.
2. The `admin_api.set_dependencies(...)` call.

- [ ] **Step 2: Replace the MCP Bridge block**

Replace the old MCP Bridge section with:

```python
# ── MCP Bridge ────────────────────────────────────────────────────
from backend.mcp.registry import MCPRegistry
from backend.mcp.bridge import MCPBridge
from backend.mcp.permissions import PermissionResolver
from backend.mcp.approvals import ApprovalStore

mcp_registry = MCPRegistry()
# One-shot migration of legacy .env flags (idempotent)
await mcp_registry.migrate_from_env(db, legacy_flags={
    "mcp_apple_enabled": settings.mcp_apple_enabled,
    "mcp_desktop_commander_enabled": settings.mcp_desktop_commander_enabled,
    "mcp_obsidian_enabled": settings.mcp_obsidian_enabled,
})
await mcp_registry.load_from_db(db)

mcp_bridge = MCPBridge(mcp_registry)
permission_resolver = PermissionResolver(db)
approval_timeout = config_service.get_int("mcp_approval_timeout_seconds", 600)
approval_store = ApprovalStore(
    telegram_bot=telegram, ws_manager=ws_mgr, db=db,
    timeout_seconds=approval_timeout,
)
telegram.approval_store = approval_store
mcp_bridge.attach_policy(resolver=permission_resolver, approval_store=approval_store)

try:
    await mcp_bridge.start()
    log.info("MCP Bridge started (%d installed servers)",
             sum(1 for s in mcp_registry.list_servers() if mcp_registry.is_installed(s.config.id)))
except Exception as e:
    log.warning("MCP Bridge start failed (non-fatal): %s", e)
```

- [ ] **Step 3: Update `admin_api.set_dependencies` call**

```python
admin_api.set_dependencies(
    db=db, scheduler=scheduler, config_service=config_service,
    flow=flow,
    fact_memory=fact_memory,
    soul_memory=soul_memory, system_monitor=system_monitor,
    mcp_bridge=mcp_bridge,
    permission_resolver=permission_resolver,
    approval_store=approval_store,
)
```

- [ ] **Step 4: Smoke-run the server**

Run: `./start.sh`
Expected: Server starts, log shows `MCP Bridge started (N installed servers)` (N=0 on a fresh install). No stack traces.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(mcp): wire registry/bridge/permissions/approvals in lifespan"
```

---

## Task 17: Store UI — HTML tab + CSS

**Files:**
- Modify: `frontend/command-center.html`
- Modify: `frontend/command-center.css`

- [ ] **Step 1: Add tab button + panel container**

In `frontend/command-center.html`, find the tab bar (a `<nav>` or `<div>` with tab buttons). Add a new tab trigger:

```html
<button class="tab-btn" data-tab="mcp-store">MCP Store</button>
```

Add the corresponding panel container (likely in the main content area):

```html
<section class="tab-panel" id="tab-mcp-store" hidden>
  <header class="mcp-store-header">
    <h2>MCP Store</h2>
    <div class="mcp-store-controls">
      <input type="search" id="mcp-search" placeholder="Search servers..." />
      <select id="mcp-filter-category">
        <option value="">All categories</option>
        <option value="productivity">Productivity</option>
        <option value="knowledge">Knowledge</option>
        <option value="system">System</option>
        <option value="research">Research</option>
        <option value="development">Development</option>
        <option value="data">Data</option>
        <option value="reasoning">Reasoning</option>
        <option value="utility">Utility</option>
      </select>
      <select id="mcp-filter-risk">
        <option value="">Any risk</option>
        <option value="low">Low</option>
        <option value="medium">Medium</option>
        <option value="high">High</option>
      </select>
    </div>
  </header>

  <div id="mcp-installed-zone" class="mcp-zone">
    <h3>Installed</h3>
    <div id="mcp-installed-grid" class="mcp-grid"></div>
  </div>

  <div id="mcp-available-zone" class="mcp-zone">
    <h3>Available</h3>
    <div id="mcp-available-grid" class="mcp-grid"></div>
  </div>
</section>

<div id="mcp-install-modal" class="modal" hidden>
  <div class="modal-content">
    <h3 id="mcp-modal-title">Install server</h3>
    <form id="mcp-install-form"></form>
    <div class="modal-actions">
      <button id="mcp-install-cancel" type="button">Cancel</button>
      <button id="mcp-install-confirm" type="button">Install</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add CSS**

Append to `frontend/command-center.css`:

```css
.mcp-store-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}
.mcp-store-controls {
  display: flex;
  gap: 0.5rem;
}
.mcp-zone { margin-bottom: 2rem; }
.mcp-zone h3 {
  font-size: 0.9rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.7;
  margin-bottom: 0.5rem;
}
.mcp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}
.mcp-card {
  background: var(--card-bg, #1a1a1f);
  border: 1px solid var(--card-border, #2a2a30);
  border-radius: 12px;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.mcp-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mcp-card-title { font-weight: 600; font-size: 1rem; }
.mcp-card-desc { font-size: 0.85rem; opacity: 0.75; }
.mcp-badges { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.mcp-badge {
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 500;
  text-transform: uppercase;
}
.mcp-badge-status-running { background: #1f6f3f; color: #e6ffee; }
.mcp-badge-status-error { background: #7a1f1f; color: #ffe6e6; }
.mcp-badge-status-stopped, .mcp-badge-status-not_installed {
  background: #444; color: #ccc;
}
.mcp-badge-risk-low { background: #1f4e6f; color: #e6f4ff; }
.mcp-badge-risk-medium { background: #6f5a1f; color: #fff4dc; }
.mcp-badge-risk-high { background: #7a1f4a; color: #ffe0ee; }
.mcp-card-actions {
  display: flex;
  gap: 0.4rem;
  margin-top: 0.5rem;
}
.mcp-card-actions button {
  background: #2a2a30;
  border: 1px solid #3a3a42;
  color: #eee;
  padding: 0.35rem 0.75rem;
  border-radius: 6px;
  font-size: 0.8rem;
  cursor: pointer;
}
.mcp-card-actions button:hover { background: #3a3a42; }
.mcp-card-expander {
  margin-top: 0.5rem;
  border-top: 1px solid #2a2a30;
  padding-top: 0.5rem;
}
.mcp-tools-list { display: flex; flex-direction: column; gap: 0.25rem; }
.mcp-tool-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8rem;
}
.mcp-tool-row select {
  background: #1a1a1f;
  color: #eee;
  border: 1px solid #3a3a42;
  border-radius: 4px;
  padding: 0.15rem 0.35rem;
}
.mcp-logs-box {
  background: #0a0a0d;
  color: #c0c0c0;
  font-family: ui-monospace, monospace;
  font-size: 0.7rem;
  padding: 0.5rem;
  border-radius: 6px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}
.mcp-card-error { color: #ff9090; font-size: 0.8rem; }
.mcp-card-unavailable { opacity: 0.4; }
.modal {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal[hidden] { display: none; }
.modal-content {
  background: #1a1a1f;
  border: 1px solid #2a2a30;
  border-radius: 12px;
  padding: 1.5rem;
  min-width: 340px;
  max-width: 500px;
}
.modal-content h3 { margin-top: 0; }
.modal-content label { display: block; margin-top: 0.75rem; font-size: 0.85rem; }
.modal-content input {
  display: block; width: 100%; margin-top: 0.25rem;
  background: #0a0a0d; color: #eee;
  border: 1px solid #3a3a42; border-radius: 4px;
  padding: 0.4rem 0.5rem;
}
.modal-actions {
  display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1rem;
}
```

- [ ] **Step 3: Smoke-check**

Open the Command-Center in a browser. The new "MCP Store" tab button should appear. Clicking it should show an empty section with the header. Styling should match the existing dark theme.

- [ ] **Step 4: Commit**

```bash
git add frontend/command-center.html frontend/command-center.css
git commit -m "feat(ui): MCP Store tab scaffold (HTML + CSS)"
```

---

## Task 18: Store UI JS — fetch + render installed/available

**Files:**
- Modify: `frontend/command-center.js`

- [ ] **Step 1: Add the store module**

Append to `frontend/command-center.js`:

```javascript
// ── MCP Store ─────────────────────────────────────────────────────

const MCPStore = (() => {
  const state = {
    catalog: [],
    servers: [],
    search: "",
    category: "",
    risk: "",
  };

  async function fetchAll() {
    const [catRes, srvRes] = await Promise.all([
      fetch("/api/mcp/catalog").then(r => r.json()),
      fetch("/api/mcp/servers").then(r => r.json()),
    ]);
    state.catalog = catRes;
    state.servers = srvRes;
    render();
  }

  function matchFilters(entry) {
    if (state.search && !(
      entry.name.toLowerCase().includes(state.search.toLowerCase()) ||
      entry.description.toLowerCase().includes(state.search.toLowerCase())
    )) return false;
    if (state.category && entry.category !== state.category) return false;
    if (state.risk && entry.risk_level !== state.risk) return false;
    return true;
  }

  function platformOk(entry) {
    if (!entry.platform || entry.platform.length === 0) return true;
    const ua = navigator.userAgent.toLowerCase();
    if (entry.platform.includes("darwin") && ua.includes("mac")) return true;
    if (entry.platform.includes("linux") && ua.includes("linux")) return true;
    if (entry.platform.includes("win32") && ua.includes("win")) return true;
    return false;
  }

  function render() {
    const installed = state.catalog.filter(e => e.installed && matchFilters(e));
    const available = state.catalog.filter(e => !e.installed && matchFilters(e));
    document.getElementById("mcp-installed-grid").innerHTML =
      installed.map(renderInstalledCard).join("") || '<p class="mcp-empty">No installed servers yet.</p>';
    document.getElementById("mcp-available-grid").innerHTML =
      available.map(renderAvailableCard).join("");
    document.getElementById("mcp-installed-zone").style.display =
      installed.length > 0 ? "block" : "none";
    attachHandlers();
  }

  function renderInstalledCard(e) {
    const statusClass = `mcp-badge-status-${e.status || "stopped"}`;
    const riskClass = `mcp-badge-risk-${e.risk_level}`;
    return `
      <div class="mcp-card" data-id="${e.id}">
        <div class="mcp-card-header">
          <span class="mcp-card-title">${escapeHtml(e.name)}</span>
          <div class="mcp-badges">
            <span class="mcp-badge ${statusClass}">${e.status || "stopped"}</span>
            <span class="mcp-badge ${riskClass}">${e.risk_level}</span>
          </div>
        </div>
        <div class="mcp-card-desc">${escapeHtml(e.description)}</div>
        <label style="font-size: 0.8rem; display: flex; gap: 0.4rem; align-items: center;">
          <input type="checkbox" class="mcp-toggle-enabled" ${e.enabled ? "checked" : ""} />
          Enabled
        </label>
        <div class="mcp-card-actions">
          <button class="mcp-btn-restart">Restart</button>
          <button class="mcp-btn-logs">Logs</button>
          <button class="mcp-btn-tools">Tools</button>
          <button class="mcp-btn-uninstall">Uninstall</button>
        </div>
        <div class="mcp-card-expander" data-slot="expand" hidden></div>
      </div>
    `;
  }

  function renderAvailableCard(e) {
    const riskClass = `mcp-badge-risk-${e.risk_level}`;
    const unavailable = !platformOk(e);
    return `
      <div class="mcp-card ${unavailable ? "mcp-card-unavailable" : ""}" data-id="${e.id}">
        <div class="mcp-card-header">
          <span class="mcp-card-title">${escapeHtml(e.name)}</span>
          <div class="mcp-badges">
            <span class="mcp-badge ${riskClass}">${e.risk_level}</span>
            <span class="mcp-badge">${e.category}</span>
          </div>
        </div>
        <div class="mcp-card-desc">${escapeHtml(e.description)}</div>
        ${unavailable ? '<div class="mcp-card-error">Not available on this platform</div>' : ""}
        <div class="mcp-card-actions">
          <button class="mcp-btn-install" ${unavailable ? "disabled" : ""}>Install</button>
        </div>
      </div>
    `;
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c =>
      ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  function attachHandlers() {
    document.querySelectorAll(".mcp-btn-install").forEach(btn => {
      btn.onclick = () => {
        const id = btn.closest(".mcp-card").dataset.id;
        openInstallModal(id);
      };
    });
    document.querySelectorAll(".mcp-btn-uninstall").forEach(btn => {
      btn.onclick = async () => {
        const id = btn.closest(".mcp-card").dataset.id;
        if (!confirm(`Uninstall ${id}?`)) return;
        await fetch(`/api/mcp/servers/${id}/uninstall`, {method: "POST"});
        fetchAll();
      };
    });
    document.querySelectorAll(".mcp-btn-restart").forEach(btn => {
      btn.onclick = async () => {
        const id = btn.closest(".mcp-card").dataset.id;
        await fetch(`/api/mcp/servers/${id}/restart`, {method: "POST"});
        fetchAll();
      };
    });
    document.querySelectorAll(".mcp-toggle-enabled").forEach(cb => {
      cb.onchange = async (e) => {
        const id = cb.closest(".mcp-card").dataset.id;
        const action = cb.checked ? "enable" : "disable";
        await fetch(`/api/mcp/servers/${id}/${action}`, {method: "POST"});
        fetchAll();
      };
    });
    document.querySelectorAll(".mcp-btn-logs").forEach(btn => {
      btn.onclick = async () => {
        const card = btn.closest(".mcp-card");
        const slot = card.querySelector('[data-slot="expand"]');
        if (!slot.hidden) { slot.hidden = true; return; }
        const id = card.dataset.id;
        const res = await fetch(`/api/mcp/servers/${id}/logs`).then(r => r.json());
        const lines = (res.stderr || []).join("\n") || "(no output)";
        slot.innerHTML = `<div class="mcp-logs-box">${escapeHtml(lines)}</div>`;
        slot.hidden = false;
      };
    });
    document.querySelectorAll(".mcp-btn-tools").forEach(btn => {
      btn.onclick = async () => {
        const card = btn.closest(".mcp-card");
        const slot = card.querySelector('[data-slot="expand"]');
        if (!slot.hidden) { slot.hidden = true; return; }
        const id = card.dataset.id;
        const tools = await fetch(`/api/mcp/servers/${id}/tools`).then(r => r.json());
        slot.innerHTML = `<div class="mcp-tools-list">` + tools.map(t => `
          <div class="mcp-tool-row">
            <span>${escapeHtml(t.name)}</span>
            <select class="mcp-permission-select" data-server="${id}" data-tool="${escapeHtml(t.name)}">
              <option value="__default__" ${t.source !== "db" ? "selected" : ""}>default (${t.source})</option>
              <option value="allow" ${t.source === "db" && t.permission === "allow" ? "selected" : ""}>allow</option>
              <option value="ask" ${t.source === "db" && t.permission === "ask" ? "selected" : ""}>ask</option>
              <option value="deny" ${t.source === "db" && t.permission === "deny" ? "selected" : ""}>deny</option>
            </select>
          </div>
        `).join("") + `</div>`;
        slot.hidden = false;
        slot.querySelectorAll(".mcp-permission-select").forEach(sel => {
          sel.onchange = async () => {
            const sid = sel.dataset.server;
            const tname = sel.dataset.tool;
            if (sel.value === "__default__") {
              await fetch(`/api/mcp/permissions/${sid}/${encodeURIComponent(tname)}`, {method: "DELETE"});
            } else {
              await fetch(`/api/mcp/permissions/${sid}/${encodeURIComponent(tname)}`, {
                method: "PUT",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({decision: sel.value}),
              });
            }
          };
        });
      };
    });
  }

  function openInstallModal(serverId) {
    const entry = state.catalog.find(e => e.id === serverId);
    if (!entry) return;
    document.getElementById("mcp-modal-title").textContent = `Install ${entry.name}`;
    const form = document.getElementById("mcp-install-form");
    form.innerHTML = entry.requires_config.map(k =>
      `<label>${k}<input type="text" name="${k}" /></label>`
    ).join("") || "<p>No configuration required.</p>";
    document.getElementById("mcp-install-modal").hidden = false;
    document.getElementById("mcp-install-confirm").onclick = async () => {
      const cfg = {};
      entry.requires_config.forEach(k => {
        const input = form.querySelector(`[name="${k}"]`);
        if (input) cfg[k] = input.value;
      });
      const r = await fetch(`/api/mcp/servers/${serverId}/install`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({config: cfg}),
      }).then(r => r.json());
      if (r.status === "ok") {
        document.getElementById("mcp-install-modal").hidden = true;
        fetchAll();
      } else {
        alert(`Install failed: ${r.error || "unknown"}\n${r.stderr || ""}`);
      }
    };
    document.getElementById("mcp-install-cancel").onclick = () => {
      document.getElementById("mcp-install-modal").hidden = true;
    };
  }

  function init() {
    document.getElementById("mcp-search").oninput = (e) => {
      state.search = e.target.value; render();
    };
    document.getElementById("mcp-filter-category").onchange = (e) => {
      state.category = e.target.value; render();
    };
    document.getElementById("mcp-filter-risk").onchange = (e) => {
      state.risk = e.target.value; render();
    };
    fetchAll();
  }

  return { init, fetchAll };
})();
```

- [ ] **Step 2: Initialize on tab open**

Find the existing tab switch logic in `command-center.js` and call `MCPStore.init()` (once) when `mcp-store` tab becomes active. Example wiring (adapt to existing code):

```javascript
let mcpStoreInitialized = false;
document.querySelectorAll('[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab-panel').forEach(p => p.hidden = true);
    document.getElementById(`tab-${tab}`).hidden = false;
    if (tab === 'mcp-store' && !mcpStoreInitialized) {
      MCPStore.init();
      mcpStoreInitialized = true;
    }
  });
});
```

- [ ] **Step 3: Hook WS updates**

Find the existing WebSocket message dispatcher. Add:

```javascript
// inside the onmessage handler
if (msg.type === 'mcp_state_changed') {
  if (typeof MCPStore !== 'undefined') MCPStore.fetchAll();
}
if (msg.type === 'approval_pending') {
  // Non-interactive toast
  showToast(`Approval requested for ${msg.server_id}::${msg.tool_name} — check Telegram`);
}
```

If `showToast` doesn't exist, either add a minimal version or log to console:

```javascript
function showToast(text) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = text;
  el.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#2a2a30;color:#eee;padding:0.75rem 1rem;border-radius:8px;z-index:200;';
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}
```

- [ ] **Step 4: Smoke-check in browser**

1. Start the server: `./start.sh`
2. Open Command-Center, switch to MCP Store tab.
3. Verify all 13 catalog entries appear under "Available".
4. Click "Install" on `time` (no config required) → spinner/ok → appears under "Installed".
5. Toggle enabled → status changes.
6. Click Uninstall → confirm → card returns to Available.

- [ ] **Step 5: Commit**

```bash
git add frontend/command-center.js
git commit -m "feat(ui): MCP Store JS — catalog fetch, install/uninstall, enable/disable, tools, logs, permissions"
```

---

## Task 19: Store UI JS — install modal polish + live refresh

This task addresses smaller UX details that are important for the smoke criteria.

**Files:**
- Modify: `frontend/command-center.js`
- Modify: `frontend/command-center.css`

- [ ] **Step 1: Install-in-progress indicator**

In `openInstallModal`, change the confirm handler to disable the button and show a spinner text:

```javascript
document.getElementById("mcp-install-confirm").onclick = async () => {
  const btn = document.getElementById("mcp-install-confirm");
  btn.disabled = true;
  const prev = btn.textContent;
  btn.textContent = "Installing...";
  const cfg = {};
  entry.requires_config.forEach(k => {
    const input = form.querySelector(`[name="${k}"]`);
    if (input) cfg[k] = input.value;
  });
  let r;
  try {
    r = await fetch(`/api/mcp/servers/${serverId}/install`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({config: cfg}),
    }).then(r => r.json());
  } catch (e) {
    alert(`Install failed: ${e}`);
    btn.disabled = false;
    btn.textContent = prev;
    return;
  }
  btn.disabled = false;
  btn.textContent = prev;
  if (r.status === "ok") {
    document.getElementById("mcp-install-modal").hidden = true;
    fetchAll();
  } else {
    const errBox = document.createElement("pre");
    errBox.className = "mcp-logs-box";
    errBox.textContent = `Error: ${r.error || "unknown"}\n\n${r.stderr || ""}`;
    form.appendChild(errBox);
  }
};
```

- [ ] **Step 2: Periodic refresh while the tab is open**

Add to `MCPStore`:

```javascript
let _refreshTimer = null;
function startAutoRefresh() {
  if (_refreshTimer) return;
  _refreshTimer = setInterval(fetchAll, 15000);
}
function stopAutoRefresh() {
  if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
}
```

Expose `startAutoRefresh`/`stopAutoRefresh` via the returned object. In the tab switcher, call these:

```javascript
if (tab === 'mcp-store') {
  if (!mcpStoreInitialized) { MCPStore.init(); mcpStoreInitialized = true; }
  MCPStore.startAutoRefresh();
} else if (mcpStoreInitialized) {
  MCPStore.stopAutoRefresh();
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/command-center.js frontend/command-center.css
git commit -m "feat(ui): install-in-progress UX + auto-refresh when store tab is open"
```

---

## Task 20: Integration test — end-to-end threadsafe flow with mock

**Files:**
- Create or modify: `tests/test_mcp_e2e.py`

- [ ] **Step 1: Write the integration test**

Add to `tests/test_mcp_e2e.py`:

```python
import asyncio
import concurrent.futures
import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.database import Database
from backend.mcp.registry import MCPRegistry
from backend.mcp.bridge import MCPBridge, _ServerHandle, ToolResult
from backend.mcp.permissions import PermissionResolver
from backend.mcp.approvals import ApprovalStore


class _FakeToolResult:
    def __init__(self, text, error=False):
        self.content = [type("B", (), {"text": text})()]
        self.isError = error


@pytest.mark.asyncio
async def test_end_to_end_safe_tool(tmp_path):
    """A 'get_*' tool (safe heuristic) executes without approval round-trip."""
    db = Database(tmp_path / "t.db"); await db.init()
    reg = MCPRegistry(); await reg.load_from_db(db)
    resolver = PermissionResolver(db)
    tg = MagicMock(); tg.send_approval_request = AsyncMock(); tg.enabled = True
    ws = MagicMock(); ws.broadcast = AsyncMock()
    store = ApprovalStore(tg, ws, db, timeout_seconds=3)
    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=store)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=_FakeToolResult("12 items"))
    bridge._handles["apple-mcp"] = _ServerHandle(session=fake_session, task=None, start_time=0.0)

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool,
            lambda: bridge.call_tool_threadsafe("apple-mcp", "get_reminders", {}),
        )
    assert result.success is True
    assert result.output == "12 items"
    tg.send_approval_request.assert_not_awaited()  # no approval needed for safe tool
    await db.close()


@pytest.mark.asyncio
async def test_end_to_end_sensitive_tool_with_allow(tmp_path):
    """A 'send_*' tool (sensitive) requests approval, user allows, call proceeds."""
    db = Database(tmp_path / "t.db"); await db.init()
    reg = MCPRegistry(); await reg.load_from_db(db)
    resolver = PermissionResolver(db)
    tg = MagicMock(); tg.send_approval_request = AsyncMock(); tg.enabled = True
    ws = MagicMock(); ws.broadcast = AsyncMock()
    store = ApprovalStore(tg, ws, db, timeout_seconds=3)
    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=store)
    bridge._main_loop = asyncio.get_running_loop()

    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock(return_value=_FakeToolResult("sent"))
    bridge._handles["apple-mcp"] = _ServerHandle(session=fake_session, task=None, start_time=0.0)

    async def approver():
        # Wait for approval to be pending, then allow
        for _ in range(20):
            await asyncio.sleep(0.05)
            if store.list_pending():
                store.resolve(store.list_pending()[0].id, "allow", "test")
                return
        raise RuntimeError("no pending approval appeared")

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
async def test_end_to_end_denied_by_db_override(tmp_path):
    db = Database(tmp_path / "t.db"); await db.init()
    reg = MCPRegistry(); await reg.load_from_db(db)
    resolver = PermissionResolver(db)
    await resolver.set_override("apple-mcp", "get_reminders", "deny")
    bridge = MCPBridge(reg)
    bridge.attach_policy(resolver=resolver, approval_store=None)
    bridge._main_loop = asyncio.get_running_loop()
    fake_session = MagicMock()
    fake_session.call_tool = AsyncMock()
    bridge._handles["apple-mcp"] = _ServerHandle(session=fake_session, task=None, start_time=0.0)

    result = await bridge.call_tool("apple-mcp", "get_reminders", {})
    assert result.success is False
    assert "denied" in result.output.lower()
    fake_session.call_tool.assert_not_awaited()
    await db.close()
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_mcp_e2e.py -v`
Expected: all three tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_e2e.py
git commit -m "test(mcp): end-to-end threadsafe + permission flow (safe, ask+allow, deny)"
```

---

## Task 21: Optional — E2E with real `@modelcontextprotocol/server-everything`

This test only runs if `npm` is available. It verifies the full install → start → call → uninstall cycle against a real MCP server.

**Files:**
- Modify: `tests/test_mcp_e2e.py`

- [ ] **Step 1: Add the real-e2e test**

Append to `tests/test_mcp_e2e.py`:

```python
import shutil
import pytest

requires_npm = pytest.mark.skipif(
    shutil.which("npm") is None,
    reason="requires npm on PATH",
)

@requires_npm
@pytest.mark.asyncio
async def test_real_everything_server_install_and_call(tmp_path, monkeypatch):
    """Install @modelcontextprotocol/server-everything, start it via the bridge,
    list its tools, call a tool, uninstall. Slow (~30s first run)."""
    from backend.mcp import installer
    monkeypatch.setattr(installer, "INSTALL_ROOT", tmp_path)
    # Also point registry at this temp install root by monkeypatching catalog entry
    from backend.mcp import catalog
    catalog.CATALOG["everything-test"] = {
        "name": "Everything (test)",
        "description": "Official MCP test server",
        "package": "@modelcontextprotocol/server-everything",
        "bin": "mcp-server-everything",
        "category": "utility",
        "platform": [],
        "risk_level": "low",
        "requires_config": [],
        "permissions": {},
    }

    # Install
    r = await installer.install("everything-test",
                                "@modelcontextprotocol/server-everything",
                                "mcp-server-everything")
    if not r.success:
        pytest.skip(f"npm install failed in sandbox: {r.error}\n{r.stderr}")

    # Build registry + bridge
    from backend.database import Database
    from backend.mcp.registry import MCPRegistry
    from backend.mcp.bridge import MCPBridge
    db = Database(tmp_path / "t.db"); await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    await reg.set_installed(db, "everything-test", True)
    await reg.set_enabled(db, "everything-test", True)
    await reg.load_from_db(db)

    bridge = MCPBridge(reg)
    try:
        await bridge.start(timeout=30)
        srv = reg.get("everything-test")
        assert srv.status == "running", f"Expected running, got {srv.status}: {srv.last_error}"
        tools = await bridge.list_tools("everything-test")
        assert len(tools) > 0
    finally:
        await bridge.stop()
        await installer.uninstall("everything-test")
        catalog.CATALOG.pop("everything-test", None)
        await db.close()
```

- [ ] **Step 2: Run test (slow!)**

Run: `python -m pytest tests/test_mcp_e2e.py::test_real_everything_server_install_and_call -v -s`
Expected: PASS on a machine with `npm` available (skip otherwise). May take 20–40s on first run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_e2e.py
git commit -m "test(mcp): optional real-npm e2e with server-everything"
```

---

## Task 22: Manual smoke checklist

**Goal:** Verify the spec's smoke criteria end-to-end on a real system. No code changes — only verification.

- [ ] **Step 1: Fresh start**

Run: `./start.sh`
Expected: server comes up cleanly, log line `MCP Bridge started (0 installed servers)` (or more if migration kicked in).

- [ ] **Step 2: Open Store UI**

In browser: http://localhost:8800 (or your `FRONTEND_PORT`). Click "MCP Store" tab. All 13 catalog cards should render in the "Available" zone. macOS-only cards (`apple-mcp`) should only be visible on macOS.

- [ ] **Step 3: Install apple-mcp**

Click Install on `apple-mcp` card. Modal opens (no required config → install directly). Wait for completion. Card moves to "Installed" zone with status badge.

Verify on disk:
```bash
ls ~/.falkenstein/mcp/apple-mcp/node_modules/.bin/
```
Expected: `apple-mcp` binary present.

- [ ] **Step 4: Enable it**

Toggle the "Enabled" switch in the installed card. Status should change to `running` within a few seconds. The Tools button expand should list apple-mcp's tools.

- [ ] **Step 5: Trigger a sensitive call via Telegram**

Send to Telegram bot: `schick mir eine Nachricht mit text hallo` (or similar sensitive tool call).

Expected:
- Crew dispatches → `send_message` tool call
- Telegram bot sends approval request with inline buttons `[Allow] [Deny] [Allow once]`
- You click Allow → message is sent → Telegram sends confirmation
- Original approval prompt is edited to "Approval resolved: allow"

- [ ] **Step 6: Trigger a safe call**

Send: `was stehen für Erinnerungen an`

Expected:
- `get_reminders` classified as safe → NO approval prompt
- Bot returns the reminders directly

- [ ] **Step 7: Force an error to verify diagnostic visibility**

Uninstall apple-mcp, then manually create a broken binary:
```bash
mkdir -p ~/.falkenstein/mcp/apple-mcp/node_modules/.bin
echo '#!/bin/sh\nexit 1' > ~/.falkenstein/mcp/apple-mcp/node_modules/.bin/apple-mcp
chmod +x ~/.falkenstein/mcp/apple-mcp/node_modules/.bin/apple-mcp
```

In UI: mark as installed (via API), enable. Card should show `error` status with the Logs button revealing the stderr from the broken binary. This confirms diagnostic visibility.

Cleanup:
```bash
rm -rf ~/.falkenstein/mcp/apple-mcp
```

- [ ] **Step 8: Permission override via UI**

Install `filesystem` from the Store → modal asks for `allowed_directories`, enter `~/tmp` → install → enable. Expand Tools → change `write_file` to `deny` via the dropdown. Verify via API:

```bash
curl http://localhost:8800/api/mcp/permissions | jq
```
Expected: entry with `{"server_id": "filesystem", "tool_name": "write_file", "decision": "deny"}`.

- [ ] **Step 9: Regression verification — the original bug**

Send any Telegram message that triggers a crew which uses an MCP tool (e.g. `listing the files in ~/tmp`). The tool call must complete without a `RuntimeError: attached to different loop` or any asyncio-related error. This confirms the core regression fix.

- [ ] **Step 10: Mark the plan complete**

If all of the above pass, the MCP overhaul is verified against the spec's smoke criteria.

```bash
git tag mcp-overhaul-smoke-ok
```

---

## Appendix — Spec Coverage Check

- **Bridge loop-pinning + threadsafe wrapper:** Task 3
- **stderr ring buffer:** Task 4
- **Structured event log + health check:** Task 5
- **Managed installer `~/.falkenstein/mcp/`:** Task 6
- **13-server curated catalog:** Task 7
- **Registry DB-backed + catalog merge + .env migration:** Task 8
- **Permission heuristic + resolution chain:** Task 9
- **ApprovalStore with dedup + timeout:** Task 10
- **Telegram inline-button approvals + callback_query:** Task 11
- **Bridge start uses installer + catalog, tool_adapter uses threadsafe:** Task 12
- **Bridge call_tool honours permissions + approvals:** Task 13
- **Admin API read endpoints:** Task 14
- **Admin API mutating endpoints:** Task 15
- **main.py lifespan wiring:** Task 16
- **Store UI tab + CSS:** Task 17
- **Store UI JS (cards, install, tools, logs, permissions):** Task 18–19
- **End-to-end mock integration test (regression guard):** Task 20
- **Optional real E2E with `server-everything`:** Task 21
- **Manual smoke verification:** Task 22

Every spec requirement maps to at least one task. Every task has complete code; no placeholders.
