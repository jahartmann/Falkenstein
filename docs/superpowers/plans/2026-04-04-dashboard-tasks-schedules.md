# Dashboard, Tasks & Schedules Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Falkenstein dashboard as a sidebar-navigated control center with robust task CRUD (filterable table, expandable rows, manual status changes), reliable schedule management (inline editing, next-run previews, cron warning), and a clean Tailwind-dark UI.

**Architecture:** Icon-sidebar (48px fixed left) navigates 4 sections: Dashboard, Tasks, Schedules, Config (drawer). Backend gets new filtered task queries, single-task endpoint, PATCH/DELETE endpoints, and scheduler timing fixes. Frontend is a full rewrite of dashboard.html/css/js — vanilla JS, no framework.

**Tech Stack:** FastAPI, aiosqlite, vanilla JS, CSS custom properties (Tailwind gray palette)

---

### Task 1: Backend — Database Task CRUD Methods

**Files:**
- Modify: `backend/database.py:210-303`
- Test: `tests/test_database_tasks.py` (create)

- [ ] **Step 1: Write failing tests for new task methods**

```python
# tests/test_database_tasks.py
import pytest
import asyncio
from pathlib import Path
from backend.database import Database
from backend.models import TaskData, TaskStatus


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_get_all_tasks_no_filter(db):
    for i in range(5):
        await db.create_task(TaskData(title=f"Task {i}", description="desc", status=TaskStatus.OPEN))
    result = await db.get_all_tasks(limit=50, offset=0)
    assert len(result) == 5
    # Ordered by created_at DESC
    assert result[0].title == "Task 4"


@pytest.mark.asyncio
async def test_get_all_tasks_filter_status(db):
    await db.create_task(TaskData(title="open1", description="d", status=TaskStatus.OPEN))
    t2 = await db.create_task(TaskData(title="done1", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t2, TaskStatus.DONE)
    result = await db.get_all_tasks(status="done")
    assert len(result) == 1
    assert result[0].title == "done1"


@pytest.mark.asyncio
async def test_get_all_tasks_filter_agent(db):
    t1 = await db.create_task(TaskData(title="t1", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t1, TaskStatus.IN_PROGRESS, "researcher")
    t2 = await db.create_task(TaskData(title="t2", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t2, TaskStatus.IN_PROGRESS, "coder")
    result = await db.get_all_tasks(agent="researcher")
    assert len(result) == 1
    assert result[0].title == "t1"


@pytest.mark.asyncio
async def test_get_all_tasks_search(db):
    await db.create_task(TaskData(title="News recherche", description="daily news", status=TaskStatus.OPEN))
    await db.create_task(TaskData(title="Backup DB", description="run backup", status=TaskStatus.OPEN))
    result = await db.get_all_tasks(search="news")
    assert len(result) == 1
    assert result[0].title == "News recherche"


@pytest.mark.asyncio
async def test_get_all_tasks_pagination(db):
    for i in range(10):
        await db.create_task(TaskData(title=f"Task {i}", description="d", status=TaskStatus.OPEN))
    page1 = await db.get_all_tasks(limit=3, offset=0)
    page2 = await db.get_all_tasks(limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 3
    assert page1[0].id != page2[0].id


@pytest.mark.asyncio
async def test_get_task_count(db):
    await db.create_task(TaskData(title="t1", description="d", status=TaskStatus.OPEN))
    t2 = await db.create_task(TaskData(title="t2", description="d", status=TaskStatus.OPEN))
    await db.update_task_status(t2, TaskStatus.DONE)
    assert await db.get_task_count() == 2
    assert await db.get_task_count(status="open") == 1


@pytest.mark.asyncio
async def test_delete_task(db):
    tid = await db.create_task(TaskData(title="del me", description="d", status=TaskStatus.OPEN))
    assert await db.delete_task(tid) is True
    assert await db.get_task(tid) is None
    assert await db.delete_task(999) is False


@pytest.mark.asyncio
async def test_update_task_status_manual(db):
    tid = await db.create_task(TaskData(title="t", description="d", status=TaskStatus.OPEN))
    assert await db.update_task_status_manual(tid, TaskStatus.DONE) is True
    task = await db.get_task(tid)
    assert task.status == TaskStatus.DONE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_database_tasks.py -v`
Expected: FAIL — `get_all_tasks`, `get_task_count`, `delete_task`, `update_task_status_manual` not defined.

- [ ] **Step 3: Implement the new methods in database.py**

Add after line 303 (after `all_subtasks_done`):

```python
    async def get_all_tasks(self, limit: int = 50, offset: int = 0,
                            status: str | None = None, agent: str | None = None,
                            search: str | None = None) -> list[TaskData]:
        """Get tasks with optional filters, ordered by created_at DESC."""
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if agent:
            query += " AND assigned_to = ?"
            params.append(agent)
        if search:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def get_task_count(self, status: str | None = None,
                             agent: str | None = None,
                             search: str | None = None) -> int:
        """Count tasks matching filters."""
        query = "SELECT COUNT(*) FROM tasks WHERE 1=1"
        params: list = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if agent:
            query += " AND assigned_to = ?"
            params.append(agent)
        if search:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        async with self._conn.execute(query, params) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def delete_task(self, task_id: int) -> bool:
        """Delete a task by ID. Returns True if deleted."""
        async with self._conn.execute(
            "DELETE FROM tasks WHERE id = ?", (task_id,)
        ) as cur:
            deleted = cur.rowcount > 0
        await self._conn.commit()
        return deleted

    async def update_task_status_manual(self, task_id: int, status: TaskStatus) -> bool:
        """Manually update task status (from dashboard)."""
        async with self._conn.execute(
            "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status.value, task_id),
        ) as cur:
            updated = cur.rowcount > 0
        await self._conn.commit()
        return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_database_tasks.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS (280+)

- [ ] **Step 6: Commit**

```bash
git add backend/database.py tests/test_database_tasks.py
git commit -m "feat: add filtered task queries, delete, manual status update to Database"
```

---

### Task 2: Backend — Admin API Task Endpoints

**Files:**
- Modify: `backend/admin_api.py:282-315`
- Test: `tests/test_admin_api_tasks.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_admin_api_tasks.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.models import TaskData, TaskStatus


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_all_tasks = AsyncMock(return_value=[
        TaskData(id=1, title="T1", description="d", status=TaskStatus.DONE, assigned_to="researcher", result="result text"),
    ])
    db.get_task_count = AsyncMock(return_value=1)
    db.get_task = AsyncMock(return_value=TaskData(id=1, title="T1", description="d", status=TaskStatus.DONE, result="full result"))
    db.delete_task = AsyncMock(return_value=True)
    db.update_task_status_manual = AsyncMock(return_value=True)
    return db


@pytest.mark.asyncio
async def test_get_tasks_filtered(mock_db):
    """GET /tasks with query params calls db.get_all_tasks with filters."""
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.get_tasks(status="done", agent="researcher", search="T1", limit=50, offset=0)
    mock_db.get_all_tasks.assert_called_once_with(limit=50, offset=0, status="done", agent="researcher", search="T1")
    assert result["total"] == 1
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["result"] == "result text"


@pytest.mark.asyncio
async def test_get_single_task(mock_db):
    """GET /tasks/{id} returns full task."""
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.get_single_task(1)
    assert result["title"] == "T1"
    assert result["result"] == "full result"


@pytest.mark.asyncio
async def test_patch_task_status(mock_db):
    """PATCH /tasks/{id} updates status."""
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.patch_task(1, admin_api.TaskPatch(status="done"))
    mock_db.update_task_status_manual.assert_called_once()
    assert result["updated"] is True


@pytest.mark.asyncio
async def test_delete_task_endpoint(mock_db):
    """DELETE /tasks/{id} deletes task."""
    from backend import admin_api
    admin_api._db = mock_db
    result = await admin_api.delete_task(1)
    mock_db.delete_task.assert_called_once_with(1)
    assert result["deleted"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_admin_api_tasks.py -v`
Expected: FAIL — functions not defined

- [ ] **Step 3: Add Pydantic model and rewrite task endpoints**

Add `TaskPatch` model after line 63 in `admin_api.py`:

```python
class TaskPatch(BaseModel):
    status: str
```

Replace the existing `GET /tasks` endpoint (lines 282-305) and add new endpoints:

```python
@router.get("/tasks")
async def get_tasks(status: str | None = None, agent: str | None = None,
                    search: str | None = None, limit: int = 50, offset: int = 0):
    """Get tasks with optional filters and pagination."""
    tasks = await _db.get_all_tasks(limit=limit, offset=offset, status=status, agent=agent, search=search)
    total = await _db.get_task_count(status=status, agent=agent, search=search)
    return {
        "tasks": [
            {
                "id": t.id, "title": t.title, "description": t.description,
                "status": t.status.value, "agent": t.assigned_to or "",
                "result": t.result or "", "project": t.project or "",
                "created_at": str(t.created_at) if t.created_at else "",
                "updated_at": str(t.updated_at) if t.updated_at else "",
            }
            for t in tasks
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tasks/{task_id}")
async def get_single_task(task_id: int):
    """Get a single task with full result."""
    task = await _db.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    return {
        "id": task.id, "title": task.title, "description": task.description,
        "status": task.status.value, "agent": task.assigned_to or "",
        "result": task.result or "", "project": task.project or "",
        "created_at": str(task.created_at) if task.created_at else "",
        "updated_at": str(task.updated_at) if task.updated_at else "",
    }


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: int, patch: TaskPatch):
    """Manually update task status from dashboard."""
    status = TaskStatus(patch.status)
    updated = await _db.update_task_status_manual(task_id, status)
    return {"updated": updated}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    """Delete a task."""
    deleted = await _db.delete_task(task_id)
    return {"deleted": deleted}
```

Keep the existing `POST /tasks/submit` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_admin_api_tasks.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/admin_api.py tests/test_admin_api_tasks.py
git commit -m "feat: add filtered GET, single GET, PATCH, DELETE task endpoints"
```

---

### Task 3: Backend — Scheduler Fixes

**Files:**
- Modify: `backend/scheduler.py`
- Test: `tests/test_scheduler_fixes.py` (create)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scheduler_fixes.py
import pytest
import datetime
from unittest.mock import AsyncMock, MagicMock
from backend.scheduler import Scheduler, parse_schedule, next_run


@pytest.mark.asyncio
async def test_reload_preserves_next_run():
    """reload_tasks should preserve _next_run for unchanged schedules."""
    db = AsyncMock()
    sched = Scheduler(db)

    # First load: one schedule
    db.get_all_schedules.return_value = [
        {"id": 1, "name": "Test", "schedule": "täglich 09:00", "agent_type": "ops",
         "prompt": "do stuff", "active": 1, "active_hours": None, "light_context": 0,
         "last_run": None, "last_status": None, "last_error": None}
    ]
    await sched.load_tasks()
    original_next_run = sched.tasks[0]["_next_run"]

    # Reload: same schedule should keep its _next_run
    await sched.reload_tasks()
    assert sched.tasks[0]["_next_run"] == original_next_run


@pytest.mark.asyncio
async def test_cron_syntax_sets_error():
    """cron: prefix should deactivate schedule and set error."""
    db = AsyncMock()
    sched = Scheduler(db)

    db.get_all_schedules.return_value = [
        {"id": 1, "name": "Cron", "schedule": "cron: 0 9 * * 1-5", "agent_type": "ops",
         "prompt": "do stuff", "active": 1, "active_hours": None, "light_context": 0,
         "last_run": None, "last_status": None, "last_error": None}
    ]
    await sched.load_tasks()

    # Should have called update_schedule_result with error
    db.update_schedule_result.assert_called_once()
    call_args = db.update_schedule_result.call_args
    assert call_args[0][1] == "error"
    assert "nicht unterstützt" in call_args[0][2].lower() or "cron" in call_args[0][2].lower()


def test_get_next_runs():
    """get_next_runs should return N future run times."""
    sched_dict = parse_schedule("täglich 09:00")
    from backend.scheduler import get_next_runs
    now = datetime.datetime(2026, 4, 4, 10, 0)
    runs = get_next_runs(sched_dict, count=3, after=now)
    assert len(runs) == 3
    assert runs[0] == datetime.datetime(2026, 4, 5, 9, 0)
    assert runs[1] == datetime.datetime(2026, 4, 6, 9, 0)
    assert runs[2] == datetime.datetime(2026, 4, 7, 9, 0)


def test_tasks_info_includes_full_prompt():
    """get_all_tasks_info should include full prompt, not just preview."""
    from backend.scheduler import Scheduler
    sched = Scheduler.__new__(Scheduler)
    sched.tasks = [
        {"id": 1, "name": "T", "schedule": "stündlich", "agent_type": "ops",
         "prompt": "A" * 500, "active": 1, "active_hours": None,
         "_next_run": datetime.datetime.now(), "_last_run": None,
         "last_status": None, "last_error": None}
    ]
    info = sched.get_all_tasks_info()
    assert len(info[0]["prompt"]) == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler_fixes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement scheduler fixes**

Replace `backend/scheduler.py` with these changes:

**Add `get_next_runs` function** after the `next_run` function (after line ~118):

```python
def get_next_runs(schedule: dict, count: int = 3, after: datetime.datetime | None = None) -> list[datetime.datetime]:
    """Compute the next N run times for a schedule."""
    if after is None:
        after = datetime.datetime.now()
    runs = []
    current = after
    for _ in range(count):
        nxt = next_run(schedule, current)
        runs.append(nxt)
        current = nxt
    return runs
```

**Fix `reload_tasks`** — replace the method (line 178):

```python
    async def reload_tasks(self) -> None:
        """Reload schedules from DB, preserving _next_run for unchanged tasks."""
        old_runs = {t["id"]: t["_next_run"] for t in self.tasks}
        old_last_run = {t["id"]: t.get("_last_run") for t in self.tasks}
        await self.load_tasks()
        # Restore _next_run for schedules that haven't changed
        for t in self.tasks:
            tid = t["id"]
            if tid in old_runs and old_last_run.get(tid) == t.get("_last_run"):
                t["_next_run"] = old_runs[tid]
```

**Fix `load_tasks` to handle cron warning** — in the `load_tasks` method, after parsing each schedule, add cron detection:

```python
    async def load_tasks(self) -> None:
        rows = await self.db.get_all_schedules()
        self.tasks = []
        for row in rows:
            parsed = parse_schedule(row["schedule"])
            # Warn and deactivate cron schedules
            if parsed.get("type") == "cron":
                await self.db.update_schedule_result(
                    row["id"], "error",
                    "Cron-Syntax nicht unterstützt. Verwende deutsche Zeitangaben (z.B. 'täglich 09:00')."
                )
                continue
            last_run = None
            if row.get("last_run"):
                try:
                    last_run = datetime.datetime.fromisoformat(row["last_run"])
                except (ValueError, TypeError):
                    pass
            after = last_run or datetime.datetime.now()
            task = {**row, "_parsed": parsed, "_next_run": next_run(parsed, after), "_last_run": last_run}
            self.tasks.append(task)
```

**Fix `get_all_tasks_info`** — replace `prompt_preview` with full `prompt`:

```python
    def get_all_tasks_info(self) -> list[dict]:
        result = []
        for t in self.tasks:
            result.append({
                "id": t["id"],
                "name": t["name"],
                "schedule": t.get("schedule", ""),
                "agent_type": t.get("agent_type", ""),
                "active": t.get("active", 0),
                "last_run": str(t["_last_run"]) if t.get("_last_run") else None,
                "last_status": t.get("last_status"),
                "last_error": t.get("last_error"),
                "next_run": t["_next_run"].isoformat() if t.get("_next_run") else None,
                "prompt": t.get("prompt", ""),
                "active_hours": t.get("active_hours"),
            })
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler_fixes.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/scheduler.py tests/test_scheduler_fixes.py
git commit -m "fix: scheduler preserves timing on reload, warns on cron, adds get_next_runs"
```

---

### Task 4: Backend — Schedule API Enhancements

**Files:**
- Modify: `backend/admin_api.py:125-245`

- [ ] **Step 1: Add next_runs_preview to GET /schedules/{id}**

Replace the `get_schedule_detail` handler (line 132):

```python
@router.get("/schedules/{schedule_id}")
async def get_schedule_detail(schedule_id: int):
    row = await _db.get_schedule(schedule_id)
    if not row:
        return {"error": "Schedule nicht gefunden"}
    # Add next runs preview
    from backend.scheduler import parse_schedule, get_next_runs
    parsed = parse_schedule(row.get("schedule", ""))
    preview = []
    if parsed.get("type") != "cron":
        runs = get_next_runs(parsed, count=3)
        preview = [r.isoformat() for r in runs]
    return {**row, "next_runs_preview": preview}
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/admin_api.py
git commit -m "feat: schedule detail endpoint includes next_runs_preview"
```

---

### Task 5: Backend — WebSocket Events for Activity Feed

**Files:**
- Modify: `backend/main_agent.py`

- [ ] **Step 1: Add task_created WS events in _handle_action and _handle_content**

In `_handle_action` (after `task_id = await self.db.create_task(task)`, around line 511), add:

```python
            if self.ws_callback:
                await self.ws_callback({"type": "task_created", "task_id": task_id, "title": title})
```

In `_handle_content` (after `task_id = await self.db.create_task(task)`, around line 601), add:

```python
            if self.ws_callback:
                await self.ws_callback({"type": "task_created", "task_id": task_id, "title": title})
```

In `handle_scheduled` (after `task_id = await self.db.create_task(db_task)`, around line 698), add:

```python
        if self.ws_callback:
            await self.ws_callback({"type": "task_created", "task_id": task_id, "title": f"[Schedule] {name}"})
```

- [ ] **Step 2: Add schedule_fired WS event in handle_scheduled**

In `handle_scheduled`, after the `agent_spawned` WS event (around line 707), add:

```python
        if self.ws_callback:
            await self.ws_callback({"type": "schedule_fired", "schedule_id": schedule_id, "name": name})
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add backend/main_agent.py
git commit -m "feat: emit task_created and schedule_fired WS events for activity feed"
```

---

### Task 6: Frontend — Dashboard HTML Rewrite (Sidebar Layout)

**Files:**
- Rewrite: `frontend/dashboard.html`

- [ ] **Step 1: Rewrite dashboard.html with sidebar layout**

```html
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Falkenstein</title>
  <link rel="stylesheet" href="/static/dashboard.css">
</head>
<body>
  <div class="app">
    <!-- Sidebar -->
    <nav class="sidebar">
      <div class="sidebar-top">
        <div class="sidebar-logo">F</div>
        <button class="sidebar-btn active" data-section="dashboard" title="Dashboard">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="2" y="2" width="7" height="7" rx="1.5"/><rect x="11" y="2" width="7" height="7" rx="1.5"/>
            <rect x="2" y="11" width="7" height="7" rx="1.5"/><rect x="11" y="11" width="7" height="7" rx="1.5"/>
          </svg>
        </button>
        <button class="sidebar-btn" data-section="tasks" title="Tasks">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="3" y="3" width="14" height="14" rx="2"/><path d="M7 10l2 2 4-4"/>
          </svg>
        </button>
        <button class="sidebar-btn" data-section="schedules" title="Schedules">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.5 2.5"/>
          </svg>
        </button>
      </div>
      <div class="sidebar-bottom">
        <button class="sidebar-btn" data-section="config" title="Config">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="10" cy="10" r="3"/><path d="M10 2v2m0 12v2M2 10h2m12 0h2M4.22 4.22l1.42 1.42m8.72 8.72l1.42 1.42M4.22 15.78l1.42-1.42m8.72-8.72l1.42-1.42"/>
          </svg>
        </button>
        <div class="sidebar-status">
          <div class="status-dot" id="ws-dot"></div>
          <div class="status-dot" id="ollama-dot"></div>
        </div>
      </div>
    </nav>

    <!-- Main Content -->
    <main class="content">
      <!-- Dashboard Section -->
      <section class="section active" id="section-dashboard">
        <div class="section-header">
          <h1>Dashboard</h1>
          <div class="ws-indicator">
            <span id="ws-status">Verbinde...</span>
          </div>
        </div>

        <div class="stats-row">
          <div class="stat-card">
            <div class="stat-label">Aktive Agents</div>
            <div class="stat-value" id="stat-agents">0</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Offene Tasks</div>
            <div class="stat-value" id="stat-tasks">0</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Aktive Schedules</div>
            <div class="stat-value" id="stat-schedules">0</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Fehler heute</div>
            <div class="stat-value" id="stat-errors">0</div>
          </div>
        </div>

        <div class="panels">
          <div class="panel">
            <h2>Aktive Agents</h2>
            <div id="agents-list" class="agents-list">
              <span class="text-muted">Keine aktiven Agents</span>
            </div>
          </div>
          <div class="panel">
            <h2>Letzte Aktivität</h2>
            <div id="activity-feed" class="activity-feed">
              <span class="text-muted">Keine Aktivität</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Tasks Section -->
      <section class="section" id="section-tasks">
        <div class="section-header">
          <h1>Tasks</h1>
          <button class="btn btn-primary" onclick="openModal('modal-task')">+ Neuer Task</button>
        </div>

        <div class="filter-bar">
          <select id="filter-status" onchange="loadTasks()">
            <option value="">Alle Status</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="done">Done</option>
            <option value="failed">Failed</option>
          </select>
          <select id="filter-agent" onchange="loadTasks()">
            <option value="">Alle Agents</option>
            <option value="coder">Coder</option>
            <option value="researcher">Researcher</option>
            <option value="writer">Writer</option>
            <option value="ops">Ops</option>
          </select>
          <input type="text" id="filter-search" placeholder="Suche..." oninput="debouncedLoadTasks()">
        </div>

        <div class="card">
          <table>
            <thead>
              <tr>
                <th style="width:50px">ID</th>
                <th>Titel</th>
                <th style="width:100px">Status</th>
                <th style="width:100px">Agent</th>
                <th style="width:120px">Erstellt</th>
                <th style="width:150px">Ergebnis</th>
                <th style="width:80px">Aktionen</th>
              </tr>
            </thead>
            <tbody id="tasks-table"></tbody>
          </table>
          <div class="pagination" id="tasks-pagination"></div>
        </div>
      </section>

      <!-- Schedules Section -->
      <section class="section" id="section-schedules">
        <div class="section-header">
          <h1>Schedules</h1>
          <div class="btn-group">
            <button class="btn btn-primary" onclick="openScheduleModal()">+ Manuell</button>
            <button class="btn" onclick="openModal('modal-ai-schedule')">KI-Erstellen</button>
          </div>
        </div>

        <div class="card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th style="width:160px">Zeitplan</th>
                <th style="width:90px">Agent</th>
                <th style="width:70px">Aktiv</th>
                <th style="width:120px">Letzter Lauf</th>
                <th style="width:120px">Nächster Lauf</th>
                <th style="width:90px">Ergebnis</th>
                <th style="width:120px">Aktionen</th>
              </tr>
            </thead>
            <tbody id="schedules-table"></tbody>
          </table>
        </div>
      </section>

      <!-- Config Section -->
      <section class="section" id="section-config">
        <div class="section-header">
          <h1>Konfiguration</h1>
        </div>
        <div id="config-container"></div>
      </section>
    </main>
  </div>

  <!-- Task Modal -->
  <div class="modal-overlay" id="modal-task" onclick="closeModalOverlay(event)">
    <div class="modal">
      <h2>Neuer Task</h2>
      <div class="form-group">
        <label>Beschreibung</label>
        <textarea id="task-text" rows="4" placeholder="Was soll Falki tun?"></textarea>
      </div>
      <div class="modal-actions">
        <button class="btn" onclick="closeModal('modal-task')">Abbrechen</button>
        <button class="btn btn-primary" onclick="submitTask()">Absenden</button>
      </div>
    </div>
  </div>

  <!-- Schedule Modal -->
  <div class="modal-overlay" id="modal-schedule" onclick="closeModalOverlay(event)">
    <div class="modal">
      <h2 id="schedule-modal-title">Neuer Schedule</h2>
      <input type="hidden" id="schedule-edit-id">
      <div class="form-group">
        <label>Name</label>
        <input type="text" id="sched-name" placeholder="z.B. Morgen-Briefing">
      </div>
      <div class="form-group">
        <label>Zeitplan</label>
        <input type="text" id="sched-schedule" placeholder="z.B. täglich 09:00, alle 30 Minuten">
      </div>
      <div class="form-group">
        <label>Agent-Typ</label>
        <select id="sched-agent-type">
          <option value="researcher">Researcher</option>
          <option value="writer">Writer</option>
          <option value="coder">Coder</option>
          <option value="ops">Ops</option>
        </select>
      </div>
      <div class="form-group">
        <label>Aktive Stunden (optional)</label>
        <input type="text" id="sched-active-hours" placeholder="z.B. 08:00-20:00">
      </div>
      <div class="form-group">
        <label>Prompt</label>
        <textarea id="sched-prompt" rows="4" placeholder="Was soll der Agent tun?"></textarea>
      </div>
      <div id="schedule-preview" class="schedule-preview"></div>
      <div class="modal-actions">
        <button class="btn" onclick="closeModal('modal-schedule')">Abbrechen</button>
        <button class="btn btn-primary" onclick="saveSchedule()">Speichern</button>
      </div>
    </div>
  </div>

  <!-- AI Schedule Modal -->
  <div class="modal-overlay" id="modal-ai-schedule" onclick="closeModalOverlay(event)">
    <div class="modal">
      <h2>Schedule per KI erstellen</h2>
      <div class="form-group">
        <label>Beschreibe den gewünschten Schedule</label>
        <textarea id="ai-sched-desc" rows="4" placeholder="z.B. Jeden Morgen um 9 die Tech-News zusammenfassen"></textarea>
      </div>
      <div class="modal-actions">
        <button class="btn" onclick="closeModal('modal-ai-schedule')">Abbrechen</button>
        <button class="btn btn-primary" onclick="aiCreateSchedule()">Erstellen</button>
      </div>
    </div>
  </div>

  <!-- Task Detail Slide-out -->
  <div class="slideout" id="task-detail">
    <div class="slideout-header">
      <h2 id="detail-title">Task</h2>
      <button class="btn btn-sm" onclick="closeSlideout()">×</button>
    </div>
    <div class="slideout-body" id="detail-body"></div>
  </div>

  <script src="/static/dashboard.js"></script>
</body>
</html>
```

- [ ] **Step 2: Verify file saved correctly**

Run: `python -m backend.main &` then open `http://localhost:8800` — should show sidebar layout (unstyled until CSS is updated). Kill server.

- [ ] **Step 3: Commit**

```bash
git add frontend/dashboard.html
git commit -m "feat: rewrite dashboard HTML with sidebar navigation layout"
```

---

### Task 7: Frontend — CSS Rewrite (Tailwind Dark Theme)

**Files:**
- Rewrite: `frontend/dashboard.css`

- [ ] **Step 1: Rewrite CSS with sidebar layout and Tailwind-dark palette**

```css
/* ── Falkenstein Dashboard — Tailwind Dark Theme ──────────────────── */
:root {
  --bg: #111827;
  --bg-secondary: #1f2937;
  --border: #374151;
  --text: #f9fafb;
  --text-secondary: #d1d5db;
  --text-muted: #9ca3af;
  --accent: #6366f1;
  --accent-hover: #818cf8;
  --green: #10b981;
  --green-bg: rgba(16,185,129,.12);
  --red: #ef4444;
  --red-bg: rgba(239,68,68,.12);
  --blue: #3b82f6;
  --blue-bg: rgba(59,130,246,.12);
  --amber: #f59e0b;
  --amber-bg: rgba(245,158,11,.12);
  --purple: #8b5cf6;
  --purple-bg: rgba(139,92,246,.12);
  --cyan: #06b6d4;
  --cyan-bg: rgba(6,182,212,.12);
  --radius: 8px;
  --radius-lg: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}

/* ── App Layout ───────────────────────────────────────────────────── */
.app {
  display: flex;
  min-height: 100vh;
}

/* ── Sidebar ──────────────────────────────────────────────────────── */
.sidebar {
  width: 56px;
  background: #0d1117;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 12px 0;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 100;
}

.sidebar-top, .sidebar-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.sidebar-logo {
  width: 36px;
  height: 36px;
  background: var(--accent);
  color: #fff;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 12px;
}

.sidebar-btn {
  width: 40px;
  height: 40px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  border-radius: var(--radius);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all .15s;
  position: relative;
}

.sidebar-btn:hover { color: var(--text-secondary); background: var(--bg-secondary); }

.sidebar-btn.active {
  color: var(--accent);
  background: rgba(99,102,241,.1);
}

.sidebar-btn.active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 8px;
  bottom: 8px;
  width: 3px;
  background: var(--accent);
  border-radius: 0 2px 2px 0;
}

.sidebar-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--red);
}

.status-dot.connected { background: var(--green); }

/* ── Content ──────────────────────────────────────────────────────── */
.content {
  flex: 1;
  margin-left: 56px;
  min-height: 100vh;
}

.section { display: none; padding: 24px 32px; }
.section.active { display: block; }

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.section-header h1 {
  font-size: 22px;
  font-weight: 600;
}

.ws-indicator {
  font-size: 13px;
  color: var(--text-muted);
}

/* ── Stats ────────────────────────────────────────────────────────── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 20px;
}

.stat-label { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: .3px; }
.stat-value { font-size: 28px; font-weight: 600; }

/* ── Panels ───────────────────────────────────────────────────────── */
.panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.panel {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}

.panel h2 { font-size: 14px; font-weight: 600; margin-bottom: 16px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .3px; }

/* ── Agents ───────────────────────────────────────────────────────── */
.agents-list { display: flex; flex-direction: column; gap: 8px; }

.agent-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 13px;
}

.agent-pulse {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--green);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .4; transform: scale(1.3); }
}

.agent-type { font-size: 11px; color: var(--text-muted); margin-left: auto; }

.text-muted { color: var(--text-muted); font-size: 13px; }

/* ── Activity Feed ────────────────────────────────────────────────── */
.activity-feed { display: flex; flex-direction: column; gap: 6px; max-height: 300px; overflow-y: auto; }

.activity-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

.activity-item:last-child { border-bottom: none; }

.activity-icon { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

.activity-time { color: var(--text-muted); font-size: 11px; margin-left: auto; flex-shrink: 0; }

/* ── Filter Bar ───────────────────────────────────────────────────── */
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.filter-bar select, .filter-bar input {
  width: auto;
  min-width: 140px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 13px;
}

.filter-bar input { flex: 1; min-width: 200px; }

/* ── Cards / Tables ───────────────────────────────────────────────── */
.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

table { width: 100%; border-collapse: collapse; }

th {
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--text-muted);
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  background: rgba(0,0,0,.15);
}

td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
}

tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,.02); }
tr.expandable { cursor: pointer; }

/* Expanded row */
.task-expanded {
  background: var(--bg);
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.task-expanded pre {
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px;
  font-size: 12px;
  max-height: 400px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-secondary);
  margin: 8px 0;
}

.task-expanded .meta { font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }

.task-actions { display: flex; gap: 8px; align-items: center; margin-top: 12px; }

/* ── Badges ───────────────────────────────────────────────────────── */
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.badge-open { background: var(--blue-bg); color: var(--blue); }
.badge-in_progress { background: var(--amber-bg); color: var(--amber); }
.badge-done { background: var(--green-bg); color: var(--green); }
.badge-failed { background: var(--red-bg); color: var(--red); }
.badge-active { background: var(--green-bg); color: var(--green); }
.badge-inactive { background: rgba(107,114,128,.15); color: #6b7280; }
.badge-error { background: var(--red-bg); color: var(--red); }
.badge-ok { background: var(--green-bg); color: var(--green); }
.badge-coder { background: var(--purple-bg); color: var(--purple); }
.badge-researcher { background: var(--blue-bg); color: var(--blue); }
.badge-writer { background: var(--green-bg); color: var(--green); }
.badge-ops { background: var(--amber-bg); color: var(--amber); }

/* ── Toggle Switch ────────────────────────────────────────────────── */
.toggle {
  position: relative;
  width: 36px;
  height: 20px;
  cursor: pointer;
}

.toggle input { opacity: 0; width: 0; height: 0; }

.toggle-slider {
  position: absolute;
  inset: 0;
  background: #374151;
  border-radius: 10px;
  transition: .2s;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  top: 3px;
  left: 3px;
  transition: .2s;
}

.toggle input:checked + .toggle-slider { background: var(--green); }
.toggle input:checked + .toggle-slider::before { left: 19px; }

/* ── Buttons ──────────────────────────────────────────────────────── */
.btn {
  padding: 7px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}

.btn:hover { border-color: var(--text-muted); color: var(--text); }

.btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; }
.btn-primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }

.btn-danger { color: var(--red); border-color: transparent; background: var(--red-bg); }
.btn-danger:hover { background: rgba(239,68,68,.25); }

.btn-sm { padding: 4px 10px; font-size: 11px; }
.btn-group { display: flex; gap: 6px; }

/* ── Forms ────────────────────────────────────────────────────────── */
input, textarea, select {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
}

input:focus, textarea:focus, select:focus { outline: none; border-color: var(--accent); }

textarea { resize: vertical; min-height: 80px; }

label { display: block; font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
.form-group { margin-bottom: 14px; }

/* ── Config ───────────────────────────────────────────────────────── */
.config-group {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 16px;
}

.config-group h3 { font-size: 13px; margin-bottom: 16px; color: var(--accent); text-transform: uppercase; letter-spacing: .3px; }

.config-row { display: grid; grid-template-columns: 200px 1fr; gap: 12px; align-items: start; margin-bottom: 10px; }
.config-row label { padding-top: 8px; }
.config-actions { display: flex; justify-content: flex-end; margin-top: 12px; }

/* ── Modals ───────────────────────────────────────────────────────── */
.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.6);
  z-index: 200;
  align-items: center;
  justify-content: center;
}

.modal-overlay.open { display: flex; }

.modal {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  width: 90%;
  max-width: 520px;
  max-height: 80vh;
  overflow-y: auto;
}

.modal h2 { font-size: 17px; margin-bottom: 20px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }

/* ── Schedule Preview ─────────────────────────────────────────────── */
.schedule-preview {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 8px;
  display: none;
}

.schedule-preview.visible { display: block; }

/* ── Pagination ───────────────────────────────────────────────────── */
.pagination {
  display: flex;
  justify-content: center;
  padding: 12px;
}

.pagination .btn { font-size: 12px; }

/* ── Slideout ─────────────────────────────────────────────────────── */
.slideout {
  position: fixed;
  top: 0;
  right: -450px;
  width: 440px;
  height: 100vh;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border);
  z-index: 150;
  transition: right .25s ease;
  display: flex;
  flex-direction: column;
}

.slideout.open { right: 0; }

.slideout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.slideout-header h2 { font-size: 15px; }

.slideout-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

/* ── Responsive ───────────────────────────────────────────────────── */
@media (max-width: 900px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .panels { grid-template-columns: 1fr; }
  .config-row { grid-template-columns: 1fr; }
}

@media (max-width: 600px) {
  .sidebar { width: 44px; }
  .sidebar-btn { width: 32px; height: 32px; }
  .content { margin-left: 44px; }
  .section { padding: 16px; }
  .filter-bar { flex-direction: column; }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/dashboard.css
git commit -m "feat: rewrite CSS with Tailwind-dark sidebar theme"
```

---

### Task 8: Frontend — Dashboard.js Rewrite

**Files:**
- Rewrite: `frontend/dashboard.js`

- [ ] **Step 1: Rewrite dashboard.js with all section logic**

```javascript
// ── Falkenstein Dashboard JS ──────────────────────────────────────────
'use strict';

const API = '/api/admin';
let ws = null;
let tasksOffset = 0;
const TASKS_LIMIT = 50;
const activityLog = []; // in-memory activity feed (max 20)
let _searchTimer = null;

// ── Helpers ──────────────────────────────────────────────────────────

function esc(str) {
  const d = document.createElement('div');
  d.textContent = String(str ?? '');
  return d.innerHTML;
}

function badge(status) {
  const cls = {
    open: 'badge-open', in_progress: 'badge-in_progress', done: 'badge-done',
    failed: 'badge-failed', active: 'badge-active', inactive: 'badge-inactive',
    error: 'badge-error', ok: 'badge-ok',
  }[status] || 'badge-open';
  return `<span class="badge ${cls}">${esc(status)}</span>`;
}

function agentBadge(agent) {
  if (!agent) return '';
  const cls = {
    coder: 'badge-coder', researcher: 'badge-researcher',
    writer: 'badge-writer', ops: 'badge-ops',
  }[agent] || '';
  return `<span class="badge ${cls}">${esc(agent)}</span>`;
}

function relTime(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return 'gerade eben';
  if (diff < 3600) return Math.floor(diff / 60) + ' Min';
  if (diff < 86400) return Math.floor(diff / 3600) + ' Std';
  return d.toLocaleDateString('de');
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  return res.json();
}

function debouncedLoadTasks() {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => { tasksOffset = 0; loadTasks(); }, 300);
}

// ── Navigation ───────────────────────────────────────────────────────

document.querySelectorAll('.sidebar-btn[data-section]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sidebar-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    const section = document.getElementById('section-' + btn.dataset.section);
    if (section) section.classList.add('active');

    const s = btn.dataset.section;
    if (s === 'dashboard') loadDashboard();
    else if (s === 'tasks') loadTasks();
    else if (s === 'schedules') loadSchedules();
    else if (s === 'config') loadConfig();
  });
});

// ── Dashboard ────────────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const data = await api('/dashboard');
    document.getElementById('stat-agents').textContent = data.active_agents ? data.active_agents.length : 0;
    document.getElementById('stat-tasks').textContent = data.open_tasks_count || 0;

    // Count active schedules
    try {
      const sData = await api('/schedules');
      const activeCount = (sData.tasks || []).filter(s => s.active).length;
      document.getElementById('stat-schedules').textContent = activeCount;
    } catch (_) {}

    // Errors today (count failed tasks from today)
    try {
      const errData = await api('/tasks?status=failed&limit=100');
      const today = new Date().toISOString().slice(0, 10);
      const todayErrors = (errData.tasks || []).filter(t => (t.created_at || '').startsWith(today));
      document.getElementById('stat-errors').textContent = todayErrors.length;
    } catch (_) {}

    // Active agents
    const agentsList = document.getElementById('agents-list');
    if (data.active_agents && data.active_agents.length > 0) {
      agentsList.innerHTML = data.active_agents.map(a => {
        const task = a.task || a.name || 'agent';
        const type = a.type || '';
        return `<div class="agent-chip">
          <div class="agent-pulse"></div>
          <span>${esc(task)}</span>
          <span class="agent-type">${esc(type)}</span>
        </div>`;
      }).join('');
    } else {
      agentsList.innerHTML = '<span class="text-muted">Keine aktiven Agents</span>';
    }

    renderActivity();
  } catch (e) {
    console.error('Dashboard load error:', e);
  }
}

// ── Activity Feed ────────────────────────────────────────────────────

function addActivity(type, text) {
  const colors = {
    agent_spawned: 'var(--blue)', agent_done: 'var(--green)', agent_error: 'var(--red)',
    task_created: 'var(--cyan)', schedule_fired: 'var(--purple)',
  };
  activityLog.unshift({ type, text, color: colors[type] || 'var(--text-muted)', time: new Date() });
  if (activityLog.length > 20) activityLog.length = 20;
  if (document.getElementById('section-dashboard').classList.contains('active')) {
    renderActivity();
  }
}

function renderActivity() {
  const el = document.getElementById('activity-feed');
  if (activityLog.length === 0) {
    el.innerHTML = '<span class="text-muted">Keine Aktivität</span>';
    return;
  }
  el.innerHTML = activityLog.map(a =>
    `<div class="activity-item">
      <div class="activity-icon" style="background:${a.color}"></div>
      <span>${esc(a.text)}</span>
      <span class="activity-time">${relTime(a.time)}</span>
    </div>`
  ).join('');
}

// ── Tasks ────────────────────────────────────────────────────────────

async function loadTasks() {
  try {
    const status = document.getElementById('filter-status').value;
    const agent = document.getElementById('filter-agent').value;
    const search = document.getElementById('filter-search').value.trim();
    const params = new URLSearchParams({ limit: TASKS_LIMIT, offset: tasksOffset });
    if (status) params.set('status', status);
    if (agent) params.set('agent', agent);
    if (search) params.set('search', search);

    const data = await api('/tasks?' + params);
    const tbody = document.getElementById('tasks-table');
    const tasks = data.tasks || [];

    if (tasks.length > 0) {
      tbody.innerHTML = tasks.map(t => {
        const preview = t.result ? t.result.slice(0, 80) + (t.result.length > 80 ? '...' : '') : '';
        return `<tr class="expandable" onclick="toggleTaskRow(this, ${t.id})">
          <td>#${t.id}</td>
          <td>${esc(t.title)}</td>
          <td>${badge(t.status)}</td>
          <td>${agentBadge(t.agent)}</td>
          <td>${relTime(t.created_at)}</td>
          <td class="text-muted" style="font-size:12px">${esc(preview)}</td>
          <td>
            <button class="btn btn-sm btn-danger" onclick="event.stopPropagation();deleteTask(${t.id})">×</button>
          </td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:24px">Keine Tasks</td></tr>';
    }

    // Pagination
    const pag = document.getElementById('tasks-pagination');
    if (data.total > TASKS_LIMIT) {
      const hasMore = tasksOffset + TASKS_LIMIT < data.total;
      const hasPrev = tasksOffset > 0;
      pag.innerHTML = `
        ${hasPrev ? `<button class="btn btn-sm" onclick="tasksOffset -= ${TASKS_LIMIT}; loadTasks()">← Zurück</button>` : ''}
        <span class="text-muted" style="padding:0 12px;font-size:12px">${tasksOffset + 1}–${Math.min(tasksOffset + TASKS_LIMIT, data.total)} von ${data.total}</span>
        ${hasMore ? `<button class="btn btn-sm" onclick="tasksOffset += ${TASKS_LIMIT}; loadTasks()">Weiter →</button>` : ''}
      `;
    } else {
      pag.innerHTML = '';
    }
  } catch (e) {
    console.error('Tasks load error:', e);
  }
}

async function toggleTaskRow(tr, taskId) {
  // Close if already expanded
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('task-expanded-row')) {
    existing.remove();
    return;
  }
  // Close any other expanded row
  document.querySelectorAll('.task-expanded-row').forEach(r => r.remove());

  try {
    const t = await api('/tasks/' + taskId);
    if (t.error) return;
    const expandedRow = document.createElement('tr');
    expandedRow.className = 'task-expanded-row';
    expandedRow.innerHTML = `<td colspan="7">
      <div class="task-expanded">
        <div class="meta">Erstellt: ${esc(t.created_at)} | Aktualisiert: ${esc(t.updated_at)} ${t.project ? '| Projekt: ' + esc(t.project) : ''}</div>
        ${t.description ? `<div class="meta"><strong>Beschreibung:</strong> ${esc(t.description)}</div>` : ''}
        ${t.result ? `<pre>${esc(t.result)}</pre>` : '<span class="text-muted">Kein Ergebnis</span>'}
        <div class="task-actions">
          <select onchange="patchTaskStatus(${t.id}, this.value)" style="width:auto;min-width:120px">
            ${['open','in_progress','done','failed'].map(s =>
              `<option value="${s}" ${s === t.status ? 'selected' : ''}>${s}</option>`
            ).join('')}
          </select>
        </div>
      </div>
    </td>`;
    tr.after(expandedRow);
  } catch (e) {
    console.error('Task detail error:', e);
  }
}

async function patchTaskStatus(id, status) {
  try {
    await api('/tasks/' + id, { method: 'PATCH', body: JSON.stringify({ status }) });
    loadTasks();
  } catch (e) {
    console.error('Patch task error:', e);
  }
}

async function deleteTask(id) {
  if (!confirm('Task löschen?')) return;
  try {
    await api('/tasks/' + id, { method: 'DELETE' });
    loadTasks();
  } catch (e) {
    console.error('Delete task error:', e);
  }
}

async function submitTask() {
  const text = document.getElementById('task-text').value.trim();
  if (!text) return;
  try {
    await api('/tasks/submit', { method: 'POST', body: JSON.stringify({ text }) });
    document.getElementById('task-text').value = '';
    closeModal('modal-task');
    setTimeout(loadTasks, 1000); // brief delay for async processing
    loadDashboard();
  } catch (e) {
    console.error('Submit task error:', e);
  }
}

// ── Schedules ────────────────────────────────────────────────────────

async function loadSchedules() {
  try {
    const data = await api('/schedules');
    const tbody = document.getElementById('schedules-table');
    const tasks = data.tasks || [];

    if (tasks.length > 0) {
      tbody.innerHTML = tasks.map(s => {
        const active = s.active === 1 || s.active === true;
        const lastRun = s.last_run ? relTime(s.last_run) : 'Nie';
        const nextRun = s.next_run ? relTime(s.next_run) : '—';
        const resultBadge = s.last_status ? badge(s.last_status) : '<span class="text-muted">—</span>';
        return `<tr class="expandable" onclick="toggleScheduleRow(this, ${s.id})">
          <td><strong>${esc(s.name)}</strong></td>
          <td class="text-muted">${esc(s.schedule || '')}</td>
          <td>${agentBadge(s.agent_type)}</td>
          <td>
            <label class="toggle" onclick="event.stopPropagation()">
              <input type="checkbox" ${active ? 'checked' : ''} onchange="toggleSchedule(${s.id})">
              <span class="toggle-slider"></span>
            </label>
          </td>
          <td class="text-muted">${lastRun}</td>
          <td class="text-muted">${nextRun}</td>
          <td>${resultBadge}</td>
          <td>
            <div class="btn-group" onclick="event.stopPropagation()">
              <button class="btn btn-sm" onclick="editSchedule(${s.id})">Edit</button>
              <button class="btn btn-sm" onclick="runSchedule(${s.id})">Run</button>
              <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${s.id})">×</button>
            </div>
          </td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="8" class="text-muted" style="text-align:center;padding:24px">Keine Schedules</td></tr>';
    }
  } catch (e) {
    console.error('Schedules load error:', e);
  }
}

async function toggleScheduleRow(tr, scheduleId) {
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('schedule-expanded-row')) {
    existing.remove();
    return;
  }
  document.querySelectorAll('.schedule-expanded-row').forEach(r => r.remove());

  try {
    const s = await api('/schedules/' + scheduleId);
    if (s.error) return;
    const preview = (s.next_runs_preview || []).map(r =>
      new Date(r).toLocaleString('de')
    ).join('<br>');

    const expandedRow = document.createElement('tr');
    expandedRow.className = 'schedule-expanded-row';
    expandedRow.innerHTML = `<td colspan="8">
      <div class="task-expanded">
        <div class="meta"><strong>Prompt:</strong></div>
        <pre>${esc(s.prompt)}</pre>
        ${s.active_hours ? `<div class="meta">Aktive Stunden: ${esc(s.active_hours)}</div>` : ''}
        ${s.last_error ? `<div class="meta" style="color:var(--red)">Letzter Fehler: ${esc(s.last_error)}</div>` : ''}
        ${preview ? `<div class="meta"><strong>Nächste Ausführungen:</strong><br>${preview}</div>` : ''}
      </div>
    </td>`;
    tr.after(expandedRow);
  } catch (e) {
    console.error('Schedule detail error:', e);
  }
}

function openScheduleModal(id) {
  document.getElementById('schedule-edit-id').value = id || '';
  document.getElementById('schedule-modal-title').textContent = id ? 'Schedule bearbeiten' : 'Neuer Schedule';
  document.getElementById('sched-name').value = '';
  document.getElementById('sched-schedule').value = '';
  document.getElementById('sched-agent-type').value = 'researcher';
  document.getElementById('sched-active-hours').value = '';
  document.getElementById('sched-prompt').value = '';
  document.getElementById('schedule-preview').classList.remove('visible');
  openModal('modal-schedule');
}

async function editSchedule(id) {
  try {
    const data = await api('/schedules/' + id);
    if (data.error) { alert(data.error); return; }
    document.getElementById('schedule-edit-id').value = id;
    document.getElementById('schedule-modal-title').textContent = 'Schedule bearbeiten';
    document.getElementById('sched-name').value = data.name || '';
    document.getElementById('sched-schedule').value = data.schedule || '';
    document.getElementById('sched-agent-type').value = data.agent_type || 'researcher';
    document.getElementById('sched-active-hours').value = data.active_hours || '';
    document.getElementById('sched-prompt').value = data.prompt || '';
    // Show next runs preview
    if (data.next_runs_preview && data.next_runs_preview.length) {
      const el = document.getElementById('schedule-preview');
      el.innerHTML = '<strong>Nächste Ausführungen:</strong><br>' +
        data.next_runs_preview.map(r => new Date(r).toLocaleString('de')).join('<br>');
      el.classList.add('visible');
    }
    openModal('modal-schedule');
  } catch (e) {
    console.error('Edit schedule error:', e);
  }
}

async function saveSchedule() {
  const editId = document.getElementById('schedule-edit-id').value;
  const payload = {
    name: document.getElementById('sched-name').value.trim(),
    schedule: document.getElementById('sched-schedule').value.trim(),
    agent_type: document.getElementById('sched-agent-type').value,
    prompt: document.getElementById('sched-prompt').value.trim(),
    active: true,
    active_hours: document.getElementById('sched-active-hours').value.trim() || null,
  };
  if (!payload.name || !payload.prompt) {
    alert('Name und Prompt sind Pflichtfelder');
    return;
  }
  try {
    if (editId) {
      await api('/schedules/' + editId, { method: 'PUT', body: JSON.stringify(payload) });
    } else {
      await api('/schedules', { method: 'POST', body: JSON.stringify(payload) });
    }
    closeModal('modal-schedule');
    loadSchedules();
  } catch (e) {
    console.error('Save schedule error:', e);
  }
}

async function toggleSchedule(id) {
  try {
    await api('/schedules/' + id + '/toggle', { method: 'POST' });
    loadSchedules();
  } catch (e) {
    console.error('Toggle error:', e);
  }
}

async function runSchedule(id) {
  try {
    const res = await api('/schedules/' + id + '/run', { method: 'POST' });
    if (res.error) alert(res.error);
    else { loadSchedules(); loadDashboard(); }
  } catch (e) {
    console.error('Run error:', e);
  }
}

async function deleteSchedule(id) {
  if (!confirm('Schedule wirklich löschen?')) return;
  try {
    await api('/schedules/' + id, { method: 'DELETE' });
    loadSchedules();
  } catch (e) {
    console.error('Delete error:', e);
  }
}

async function aiCreateSchedule() {
  const desc = document.getElementById('ai-sched-desc').value.trim();
  if (!desc) return;
  try {
    const res = await api('/schedules/ai-create', { method: 'POST', body: JSON.stringify({ description: desc }) });
    if (res.created) {
      document.getElementById('ai-sched-desc').value = '';
      closeModal('modal-ai-schedule');
      loadSchedules();
    } else if (res.error) {
      alert(res.error);
    }
  } catch (e) {
    console.error('AI create error:', e);
  }
}

// ── Config ───────────────────────────────────────────────────────────

const CONFIG_CATEGORIES = {
  'LLM': ['ollama_host', 'ollama_model', 'ollama_model_light', 'ollama_model_heavy', 'ollama_num_ctx', 'ollama_num_ctx_extended', 'llm_max_retries', 'llm_provider_classify', 'llm_provider_action', 'llm_provider_content', 'llm_provider_scheduled', 'cli_provider', 'cli_daily_token_budget'],
  'Pfade': ['obsidian_vault_path', 'workspace_path'],
  'Persönlichkeit': ['soul_prompt'],
  'API Keys': ['brave_api_key'],
  'Allgemein': ['obsidian_enabled', 'obsidian_auto_knowledge'],
};

const TEXTAREA_KEYS = new Set(['soul_prompt']);
const PASSWORD_KEYS = new Set(['brave_api_key']);

async function loadConfig() {
  try {
    const data = await api('/config');
    const container = document.getElementById('config-container');
    const items = data.config || [];

    const configMap = {};
    items.forEach(item => {
      const key = item.key || item.name || '';
      const value = item.value || '';
      if (key) configMap[key] = value;
    });

    const assigned = new Set();
    const groups = {};
    for (const [cat, keys] of Object.entries(CONFIG_CATEGORIES)) {
      groups[cat] = {};
      keys.forEach(k => { if (k in configMap) { groups[cat][k] = configMap[k]; assigned.add(k); } });
    }
    for (const k of Object.keys(configMap)) {
      if (!assigned.has(k)) groups['Allgemein'][k] = configMap[k];
    }

    let html = '';
    for (const [cat, entries] of Object.entries(groups)) {
      const keys = Object.keys(entries);
      if (keys.length === 0) continue;
      html += `<div class="config-group"><h3>${esc(cat)}</h3>`;
      keys.forEach(key => {
        const val = entries[key];
        html += `<div class="config-row"><label>${esc(key)}</label>`;
        if (TEXTAREA_KEYS.has(key)) {
          html += `<textarea data-key="${esc(key)}" rows="4">${esc(val)}</textarea>`;
        } else if (PASSWORD_KEYS.has(key)) {
          html += `<input type="password" data-key="${esc(key)}" value="${esc(val)}">`;
        } else {
          html += `<input type="text" data-key="${esc(key)}" value="${esc(val)}">`;
        }
        html += `</div>`;
      });
      html += `<div class="config-actions"><button class="btn btn-primary btn-sm" onclick="saveConfigGroup(this)">Speichern</button></div></div>`;
    }
    container.innerHTML = html || '<p class="text-muted">Keine Konfiguration</p>';
  } catch (e) {
    console.error('Config load error:', e);
  }
}

async function saveConfigGroup(btn) {
  const group = btn.closest('.config-group');
  const inputs = group.querySelectorAll('[data-key]');
  const updates = {};
  inputs.forEach(el => { updates[el.dataset.key] = el.value; });
  try {
    const res = await api('/config', { method: 'PUT', body: JSON.stringify({ updates }) });
    if (res.saved) {
      btn.textContent = '✓ Gespeichert';
      setTimeout(() => { btn.textContent = 'Speichern'; }, 1500);
    }
  } catch (e) {
    console.error('Save config error:', e);
  }
}

// ── Modals ───────────────────────────────────────────────────────────

function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function closeModalOverlay(e) { if (e.target === e.currentTarget) e.target.classList.remove('open'); }
function closeSlideout() { document.querySelectorAll('.slideout').forEach(s => s.classList.remove('open')); }

// ── WebSocket ────────────────────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws');

  ws.onopen = () => {
    document.getElementById('ws-dot').classList.add('connected');
    document.getElementById('ws-status').textContent = 'Verbunden';
  };

  ws.onclose = () => {
    document.getElementById('ws-dot').classList.remove('connected');
    document.getElementById('ws-status').textContent = 'Getrennt';
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      const type = msg.type || '';

      // Activity feed
      const labels = {
        agent_spawned: `Agent gestartet: ${msg.task || msg.agent_type || ''}`,
        agent_done: `Agent fertig: ${msg.task || ''}`,
        agent_error: `Agent Fehler: ${msg.error || msg.task || ''}`,
        task_created: `Task erstellt: ${msg.title || ''}`,
        schedule_fired: `Schedule ausgeführt: ${msg.name || ''}`,
      };
      if (labels[type]) addActivity(type, labels[type]);

      // Refresh relevant sections
      if (['agent_spawned', 'agent_done', 'agent_error', 'task_created'].includes(type)) {
        loadDashboard();
        if (document.getElementById('section-tasks').classList.contains('active')) loadTasks();
      }
      if (['schedule_fired', 'agent_done'].includes(type)) {
        if (document.getElementById('section-schedules').classList.contains('active')) loadSchedules();
      }
    } catch (_) {}
  };
}

// ── Init ─────────────────────────────────────────────────────────────

loadDashboard();
connectWS();
```

- [ ] **Step 2: Start server and manually verify all sections**

Run: `python -m backend.main`
Open: `http://localhost:8800`
Verify:
- Sidebar navigation works (all 4 sections switch)
- Dashboard shows stats, agents, activity feed
- Tasks shows table with filters, expandable rows, delete, status change
- Schedules shows table with toggle, edit, run, delete, expandable prompt
- Config shows grouped settings with save
- WebSocket connection indicator works

- [ ] **Step 3: Commit**

```bash
git add frontend/dashboard.js
git commit -m "feat: rewrite dashboard.js with sidebar nav, filters, expandable rows, activity feed"
```

---

### Task 9: Integration Test & Cleanup

**Files:**
- Modify: `frontend/websocket.js` (delete — dead code)

- [ ] **Step 1: Delete dead websocket.js file**

```bash
rm frontend/websocket.js
```

- [ ] **Step 2: Run full backend test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 3: Start server and do end-to-end smoke test**

Run: `python -m backend.main`
Open: `http://localhost:8800`

Test sequence:
1. Dashboard loads with stats
2. Create a task via "Neuer Task" button → verify it appears in Tasks tab
3. Filter tasks by status → verify filter works
4. Click a task row → verify expanded row shows result
5. Change task status via dropdown → verify it updates
6. Delete a task → verify it disappears
7. Go to Schedules → verify existing schedules show with toggle switches
8. Click a schedule row → verify prompt and next runs preview show
9. Edit a schedule → verify modal pre-fills, save works
10. Toggle a schedule on/off → verify toggle works
11. Check Config → verify all groups load and save works

- [ ] **Step 4: Add .superpowers to .gitignore**

```bash
echo ".superpowers/" >> .gitignore
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: cleanup dead websocket.js, add integration smoke test notes"
```

---

## File Summary

| File | Action |
|------|--------|
| `backend/database.py` | Modify — add `get_all_tasks`, `get_task_count`, `delete_task`, `update_task_status_manual` |
| `backend/admin_api.py` | Modify — rewrite GET /tasks, add GET/PATCH/DELETE /tasks/{id}, enhance GET /schedules/{id} |
| `backend/scheduler.py` | Modify — fix reload timing, add `get_next_runs`, cron warning, full prompt in info |
| `backend/main_agent.py` | Modify — emit `task_created` and `schedule_fired` WS events |
| `frontend/dashboard.html` | Rewrite — sidebar layout, filter bar, expandable rows, modals |
| `frontend/dashboard.css` | Rewrite — Tailwind-dark theme, sidebar, toggle switches, activity feed |
| `frontend/dashboard.js` | Rewrite — all section logic, filters, pagination, WS activity feed |
| `frontend/websocket.js` | Delete — dead code |
| `tests/test_database_tasks.py` | Create — tests for new DB methods |
| `tests/test_admin_api_tasks.py` | Create — tests for new API endpoints |
| `tests/test_scheduler_fixes.py` | Create — tests for scheduler fixes |
