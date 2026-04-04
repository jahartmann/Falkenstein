# Falkenstein Async Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor Falkenstein to be fully async with SQLite as single source of truth, a new Admin Dashboard replacing Phaser.js, and Obsidian as a managed knowledge base (no watcher).

**Architecture:** SQLite stores everything (tasks, schedules, config, facts). Telegram + Admin Dashboard are control planes. SubAgents run as background `asyncio.Task`s with immediate responses. Obsidian is write-only from app perspective (plus reads for RAG context), no file-watching input channel.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, asyncio, Vanilla HTML/JS/CSS, WebSocket

**Spec:** `docs/superpowers/specs/2026-04-04-async-refactor-design.md`

---

## File Structure

### New files:
- `backend/config_service.py` — Read/write config from SQLite `config` table, seed defaults, replace pydantic-settings for runtime config
- `frontend/dashboard.html` — New admin dashboard (replaces index.html Phaser + admin.html)
- `frontend/dashboard.js` — Dashboard logic (tabs, API calls, WebSocket live updates)
- `frontend/dashboard.css` — Dashboard styles
- `tests/test_config_service.py` — Tests for config service
- `tests/test_scheduler_db.py` — Tests for DB-based scheduler
- `tests/test_async_dispatch.py` — Tests for background task dispatch
- `tests/test_admin_api_v2.py` — Tests for new admin API endpoints

### Modified files:
- `backend/database.py` — Add `schedules` + `config` tables
- `backend/scheduler.py` — Read/write schedules from DB instead of Obsidian .md files
- `backend/main_agent.py` — Async dispatch, `_build_context` from DB, schedule commands use DB
- `backend/telegram_bot.py` — Non-blocking message dispatch
- `backend/main.py` — New routes, lifespan changes, serve dashboard
- `backend/admin_api.py` — Refactor to use DB for schedules/config
- `backend/config.py` — Minimal bootstrap-only config

### Removed files (Task 9):
- `frontend/game.js` — Phaser.js scene
- `frontend/agents.js` — Sprite management
- `frontend/index.html` — Old Phaser frontend
- `frontend/admin.html` — Old admin page (merged into dashboard)
- `backend/obsidian_watcher.py` — No longer needed

---

### Task 1: Add `schedules` and `config` tables to database.py

**Files:**
- Modify: `backend/database.py:33-98` (add tables to `_create_tables`)
- Test: `tests/test_database_new_tables.py`

- [ ] **Step 1: Write failing tests for schedules table CRUD**

```python
# tests/test_database_new_tables.py
import pytest
import pytest_asyncio
from pathlib import Path
from backend.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_create_schedule(db):
    sid = await db.create_schedule(
        name="Morning News",
        schedule="täglich 09:00",
        agent_type="researcher",
        prompt="Recherchiere Tech-News",
        active=True,
        active_hours="08:00-22:00",
        light_context=False,
    )
    assert sid > 0
    s = await db.get_schedule(sid)
    assert s["name"] == "Morning News"
    assert s["schedule"] == "täglich 09:00"
    assert s["active"] == 1


@pytest.mark.asyncio
async def test_list_schedules(db):
    await db.create_schedule(name="A", schedule="täglich 09:00", agent_type="researcher", prompt="p1")
    await db.create_schedule(name="B", schedule="stündlich", agent_type="ops", prompt="p2")
    all_s = await db.get_all_schedules()
    assert len(all_s) == 2


@pytest.mark.asyncio
async def test_update_schedule(db):
    sid = await db.create_schedule(name="Old", schedule="täglich 09:00", agent_type="researcher", prompt="p")
    await db.update_schedule(sid, name="New", schedule="stündlich")
    s = await db.get_schedule(sid)
    assert s["name"] == "New"
    assert s["schedule"] == "stündlich"


@pytest.mark.asyncio
async def test_delete_schedule(db):
    sid = await db.create_schedule(name="X", schedule="täglich 09:00", agent_type="ops", prompt="p")
    await db.delete_schedule(sid)
    s = await db.get_schedule(sid)
    assert s is None


@pytest.mark.asyncio
async def test_toggle_schedule(db):
    sid = await db.create_schedule(name="T", schedule="täglich 09:00", agent_type="ops", prompt="p", active=True)
    new_state = await db.toggle_schedule(sid)
    assert new_state is False
    new_state = await db.toggle_schedule(sid)
    assert new_state is True


@pytest.mark.asyncio
async def test_mark_schedule_run(db):
    sid = await db.create_schedule(name="R", schedule="täglich 09:00", agent_type="ops", prompt="p")
    await db.mark_schedule_run(sid)
    s = await db.get_schedule(sid)
    assert s["last_run"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_database_new_tables.py -v`
Expected: FAIL — `create_schedule` method does not exist

- [ ] **Step 3: Write failing tests for config table CRUD**

Add to `tests/test_database_new_tables.py`:

```python
@pytest.mark.asyncio
async def test_set_and_get_config(db):
    await db.set_config("ollama_model", "gemma4:26b", category="llm", description="Main model")
    val = await db.get_config("ollama_model")
    assert val == "gemma4:26b"


@pytest.mark.asyncio
async def test_get_config_default(db):
    val = await db.get_config("nonexistent", default="fallback")
    assert val == "fallback"


@pytest.mark.asyncio
async def test_get_config_by_category(db):
    await db.set_config("ollama_model", "gemma4:26b", category="llm")
    await db.set_config("brave_api_key", "xxx", category="api_keys")
    llm_config = await db.get_config_by_category("llm")
    assert len(llm_config) == 1
    assert llm_config[0]["key"] == "ollama_model"


@pytest.mark.asyncio
async def test_get_all_config(db):
    await db.set_config("a", "1", category="llm")
    await db.set_config("b", "2", category="paths")
    all_c = await db.get_all_config()
    assert len(all_c) == 2


@pytest.mark.asyncio
async def test_set_config_upsert(db):
    await db.set_config("key1", "old", category="llm")
    await db.set_config("key1", "new", category="llm")
    val = await db.get_config("key1")
    assert val == "new"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_database_new_tables.py -v`
Expected: FAIL — `set_config` method does not exist

- [ ] **Step 5: Implement schedules and config tables + methods in database.py**

Add to `backend/database.py` in `_create_tables()` after existing tables (after line 97):

```python
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                schedule TEXT NOT NULL,
                agent_type TEXT DEFAULT 'researcher',
                prompt TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                active_hours TEXT,
                light_context INTEGER DEFAULT 0,
                last_run TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                description TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
```

Add schedule methods to `Database` class:

```python
    async def create_schedule(self, name: str, schedule: str, agent_type: str = "researcher",
                              prompt: str = "", active: bool = True,
                              active_hours: str | None = None,
                              light_context: bool = False) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO schedules (name, schedule, agent_type, prompt, active, active_hours, light_context) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, schedule, agent_type, prompt, int(active), active_hours, int(light_context)),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_schedule(self, schedule_id: int) -> dict | None:
        cursor = await self._conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_schedules(self) -> list[dict]:
        cursor = await self._conn.execute("SELECT * FROM schedules ORDER BY name")
        return [dict(r) for r in await cursor.fetchall()]

    async def get_active_schedules(self) -> list[dict]:
        cursor = await self._conn.execute("SELECT * FROM schedules WHERE active = 1 ORDER BY name")
        return [dict(r) for r in await cursor.fetchall()]

    async def update_schedule(self, schedule_id: int, **kwargs) -> None:
        allowed = {"name", "schedule", "agent_type", "prompt", "active", "active_hours", "light_context"}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [schedule_id]
        await self._conn.execute(
            f"UPDATE schedules SET {sets}, updated_at = datetime('now') WHERE id = ?", vals
        )
        await self._conn.commit()

    async def delete_schedule(self, schedule_id: int) -> None:
        await self._conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        await self._conn.commit()

    async def toggle_schedule(self, schedule_id: int) -> bool:
        cursor = await self._conn.execute("SELECT active FROM schedules WHERE id = ?", (schedule_id,))
        row = await cursor.fetchone()
        if not row:
            return False
        new_state = 0 if row["active"] else 1
        await self._conn.execute(
            "UPDATE schedules SET active = ?, updated_at = datetime('now') WHERE id = ?",
            (new_state, schedule_id),
        )
        await self._conn.commit()
        return bool(new_state)

    async def mark_schedule_run(self, schedule_id: int) -> None:
        await self._conn.execute(
            "UPDATE schedules SET last_run = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (schedule_id,),
        )
        await self._conn.commit()
```

Add config methods to `Database` class:

```python
    async def set_config(self, key: str, value: str, category: str = "general",
                         description: str | None = None) -> None:
        await self._conn.execute(
            "INSERT INTO config (key, value, category, description) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "category = excluded.category, updated_at = datetime('now')",
            (key, value, category, description),
        )
        await self._conn.commit()

    async def get_config(self, key: str, default: str | None = None) -> str | None:
        cursor = await self._conn.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else default

    async def get_config_by_category(self, category: str) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT key, value, category, description FROM config WHERE category = ? ORDER BY key",
            (category,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_all_config(self) -> list[dict]:
        cursor = await self._conn.execute("SELECT key, value, category, description FROM config ORDER BY category, key")
        return [dict(r) for r in await cursor.fetchall()]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_database_new_tables.py -v`
Expected: ALL PASS

- [ ] **Step 7: Run full test suite to check nothing broke**

Run: `python -m pytest tests/ -v`
Expected: All existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add backend/database.py tests/test_database_new_tables.py
git commit -m "feat: add schedules + config tables to database"
```

---

### Task 2: Config Service — Read/Write config from DB

**Files:**
- Create: `backend/config_service.py`
- Modify: `backend/config.py` (strip to bootstrap-only)
- Test: `tests/test_config_service.py`

- [ ] **Step 1: Write failing tests for ConfigService**

```python
# tests/test_config_service.py
import pytest
import pytest_asyncio
from pathlib import Path
from backend.database import Database
from backend.config_service import ConfigService, CONFIG_DEFAULTS


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def config_svc(db):
    svc = ConfigService(db)
    await svc.init()
    return svc


@pytest.mark.asyncio
async def test_seed_defaults(config_svc, db):
    """First init seeds all defaults into DB."""
    all_config = await db.get_all_config()
    assert len(all_config) >= len(CONFIG_DEFAULTS)


@pytest.mark.asyncio
async def test_get_returns_default(config_svc):
    val = config_svc.get("ollama_model")
    assert val == "gemma4:26b"


@pytest.mark.asyncio
async def test_set_and_get(config_svc):
    await config_svc.set("ollama_model", "llama3:8b")
    assert config_svc.get("ollama_model") == "llama3:8b"


@pytest.mark.asyncio
async def test_get_category(config_svc):
    llm = config_svc.get_category("llm")
    assert "ollama_model" in llm


@pytest.mark.asyncio
async def test_get_all(config_svc):
    all_c = config_svc.get_all()
    assert len(all_c) >= len(CONFIG_DEFAULTS)


@pytest.mark.asyncio
async def test_set_updates_cache(config_svc):
    """set() updates both DB and in-memory cache."""
    await config_svc.set("soul_prompt", "New soul")
    assert config_svc.get("soul_prompt") == "New soul"


@pytest.mark.asyncio
async def test_seed_does_not_overwrite_existing(db):
    """If a config key already exists in DB, seed doesn't overwrite it."""
    await db.set_config("ollama_model", "custom_model", category="llm")
    svc = ConfigService(db)
    await svc.init()
    assert svc.get("ollama_model") == "custom_model"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_service.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement ConfigService**

```python
# backend/config_service.py
"""Runtime config backed by SQLite. Caches all values in memory for fast sync reads."""

from __future__ import annotations
from pathlib import Path

CONFIG_DEFAULTS: list[dict] = [
    {"key": "soul_prompt", "value": "", "category": "personality", "description": "Falki system prompt / personality"},
    {"key": "obsidian_vault_path", "value": str(Path.home() / "Obsidian"), "category": "paths", "description": "Obsidian vault root"},
    {"key": "workspace_path", "value": "./workspace", "category": "paths", "description": "SubAgent workspace directory"},
    {"key": "ollama_host", "value": "http://localhost:11434", "category": "llm", "description": "Ollama API host"},
    {"key": "ollama_model", "value": "gemma4:26b", "category": "llm", "description": "Default Ollama model"},
    {"key": "ollama_model_light", "value": "", "category": "llm", "description": "Light model (fast, cheap)"},
    {"key": "ollama_model_heavy", "value": "", "category": "llm", "description": "Heavy model (tool-use)"},
    {"key": "ollama_num_ctx", "value": "16384", "category": "llm", "description": "Context window size"},
    {"key": "ollama_num_ctx_extended", "value": "32768", "category": "llm", "description": "Extended context window"},
    {"key": "llm_max_retries", "value": "2", "category": "llm", "description": "LLM call retries"},
    {"key": "llm_provider_classify", "value": "local", "category": "llm", "description": "LLM provider for classification"},
    {"key": "llm_provider_action", "value": "local", "category": "llm", "description": "LLM provider for actions"},
    {"key": "llm_provider_content", "value": "local", "category": "llm", "description": "LLM provider for content"},
    {"key": "llm_provider_scheduled", "value": "local", "category": "llm", "description": "LLM provider for scheduled tasks"},
    {"key": "cli_provider", "value": "claude", "category": "llm", "description": "CLI LLM provider (claude/gemini)"},
    {"key": "cli_daily_token_budget", "value": "100000", "category": "llm", "description": "Daily CLI token budget"},
    {"key": "brave_api_key", "value": "", "category": "api_keys", "description": "Brave Search API key"},
    {"key": "obsidian_enabled", "value": "true", "category": "general", "description": "Write results to Obsidian"},
    {"key": "obsidian_auto_knowledge", "value": "true", "category": "general", "description": "Auto-write content results to Obsidian"},
]


class ConfigService:
    """In-memory config cache backed by SQLite."""

    def __init__(self, db):
        self._db = db
        self._cache: dict[str, dict] = {}  # key -> {value, category, description}

    async def init(self) -> None:
        """Seed defaults (skip existing keys) and load all into cache."""
        for item in CONFIG_DEFAULTS:
            existing = await self._db.get_config(item["key"])
            if existing is None:
                await self._db.set_config(
                    item["key"], item["value"],
                    category=item["category"],
                    description=item.get("description"),
                )
        # Load all into cache
        all_rows = await self._db.get_all_config()
        for row in all_rows:
            self._cache[row["key"]] = {
                "value": row["value"],
                "category": row["category"],
                "description": row.get("description", ""),
            }

    def get(self, key: str, default: str | None = None) -> str | None:
        """Sync read from cache."""
        entry = self._cache.get(key)
        return entry["value"] if entry else default

    def get_int(self, key: str, default: int = 0) -> int:
        val = self.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes")

    def get_path(self, key: str, default: str = ".") -> Path:
        val = self.get(key, default)
        return Path(val).expanduser()

    async def set(self, key: str, value: str, category: str | None = None,
                  description: str | None = None) -> None:
        """Write to DB and update cache."""
        cat = category or self._cache.get(key, {}).get("category", "general")
        desc = description or self._cache.get(key, {}).get("description")
        await self._db.set_config(key, value, category=cat, description=desc)
        self._cache[key] = {"value": value, "category": cat, "description": desc or ""}

    async def set_many(self, updates: dict[str, str]) -> None:
        """Batch update multiple keys."""
        for key, value in updates.items():
            await self.set(key, value)

    def get_category(self, category: str) -> dict[str, str]:
        """Get all key-value pairs for a category."""
        return {
            k: v["value"] for k, v in self._cache.items()
            if v["category"] == category
        }

    def get_all(self) -> list[dict]:
        """Get all config entries."""
        return [
            {"key": k, "value": v["value"], "category": v["category"], "description": v["description"]}
            for k, v in sorted(self._cache.items())
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_service.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/config_service.py tests/test_config_service.py
git commit -m "feat: add ConfigService backed by SQLite"
```

---

### Task 3: Refactor Scheduler to use DB instead of Obsidian files

**Files:**
- Modify: `backend/scheduler.py` (major rewrite — DB-backed)
- Test: `tests/test_scheduler_db.py`

- [ ] **Step 1: Write failing tests for DB-backed scheduler**

```python
# tests/test_scheduler_db.py
import pytest
import pytest_asyncio
import datetime
from unittest.mock import AsyncMock
from backend.database import Database
from backend.scheduler import Scheduler, parse_schedule, next_run


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def sched(db):
    s = Scheduler(db)
    await s.load_tasks()
    return s


@pytest.mark.asyncio
async def test_load_empty(sched):
    assert sched.tasks == []


@pytest.mark.asyncio
async def test_load_with_schedules(db):
    await db.create_schedule(name="Test", schedule="täglich 09:00", agent_type="researcher", prompt="Do stuff")
    s = Scheduler(db)
    await s.load_tasks()
    assert len(s.tasks) == 1
    assert s.tasks[0]["name"] == "Test"


@pytest.mark.asyncio
async def test_get_due_tasks(db):
    sid = await db.create_schedule(name="Due", schedule="alle 1 Minuten", agent_type="ops", prompt="check")
    s = Scheduler(db)
    await s.load_tasks()
    due = s.get_due_tasks()
    # First run — never ran before, should be due
    assert len(due) == 1
    assert due[0]["name"] == "Due"


@pytest.mark.asyncio
async def test_mark_run_updates_db(db):
    sid = await db.create_schedule(name="MR", schedule="täglich 09:00", agent_type="ops", prompt="p")
    s = Scheduler(db)
    await s.load_tasks()
    await s.mark_run(s.tasks[0])
    row = await db.get_schedule(sid)
    assert row["last_run"] is not None


@pytest.mark.asyncio
async def test_inactive_schedules_not_due(db):
    await db.create_schedule(name="Off", schedule="alle 1 Minuten", agent_type="ops", prompt="p", active=False)
    s = Scheduler(db)
    await s.load_tasks()
    due = s.get_due_tasks()
    assert len(due) == 0


def test_parse_schedule_taeglich():
    result = parse_schedule("täglich 09:00")
    assert result["type"] == "daily"
    assert result["hour"] == 9
    assert result["minute"] == 0


def test_parse_schedule_stuendlich():
    result = parse_schedule("stündlich")
    assert result["type"] == "hourly"


def test_parse_schedule_interval_minutes():
    result = parse_schedule("alle 30 Minuten")
    assert result["type"] == "interval"
    assert result["minutes"] == 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_scheduler_db.py -v`
Expected: FAIL — Scheduler constructor expects vault_path, not db

- [ ] **Step 3: Rewrite Scheduler class to use DB**

Rewrite `backend/scheduler.py`. Keep `parse_schedule()` and `next_run()` functions unchanged (lines 13-119). Replace the `ScheduledTask` class and `Scheduler` class:

```python
# backend/scheduler.py
"""Scheduler that reads schedules from SQLite database."""

import asyncio
import datetime
import re

_WEEKDAY_MAP = {
    "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6,
    "montags": 0, "dienstags": 1, "mittwochs": 2, "donnerstags": 3,
    "freitags": 4, "samstags": 5, "sonntags": 6,
}

# Keep parse_schedule() exactly as-is (lines 13-61 of current file)
# Keep next_run() exactly as-is (lines 64-119 of current file)
# Keep _parse_active_hours() exactly as-is (lines 144-151 of current file)


def parse_schedule(schedule_str: str) -> dict:
    s = schedule_str.strip().lower()

    m = re.match(r"täglich\s+(\d{1,2}):(\d{2})", s)
    if m:
        return {"type": "daily", "hour": int(m.group(1)), "minute": int(m.group(2))}

    if s == "stündlich":
        return {"type": "hourly"}

    m = re.match(r"alle\s+(\d+)\s+minuten", s)
    if m:
        return {"type": "interval", "minutes": int(m.group(1))}

    m = re.match(r"alle\s+(\d+)\s+stunden", s)
    if m:
        return {"type": "interval", "minutes": int(m.group(1)) * 60}

    m = re.match(r"mo-fr\s+(\d{1,2}):(\d{2})", s)
    if m:
        return {"type": "weekday_range", "days": [0, 1, 2, 3, 4],
                "hour": int(m.group(1)), "minute": int(m.group(2))}

    for name, idx in _WEEKDAY_MAP.items():
        m = re.match(rf"{name}\s+(\d{{1,2}}):(\d{{2}})", s)
        if m:
            return {"type": "weekly", "day": idx,
                    "hour": int(m.group(1)), "minute": int(m.group(2))}

    m = re.match(r"wöchentlich\s+(\w+)\s+(\d{1,2}):(\d{2})", s)
    if m:
        day = _WEEKDAY_MAP.get(m.group(1).lower(), 0)
        return {"type": "weekly", "day": day,
                "hour": int(m.group(2)), "minute": int(m.group(3))}

    m = re.match(r"cron:\s*(.+)", s)
    if m:
        return {"type": "cron", "expression": m.group(1).strip()}

    return {"type": "interval", "minutes": 60}


def next_run(schedule: dict, after: datetime.datetime) -> datetime.datetime:
    t = schedule["type"]

    if t == "daily":
        candidate = after.replace(hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0)
        if candidate <= after:
            candidate += datetime.timedelta(days=1)
        return candidate

    if t == "hourly":
        candidate = after.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
        return candidate

    if t == "interval":
        return after + datetime.timedelta(minutes=schedule["minutes"])

    if t == "weekday_range":
        for offset in range(8):
            candidate = after + datetime.timedelta(days=offset)
            candidate = candidate.replace(hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0)
            if candidate > after and candidate.weekday() in schedule["days"]:
                return candidate
        return after + datetime.timedelta(days=1)

    if t == "weekly":
        for offset in range(8):
            candidate = after + datetime.timedelta(days=offset)
            candidate = candidate.replace(hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0)
            if candidate > after and candidate.weekday() == schedule["day"]:
                return candidate
        return after + datetime.timedelta(days=7)

    return after + datetime.timedelta(hours=1)


def _parse_active_hours(s) -> tuple[int, int, int, int] | None:
    if not s:
        return None
    m = re.match(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", str(s))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


class Scheduler:
    """DB-backed scheduler. Reads schedules from SQLite, fires due tasks."""

    def __init__(self, db):
        self._db = db
        self.tasks: list[dict] = []
        self._running = False
        self._task: asyncio.Task | None = None

    async def load_tasks(self) -> None:
        """Load all schedules from DB into memory."""
        rows = await self._db.get_all_schedules()
        self.tasks = []
        for row in rows:
            parsed = parse_schedule(row["schedule"])
            last_run = None
            if row["last_run"]:
                try:
                    last_run = datetime.datetime.fromisoformat(row["last_run"])
                except ValueError:
                    pass
            active_hours = _parse_active_hours(row.get("active_hours"))
            self.tasks.append({
                **row,
                "_parsed": parsed,
                "_last_run": last_run,
                "_active_hours": active_hours,
                "_next_run": next_run(parsed, last_run or datetime.datetime.now()) if row["active"] else None,
            })

    async def reload_tasks(self) -> None:
        await self.load_tasks()

    def get_due_tasks(self, now: datetime.datetime | None = None) -> list[dict]:
        now = now or datetime.datetime.now()
        due = []
        for t in self.tasks:
            if not t["active"]:
                continue
            ah = t["_active_hours"]
            if ah:
                now_mins = now.hour * 60 + now.minute
                start_mins = ah[0] * 60 + ah[1]
                end_mins = ah[2] * 60 + ah[3]
                if not (start_mins <= now_mins <= end_mins):
                    continue
            if t["_next_run"] and t["_next_run"] <= now:
                due.append(t)
            elif t["_last_run"] is None:
                due.append(t)
        return due

    async def mark_run(self, task: dict) -> None:
        now = datetime.datetime.now()
        await self._db.mark_schedule_run(task["id"])
        task["_last_run"] = now
        task["last_run"] = now.isoformat()
        task["_next_run"] = next_run(task["_parsed"], now)

    async def start(self, on_task_due) -> None:
        self._on_task_due = on_task_due
        self._running = True
        await self.load_tasks()
        self._task = asyncio.create_task(self._tick_loop())

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                due = self.get_due_tasks()
                for task in due:
                    await self.mark_run(task)
                    asyncio.create_task(self._on_task_due(task))
            except Exception as e:
                print(f"Scheduler error: {e}")
            await asyncio.sleep(60)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    def get_all_tasks_info(self) -> list[dict]:
        result = []
        for t in self.tasks:
            result.append({
                "id": t["id"],
                "name": t["name"],
                "schedule": t["schedule"],
                "agent_type": t["agent_type"],
                "active": bool(t["active"]),
                "last_run": t.get("last_run"),
                "next_run": t["_next_run"].isoformat() if t.get("_next_run") else None,
                "prompt_preview": t["prompt"][:100] if t.get("prompt") else "",
            })
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scheduler_db.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scheduler.py tests/test_scheduler_db.py
git commit -m "feat: rewrite scheduler to use SQLite instead of Obsidian files"
```

---

### Task 4: Async dispatch — Telegram, MainAgent, background tasks

**Files:**
- Modify: `backend/telegram_bot.py:68-86` (non-blocking dispatch)
- Modify: `backend/main_agent.py:524-560,586-655,657-741` (background sub-agent dispatch)
- Test: `tests/test_async_dispatch.py`

- [ ] **Step 1: Write failing tests for non-blocking Telegram dispatch**

```python
# tests/test_async_dispatch.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_telegram_dispatches_concurrently():
    """Two messages should be dispatched without waiting for each other."""
    from backend.telegram_bot import TelegramBot

    call_order = []
    async def slow_handler(msg):
        call_order.append(f"start_{msg['text']}")
        await asyncio.sleep(0.1)
        call_order.append(f"end_{msg['text']}")

    bot = TelegramBot.__new__(TelegramBot)
    bot._handlers = [slow_handler]
    bot._offset = 0
    bot._started = False
    bot._token = "fake"
    bot._chat_id = "123"

    msgs = [{"text": "a", "chat_id": "1", "from": "u"}, {"text": "b", "chat_id": "1", "from": "u"}]
    with patch.object(bot, "poll_updates", new_callable=AsyncMock, side_effect=[msgs, []]):
        # Simulate one poll iteration
        messages = await bot.poll_updates()
        tasks = []
        for msg in messages:
            for handler in bot._handlers:
                tasks.append(asyncio.create_task(handler(msg)))
        await asyncio.gather(*tasks)

    # Both should have started before either ended
    assert call_order[0] == "start_a"
    assert call_order[1] == "start_b"


@pytest.mark.asyncio
async def test_handle_message_returns_immediately_for_action():
    """handle_message should return quickly when spawning an action agent."""
    from backend.main_agent import MainAgent

    mock_llm = AsyncMock()
    mock_llm.chat.return_value = '{"type":"action","agent":"coder","title":"Test"}'
    mock_db = AsyncMock()
    mock_db.create_task.return_value = 1
    mock_db.get_open_tasks.return_value = []
    mock_tools = MagicMock()
    mock_telegram = AsyncMock()
    mock_writer = MagicMock()

    agent = MainAgent(
        llm=mock_llm, tools=mock_tools, db=mock_db,
        obsidian_writer=mock_writer, telegram=mock_telegram,
    )

    # Patch SubAgent.run to simulate slow work
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub_instance = AsyncMock()
        mock_sub_instance.run = AsyncMock(side_effect=lambda: asyncio.sleep(10))
        mock_sub_instance.agent_id = "sub_coder_abc"
        MockSub.return_value = mock_sub_instance

        import time
        start = time.monotonic()
        result = await agent.handle_message("do something", chat_id="test")
        elapsed = time.monotonic() - start

    # Should return in under 2 seconds (not wait for 10s sub.run())
    assert elapsed < 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_async_dispatch.py -v`
Expected: FAIL — `handle_message` still blocks on `sub.run()`

- [ ] **Step 3: Modify telegram_bot.py — non-blocking message dispatch**

In `backend/telegram_bot.py`, change the poll loop (around line 78-81):

Replace:
```python
        for msg in messages:
            for handler in self._handlers:
                await handler(msg)
```
With:
```python
        for msg in messages:
            for handler in self._handlers:
                asyncio.create_task(handler(msg))
```

Add `import asyncio` at top if not present.

- [ ] **Step 4: Modify main_agent.py — background SubAgent dispatch**

Refactor `_handle_action` (line 586-655) and `_handle_content` (line 657-741) to dispatch SubAgent as background task. The key change: split each into an immediate response part and a background execution part.

In `handle_message` (line 524), change the action/content dispatch:

Replace the direct calls to `_handle_action` / `_handle_content` (around lines 543-558):
```python
        if typ == "action":
            asyncio.create_task(self._handle_action(classification, text, chat_id, project_hint))
            return classification.get("title", "Agent gestartet")
        elif typ == "content":
            asyncio.create_task(self._handle_content(classification, text, chat_id, project_hint))
            return classification.get("title", "Agent gestartet")
```

Add `import asyncio` at top of `main_agent.py` if not already present.

Wrap the body of `_handle_action` and `_handle_content` in try/except to catch errors in background:

At the beginning of `_handle_action`, after the DB task creation and initial Telegram message, add error handling:

```python
    async def _handle_action(self, classification, original_text, chat_id, project=None):
        try:
            # ... existing logic (DB task, SubAgent creation, sub.run(), result handling)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error_msg = f"Agent-Fehler: {e}"
            if self.telegram:
                await self.telegram.send_message(error_msg, chat_id)
```

Same pattern for `_handle_content`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_async_dispatch.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All pass (may need minor mock adjustments in existing tests since handle_message now returns early)

- [ ] **Step 7: Commit**

```bash
git add backend/telegram_bot.py backend/main_agent.py tests/test_async_dispatch.py
git commit -m "feat: async dispatch — non-blocking Telegram + background SubAgents"
```

---

### Task 5: Refactor MainAgent to use DB for context + schedule commands

**Files:**
- Modify: `backend/main_agent.py:76-138` (`_build_context` reads from DB), `259-475` (schedule commands use DB)
- Test: Update `tests/test_main_agent.py`

- [ ] **Step 1: Write failing tests for DB-based _build_context**

Add to `tests/test_main_agent.py`:

```python
@pytest.mark.asyncio
async def test_build_context_from_db(agent):
    """_build_context should read from DB, not Obsidian files."""
    agent.db.get_open_tasks.return_value = [
        MagicMock(title="Task A", status="open", assigned_to=None),
        MagicMock(title="Task B", status="in_progress", assigned_to="sub_coder_x"),
    ]
    ctx = await agent._build_context()
    assert "Task A" in ctx
    assert "Task B" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main_agent.py::test_build_context_from_db -v`
Expected: FAIL — `_build_context` still reads Obsidian files

- [ ] **Step 3: Rewrite _build_context to use DB only**

Replace `_build_context` (lines 76-138) in `backend/main_agent.py`:

```python
    async def _build_context(self) -> str:
        """Build context string from DB state (no Obsidian reads)."""
        parts = []

        # Active agents
        if self.active_agents:
            lines = ["Aktive Agents:"]
            for aid, info in self.active_agents.items():
                lines.append(f"  - {aid}: {info.get('task', '?')}")
            parts.append("\n".join(lines))

        # Open tasks from DB
        try:
            open_tasks = await self.db.get_open_tasks()
            if open_tasks:
                lines = ["Offene Tasks:"]
                for t in open_tasks[:10]:
                    status = t.status if hasattr(t, 'status') else t.get('status', '?')
                    title = t.title if hasattr(t, 'title') else t.get('title', '?')
                    lines.append(f"  - [{status}] {title}")
                parts.append("\n".join(lines))
        except Exception:
            pass

        return "\n\n".join(parts) if parts else "Keine aktiven Tasks."
```

- [ ] **Step 4: Rewrite schedule commands to use DB**

Replace `_schedule_list`, `_schedule_create`, `_schedule_edit`, `_schedule_toggle`, `_schedule_delete`, `_schedule_run` to use `self.db` and `self.scheduler` (which now wraps DB).

Key changes for each command:

`_schedule_list`: Use `self.scheduler.get_all_tasks_info()` (unchanged, scheduler already returns list).

`_schedule_create`: Instead of writing `.md` file, call `self.db.create_schedule(...)` then `self.scheduler.reload_tasks()`.

```python
    async def _schedule_create(self, args: str, chat_id: str) -> str:
        if not args.strip():
            return "Bitte Beschreibung angeben: /schedule create <beschreibung>"
        meta, enriched = await asyncio.gather(
            self._extract_schedule_meta(args),
            self._enrich_prompt(args),
        )
        name = meta.get("name", "Neuer Task")
        schedule = meta.get("schedule", "täglich 09:00")
        agent_type = meta.get("agent", "researcher")
        active_hours = meta.get("active_hours", "")

        await self.db.create_schedule(
            name=name, schedule=schedule, agent_type=agent_type,
            prompt=enriched, active=True, active_hours=active_hours or None,
        )
        await self.scheduler.reload_tasks()
        return f"Schedule '{name}' erstellt ({schedule}, {agent_type})"
```

`_schedule_toggle`: Use `self.db.toggle_schedule(schedule_id)` then reload.

`_schedule_delete`: Use `self.db.delete_schedule(schedule_id)` then reload.

`_schedule_run`: Find schedule by name from `self.scheduler.tasks`, call `handle_scheduled`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_main_agent.py -v`
Expected: ALL PASS (update fixtures as needed — scheduler mock now needs DB methods)

- [ ] **Step 6: Commit**

```bash
git add backend/main_agent.py tests/test_main_agent.py
git commit -m "feat: MainAgent uses DB for context and schedule commands"
```

---

### Task 6: Refactor Admin API to use DB for schedules + config

**Files:**
- Modify: `backend/admin_api.py` (all schedule endpoints use DB, config endpoints use ConfigService)
- Test: `tests/test_admin_api_v2.py`

- [ ] **Step 1: Write failing tests for new admin API**

```python
# tests/test_admin_api_v2.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.admin_api import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)

    # Mock the imports from backend.main
    with patch("backend.admin_api.get_db") as mock_db_fn, \
         patch("backend.admin_api.get_scheduler") as mock_sched_fn, \
         patch("backend.admin_api.get_config_service") as mock_cfg_fn, \
         patch("backend.admin_api.get_main_agent") as mock_agent_fn:

        mock_db = AsyncMock()
        mock_sched = MagicMock()
        mock_cfg = MagicMock()
        mock_agent = AsyncMock()

        mock_db_fn.return_value = mock_db
        mock_sched_fn.return_value = mock_sched
        mock_cfg_fn.return_value = mock_cfg
        mock_agent_fn.return_value = mock_agent

        mock_sched.get_all_tasks_info.return_value = [
            {"id": 1, "name": "Test", "schedule": "täglich 09:00", "active": True}
        ]
        mock_cfg.get_all.return_value = [
            {"key": "ollama_model", "value": "gemma4:26b", "category": "llm", "description": "Model"}
        ]
        mock_cfg.get_category.return_value = {"ollama_model": "gemma4:26b"}

        yield TestClient(app)


def test_get_schedules(client):
    resp = client.get("/api/admin/schedules")
    assert resp.status_code == 200
    assert "tasks" in resp.json()


def test_get_config(client):
    resp = client.get("/api/admin/config")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_admin_api_v2.py -v`
Expected: FAIL — admin_api doesn't have `get_db` etc.

- [ ] **Step 3: Refactor admin_api.py**

Rewrite `backend/admin_api.py` to use dependency injection functions instead of importing globals from `backend.main`. Add accessor functions and refactor all schedule endpoints to use DB, all config endpoints to use ConfigService.

Key changes:
- Add `get_db()`, `get_scheduler()`, `get_config_service()`, `get_main_agent()` accessor functions
- Schedule endpoints: use `db.create_schedule()`, `db.update_schedule()`, `db.delete_schedule()`, `db.toggle_schedule()` + `scheduler.reload_tasks()`
- Config endpoints: use `config_service.get_all()`, `config_service.get_category()`, `config_service.set()`
- Remove all Obsidian file reads/writes from schedule endpoints
- Remove `write_env_file()` — config goes to DB not .env
- Settings endpoint becomes config endpoint using ConfigService

```python
# backend/admin_api.py
"""Admin API — all state from SQLite via DB + ConfigService."""

import time
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin", tags=["admin"])

_start_time: float = 0.0


def init(start_time: float):
    global _start_time
    _start_time = start_time


# --- Dependency accessors (set during lifespan) ---
_db = None
_scheduler = None
_config_service = None
_main_agent = None
_budget_tracker = None
_llm_router = None


def set_dependencies(db=None, scheduler=None, config_service=None,
                     main_agent=None, budget_tracker=None, llm_router=None):
    global _db, _scheduler, _config_service, _main_agent, _budget_tracker, _llm_router
    _db = db
    _scheduler = scheduler
    _config_service = config_service
    _main_agent = main_agent
    _budget_tracker = budget_tracker
    _llm_router = llm_router


# --- Models ---
class ScheduleCreate(BaseModel):
    name: str
    schedule: str
    agent_type: str = "researcher"
    prompt: str
    active: bool = True
    active_hours: str | None = None

class ScheduleUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    agent_type: str | None = None
    prompt: str | None = None
    active: bool | None = None
    active_hours: str | None = None

class ScheduleAICreate(BaseModel):
    description: str

class TaskSubmit(BaseModel):
    text: str

class ConfigUpdate(BaseModel):
    key: str
    value: str

class ConfigBatchUpdate(BaseModel):
    updates: dict[str, str]


# --- Dashboard ---
@router.get("/dashboard")
async def get_dashboard():
    import httpx
    active = []
    if _main_agent:
        active = _main_agent.get_status().get("active_agents", [])

    open_count = 0
    recent = []
    if _db and _db._conn:
        open_tasks = await _db.get_open_tasks()
        open_count = len(open_tasks)
        cursor = await _db._conn.execute(
            "SELECT id, title, status, assigned_to FROM tasks ORDER BY id DESC LIMIT 5"
        )
        rows = await cursor.fetchall()
        recent = [
            {"id": r["id"], "title": r["title"], "status": r["status"], "agent": r["assigned_to"] or ""}
            for r in rows
        ]

    budget = {}
    if _budget_tracker:
        budget = {"used": _budget_tracker.used, "budget": _budget_tracker.daily_budget, "remaining": _budget_tracker.remaining}

    ollama_status = "offline"
    ollama_host = _config_service.get("ollama_host", "http://localhost:11434") if _config_service else "http://localhost:11434"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            if resp.status_code == 200:
                ollama_status = "online"
    except Exception:
        pass

    return {
        "active_agents": active,
        "open_tasks_count": open_count,
        "recent_tasks": recent,
        "budget": budget,
        "uptime_seconds": int(time.time() - _start_time) if _start_time else 0,
        "ollama_status": ollama_status,
    }


# --- Schedules (DB-backed) ---
@router.get("/schedules")
async def get_schedules():
    if not _scheduler:
        return {"tasks": []}
    return {"tasks": _scheduler.get_all_tasks_info()}

@router.get("/schedules/{schedule_id}")
async def get_schedule_detail(schedule_id: int):
    if not _db:
        return {"error": "DB not initialized"}
    row = await _db.get_schedule(schedule_id)
    if not row:
        return {"error": "Not found"}
    return row

@router.post("/schedules")
async def create_schedule(data: ScheduleCreate):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    sid = await _db.create_schedule(
        name=data.name, schedule=data.schedule, agent_type=data.agent_type,
        prompt=data.prompt, active=data.active, active_hours=data.active_hours,
    )
    await _scheduler.reload_tasks()
    return {"created": True, "id": sid, "name": data.name}

@router.post("/schedules/ai-create")
async def ai_create_schedule(data: ScheduleAICreate):
    if not _db or not _scheduler or not _main_agent:
        return {"error": "Not initialized"}
    meta, enriched = await asyncio.gather(
        _main_agent._extract_schedule_meta(data.description),
        _main_agent._enrich_prompt(data.description),
    )
    name = meta.get("name", "Neuer Task")
    schedule = meta.get("schedule", "täglich 09:00")
    agent_type = meta.get("agent", "researcher")
    active_hours = meta.get("active_hours", "")

    sid = await _db.create_schedule(
        name=name, schedule=schedule, agent_type=agent_type,
        prompt=enriched, active=True, active_hours=active_hours or None,
    )
    await _scheduler.reload_tasks()
    return {"created": True, "id": sid, "name": name, "schedule": schedule, "prompt": enriched}

@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, data: ScheduleUpdate):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if "active" in updates:
        updates["active"] = int(updates["active"])
    await _db.update_schedule(schedule_id, **updates)
    await _scheduler.reload_tasks()
    return {"saved": True, "id": schedule_id}

@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    new_state = await _db.toggle_schedule(schedule_id)
    await _scheduler.reload_tasks()
    return {"active": new_state, "id": schedule_id}

@router.post("/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: int):
    if not _scheduler or not _main_agent:
        return {"error": "Not initialized"}
    task = next((t for t in _scheduler.tasks if t["id"] == schedule_id), None)
    if not task:
        return {"error": "Schedule not found"}
    await _scheduler.mark_run(task)
    asyncio.create_task(_main_agent.handle_scheduled(task))
    return {"triggered": True, "name": task["name"]}

@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    row = await _db.get_schedule(schedule_id)
    if not row:
        return {"error": "Not found"}
    await _db.delete_schedule(schedule_id)
    await _scheduler.reload_tasks()
    return {"deleted": True, "name": row["name"]}


# --- Tasks ---
@router.get("/tasks")
async def get_all_tasks():
    if not _db or not _db._conn:
        return {"tasks": []}
    cursor = await _db._conn.execute(
        "SELECT id, title, description, status, assigned_to, result, created_at "
        "FROM tasks ORDER BY id DESC LIMIT 50"
    )
    rows = await cursor.fetchall()
    return {"tasks": [
        {"id": r["id"], "title": r["title"], "description": r["description"] or "",
         "status": r["status"], "agent": r["assigned_to"] or "",
         "result": (r["result"] or "")[:500], "created_at": r["created_at"] or ""}
        for r in rows
    ]}

@router.post("/tasks/submit")
async def submit_task(data: TaskSubmit):
    if not _main_agent:
        return {"error": "Not initialized"}
    asyncio.create_task(_main_agent.handle_message(data.text))
    return {"submitted": True}


# --- Config (DB-backed via ConfigService) ---
@router.get("/config")
async def get_config():
    if not _config_service:
        return {"config": []}
    return {"config": _config_service.get_all()}

@router.get("/config/{category}")
async def get_config_category(category: str):
    if not _config_service:
        return {"config": {}}
    return {"config": _config_service.get_category(category)}

@router.put("/config")
async def update_config(data: ConfigBatchUpdate):
    if not _config_service:
        return {"error": "Not initialized"}
    await _config_service.set_many(data.updates)
    return {"saved": True}

@router.put("/config/{key}")
async def update_config_key(key: str, data: ConfigUpdate):
    if not _config_service:
        return {"error": "Not initialized"}
    await _config_service.set(data.key, data.value)
    return {"saved": True}


# --- Memory ---
@router.get("/memory")
async def get_memory():
    from backend.main import fact_memory
    if not fact_memory:
        return {"facts": []}
    facts = await fact_memory.get_all_active()
    return {"facts": [
        {"id": f.id, "category": f.category, "content": f.content, "source": f.source}
        for f in facts
    ]}


# --- LLM Routing ---
@router.get("/llm-routing")
async def get_llm_routing():
    if not _llm_router:
        return {"routing": {}, "providers": []}
    from backend.llm_router import PROVIDERS
    return {"routing": _llm_router.get_routing(), "providers": list(PROVIDERS)}

@router.put("/llm-routing")
async def put_llm_routing(data: dict):
    if not _llm_router:
        return {"error": "Router not initialized"}
    from backend.llm_router import PROVIDERS
    routing = data.get("routing", {})
    for task_type, provider in routing.items():
        if provider not in PROVIDERS:
            return {"error": f"Unknown provider: {provider}"}
        _llm_router.set_routing(task_type, provider)
    return {"saved": True, "routing": _llm_router.get_routing()}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_admin_api_v2.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/admin_api.py tests/test_admin_api_v2.py
git commit -m "feat: admin API uses DB for schedules + ConfigService for config"
```

---

### Task 7: Update main.py lifespan — wire everything together

**Files:**
- Modify: `backend/main.py:72-179` (lifespan), routes, imports
- Modify: `backend/config.py` (strip to bootstrap-only)

- [ ] **Step 1: Strip config.py to bootstrap-only**

Replace `backend/config.py`:

```python
# backend/config.py
"""Bootstrap config — only what's needed before DB is available."""

import os
from pathlib import Path

PORT = int(os.getenv("PORT", "8800"))
DB_PATH = Path(os.getenv("DB_PATH", "./data/falkenstein.db"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
```

- [ ] **Step 2: Update main.py lifespan to use ConfigService + DB-backed Scheduler**

Key changes to `backend/main.py`:
- Import `ConfigService` and use it for all config reads
- Create `Scheduler(db)` instead of `Scheduler(vault_path)`
- Call `admin_api.set_dependencies(...)` to inject all dependencies
- Remove ObsidianWatcher startup
- Serve `dashboard.html` at `/` instead of Phaser index
- Pass `config_service` to components that need config

```python
# In lifespan():
from backend.config import DB_PATH, PORT, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from backend.config_service import ConfigService

# DB init
db = Database(DB_PATH)
await db.init()

# Config service
config_service = ConfigService(db)
await config_service.init()

# LLM client (reads from config_service)
llm = LLMClient(config_service)
llm_router = LLMRouter(llm)

# Tools, writer, etc use config_service for paths
vault_path = config_service.get_path("obsidian_vault_path")
obsidian_writer = ObsidianWriter(vault_path)

# Scheduler (DB-backed)
scheduler = Scheduler(db)

# MainAgent
main_agent = MainAgent(llm=llm, tools=tool_registry, db=db,
                       obsidian_writer=obsidian_writer, telegram=telegram,
                       scheduler=scheduler, llm_router=llm_router,
                       config_service=config_service)

# Wire admin API
admin_api.set_dependencies(db=db, scheduler=scheduler, config_service=config_service,
                           main_agent=main_agent, budget_tracker=budget_tracker,
                           llm_router=llm_router)

# Scheduler start (fires background tasks)
await scheduler.start(on_task_due=main_agent.handle_scheduled)

# NO ObsidianWatcher start
```

- [ ] **Step 3: Update route for `/` to serve dashboard**

```python
@app.get("/")
async def index():
    return FileResponse("frontend/dashboard.html")
```

Remove the old `/admin` route (dashboard.html replaces both).

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All pass (may need fixture updates for new config.py shape)

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/config.py
git commit -m "feat: wire ConfigService + DB scheduler in lifespan, serve dashboard"
```

---

### Task 8: Admin Dashboard Frontend

**Files:**
- Create: `frontend/dashboard.html`
- Create: `frontend/dashboard.js`
- Create: `frontend/dashboard.css`

- [ ] **Step 1: Create dashboard.css**

```css
/* frontend/dashboard.css */
:root {
    --bg: #0f1117;
    --bg-card: #1a1d27;
    --bg-input: #252833;
    --border: #2d3040;
    --text: #e1e2e8;
    --text-muted: #8b8d98;
    --accent: #fbbf24;
    --accent-hover: #f59e0b;
    --success: #34d399;
    --danger: #f87171;
    --info: #60a5fa;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
}

/* Header */
.header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-card);
}
.header h1 { font-size: 18px; font-weight: 600; }
.header .status { display: flex; gap: 12px; align-items: center; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-dot.online { background: var(--success); }
.status-dot.offline { background: var(--danger); }

/* Tabs */
.tabs {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--border);
    background: var(--bg-card);
    padding: 0 24px;
}
.tab {
    padding: 12px 20px;
    cursor: pointer;
    color: var(--text-muted);
    border-bottom: 2px solid transparent;
    font-size: 14px;
    transition: all 0.2s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }

/* Content */
.content { padding: 24px; max-width: 1200px; margin: 0 auto; }
.panel { display: none; }
.panel.active { display: block; }

/* Cards */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 16px;
}
.card h3 { font-size: 14px; color: var(--text-muted); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }

/* Stats grid */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
.stat-value { font-size: 28px; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

/* Tables */
table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 8px 12px; font-size: 12px; color: var(--text-muted); text-transform: uppercase; border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
tr:hover { background: rgba(255,255,255,0.02); }

/* Badges */
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.badge-active { background: rgba(52,211,153,0.15); color: var(--success); }
.badge-inactive { background: rgba(248,113,113,0.15); color: var(--danger); }
.badge-open { background: rgba(96,165,250,0.15); color: var(--info); }
.badge-done { background: rgba(52,211,153,0.15); color: var(--success); }
.badge-in_progress { background: rgba(251,191,36,0.15); color: var(--accent); }

/* Buttons */
.btn {
    padding: 8px 16px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg-input);
    color: var(--text);
    cursor: pointer;
    font-size: 13px;
    transition: all 0.2s;
}
.btn:hover { border-color: var(--accent); color: var(--accent); }
.btn-primary { background: var(--accent); color: #000; border-color: var(--accent); }
.btn-primary:hover { background: var(--accent-hover); }
.btn-danger { color: var(--danger); border-color: var(--danger); }
.btn-sm { padding: 4px 10px; font-size: 12px; }

/* Forms */
input, textarea, select {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 8px 12px;
    font-size: 14px;
    width: 100%;
    font-family: inherit;
}
input:focus, textarea:focus, select:focus { outline: none; border-color: var(--accent); }
textarea { min-height: 100px; resize: vertical; }
label { display: block; font-size: 13px; color: var(--text-muted); margin-bottom: 4px; }
.form-group { margin-bottom: 16px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

/* Modal */
.modal-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    z-index: 100;
    align-items: center;
    justify-content: center;
}
.modal-overlay.open { display: flex; }
.modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    width: 90%;
    max-width: 600px;
    max-height: 80vh;
    overflow-y: auto;
}
.modal h2 { font-size: 18px; margin-bottom: 16px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }

/* Active agents live list */
.agent-live { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.agent-live:last-child { border-bottom: none; }
.agent-pulse { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

/* Config sections */
.config-section { margin-bottom: 24px; }
.config-section h3 { margin-bottom: 16px; }
```

- [ ] **Step 2: Create dashboard.html**

```html
<!-- frontend/dashboard.html -->
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Falkenstein</title>
    <link rel="stylesheet" href="/static/dashboard.css">
</head>
<body>
    <div class="header">
        <h1>Falkenstein</h1>
        <div class="status">
            <span>Ollama: <span class="status-dot" id="ollama-dot"></span></span>
            <span>Uptime: <span id="uptime">--</span></span>
        </div>
    </div>

    <div class="tabs">
        <div class="tab active" data-panel="dashboard">Dashboard</div>
        <div class="tab" data-panel="tasks">Tasks</div>
        <div class="tab" data-panel="schedules">Schedules</div>
        <div class="tab" data-panel="config">Config</div>
    </div>

    <div class="content">
        <!-- Dashboard -->
        <div class="panel active" id="panel-dashboard">
            <div class="stats" id="stats"></div>
            <div class="card">
                <h3>Aktive Agents</h3>
                <div id="active-agents"><span style="color:var(--text-muted)">Keine aktiven Agents</span></div>
            </div>
            <div class="card">
                <h3>Letzte Tasks</h3>
                <table><thead><tr><th>ID</th><th>Titel</th><th>Status</th><th>Agent</th></tr></thead>
                <tbody id="recent-tasks"></tbody></table>
            </div>
        </div>

        <!-- Tasks -->
        <div class="panel" id="panel-tasks">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                <h2>Tasks</h2>
                <button class="btn btn-primary" onclick="openNewTaskModal()">Neuer Task</button>
            </div>
            <div class="card">
                <table><thead><tr><th>ID</th><th>Titel</th><th>Status</th><th>Agent</th><th>Erstellt</th><th></th></tr></thead>
                <tbody id="tasks-table"></tbody></table>
            </div>
        </div>

        <!-- Schedules -->
        <div class="panel" id="panel-schedules">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
                <h2>Schedules</h2>
                <div style="display:flex;gap:8px">
                    <button class="btn" onclick="openAIScheduleModal()">AI Erstellen</button>
                    <button class="btn btn-primary" onclick="openScheduleModal()">Neu</button>
                </div>
            </div>
            <div class="card">
                <table><thead><tr><th>Name</th><th>Schedule</th><th>Agent</th><th>Status</th><th>Letzter Lauf</th><th></th></tr></thead>
                <tbody id="schedules-table"></tbody></table>
            </div>
        </div>

        <!-- Config -->
        <div class="panel" id="panel-config">
            <h2 style="margin-bottom:16px">Konfiguration</h2>
            <div id="config-sections"></div>
        </div>
    </div>

    <!-- New Task Modal -->
    <div class="modal-overlay" id="modal-task">
        <div class="modal">
            <h2>Neuer Task</h2>
            <div class="form-group">
                <label>Aufgabe</label>
                <textarea id="task-text" placeholder="Was soll Falki tun?"></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" onclick="closeModal('modal-task')">Abbrechen</button>
                <button class="btn btn-primary" onclick="submitTask()">Absenden</button>
            </div>
        </div>
    </div>

    <!-- Schedule Modal -->
    <div class="modal-overlay" id="modal-schedule">
        <div class="modal">
            <h2 id="schedule-modal-title">Neuer Schedule</h2>
            <input type="hidden" id="schedule-edit-id">
            <div class="form-group">
                <label>Name</label>
                <input id="sched-name" placeholder="z.B. Morning News">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Schedule</label>
                    <input id="sched-schedule" placeholder="z.B. täglich 09:00">
                </div>
                <div class="form-group">
                    <label>Agent-Typ</label>
                    <select id="sched-agent">
                        <option value="researcher">Researcher</option>
                        <option value="coder">Coder</option>
                        <option value="writer">Writer</option>
                        <option value="ops">Ops</option>
                    </select>
                </div>
            </div>
            <div class="form-group">
                <label>Active Hours (optional)</label>
                <input id="sched-hours" placeholder="z.B. 08:00-22:00">
            </div>
            <div class="form-group">
                <label>Prompt</label>
                <textarea id="sched-prompt" placeholder="Was soll der Agent tun?"></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" onclick="closeModal('modal-schedule')">Abbrechen</button>
                <button class="btn btn-primary" onclick="saveSchedule()">Speichern</button>
            </div>
        </div>
    </div>

    <!-- AI Schedule Modal -->
    <div class="modal-overlay" id="modal-ai-schedule">
        <div class="modal">
            <h2>Schedule per AI erstellen</h2>
            <div class="form-group">
                <label>Beschreibung</label>
                <textarea id="ai-sched-desc" placeholder="z.B. Jeden Morgen Tech-News recherchieren"></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn" onclick="closeModal('modal-ai-schedule')">Abbrechen</button>
                <button class="btn btn-primary" onclick="aiCreateSchedule()">Erstellen</button>
            </div>
        </div>
    </div>

    <script src="/static/dashboard.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create dashboard.js**

```javascript
// frontend/dashboard.js

const API = '/api/admin';

// --- Tabs ---
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('panel-' + tab.dataset.panel).classList.add('active');
    });
});

// --- WebSocket ---
let ws;
function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === 'agent_spawned' || data.type === 'agent_done' || data.type === 'agent_error') {
            loadDashboard();
            loadTasks();
        }
    };
    ws.onclose = () => setTimeout(connectWS, 3000);
}
connectWS();

// --- Dashboard ---
async function loadDashboard() {
    try {
        const resp = await fetch(`${API}/dashboard`);
        const d = await resp.json();

        document.getElementById('ollama-dot').className = 'status-dot ' + d.ollama_status;
        const mins = Math.floor(d.uptime_seconds / 60);
        const hrs = Math.floor(mins / 60);
        document.getElementById('uptime').textContent = hrs > 0 ? `${hrs}h ${mins % 60}m` : `${mins}m`;

        document.getElementById('stats').innerHTML = `
            <div class="card"><div class="stat-value">${d.active_agents.length}</div><div class="stat-label">Aktive Agents</div></div>
            <div class="card"><div class="stat-value">${d.open_tasks_count}</div><div class="stat-label">Offene Tasks</div></div>
            <div class="card"><div class="stat-value">${d.budget?.remaining ?? '--'}</div><div class="stat-label">Token Budget</div></div>
        `;

        const agentsEl = document.getElementById('active-agents');
        if (d.active_agents.length === 0) {
            agentsEl.innerHTML = '<span style="color:var(--text-muted)">Keine aktiven Agents</span>';
        } else {
            agentsEl.innerHTML = d.active_agents.map(a => `
                <div class="agent-live">
                    <div class="agent-pulse"></div>
                    <div><strong>${a.agent_id || a.id}</strong> — ${a.task || ''}</div>
                </div>
            `).join('');
        }

        document.getElementById('recent-tasks').innerHTML = d.recent_tasks.map(t => `
            <tr>
                <td>${t.id}</td>
                <td>${t.title}</td>
                <td><span class="badge badge-${t.status}">${t.status}</span></td>
                <td>${t.agent}</td>
            </tr>
        `).join('');
    } catch (e) { console.error('Dashboard load failed:', e); }
}

// --- Tasks ---
async function loadTasks() {
    try {
        const resp = await fetch(`${API}/tasks`);
        const d = await resp.json();
        document.getElementById('tasks-table').innerHTML = d.tasks.map(t => `
            <tr>
                <td>${t.id}</td>
                <td>${t.title}</td>
                <td><span class="badge badge-${t.status}">${t.status}</span></td>
                <td>${t.agent}</td>
                <td>${t.created_at ? new Date(t.created_at).toLocaleString('de') : ''}</td>
                <td>${t.result ? '<button class="btn btn-sm" onclick="alert(\`' + t.result.replace(/`/g, "'").replace(/\\/g, '\\\\') + '\`)">Ergebnis</button>' : ''}</td>
            </tr>
        `).join('');
    } catch (e) { console.error('Tasks load failed:', e); }
}

// --- Schedules ---
async function loadSchedules() {
    try {
        const resp = await fetch(`${API}/schedules`);
        const d = await resp.json();
        document.getElementById('schedules-table').innerHTML = d.tasks.map(s => `
            <tr>
                <td>${s.name}</td>
                <td>${s.schedule}</td>
                <td>${s.agent_type || ''}</td>
                <td><span class="badge badge-${s.active ? 'active' : 'inactive'}">${s.active ? 'Aktiv' : 'Pausiert'}</span></td>
                <td>${s.last_run ? new Date(s.last_run).toLocaleString('de') : 'Nie'}</td>
                <td style="display:flex;gap:4px">
                    <button class="btn btn-sm" onclick="toggleSchedule(${s.id})">${s.active ? 'Pause' : 'Start'}</button>
                    <button class="btn btn-sm" onclick="editSchedule(${s.id})">Edit</button>
                    <button class="btn btn-sm" onclick="runSchedule(${s.id})">Run</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${s.id}, '${s.name}')">X</button>
                </td>
            </tr>
        `).join('');
    } catch (e) { console.error('Schedules load failed:', e); }
}

async function toggleSchedule(id) {
    await fetch(`${API}/schedules/${id}/toggle`, {method: 'POST'});
    loadSchedules();
}

async function runSchedule(id) {
    await fetch(`${API}/schedules/${id}/run`, {method: 'POST'});
    loadSchedules();
}

async function deleteSchedule(id, name) {
    if (!confirm(`Schedule "${name}" wirklich loeschen?`)) return;
    await fetch(`${API}/schedules/${id}`, {method: 'DELETE'});
    loadSchedules();
}

async function editSchedule(id) {
    const resp = await fetch(`${API}/schedules/${id}`);
    const s = await resp.json();
    document.getElementById('schedule-modal-title').textContent = 'Schedule bearbeiten';
    document.getElementById('schedule-edit-id').value = id;
    document.getElementById('sched-name').value = s.name || '';
    document.getElementById('sched-schedule').value = s.schedule || '';
    document.getElementById('sched-agent').value = s.agent_type || 'researcher';
    document.getElementById('sched-hours').value = s.active_hours || '';
    document.getElementById('sched-prompt').value = s.prompt || '';
    document.getElementById('modal-schedule').classList.add('open');
}

function openScheduleModal() {
    document.getElementById('schedule-modal-title').textContent = 'Neuer Schedule';
    document.getElementById('schedule-edit-id').value = '';
    document.getElementById('sched-name').value = '';
    document.getElementById('sched-schedule').value = '';
    document.getElementById('sched-agent').value = 'researcher';
    document.getElementById('sched-hours').value = '';
    document.getElementById('sched-prompt').value = '';
    document.getElementById('modal-schedule').classList.add('open');
}

async function saveSchedule() {
    const id = document.getElementById('schedule-edit-id').value;
    const body = {
        name: document.getElementById('sched-name').value,
        schedule: document.getElementById('sched-schedule').value,
        agent_type: document.getElementById('sched-agent').value,
        active_hours: document.getElementById('sched-hours').value || null,
        prompt: document.getElementById('sched-prompt').value,
    };
    if (id) {
        await fetch(`${API}/schedules/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    } else {
        body.active = true;
        await fetch(`${API}/schedules`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    }
    closeModal('modal-schedule');
    loadSchedules();
}

function openAIScheduleModal() { document.getElementById('modal-ai-schedule').classList.add('open'); }

async function aiCreateSchedule() {
    const desc = document.getElementById('ai-sched-desc').value;
    if (!desc) return;
    await fetch(`${API}/schedules/ai-create`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({description: desc})});
    closeModal('modal-ai-schedule');
    document.getElementById('ai-sched-desc').value = '';
    loadSchedules();
}

// --- Config ---
async function loadConfig() {
    try {
        const resp = await fetch(`${API}/config`);
        const d = await resp.json();

        const byCategory = {};
        for (const item of d.config) {
            if (!byCategory[item.category]) byCategory[item.category] = [];
            byCategory[item.category].push(item);
        }

        const categoryLabels = {llm: 'LLM', paths: 'Pfade', personality: 'Persoenlichkeit', api_keys: 'API Keys', general: 'Allgemein'};
        let html = '';
        for (const [cat, items] of Object.entries(byCategory)) {
            html += `<div class="config-section card"><h3>${categoryLabels[cat] || cat}</h3>`;
            for (const item of items) {
                const inputType = item.key.includes('key') || item.key.includes('token') ? 'password' : 'text';
                const isTextarea = item.key === 'soul_prompt';
                html += `<div class="form-group">
                    <label>${item.key} ${item.description ? '<small style="color:var(--text-muted)">— ' + item.description + '</small>' : ''}</label>
                    ${isTextarea
                        ? `<textarea id="cfg-${item.key}" rows="6">${item.value}</textarea>`
                        : `<input type="${inputType}" id="cfg-${item.key}" value="${item.value}">`}
                </div>`;
            }
            html += `<button class="btn btn-primary" onclick="saveConfigCategory('${cat}', ${JSON.stringify(items.map(i => i.key))})">Speichern</button></div>`;
        }
        document.getElementById('config-sections').innerHTML = html;
    } catch (e) { console.error('Config load failed:', e); }
}

async function saveConfigCategory(category, keys) {
    const updates = {};
    for (const key of keys) {
        const el = document.getElementById('cfg-' + key);
        if (el) updates[key] = el.value;
    }
    await fetch(`${API}/config`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({updates})});
    alert('Gespeichert');
}

// --- Tasks Modal ---
function openNewTaskModal() { document.getElementById('modal-task').classList.add('open'); }

async function submitTask() {
    const text = document.getElementById('task-text').value;
    if (!text) return;
    await fetch(`${API}/tasks/submit`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
    closeModal('modal-task');
    document.getElementById('task-text').value = '';
    loadTasks();
}

function closeModal(id) { document.getElementById(id).classList.remove('open'); }

// Close modals on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.classList.remove('open'); });
});

// --- Init ---
loadDashboard();
loadTasks();
loadSchedules();
loadConfig();
setInterval(loadDashboard, 10000);
```

- [ ] **Step 4: Commit**

```bash
git add frontend/dashboard.html frontend/dashboard.js frontend/dashboard.css
git commit -m "feat: new admin dashboard replacing Phaser.js office"
```

---

### Task 9: Migration + handle_scheduled adaptation for DB schedules

**Files:**
- Create: `backend/migrate.py` (one-time migration: Obsidian schedules + .env to DB)
- Modify: `backend/main_agent.py` (`handle_scheduled` accepts dict instead of ScheduledTask)

- [ ] **Step 1: Write migration script**

```python
# backend/migrate.py
"""One-time migration: Obsidian schedule files + .env config -> SQLite."""

import asyncio
import re
from pathlib import Path
from backend.database import Database
from backend.config_service import ConfigService

# Map .env keys to config keys + categories
ENV_TO_CONFIG = {
    "OLLAMA_HOST": ("ollama_host", "llm"),
    "OLLAMA_MODEL": ("ollama_model", "llm"),
    "OLLAMA_MODEL_LIGHT": ("ollama_model_light", "llm"),
    "OLLAMA_MODEL_HEAVY": ("ollama_model_heavy", "llm"),
    "OLLAMA_NUM_CTX": ("ollama_num_ctx", "llm"),
    "OLLAMA_NUM_CTX_EXTENDED": ("ollama_num_ctx_extended", "llm"),
    "LLM_MAX_RETRIES": ("llm_max_retries", "llm"),
    "CLI_PROVIDER": ("cli_provider", "llm"),
    "CLI_DAILY_TOKEN_BUDGET": ("cli_daily_token_budget", "llm"),
    "OBSIDIAN_VAULT_PATH": ("obsidian_vault_path", "paths"),
    "WORKSPACE_PATH": ("workspace_path", "paths"),
    "BRAVE_API_KEY": ("brave_api_key", "api_keys"),
}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if v.lower() in ("true", "false"):
                v = v.lower() == "true"
            meta[k.strip()] = v
    body = text[end + 3:].strip()
    return meta, body


async def migrate_schedules(db: Database, vault_path: Path) -> int:
    """Migrate Obsidian schedule .md files to SQLite."""
    schedules_dir = vault_path / "KI-Büro" / "Schedules"
    if not schedules_dir.exists():
        print("No schedules directory found, skipping.")
        return 0

    count = 0
    for f in sorted(schedules_dir.glob("*.md")):
        if f.name.startswith("_"):
            continue
        content = f.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(content)
        if not meta.get("name"):
            continue

        try:
            await db.create_schedule(
                name=meta["name"],
                schedule=meta.get("schedule", "täglich 09:00"),
                agent_type=meta.get("agent", "researcher"),
                prompt=body,
                active=meta.get("active", True) if isinstance(meta.get("active"), bool) else str(meta.get("active", "true")).lower() == "true",
                active_hours=meta.get("active_hours"),
                light_context=meta.get("light_context", False) if isinstance(meta.get("light_context"), bool) else str(meta.get("light_context", "false")).lower() == "true",
            )
            count += 1
            print(f"  Migrated schedule: {meta['name']}")
        except Exception as e:
            print(f"  Skipped {f.name}: {e}")
    return count


async def migrate_env_config(db: Database, env_path: Path = Path(".env")) -> int:
    """Migrate .env values to config table."""
    if not env_path.exists():
        print("No .env file found, skipping.")
        return 0

    count = 0
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in ENV_TO_CONFIG:
            config_key, category = ENV_TO_CONFIG[key]
            existing = await db.get_config(config_key)
            if existing is None:
                await db.set_config(config_key, value, category=category)
                count += 1
                print(f"  Migrated config: {key} -> {config_key}")
    return count


async def migrate_soul(db: Database, soul_path: Path = Path("SOUL.md")) -> bool:
    """Migrate SOUL.md content to config table."""
    if not soul_path.exists():
        return False
    content = soul_path.read_text(encoding="utf-8")
    existing = await db.get_config("soul_prompt")
    if not existing:
        await db.set_config("soul_prompt", content, category="personality",
                           description="Falki system prompt / personality")
        print("  Migrated SOUL.md to config")
        return True
    return False


async def run_migration():
    import os
    db_path = Path(os.getenv("DB_PATH", "./data/falkenstein.db"))
    vault_path = Path(os.getenv("OBSIDIAN_VAULT_PATH", str(Path.home() / "Obsidian")))

    print(f"Migration: DB={db_path}, Vault={vault_path}")
    db = Database(db_path)
    await db.init()

    try:
        sched_count = await migrate_schedules(db, vault_path)
        print(f"Schedules migrated: {sched_count}")

        env_count = await migrate_env_config(db)
        print(f"Config values migrated: {env_count}")

        soul = await migrate_soul(db)
        print(f"SOUL.md migrated: {soul}")

        print("Migration complete.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
```

- [ ] **Step 2: Update handle_scheduled to accept dict**

In `backend/main_agent.py`, modify `handle_scheduled` (line 743) to accept a dict (from DB scheduler) instead of a `ScheduledTask` object:

```python
    async def handle_scheduled(self, task: dict) -> None:
        """Handle a scheduled task from DB-backed scheduler."""
        agent_type = task.get("agent_type", "researcher")
        prompt = task.get("prompt", "")
        name = task.get("name", "scheduled")
        light_context = task.get("light_context", False)

        llm = self._get_llm_for("scheduled")
        sub = SubAgent(
            agent_type=agent_type,
            task_description=prompt,
            llm=llm,
            tools=self.tools,
            db=self.db,
        )

        try:
            result = await sub.run()
        except Exception as e:
            print(f"Scheduled task '{name}' failed: {e}")
            return

        if not result or result.strip().startswith("HEARTBEAT_OK"):
            return

        # Write to Obsidian if enabled
        if self.obsidian_writer and self.config_service and self.config_service.get_bool("obsidian_enabled"):
            try:
                await asyncio.to_thread(
                    self.obsidian_writer.write_result, name, "Recherche", result
                )
            except Exception as e:
                print(f"Obsidian write failed for scheduled '{name}': {e}")

        # Send summary to Telegram
        if self.telegram:
            summary = result[:500] + ("..." if len(result) > 500 else "")
            await self.telegram.send_message(f"Schedule '{name}':\n{summary}")
```

- [ ] **Step 3: Commit**

```bash
git add backend/migrate.py backend/main_agent.py
git commit -m "feat: migration script + handle_scheduled for DB schedules"
```

---

### Task 10: Cleanup — remove Phaser frontend + ObsidianWatcher

**Files:**
- Delete: `frontend/game.js`, `frontend/agents.js`, `frontend/index.html`, `frontend/admin.html`
- Delete: `backend/obsidian_watcher.py`
- Modify: `backend/main.py` (remove watcher imports/startup, remove old routes)
- Delete: `tests/test_obsidian_watcher.py`

- [ ] **Step 1: Remove old frontend files**

```bash
git rm frontend/game.js frontend/agents.js frontend/index.html frontend/admin.html
```

- [ ] **Step 2: Remove ObsidianWatcher**

```bash
git rm backend/obsidian_watcher.py tests/test_obsidian_watcher.py
```

- [ ] **Step 3: Clean up main.py imports and watcher references**

Remove from `backend/main.py`:
- Import of `ObsidianWatcher`
- `handle_obsidian_todo` function
- Watcher startup/shutdown in lifespan
- `watcher_task` global
- Old `/` route serving `index.html`
- Old `/admin` route serving `admin.html`

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All pass (tests referencing ObsidianWatcher are removed)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "cleanup: remove Phaser frontend + ObsidianWatcher"
```

---

### Task 11: Integration test — end-to-end smoke test

**Files:**
- Create: `tests/test_integration_async.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_async.py
"""Smoke test: DB init -> ConfigService -> Scheduler -> MainAgent flow."""

import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend.database import Database
from backend.config_service import ConfigService
from backend.scheduler import Scheduler


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_full_lifecycle(db):
    """DB -> ConfigService -> Scheduler -> create schedule -> get due."""
    # Config
    cfg = ConfigService(db)
    await cfg.init()
    assert cfg.get("ollama_model") is not None

    # Scheduler
    sched = Scheduler(db)
    await sched.load_tasks()
    assert sched.tasks == []

    # Create schedule
    sid = await db.create_schedule(
        name="Test Schedule",
        schedule="alle 1 Minuten",
        agent_type="researcher",
        prompt="Do a thing",
    )
    await sched.reload_tasks()
    assert len(sched.tasks) == 1

    # Should be due (never ran)
    due = sched.get_due_tasks()
    assert len(due) == 1
    assert due[0]["name"] == "Test Schedule"

    # Mark run
    await sched.mark_run(due[0])
    due2 = sched.get_due_tasks()
    assert len(due2) == 0  # just ran, not due yet


@pytest.mark.asyncio
async def test_config_persistence(db):
    """Config changes persist across service instances."""
    cfg1 = ConfigService(db)
    await cfg1.init()
    await cfg1.set("ollama_model", "test_model")

    cfg2 = ConfigService(db)
    await cfg2.init()
    assert cfg2.get("ollama_model") == "test_model"
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_integration_async.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_async.py
git commit -m "test: integration smoke tests for async refactor"
```

---

## Execution Order Summary

| Task | Was | Abhängig von |
|------|-----|-------------|
| 1 | DB: schedules + config Tabellen | - |
| 2 | ConfigService | Task 1 |
| 3 | Scheduler DB-Rewrite | Task 1 |
| 4 | Async Dispatch (Telegram + MainAgent) | - |
| 5 | MainAgent DB-Context + Schedule-Commands | Task 1, 3 |
| 6 | Admin API Refactor | Task 1, 2, 3 |
| 7 | main.py Lifespan Wiring | Task 2, 3, 6 |
| 8 | Dashboard Frontend | Task 6 |
| 9 | Migration + handle_scheduled | Task 1, 3 |
| 10 | Cleanup (Phaser, Watcher) | Task 7, 8 |
| 11 | Integration Tests | Task 1-10 |

**Parallelisierbar:** Task 1+4 (unabhängig), Task 2+3 (beide nur von 1 abhängig), Task 8 (Frontend, unabhängig von Backend nach Task 6)
