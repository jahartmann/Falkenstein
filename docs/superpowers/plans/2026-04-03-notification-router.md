# Notification Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bidirektionales Todo-Management zwischen Telegram und Obsidian mit intelligentem Hybrid-Routing (Regeln + LLM) für alle Events.

**Architecture:** Zentraler `NotificationRouter` empfängt alle Events und routet sie regelbasiert an Telegram und/oder Obsidian. Ein `ObsidianWatcher` (watchdog) erkennt neue Todos im Vault und pusht sie an Telegram. LLM-Hybrid-Check bei Grenzfällen (kurze Inhalte).

**Tech Stack:** Python 3.11+, watchdog (File-Watching), asyncio, bestehender LLMClient (Gemma4 light model)

---

### Task 1: NotificationRouter — Kern-Klasse mit Regeltabelle

**Files:**
- Create: `backend/notification_router.py`
- Test: `tests/test_notification_router.py`

- [ ] **Step 1: Write failing test — route_event dispatcht task_assigned nur an Telegram**

```python
# tests/test_notification_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.notification_router import NotificationRouter


@pytest.fixture
def telegram():
    t = AsyncMock()
    t.enabled = True
    t.send_message = AsyncMock(return_value=True)
    return t


@pytest.fixture
def obsidian():
    o = AsyncMock()
    o.execute = AsyncMock()
    return o


@pytest.fixture
def llm():
    return AsyncMock()


@pytest.fixture
def router(telegram, obsidian, llm):
    return NotificationRouter(telegram=telegram, obsidian=obsidian, llm=llm)


@pytest.mark.asyncio
async def test_task_assigned_only_telegram(router, telegram, obsidian):
    await router.route_event("task_assigned", {
        "agent_name": "Alex",
        "task_title": "Login fixen",
    })
    telegram.send_message.assert_called_once()
    assert "Alex" in telegram.send_message.call_args[0][0]
    obsidian.execute.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notification_router.py::test_task_assigned_only_telegram -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.notification_router'`

- [ ] **Step 3: Write NotificationRouter with routing table and task_assigned rule**

```python
# backend/notification_router.py
"""Central event router: dispatches events to Telegram and/or Obsidian based on rules + LLM hybrid check."""

from __future__ import annotations
import datetime
from dataclasses import dataclass, field


@dataclass
class RouteRule:
    telegram: bool = False
    obsidian: bool = False
    # If both are True and content is short, LLM decides on obsidian
    hybrid_check: bool = False


# Default routing table — matches the spec
ROUTING_TABLE: dict[str, RouteRule] = {
    "task_assigned":      RouteRule(telegram=True),
    "task_completed":     RouteRule(telegram=True, obsidian=True, hybrid_check=True),
    "escalation_success": RouteRule(telegram=True, obsidian=True),
    "escalation_failed":  RouteRule(telegram=True, obsidian=True),
    "budget_warning":     RouteRule(telegram=True),
    "daily_report":       RouteRule(telegram=True, obsidian=True),
    "todo_from_telegram": RouteRule(telegram=True, obsidian=True),
    "todo_from_obsidian": RouteRule(telegram=True),
    "subtask_completed":  RouteRule(obsidian=True),
    "project_created":    RouteRule(telegram=True, obsidian=True),
}

HYBRID_THRESHOLD = 100  # chars — below this, LLM decides if obsidian is worth it


class NotificationRouter:
    def __init__(self, telegram, obsidian, llm, llm_routing_enabled: bool = True):
        self.telegram = telegram
        self.obsidian = obsidian
        self.llm = llm
        self.llm_routing_enabled = llm_routing_enabled

    async def route_event(self, event_type: str, payload: dict):
        """Route an event to Telegram and/or Obsidian based on rules."""
        rule = ROUTING_TABLE.get(event_type)
        if not rule:
            return

        send_telegram = rule.telegram and self.telegram and self.telegram.enabled
        send_obsidian = rule.obsidian and self.obsidian is not None

        # Hybrid check: short content → ask LLM if obsidian is worth it
        if send_obsidian and rule.hybrid_check:
            content = payload.get("result", payload.get("content", ""))
            if len(content) < HYBRID_THRESHOLD:
                if not await self._should_write_obsidian(event_type, content):
                    send_obsidian = False

        if send_telegram:
            msg = self._format_telegram(event_type, payload)
            if msg:
                await self.telegram.send_message(msg)

        if send_obsidian:
            await self._write_obsidian(event_type, payload)

    async def _should_write_obsidian(self, event_type: str, content: str) -> bool:
        """LLM hybrid check: is this content worth documenting in Obsidian?"""
        if not self.llm_routing_enabled or not self.llm:
            return True  # Default: write to obsidian if LLM check disabled
        try:
            response = await self.llm.chat(
                system_prompt="Antworte nur mit Ja oder Nein.",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Ist dieses Ergebnis detailliert genug für eine Dokumentation in Obsidian?\n\n"
                        f"Ergebnis: {content}\n\nJa oder Nein?"
                    ),
                }],
                model=self.llm.model_light,
                temperature=0.0,
            )
            return "ja" in response.lower()
        except Exception:
            return True  # On error, default to writing

    def _format_telegram(self, event_type: str, payload: dict) -> str:
        """Format event as short Telegram message."""
        name = payload.get("agent_name", "Agent")
        title = payload.get("task_title", "")
        content = payload.get("content", "")
        result = payload.get("result", "")

        formatters = {
            "task_assigned": lambda: f"📋 *{name}* arbeitet an: {title}",
            "task_completed": lambda: f"✅ *{name}* fertig: {title}\n_{(result or content)[:200]}_",
            "escalation_success": lambda: f"⚡ *Eskalation* bei {name}: CLI hat übernommen für {title}",
            "escalation_failed": lambda: f"❌ *Eskalation gescheitert* bei {name}: {title}\n_{payload.get('reason', '')[:200]}_",
            "budget_warning": lambda: f"⚠️ *Budget-Warnung*: {payload.get('used', 0):,}/{payload.get('budget', 0):,} Tokens",
            "daily_report": lambda: content[:2000] if content else "",
            "todo_from_telegram": lambda: f"✅ Todo eingetragen: {content[:200]}",
            "todo_from_obsidian": lambda: f"📝 Neuer Todo aus Obsidian: {content[:200]}",
            "project_created": lambda: f"📁 Projekt erstellt: {payload.get('project_name', content)}",
        }
        formatter = formatters.get(event_type)
        return formatter() if formatter else ""

    async def _write_obsidian(self, event_type: str, payload: dict):
        """Write event data to appropriate Obsidian location."""
        content = payload.get("content", "")
        result = payload.get("result", "")
        project = payload.get("project")
        title = payload.get("task_title", "")
        name = payload.get("agent_name", "Agent")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        if event_type == "task_completed":
            if project:
                md = f"\n\n### {title} ✅\n*{name}* — {now}\n\n{result or content}"
                await self.obsidian.execute({
                    "action": "append",
                    "path": f"Falkenstein/Projekte/{project}/Tasks.md",
                    "content": md,
                })
            else:
                await self.obsidian.execute({
                    "action": "inbox",
                    "content": f"[DONE] {title}: {(result or content)[:300]}",
                })

        elif event_type in ("escalation_success", "escalation_failed"):
            details = payload.get("details", payload.get("reason", ""))
            md = f"\n\n### Eskalation: {title}\n*{name}* — {now}\nStatus: {event_type.split('_')[1]}\n\n{details}"
            await self.obsidian.execute({
                "action": "daily_report",
                "content": md,
            })

        elif event_type == "daily_report":
            await self.obsidian.execute({
                "action": "daily_report",
                "content": content,
            })

        elif event_type == "todo_from_telegram":
            await self.obsidian.execute({
                "action": "todo",
                "content": content,
                "project": project,
            })

        elif event_type == "subtask_completed":
            if project:
                md = f"\n- [x] [{now}] {title}: {(result or content)[:300]}"
                await self.obsidian.execute({
                    "action": "append",
                    "path": f"Falkenstein/Projekte/{project}/Tasks.md",
                    "content": md,
                })

        elif event_type == "project_created":
            await self.obsidian.execute({
                "action": "project",
                "content": payload.get("project_name", content),
            })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_notification_router.py::test_task_assigned_only_telegram -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/notification_router.py tests/test_notification_router.py
git commit -m "feat: notification router with routing table — task_assigned rule"
```

---

### Task 2: NotificationRouter — Alle Routing-Regeln testen

**Files:**
- Modify: `tests/test_notification_router.py`

- [ ] **Step 1: Write failing tests for remaining event types**

```python
# Append to tests/test_notification_router.py

@pytest.mark.asyncio
async def test_task_completed_both_targets_long_result(router, telegram, obsidian):
    """Long result (>100 chars) goes to both without LLM check."""
    await router.route_event("task_completed", {
        "agent_name": "Alex",
        "task_title": "Login fixen",
        "result": "x" * 150,
        "project": "website",
    })
    telegram.send_message.assert_called_once()
    obsidian.execute.assert_called_once()
    args = obsidian.execute.call_args[0][0]
    assert args["action"] == "append"
    assert "website" in args["path"]


@pytest.mark.asyncio
async def test_task_completed_short_result_llm_says_no(router, telegram, obsidian, llm):
    """Short result + LLM says Nein → only Telegram."""
    llm.chat = AsyncMock(return_value="Nein")
    llm.model_light = "test-model"
    await router.route_event("task_completed", {
        "agent_name": "Bob",
        "task_title": "Quick fix",
        "result": "Done.",
        "project": "api",
    })
    telegram.send_message.assert_called_once()
    obsidian.execute.assert_not_called()


@pytest.mark.asyncio
async def test_task_completed_short_result_llm_says_yes(router, telegram, obsidian, llm):
    """Short result + LLM says Ja → both targets."""
    llm.chat = AsyncMock(return_value="Ja, das ist dokumentationswürdig.")
    llm.model_light = "test-model"
    await router.route_event("task_completed", {
        "agent_name": "Bob",
        "task_title": "Config update",
        "result": "Updated .env with new API key path",
        "project": "infra",
    })
    telegram.send_message.assert_called_once()
    obsidian.execute.assert_called_once()


@pytest.mark.asyncio
async def test_budget_warning_only_telegram(router, telegram, obsidian):
    await router.route_event("budget_warning", {"used": 40000, "budget": 50000})
    telegram.send_message.assert_called_once()
    assert "40,000" in telegram.send_message.call_args[0][0]
    obsidian.execute.assert_not_called()


@pytest.mark.asyncio
async def test_subtask_completed_only_obsidian(router, telegram, obsidian):
    await router.route_event("subtask_completed", {
        "task_title": "Write tests",
        "result": "All 5 tests pass",
        "project": "website",
    })
    telegram.send_message.assert_not_called()
    obsidian.execute.assert_called_once()


@pytest.mark.asyncio
async def test_todo_from_obsidian_only_telegram(router, telegram, obsidian):
    await router.route_event("todo_from_obsidian", {
        "content": "API Docs schreiben",
        "source_file": "Management/Inbox.md",
    })
    telegram.send_message.assert_called_once()
    assert "Obsidian" in telegram.send_message.call_args[0][0]
    obsidian.execute.assert_not_called()


@pytest.mark.asyncio
async def test_escalation_success_both_targets(router, telegram, obsidian):
    await router.route_event("escalation_success", {
        "agent_name": "Bob",
        "task_title": "Complex refactor",
        "details": "Claude CLI completed the refactor successfully",
    })
    telegram.send_message.assert_called_once()
    obsidian.execute.assert_called_once()
    args = obsidian.execute.call_args[0][0]
    assert args["action"] == "daily_report"


@pytest.mark.asyncio
async def test_unknown_event_type_ignored(router, telegram, obsidian):
    await router.route_event("unknown_event", {"data": "test"})
    telegram.send_message.assert_not_called()
    obsidian.execute.assert_not_called()


@pytest.mark.asyncio
async def test_llm_routing_disabled_always_writes_obsidian(telegram, obsidian, llm):
    router = NotificationRouter(telegram=telegram, obsidian=obsidian, llm=llm, llm_routing_enabled=False)
    await router.route_event("task_completed", {
        "agent_name": "Alex",
        "task_title": "Tiny fix",
        "result": "OK",
        "project": "api",
    })
    telegram.send_message.assert_called_once()
    obsidian.execute.assert_called_once()


@pytest.mark.asyncio
async def test_daily_report_both_targets(router, telegram, obsidian):
    report = "# Report\n\nAlles gut heute."
    await router.route_event("daily_report", {"content": report})
    telegram.send_message.assert_called_once()
    obsidian.execute.assert_called_once()
    args = obsidian.execute.call_args[0][0]
    assert args["action"] == "daily_report"
```

- [ ] **Step 2: Run all tests to verify they pass**

Run: `python -m pytest tests/test_notification_router.py -v`
Expected: All 10 tests PASS (implementation from Task 1 covers these)

- [ ] **Step 3: Commit**

```bash
git add tests/test_notification_router.py
git commit -m "test: comprehensive routing rules coverage for notification router"
```

---

### Task 3: ObsidianWatcher — File-Watcher mit Debouncing

**Files:**
- Create: `backend/obsidian_watcher.py`
- Test: `tests/test_obsidian_watcher.py`

- [ ] **Step 1: Write failing test — detects new todo in Inbox.md**

```python
# tests/test_obsidian_watcher.py
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from backend.obsidian_watcher import ObsidianWatcher


@pytest.fixture
def vault(tmp_path):
    """Create a minimal vault structure."""
    mgmt = tmp_path / "Management"
    mgmt.mkdir()
    inbox = mgmt / "Inbox.md"
    inbox.write_text("# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n")

    proj = tmp_path / "Falkenstein" / "Projekte" / "website"
    proj.mkdir(parents=True)
    (proj / "Tasks.md").write_text("# Tasks — website\n\n- [ ] [2026-04-01 10:00] Old task\n")

    return tmp_path


@pytest.fixture
def router():
    r = AsyncMock()
    r.route_event = AsyncMock()
    return r


@pytest.mark.asyncio
async def test_detects_new_inbox_todo(vault, router):
    watcher = ObsidianWatcher(vault_path=vault, router=router)
    watcher.scan_files()  # Initial scan — learns existing entries

    # Simulate user adding a new todo
    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-03 14:00] New todo from Obsidian\n"
    )

    new_todos = watcher.detect_changes()
    assert len(new_todos) == 1
    assert "New todo from Obsidian" in new_todos[0]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_obsidian_watcher.py::test_detects_new_inbox_todo -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write ObsidianWatcher implementation**

```python
# backend/obsidian_watcher.py
"""Watches Obsidian vault for new todos and notifies the router."""

from __future__ import annotations
import asyncio
import hashlib
import re
from pathlib import Path

TODO_RE = re.compile(r"^- \[ \] (.+)$")


class ObsidianWatcher:
    def __init__(self, vault_path: Path, router, debounce_seconds: float = 2.0):
        self.vault = vault_path
        self.router = router
        self.debounce_seconds = debounce_seconds
        # file_path → set of line hashes (known entries)
        self._known: dict[str, set[str]] = {}
        self._observer = None
        self._debounce_tasks: dict[str, asyncio.Task] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def watched_files(self) -> list[Path]:
        """All files we should monitor for new todos."""
        files = []
        inbox = self.vault / "Management" / "Inbox.md"
        if inbox.exists():
            files.append(inbox)
        proj_dir = self.vault / "Falkenstein" / "Projekte"
        if proj_dir.exists():
            for tasks_file in proj_dir.glob("*/Tasks.md"):
                files.append(tasks_file)
        return files

    @staticmethod
    def _hash_line(line: str) -> str:
        return hashlib.sha256(line.strip().encode()).hexdigest()

    @staticmethod
    def _extract_todos(text: str) -> list[dict]:
        """Extract unchecked todo lines from markdown text."""
        todos = []
        for line in text.splitlines():
            m = TODO_RE.match(line.strip())
            if m:
                todos.append({"content": m.group(1), "raw": line.strip()})
        return todos

    def scan_files(self):
        """Initial scan: learn all existing todos so we only detect NEW ones."""
        for f in self.watched_files:
            text = f.read_text(encoding="utf-8")
            todos = self._extract_todos(text)
            self._known[str(f)] = {self._hash_line(t["raw"]) for t in todos}

    def detect_changes(self) -> list[dict]:
        """Compare current file state against known entries. Returns new todos."""
        new_todos = []
        for f in self.watched_files:
            if not f.exists():
                continue
            text = f.read_text(encoding="utf-8")
            todos = self._extract_todos(text)
            current_hashes = {self._hash_line(t["raw"]) for t in todos}
            known = self._known.get(str(f), set())

            for todo in todos:
                h = self._hash_line(todo["raw"])
                if h not in known:
                    # Determine project from path
                    project = None
                    parts = f.relative_to(self.vault).parts
                    if "Projekte" in parts:
                        idx = parts.index("Projekte")
                        if idx + 1 < len(parts):
                            project = parts[idx + 1]
                    new_todos.append({
                        "content": todo["content"],
                        "source_file": str(f.relative_to(self.vault)),
                        "project": project,
                    })

            # Update known state
            self._known[str(f)] = current_hashes
        return new_todos

    async def _handle_file_change(self, file_path: str):
        """Debounced handler for file changes."""
        await asyncio.sleep(self.debounce_seconds)
        new_todos = self.detect_changes()
        for todo in new_todos:
            await self.router.route_event("todo_from_obsidian", todo)

    def _on_file_event(self, file_path: str):
        """Called from watchdog thread — schedules debounced async handler."""
        if self._loop is None:
            return
        # Cancel previous debounce timer for this file
        key = file_path
        if key in self._debounce_tasks:
            self._debounce_tasks[key].cancel()
        # Schedule new debounced handler
        self._debounce_tasks[key] = asyncio.run_coroutine_threadsafe(
            self._handle_file_change(file_path), self._loop
        ).cancel  # Store the future, not cancel
        # Actually: store and manage the future properly
        future = asyncio.run_coroutine_threadsafe(
            self._handle_file_change(file_path), self._loop
        )
        self._debounce_tasks[key] = future

    async def start(self):
        """Start watching the vault. Runs as long-lived asyncio task."""
        self._loop = asyncio.get_running_loop()
        self.scan_files()

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileModifiedEvent

            class _Handler(FileSystemEventHandler):
                def __init__(self, watcher: ObsidianWatcher):
                    self._watcher = watcher

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    path = Path(event.src_path)
                    # Only care about our watched files
                    watched_paths = {str(f) for f in self._watcher.watched_files}
                    if str(path) in watched_paths:
                        self._watcher._on_file_event(str(path))

            self._observer = Observer()
            handler = _Handler(self)
            # Watch Management/ and Projekte/ directories
            mgmt = self.vault / "Management"
            if mgmt.exists():
                self._observer.schedule(handler, str(mgmt), recursive=False)
            proj = self.vault / "Falkenstein" / "Projekte"
            if proj.exists():
                self._observer.schedule(handler, str(proj), recursive=True)
            self._observer.start()

            # Keep alive until cancelled
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass
        finally:
            if self._observer:
                self._observer.stop()
                self._observer.join()

    async def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_obsidian_watcher.py::test_detects_new_inbox_todo -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/obsidian_watcher.py tests/test_obsidian_watcher.py
git commit -m "feat: obsidian watcher with todo detection and debouncing"
```

---

### Task 4: ObsidianWatcher — Erweiterte Tests

**Files:**
- Modify: `tests/test_obsidian_watcher.py`

- [ ] **Step 1: Write additional tests**

```python
# Append to tests/test_obsidian_watcher.py

@pytest.mark.asyncio
async def test_ignores_checked_todos(vault, router):
    watcher = ObsidianWatcher(vault_path=vault, router=router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    # Change existing unchecked to checked — should NOT trigger
    inbox.write_text(
        "# Inbox\n\n- [x] [2026-04-01 10:00] Existing todo\n"
    )
    new_todos = watcher.detect_changes()
    # The checked item is not detected as new (different regex)
    assert len(new_todos) == 0


@pytest.mark.asyncio
async def test_ignores_non_todo_lines(vault, router):
    watcher = ObsidianWatcher(vault_path=vault, router=router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n"
        "\nSome random text that is not a todo\n"
        "## A new heading\n"
    )
    new_todos = watcher.detect_changes()
    assert len(new_todos) == 0


@pytest.mark.asyncio
async def test_detects_project_todo(vault, router):
    watcher = ObsidianWatcher(vault_path=vault, router=router)
    watcher.scan_files()

    tasks = vault / "Falkenstein" / "Projekte" / "website" / "Tasks.md"
    tasks.write_text(
        "# Tasks — website\n\n"
        "- [ ] [2026-04-01 10:00] Old task\n"
        "- [ ] [2026-04-03 15:00] New feature request\n"
    )
    new_todos = watcher.detect_changes()
    assert len(new_todos) == 1
    assert new_todos[0]["project"] == "website"
    assert "New feature request" in new_todos[0]["content"]


@pytest.mark.asyncio
async def test_no_duplicate_detection(vault, router):
    watcher = ObsidianWatcher(vault_path=vault, router=router)
    watcher.scan_files()

    inbox = vault / "Management" / "Inbox.md"
    inbox.write_text(
        "# Inbox\n\n- [ ] [2026-04-01 10:00] Existing todo\n"
        "- [ ] [2026-04-03 14:00] New todo\n"
    )
    # First detection
    new_todos = watcher.detect_changes()
    assert len(new_todos) == 1

    # Second detection without changes — should find nothing
    new_todos = watcher.detect_changes()
    assert len(new_todos) == 0


@pytest.mark.asyncio
async def test_new_project_tasks_file(vault, router):
    """A completely new project Tasks.md should be picked up."""
    watcher = ObsidianWatcher(vault_path=vault, router=router)
    watcher.scan_files()

    new_proj = vault / "Falkenstein" / "Projekte" / "newproj"
    new_proj.mkdir(parents=True)
    (new_proj / "Tasks.md").write_text(
        "# Tasks — newproj\n\n- [ ] [2026-04-03 16:00] Setup CI\n"
    )
    new_todos = watcher.detect_changes()
    assert len(new_todos) == 1
    assert new_todos[0]["project"] == "newproj"
```

- [ ] **Step 2: Run all watcher tests**

Run: `python -m pytest tests/test_obsidian_watcher.py -v`
Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_obsidian_watcher.py
git commit -m "test: comprehensive obsidian watcher tests — edge cases and duplicates"
```

---

### Task 5: Config-Erweiterung

**Files:**
- Modify: `backend/config.py:1-40`
- Modify: `.env.example`

- [ ] **Step 1: Add new settings to config.py**

In `backend/config.py`, add these three fields to the `Settings` class after line 27 (`ollama_num_ctx_extended`):

```python
    # Notification Router
    obsidian_watch_enabled: bool = True
    obsidian_auto_submit_tasks: bool = False
    llm_routing_enabled: bool = True
```

- [ ] **Step 2: Add to .env.example**

Append to `.env.example`:

```
# Notification Router
OBSIDIAN_WATCH_ENABLED=true
OBSIDIAN_AUTO_SUBMIT_TASKS=false
LLM_ROUTING_ENABLED=true
```

- [ ] **Step 3: Run existing tests to ensure nothing breaks**

Run: `python -m pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/config.py .env.example
git commit -m "feat: config settings for notification router and obsidian watcher"
```

---

### Task 6: ObsidianManager — Neue Methoden

**Files:**
- Modify: `backend/tools/obsidian_manager.py:58-77` (execute method) and add new methods
- Test: `tests/test_obsidian_manager.py` (erweitern oder prüfen ob es existiert)

- [ ] **Step 1: Write failing test for write_task_result**

```python
# tests/test_obsidian_manager_routing.py
import pytest
from pathlib import Path
from backend.tools.obsidian_manager import ObsidianManagerTool


@pytest.fixture
def vault(tmp_path):
    tool = ObsidianManagerTool(vault_path=tmp_path)
    return tmp_path, tool


@pytest.mark.asyncio
async def test_write_task_result_to_project(vault):
    tmp_path, tool = vault
    # Create project structure
    await tool.execute({"action": "project", "content": "website"})

    result = await tool.write_task_result(
        task_title="Login fixen",
        result="Fixed auth token validation in login.py",
        project="website",
        agent_name="Alex",
    )
    assert result.success

    tasks_path = tmp_path / "Falkenstein" / "Projekte" / "website" / "Tasks.md"
    content = tasks_path.read_text()
    assert "Login fixen" in content
    assert "Alex" in content
    assert "Fixed auth token" in content


@pytest.mark.asyncio
async def test_write_task_result_no_project(vault):
    tmp_path, tool = vault
    result = await tool.write_task_result(
        task_title="General cleanup",
        result="Removed unused imports",
        project=None,
        agent_name="Max",
    )
    assert result.success

    inbox = tmp_path / "Management" / "Inbox.md"
    content = inbox.read_text()
    assert "General cleanup" in content


@pytest.mark.asyncio
async def test_log_escalation(vault):
    tmp_path, tool = vault
    result = await tool.log_escalation(
        agent_name="Bob",
        task_title="Complex refactor",
        details="Claude CLI completed successfully after 3 retries",
    )
    assert result.success
    # Check daily report has escalation
    import datetime
    today = datetime.date.today().isoformat()
    report = tmp_path / "Falkenstein" / "Daily Reports" / f"{today}.md"
    content = report.read_text()
    assert "Eskalation" in content
    assert "Bob" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_obsidian_manager_routing.py -v`
Expected: FAIL — `AttributeError: 'ObsidianManagerTool' object has no attribute 'write_task_result'`

- [ ] **Step 3: Add write_task_result and log_escalation to ObsidianManagerTool**

Add before the `schema` method in `backend/tools/obsidian_manager.py` (before line 235):

```python
    async def write_task_result(self, task_title: str, result: str,
                                 project: str | None, agent_name: str) -> ToolResult:
        """Write a completed task result to the appropriate location."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        if project:
            md = f"\n\n### {task_title} ✅\n*{agent_name}* — {now}\n\n{result}"
            return await self._append(
                f"Falkenstein/Projekte/{project}/Tasks.md", md
            )
        else:
            return await self._inbox(f"[DONE] {task_title} ({agent_name}): {result[:300]}")

    async def log_escalation(self, agent_name: str, task_title: str,
                              details: str) -> ToolResult:
        """Log escalation details to the daily report."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        md = (
            f"## Eskalation: {task_title}\n"
            f"*{agent_name}* — {now}\n\n{details}"
        )
        return await self._daily_report(md)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_obsidian_manager_routing.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tools/obsidian_manager.py tests/test_obsidian_manager_routing.py
git commit -m "feat: obsidian manager write_task_result and log_escalation methods"
```

---

### Task 7: main.py — Router + Watcher integrieren

**Files:**
- Modify: `backend/main.py:1-42` (imports + globals)
- Modify: `backend/main.py:45-111` (sim_loop)
- Modify: `backend/main.py:114-129` (_notify_telegram → entfernen)
- Modify: `backend/main.py:186-200` (/todo command)
- Modify: `backend/main.py:269-341` (lifespan)

- [ ] **Step 1: Add imports and globals**

Add after line 27 (`from backend.daily_report import DailyReportGenerator`):

```python
from backend.notification_router import NotificationRouter
from backend.obsidian_watcher import ObsidianWatcher
```

Add after line 42 (`daily_reporter: DailyReportGenerator = None`):

```python
notification_router: NotificationRouter = None
obsidian_watcher: ObsidianWatcher = None
watcher_task: asyncio.Task = None
```

- [ ] **Step 2: Replace _notify_telegram with router.route_event in sim_loop**

Replace the sim_loop event notification block (lines 57-62) from:

```python
            for event in events:
                await ws_mgr.broadcast(event)

                # Telegram notifications for key events
                if telegram and telegram.enabled:
                    await _notify_telegram(event)
```

To:

```python
            for event in events:
                await ws_mgr.broadcast(event)

                # Route events to Telegram and/or Obsidian
                if notification_router:
                    etype = event.get("type", "")
                    agent_id = event.get("agent", "")
                    agent = pool.get_agent(agent_id) if agent_id else None
                    payload = {
                        **event,
                        "agent_name": agent.data.name if agent else agent_id,
                    }
                    await notification_router.route_event(etype, payload)
```

- [ ] **Step 3: Replace task_assigned notification (lines 75-78)**

Replace:

```python
                if telegram and telegram.enabled:
                    await telegram.notify_task_assigned(
                        assigned.get("agent", "?"), assigned.get("task_title", "")
                    )
```

With:

```python
                if notification_router:
                    agent_id = assigned.get("agent", "")
                    agent = pool.get_agent(agent_id) if agent_id else None
                    await notification_router.route_event("task_assigned", {
                        "agent_name": agent.data.name if agent else agent_id,
                        "task_title": assigned.get("task_title", ""),
                    })
```

- [ ] **Step 4: Replace daily report section (lines 92-106)**

Replace:

```python
            if daily_reporter and daily_reporter.should_generate():
                try:
                    report = await daily_reporter.generate()
                    # Save to Obsidian
                    obsidian = pool.agents[0].tools.get("obsidian_manager")
                    if obsidian:
                        await obsidian.execute({"action": "daily_report", "content": report})
                    # Send to Telegram
                    if telegram and telegram.enabled:
                        summary = await daily_reporter.generate_telegram_summary()
                        await telegram.send_message(summary)
                    await ws_mgr.broadcast({"type": "daily_report_generated"})
                except Exception as e:
                    print(f"Daily report error: {e}")
```

With:

```python
            if daily_reporter and daily_reporter.should_generate():
                try:
                    report = await daily_reporter.generate()
                    summary = await daily_reporter.generate_telegram_summary()
                    if notification_router:
                        await notification_router.route_event("daily_report", {
                            "content": summary,  # Telegram gets summary
                        })
                        # Full report to Obsidian directly (not through router formatting)
                        obsidian = pool.agents[0].tools.get("obsidian_manager")
                        if obsidian:
                            await obsidian.execute({"action": "daily_report", "content": report})
                    await ws_mgr.broadcast({"type": "daily_report_generated"})
                except Exception as e:
                    print(f"Daily report error: {e}")
```

- [ ] **Step 5: Delete _notify_telegram function (lines 114-129)**

Remove the entire `_notify_telegram` function — it's replaced by the router.

- [ ] **Step 6: Update /todo command to inform router (lines 186-200)**

Replace the /todo handler:

```python
    elif text.startswith("/todo"):
        todo_text = text[5:].strip()
        if not todo_text:
            await telegram.send_message("Nutzung: `/todo Text` oder `/todo Text | Projektname`")
            return
        # Parse optional project: "/todo Fix bug | website"
        parts = todo_text.split("|", 1)
        content = parts[0].strip()
        project = parts[1].strip() if len(parts) > 1 else None
        obsidian = pool.agents[0].tools.get("obsidian_manager")
        if obsidian:
            result = await obsidian.execute({"action": "todo", "content": content, "project": project})
            await telegram.send_message(f"✅ {result.output}")
        else:
            await telegram.send_message("Obsidian nicht verfügbar.")
```

With:

```python
    elif text.startswith("/todo"):
        todo_text = text[5:].strip()
        if not todo_text:
            await telegram.send_message("Nutzung: `/todo Text` oder `/todo Text | Projektname`")
            return
        parts = todo_text.split("|", 1)
        content = parts[0].strip()
        project = parts[1].strip() if len(parts) > 1 else None
        obsidian = pool.agents[0].tools.get("obsidian_manager")
        if obsidian:
            result = await obsidian.execute({"action": "todo", "content": content, "project": project})
            await telegram.send_message(f"✅ {result.output}")
            # Auto-submit as agent task if configured
            if settings.obsidian_auto_submit_tasks:
                await orchestrator.submit_task(title=content[:100], description=content, project=project)
                await orchestrator.assign_next_task()
        else:
            await telegram.send_message("Obsidian nicht verfügbar.")
```

- [ ] **Step 7: Update lifespan — init router + watcher**

In the lifespan function, after `daily_reporter = DailyReportGenerator(db=db, pool=pool)` (line 316), add:

```python
    # Notification Router
    obsidian_tool = tools.get("obsidian_manager")
    notification_router = NotificationRouter(
        telegram=telegram if telegram and telegram.enabled else None,
        obsidian=obsidian_tool,
        llm=llm,
        llm_routing_enabled=settings.llm_routing_enabled,
    )
```

After the Telegram task creation block (after line 325), add:

```python
    # Start Obsidian Watcher if configured
    if settings.obsidian_watch_enabled and settings.obsidian_vault_path.exists():
        obsidian_watcher = ObsidianWatcher(
            vault_path=settings.obsidian_vault_path,
            router=notification_router,
        )
        watcher_task = asyncio.create_task(obsidian_watcher.start())
        print("Obsidian watcher active")
```

In the shutdown section, after the telegram_task cancellation (after line 340), add:

```python
    if watcher_task:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
```

Also update the globals line (line 271) to include the new globals:

```python
    global db, pool, orchestrator, sim, sim_task, telegram_task
    global rel_engine, personality_engine, telegram, budget_tracker, llm_client, daily_reporter
    global notification_router, obsidian_watcher, watcher_task
```

- [ ] **Step 8: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add backend/main.py
git commit -m "feat: integrate notification router and obsidian watcher into main server"
```

---

### Task 8: requirements.txt — watchdog hinzufügen

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add watchdog**

Add to `requirements.txt`:

```
watchdog>=4.0.0
```

- [ ] **Step 2: Install**

Run: `pip install watchdog>=4.0.0`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add watchdog for obsidian file watching"
```

---

### Task 9: Integration-Test

**Files:**
- Create: `tests/test_integration_routing.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_integration_routing.py
"""End-to-end tests: events flow through router to correct targets."""
import pytest
from unittest.mock import AsyncMock
from backend.notification_router import NotificationRouter
from backend.obsidian_watcher import ObsidianWatcher


@pytest.fixture
def telegram():
    t = AsyncMock()
    t.enabled = True
    t.send_message = AsyncMock(return_value=True)
    return t


@pytest.fixture
def obsidian():
    o = AsyncMock()
    o.execute = AsyncMock()
    return o


@pytest.fixture
def llm():
    l = AsyncMock()
    l.model_light = "test"
    l.chat = AsyncMock(return_value="Ja")
    return l


@pytest.fixture
def router(telegram, obsidian, llm):
    return NotificationRouter(telegram=telegram, obsidian=obsidian, llm=llm)


@pytest.mark.asyncio
async def test_full_task_lifecycle(router, telegram, obsidian):
    """Task assigned → completed → both targets get correct messages."""
    # Assigned — only telegram
    await router.route_event("task_assigned", {
        "agent_name": "Alex",
        "task_title": "Build API",
    })
    assert telegram.send_message.call_count == 1
    assert obsidian.execute.call_count == 0

    telegram.send_message.reset_mock()

    # Completed with long result — both
    await router.route_event("task_completed", {
        "agent_name": "Alex",
        "task_title": "Build API",
        "result": "Implemented REST API with 5 endpoints: GET/POST /users, GET/POST /tasks, DELETE /tasks/:id. All tests passing.",
        "project": "backend",
    })
    assert telegram.send_message.call_count == 1
    assert obsidian.execute.call_count == 1


@pytest.mark.asyncio
async def test_obsidian_todo_triggers_telegram(tmp_path, telegram, obsidian, llm):
    """Todo added in Obsidian → Telegram notification."""
    router = NotificationRouter(telegram=telegram, obsidian=obsidian, llm=llm)
    watcher = ObsidianWatcher(vault_path=tmp_path, router=router)

    # Setup vault
    mgmt = tmp_path / "Management"
    mgmt.mkdir()
    inbox = mgmt / "Inbox.md"
    inbox.write_text("# Inbox\n")
    watcher.scan_files()

    # Simulate new todo
    inbox.write_text("# Inbox\n\n- [ ] [2026-04-03 14:00] Deploy v2.0\n")
    new_todos = watcher.detect_changes()
    assert len(new_todos) == 1

    # Route via router
    for todo in new_todos:
        await router.route_event("todo_from_obsidian", todo)

    telegram.send_message.assert_called_once()
    assert "Obsidian" in telegram.send_message.call_args[0][0]
    assert "Deploy v2.0" in telegram.send_message.call_args[0][0]
    # Obsidian should NOT be written (already there)
    obsidian.execute.assert_not_called()


@pytest.mark.asyncio
async def test_escalation_full_flow(router, telegram, obsidian):
    """Escalation success → Telegram warning + Obsidian daily report."""
    await router.route_event("escalation_success", {
        "agent_name": "Bob",
        "task_title": "Complex migration",
        "details": "Claude CLI refactored 15 files, all tests green",
    })
    telegram.send_message.assert_called_once()
    assert "Eskalation" in telegram.send_message.call_args[0][0]
    obsidian.execute.assert_called_once()
    assert obsidian.execute.call_args[0][0]["action"] == "daily_report"
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_integration_routing.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_routing.py
git commit -m "test: end-to-end integration tests for notification routing"
```
