# MCP Overhaul — Design

**Date:** 2026-04-09
**Status:** Approved for planning
**Scope:** P0 (bridge stability) + P1 (store & runtime-config) + P2 (hybrid permissions) in a single spec. P3 (office UI) and P4 (CrewAI alternatives research) are tracked as separate future projects.

---

## 1. Motivation

The current MCP integration has two fundamental problems:

1. **MCP servers appear "online" but tool calls silently fail.** Root cause: `tool_adapter._run_async()` creates a fresh event loop per call, but `ClientSession` objects live on the main asyncio loop. Using an async primitive from a different loop breaks deterministically and is the reason Apple Music and similar tool calls fail despite the bridge reporting `running`.
2. **MCP configuration is hardcoded in `.env`.** Adding/removing/reconfiguring an MCP requires editing env vars and restarting the server. There is no runtime-configurable store, no catalog of known servers, and no way to install MCPs without manually editing code and config.

Additionally, errors from MCP subprocesses are invisible: `stderr` is dropped, so when Apple Music fails there is no way to see *why* without attaching a debugger.

This spec addresses all three problems in a single coherent overhaul.

## 2. Goals

- MCP tool calls from CrewAI (thread pool) work reliably and without race conditions.
- Users can browse, install, enable/disable, configure, and uninstall MCP servers from the Command-Center UI with no code changes and no restart.
- A curated catalog of 13 official/popular MCP servers is available out of the box.
- MCP installation is managed locally (`~/.falkenstein/mcp/`) for fast, offline-capable, reproducible startup.
- A hybrid permission model separates read-only (auto-allow) from sensitive (user-approval) tool calls, with user-overridable decisions per tool.
- Approval requests reach the user via Telegram (interactive) and WebSocket (live feed), with a configurable timeout that defaults to 10 minutes.
- MCP server failures are diagnosable from the UI (status, last error, stderr ring buffer).

## 3. Non-Goals

- Replacing CrewAI or rewriting the orchestration layer. MCP bugs are independent of CrewAI.
- Rewriting the office/Phaser UI. That is P3 and will be its own spec.
- Supporting non-stdio MCP transports (SSE, HTTP). All catalog entries use stdio.
- Building a frontend test harness. UI is verified manually for this scope.
- Interactive approval widget in the dashboard. Approvals go through Telegram only; the dashboard shows pending approvals as a live feed but does not accept decisions. Interactive UI approvals can be added later without breaking this design.

## 4. Architecture Overview

### 4.1 Module layout (`backend/mcp/`)

```
backend/mcp/
├── bridge.py          [REVISED]  — loop-pinning, stderr ring buffer, health
├── registry.py        [REVISED]  — DB-backed state, catalog merge
├── installer.py       [NEW]      — managed npm install in ~/.falkenstein/mcp/
├── catalog.py         [NEW]      — static curated 13-server catalog
├── permissions.py     [NEW]      — heuristic + catalog + DB override chain
├── approvals.py       [NEW]      — pending-approval store, telegram + ws, timeout
├── tool_adapter.py    [REVISED]  — run_coroutine_threadsafe against main loop
└── config.py          [EXTENDED] — adds risk_level, permission fields
```

### 4.2 Core principle: single-loop ownership

The main asyncio loop is the *only* place where `ClientSession` objects live.
All other contexts (CrewAI thread pool, HTTP handlers, Telegram callbacks) communicate with sessions via `asyncio.run_coroutine_threadsafe(...)` or `asyncio.Event`. The bridge pins its main loop at `start()` time and exposes a `call_tool_threadsafe()` method for sync callers.

### 4.3 Data flow — tool call with approval

```
Crew → CrewAI Tool (sync _run, in thread pool)
  → tool_adapter._run()
  → bridge.call_tool_threadsafe(server_id, tool_name, args)
  → asyncio.run_coroutine_threadsafe(bridge.call_tool(...), MAIN_LOOP)
  → (in main loop) bridge.call_tool():
       1. permissions.check(server_id, tool_name) → allow | ask | deny
       2. if "ask": approvals.request(...)  ← blocks on asyncio.Event
            → telegram.send_message(inline buttons)
            → ws.broadcast({type: "approval_pending", ...})
            ← telegram callback or ws message → approvals.resolve(id, decision)
            ← event.set() → resume
       3. if "deny": return ToolResult(success=False, output="denied by policy")
       4. session.call_tool() on main loop
       5. ToolResult flows back through the future to the caller thread
```

### 4.4 Data flow — server lifecycle

```
UI "Install" click                       Startup / toggle enable
  → POST /api/mcp/servers/<id>/install     → bridge.start_all()
  → installer.install(server_id)           → for each enabled server in registry:
       mkdir ~/.falkenstein/mcp/<id>            if installer.is_installed(id):
       npm install <package> --prefix=...          resolve_binary(id)
       verify bin exists                           _start_server() (stdio_client)
  → registry: installed=1 in DB                    session.initialize()
  → ws broadcast: mcp_state_changed                session.list_tools()
  → (optional) auto-enable + start             → registry: status=running in DB
                                                → ws broadcast: mcp_state_changed
```

## 5. Bridge Fix (P0 core)

### 5.1 Loop-pinning

`bridge.py` changes:

```python
class MCPBridge:
    def __init__(self, registry):
        self.registry = registry
        self._handles: dict[str, _ServerHandle] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None

    async def start(self, timeout: float = DEFAULT_START_TIMEOUT) -> None:
        self._main_loop = asyncio.get_running_loop()
        ...

    def call_tool_threadsafe(
        self, server_id: str, tool_name: str, args: dict, timeout: float = 60.0,
    ) -> ToolResult:
        """Sync-facing API for CrewAI thread pool. Safe from any thread."""
        if self._main_loop is None:
            return ToolResult(success=False, output="Bridge not started")
        fut = asyncio.run_coroutine_threadsafe(
            self.call_tool(server_id, tool_name, args, timeout),
            self._main_loop,
        )
        try:
            return fut.result(timeout=timeout + 5)
        except concurrent.futures.TimeoutError:
            return ToolResult(success=False, output=f"Timeout after {timeout}s")
```

`tool_adapter.py` changes:

```python
class MCPDynamicTool(BaseTool):
    name: str = tool_name
    description: str = tool_desc

    def _run(self, **kwargs) -> str:
        result = bridge.call_tool_threadsafe(server_id, mcp_tool_name, kwargs)
        return result.output if result.success else f"Error: {result.output}"
```

The old `_run_async()` helper that created a fresh loop is deleted.

### 5.2 stderr ring buffer

Each `_ServerHandle` gets a `stderr: collections.deque[str] = deque(maxlen=200)`.

The stdio transport is wrapped so that stderr is captured into this deque. If the MCP SDK version in use supports the `errlog` parameter (already detected at runtime via `inspect.signature` in the current code), we pass a writer object that appends to the deque. If it doesn't, we fall back to manually managing the subprocess: `subprocess.Popen` with `stderr=PIPE`, a background task that reads lines and appends them to the deque, and our own `stdio_client`-compatible stream pair.

The bridge exposes `get_stderr(server_id: str) -> list[str]` returning a snapshot of the deque.

### 5.3 Health check

A background task in the bridge loops every `settings.mcp_health_interval` (default 30s):

- For each running server, check `handle.task.done()`. If the task finished unexpectedly, mark `status="error"` with `last_error="task exited"`, and if `auto_restart=True` for that server, schedule a restart.
- Update `uptime_seconds` in the registry.

This replaces the ad-hoc "is it still alive?" checks that don't exist today.

## 6. Managed Installer

### 6.1 Install root

```python
INSTALL_ROOT = Path.home() / ".falkenstein" / "mcp"
```

Each server gets its own subdirectory: `~/.falkenstein/mcp/<server_id>/`. Inside is a `package.json` (auto-generated) and `node_modules/` with the installed MCP package.

### 6.2 API (`installer.py`)

```python
@dataclass
class InstallResult:
    success: bool
    binary_path: Path | None
    error: str | None
    stderr: str                    # full npm stderr for diagnostics

async def install(server_id: str, package: str, bin_name: str) -> InstallResult:
    """
    npm install <package> --prefix ~/.falkenstein/mcp/<server_id>
    Returns InstallResult with resolved binary path on success.
    """

async def uninstall(server_id: str) -> bool:
    """rm -rf ~/.falkenstein/mcp/<server_id>"""

def resolve_binary(server_id: str, bin_name: str) -> Path | None:
    """Return ~/.falkenstein/mcp/<server_id>/node_modules/.bin/<bin_name> if exists."""

def is_installed(server_id: str) -> bool:
    """True if install dir exists AND binary is resolvable."""
```

### 6.3 Updated server-start flow

`bridge._start_server()` now:

1. Calls `installer.resolve_binary(server_id, catalog[server_id]["bin"])`. If `None`, marks `status="not_installed"` and returns — **no start attempt**.
2. Uses the resolved binary path as `StdioServerParameters.command` directly.
3. No `npx -y` involved. Start time drops from 5–30s to ~200ms.

### 6.4 Migration for existing users

On first startup after this change:

- If `~/.falkenstein/mcp/` doesn't exist, create it.
- If a user had `mcp_apple_enabled=true` in `.env`, auto-install `apple-mcp` once (best-effort; log warning on failure) and migrate the `enabled` flag into the new DB table.
- `.env` MCP flags are read one last time for migration, then ignored. A note is logged telling the user to manage MCPs via UI going forward.

## 7. Permissions

### 7.1 Resolution chain

On every tool call, `permissions.check(server_id, tool_name)` runs:

```
1. Look up (server_id, tool_name) in mcp_tool_permissions table (DB override). If found → return it.
2. Look up (server_id, tool_name) in catalog.CATALOG[server_id]["permissions"]. If found → return it.
3. Apply heuristic to tool_name + description → "allow" | "ask".
4. If heuristic returns neither → return "ask" (fail-safe default for unknown tools).
```

Return values: `"allow"` | `"ask"` | `"deny"`.

### 7.2 Heuristic

```python
SAFE_PATTERNS = [
    r"^(get|list|read|search|find|query|fetch|show|describe)_",
    r"^(count|exists|has|is)_",
    r"_(info|status|metadata|list|count)$",
]

SENSITIVE_PATTERNS = [
    r"^(create|delete|remove|update|set|write|send|post|put|patch)_",
    r"^(execute|run|spawn|kill|stop|start|restart)_",
    r"^(play|pause|skip|enable|disable|toggle)_",
    r"_(execute|run|write|delete)$",
]

def classify_heuristic(tool_name: str, description: str = "") -> str:
    name = tool_name.lower()
    if any(re.match(p, name) for p in SENSITIVE_PATTERNS):
        return "ask"
    if any(re.match(p, name) for p in SAFE_PATTERNS):
        return "allow"
    return "ask"  # fail-safe
```

Sensitive check runs before safe check so that `send_` wins over a subsequent `get_` match in the same name.

### 7.3 Catalog overrides

Per-MCP in `catalog.py`:

```python
"apple-mcp": {
    ...
    "permissions": {
        "get_reminders": "allow",
        "get_calendar_events": "allow",
        "play_music": "allow",          # explicitly allowed (non-destructive in practice)
        "send_message": "ask",
        "create_reminder": "ask",
    },
}
```

Any tool not listed falls through to the heuristic.

### 7.4 DB overrides

Users can override any decision per-tool in the UI. Writes to `mcp_tool_permissions`. Deletes are a "reset to default" action.

### 7.5 "Allow once" semantics (Telegram buttons)

When an approval prompt shows `[✅ Allow] [❌ Deny] [⏭️ Allow once]`:

- **Allow** → resolves this call as `allow` AND writes `mcp_tool_permissions(server_id, tool_name, "allow")`. The user can undo this in the UI later.
- **Allow once** → resolves this call as `allow`, no DB write.
- **Deny** → resolves this call as `deny`, no DB write. (To make "deny" persistent, user sets it explicitly in UI.)

## 8. Approvals

### 8.1 State

```python
@dataclass
class PendingApproval:
    id: str                      # uuid4
    server_id: str
    tool_name: str
    args: dict
    crew_id: str | None
    chat_id: str | None
    created_at: datetime
    event: asyncio.Event         # resume signal
    result: str | None = None    # "allow" | "deny" | "timeout"

class ApprovalStore:
    def __init__(self, telegram_bot, ws_manager, db, timeout_seconds: int = 600):
        ...

    async def request(
        self, server_id: str, tool_name: str, args: dict,
        crew_id: str | None = None, chat_id: str | None = None,
    ) -> str:
        """
        Register a pending approval, notify channels, block until resolved or timeout.
        Returns "allow" | "deny" | "timeout".
        """

    def resolve(self, approval_id: str, decision: str, decided_by: str) -> bool:
        """
        Resolve a pending approval. First resolve wins (race-safe).
        Returns True if this call actually resolved the approval, False if it was already resolved.
        """

    def list_pending(self) -> list[PendingApproval]: ...
```

### 8.2 Telegram integration

`telegram_bot.py` gains:

- A `send_approval_request(approval: PendingApproval)` method that builds an inline-keyboard message:

  ```
  🔒 Approval required
  Crew 'ops' wants to call:
      apple-mcp::send_message
  Args: { to: "+49...", text: "..." }

  [✅ Allow]  [❌ Deny]  [⏭️ Allow once]
  ```

- A `callback_query` handler that parses the callback data (`approval:<id>:allow` etc.) and calls `approval_store.resolve(id, decision, "telegram")`.

- Handles "Allow" action by also writing the DB override, "Allow once" skips the DB write.

### 8.3 WebSocket broadcast

On `request()`, the store also broadcasts:

```json
{"type": "approval_pending", "id": "...", "server_id": "...", "tool_name": "...", "args": {...}, "created_at": "..."}
```

The dashboard shows pending approvals as a live-feed list (non-interactive for now). On `resolve()`:

```json
{"type": "approval_resolved", "id": "...", "decision": "allow"}
```

### 8.4 Timeout

Stored in `ConfigService` under key `mcp_approval_timeout_seconds` (default 600, i.e. 10 minutes). Read on each `request()` call so changes take effect without restart. On timeout: `result = "timeout"`, treated as `deny`, logged to `mcp_approvals` table with `decided_by="auto"`.

### 8.5 Deduplication

If an identical `(server_id, tool_name, args)` request arrives within 30 seconds of an already-resolved approval, the same decision is reused automatically without re-prompting. This prevents button spam during retries. The de-dup cache lives in memory and is flushed every 60s.

### 8.6 Race resolution

If Telegram and WS both send `resolve()` for the same approval, the first one wins, the second returns `False`. Resolution sets the `asyncio.Event`, which unblocks the waiter exactly once.

## 9. Catalog

`catalog.py` is a static Python dict with 13 entries, chosen as a mix of official MCPs and popular community servers covering common use cases.

```python
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
            "get_reminders": "allow", "get_calendar_events": "allow",
            "get_notes": "allow", "play_music": "allow",
            "send_message": "ask", "create_reminder": "ask",
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
```

`requires_config` values are keys. The UI install modal asks for each value and stores them in `mcp_servers.config_json`. At start time, the bridge merges this config into the subprocess environment (e.g. `BRAVE_API_KEY=<value>`) or appends them as args where the MCP expects positional parameters (e.g. `mcp-obsidian <vault_path>`).

An empty `"permissions": {}` means *no catalog overrides* — all tools of that server fall through to the heuristic (and then the fail-safe default). This is the normal case for servers whose tool surface is small or where the heuristic is expected to classify well.

The catalog is canonical for the `package`, `bin`, `permissions`, and `requires_config` fields. It can be updated by editing `catalog.py` and restarting. A later enhancement could pull this from a remote URL; for now it's a static file.

## 10. Database Schema

Three new tables added via a migration in `database.py`:

```sql
CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    installed INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 0,
    config_json TEXT,
    last_error TEXT,
    installed_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS mcp_tool_permissions (
    server_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'ask', 'deny')),
    updated_at DATETIME,
    PRIMARY KEY (server_id, tool_name)
);

CREATE TABLE IF NOT EXISTS mcp_approvals (
    id TEXT PRIMARY KEY,
    server_id TEXT,
    tool_name TEXT,
    args_json TEXT,
    decision TEXT,
    decided_by TEXT,              -- 'telegram' | 'ws' | 'auto'
    requested_at DATETIME,
    decided_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_mcp_approvals_requested_at ON mcp_approvals(requested_at);
```

`mcp_servers.config_json` values containing keys matching `/token|secret|password|key/i` are masked in API responses (replaced with `"***"`) but stored as-is.

## 11. Admin API

All endpoints under `/api/mcp/*`, served via the existing `admin_api` router.

```
GET    /api/mcp/catalog
         → [{id, name, description, category, platform, risk_level,
             requires_config, installed, enabled, status}]

GET    /api/mcp/servers
         → installed servers with live status
GET    /api/mcp/servers/{id}
         → details including tools list, permissions, last_error, uptime
POST   /api/mcp/servers/{id}/install
         body: {config: {key: value, ...}}
         → installs package, stores config, sets enabled=false
         (user explicitly toggles enabled after install)
POST   /api/mcp/servers/{id}/uninstall
POST   /api/mcp/servers/{id}/enable
POST   /api/mcp/servers/{id}/disable
POST   /api/mcp/servers/{id}/restart
GET    /api/mcp/servers/{id}/logs
         → {stderr: [line, ...]}  (ring buffer snapshot)
GET    /api/mcp/servers/{id}/tools
         → [{name, description, permission: "allow"|"ask"|"deny", source: "db"|"catalog"|"heuristic"}]

GET    /api/mcp/permissions
         → all DB overrides
PUT    /api/mcp/permissions/{server_id}/{tool_name}
         body: {decision: "allow"|"ask"|"deny"}
DELETE /api/mcp/permissions/{server_id}/{tool_name}
         → reset to catalog/heuristic

GET    /api/mcp/approvals/pending
         → live list of open approvals (read-only feed for dashboard)
POST   /api/mcp/approvals/{id}/resolve
         body: {decision: "allow"|"deny"|"allow_once"}
         → available for API clients and future interactive widgets.
         The in-scope dashboard UI does NOT call this endpoint; all
         interactive approvals happen via Telegram buttons.
GET    /api/mcp/approvals/history?limit=50
         → rows from mcp_approvals table
```

All mutating endpoints broadcast `mcp_state_changed` over WebSocket after success, so all connected dashboards refresh.

## 12. Store UI Panel

Added to `frontend/command-center.html` + `command-center.css` + `command-center.js` as a new tab "MCP Store" in the existing tab bar.

### 12.1 Layout

**Top:** search input + category/risk-level filter pills.

**Zone 1 — Installed (only shown if at least one server is installed):**
- Cards for each installed server.
- Each card:
  - Name + status badge (`running`=green, `error`=red, `stopped`=grey)
  - Risk-level pill
  - Toggle switch for `enabled`
  - `[Restart] [Uninstall] [Configure] [Logs]` buttons
  - Expandable "Tools" section: list of tools, each with a permission `<select>` (`default` | `allow` | `ask` | `deny`) — changes persist immediately via API
  - Expandable "Logs" section (only when clicked): shows last ~20 lines of stderr from `GET /api/mcp/servers/{id}/logs`
  - If `status=error`: `last_error` shown in red with the stderr expanded by default

**Zone 2 — Available:**
- Grid of cards for catalog entries that are **not installed**.
- Each card:
  - Name, description, category pill, risk-level pill
  - `[Install]` button:
    - If `requires_config` is empty → direct install
    - Else → opens a modal asking for each config value; submits to `/install`
  - Platform filter: if `platform=["darwin"]` and current OS is not macOS, the card is shown greyed out with a "macOS only" note

### 12.2 Live updates

Subscribe to the existing WS stream. On `mcp_state_changed`, re-fetch `/api/mcp/catalog` and `/api/mcp/servers`. On `approval_pending`, show a non-interactive toast "Approval requested (reply in Telegram)" — no UI-side decision for now.

## 13. Error Handling & Diagnostics

### 13.1 Visibility layers

1. **Registry status** (`running` | `error` | `stopped` | `not_installed` | `disabled`) + `last_error` — shown in status badge and expand header.
2. **stderr ring buffer** (200 lines, per server) — fetched via `/logs` endpoint, shown in Logs panel.
3. **Structured event log** (`data/mcp_events.log`) — JSON lines, rotating at 10 MB, for post-hoc analysis. Events: `install_*`, `start_*`, `stop_*`, `tool_call`, `tool_error`, `approval_*`.

### 13.2 Failure-mode matrix

| Failure | Where visible | Recovery |
|---|---|---|
| Binary not installed | Card: `not_installed`, `[Install]` button | User installs from UI |
| `npm install` failed | Install modal shows stderr inline | Retry button |
| `session.initialize()` timeout | Card: `error`, `last_error` + stderr expanded | Restart button |
| Subprocess crashed post-start | Health-check loop sets `error`, Telegram notification on repeated crash (2+ within 5 min) | Auto-restart if enabled |
| Tool-call timeout (> 60s) | Crew receives error output | Independent per call |
| Tool-call MCP error | `ToolResult(success=False)`, propagated to crew | — |
| Approval timeout | `mcp_approvals` row `decided_by=auto`, Telegram follow-up "Approval expired" | — |

### 13.3 Non-fatal startup

If the entire bridge fails to start (e.g. no network, no node), Falkenstein continues without MCP. A `log.warning` is emitted and the Store UI shows all servers as `not_installed`. This matches current behavior.

## 14. Testing Strategy

### 14.1 Unit tests

- `test_mcp_permissions.py` — heuristic classification (safe/sensitive/unknown edge cases), resolution chain (DB > catalog > heuristic > fail-safe).
- `test_mcp_approvals.py` — request→resolve happy path, timeout, race (first resolve wins), deduplication window.
- `test_mcp_installer.py` — `resolve_binary` with and without `.bin/` entry, `is_installed` with and without dir; `install`/`uninstall` mocked (no real npm).
- `test_mcp_catalog.py` — catalog schema validation (each entry has `package`, `bin`, `category`, `risk_level`, `permissions`), platform filter.
- `test_mcp_registry.py` (extended) — DB merge: catalog + installed state → correct server list; DB migration of legacy `.env` flags.
- `test_mcp_bridge.py` (extended) — **threading regression test**: tool-call from a separate thread via `call_tool_threadsafe`, asserts no `RuntimeError: attached to different loop`. Mock `ClientSession` stands in for a real MCP process. This is the specific regression guard for the Apple Music bug.

### 14.2 Integration test

- `test_mcp_e2e.py` (extended) — real `@modelcontextprotocol/server-everything` (official test server, lightweight): install → start → list_tools → call_tool → stop → uninstall. Skipped unless `npm` is available.

### 14.3 Admin API tests

- `test_mcp_admin_api.py` (extended) — all new endpoints with a mock bridge; permission PUT/DELETE persists and returns correct merged view; approval resolve changes pending state; WS broadcast fires on state change.

### 14.4 No UI tests

The Store panel is verified manually. Building a frontend test harness is out of scope.

### 14.5 Smoke criteria (spec is "done" when all pass)

1. Fresh install: open Command-Center → MCP Store → click Install on `apple-mcp` → `~/.falkenstein/mcp/apple-mcp/node_modules/` exists and contains the package.
2. After enable: card shows `running`, tool list populated in the expandable section.
3. Telegram message "spiel Musik" → crew calls `play_music` → Telegram approval prompt → Allow → music plays. (If `play_music` is set to `allow` via the catalog, this step bypasses the prompt and the music plays directly.)
4. Force a failure: configure `apple-mcp` with invalid permissions → card shows `error` + real stderr visible in Logs panel (not "Error" with no context).
5. Install `filesystem` from the Store → modal asks for `allowed_directories` → after config, server starts and tools are listed.
6. Tool-call from a crew running in the CrewAI thread pool succeeds (regression for the loop/thread bug).

## 15. Out of scope (explicitly deferred)

- Interactive approval UI widget in the dashboard (Phase 2 candidate).
- Pulling the catalog from a remote URL (future enhancement).
- Non-stdio transports (SSE, HTTP).
- Replacing CrewAI or refactoring orchestration (P4, separate project).
- Office/Phaser UI visualization overhaul (P3, separate project).
- Auto-updating installed MCP packages (user triggers uninstall+install manually).
- Frontend test harness.

## 16. Open decisions

None. All major design questions were resolved during brainstorming:

- Permission model: hybrid (heuristic + catalog + DB).
- Catalog scope: curated 13 MCPs, static file.
- Approval channel: Telegram + WS (WS non-interactive for now), 10-minute default timeout.
- Risk tagging: heuristic + catalog overrides + UI overrides, fail-safe "ask".
- UI scope: full Store panel with cards, no interactive approval widget.
- Installation strategy: managed per-server `node_modules` in `~/.falkenstein/mcp/`, fast and offline-capable.
