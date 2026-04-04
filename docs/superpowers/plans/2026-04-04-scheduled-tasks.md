# Scheduled Tasks & Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scheduled Tasks System mit Obsidian als Source of Truth, HEARTBEAT_OK-Unterdrückung, und Admin-UI Integration.

**Architecture:** `backend/scheduler.py` liest `.md` Files aus `KI-Büro/Management/Schedules/`, parst Schedule-Strings zu nächsten Ausführungszeitpunkten, und triggert Tasks über MainAgent. Persistente Last-Run-Zeiten in `.last_run.json`. ObsidianWatcher beobachtet den Schedules-Ordner für Live-Reload.

**Tech Stack:** asyncio, YAML frontmatter (python-frontmatter oder manuell), croniter (optional), pathlib

---

## File Structure

### New files:
- `backend/scheduler.py` — Schedule-Parser, Task-Loader, async Tick-Loop, .last_run.json
- `tests/test_scheduler.py` — Tests für Parser und Scheduler-Logik

### Modified files:
- `backend/main_agent.py` — `handle_scheduled()` mit HEARTBEAT_OK
- `backend/main.py` — Scheduler im Lifespan starten
- `backend/admin_api.py` — Schedule-Endpoints
- `frontend/admin.html` — Schedules-Sektion
- `backend/tools/obsidian_manager.py` — `Schedules/` in Vault-Struktur

---

### Task 1: Schedule Parser

**Files:**
- Create: `backend/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests for schedule parser**

```python
# tests/test_scheduler.py
import datetime
import pytest

from backend.scheduler import parse_schedule, next_run


def test_parse_taeglich():
    s = parse_schedule("täglich 07:00")
    assert s["type"] == "daily"
    assert s["hour"] == 7
    assert s["minute"] == 0


def test_parse_stuendlich():
    s = parse_schedule("stündlich")
    assert s["type"] == "hourly"


def test_parse_alle_minuten():
    s = parse_schedule("alle 30 Minuten")
    assert s["type"] == "interval_minutes"
    assert s["minutes"] == 30


def test_parse_alle_stunden():
    s = parse_schedule("alle 6 Stunden")
    assert s["type"] == "interval_hours"
    assert s["hours"] == 6


def test_parse_wochentags():
    s = parse_schedule("Mo-Fr 09:00")
    assert s["type"] == "weekdays"
    assert s["hour"] == 9


def test_parse_wochentag():
    s = parse_schedule("montags 08:00")
    assert s["type"] == "weekly"
    assert s["weekday"] == 0  # Monday
    assert s["hour"] == 8


def test_parse_cron():
    s = parse_schedule("cron: 0 7 * * 1-5")
    assert s["type"] == "cron"
    assert s["expr"] == "0 7 * * 1-5"


def test_next_run_daily():
    # If it's 06:00 and task is "täglich 07:00" -> next run today at 07:00
    after = datetime.datetime(2026, 4, 4, 6, 0)
    schedule = parse_schedule("täglich 07:00")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 7, 0)


def test_next_run_daily_past():
    # If it's 08:00 and task is "täglich 07:00" -> next run tomorrow at 07:00
    after = datetime.datetime(2026, 4, 4, 8, 0)
    schedule = parse_schedule("täglich 07:00")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 5, 7, 0)


def test_next_run_hourly():
    after = datetime.datetime(2026, 4, 4, 8, 15)
    schedule = parse_schedule("stündlich")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 9, 0)


def test_next_run_interval_minutes():
    after = datetime.datetime(2026, 4, 4, 8, 0)
    schedule = parse_schedule("alle 30 Minuten")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 8, 30)


def test_next_run_weekdays_on_weekday():
    # Friday 2026-04-03 at 10:00, task is Mo-Fr 09:00 -> already past today, next is Monday
    after = datetime.datetime(2026, 4, 4, 10, 0)  # Saturday
    schedule = parse_schedule("Mo-Fr 09:00")
    nxt = next_run(schedule, after)
    assert nxt.weekday() == 0  # Monday
    assert nxt.hour == 9


def test_next_run_weekly():
    after = datetime.datetime(2026, 4, 4, 10, 0)  # Friday
    schedule = parse_schedule("montags 08:00")
    nxt = next_run(schedule, after)
    assert nxt.weekday() == 0
    assert nxt.hour == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement schedule parser**

```python
# backend/scheduler.py
import asyncio
import datetime
import json
import re
from pathlib import Path

_WEEKDAY_MAP = {
    "montags": 0, "dienstags": 1, "mittwochs": 2, "donnerstags": 3,
    "freitags": 4, "samstags": 5, "sonntags": 6,
}


def parse_schedule(schedule_str: str) -> dict:
    """Parse a human-readable schedule string into a structured dict."""
    s = schedule_str.strip().lower()

    # "täglich HH:MM"
    m = re.match(r"täglich\s+(\d{1,2}):(\d{2})", s)
    if m:
        return {"type": "daily", "hour": int(m.group(1)), "minute": int(m.group(2))}

    # "stündlich"
    if s == "stündlich":
        return {"type": "hourly"}

    # "alle N Minuten"
    m = re.match(r"alle\s+(\d+)\s+minuten", s)
    if m:
        return {"type": "interval_minutes", "minutes": int(m.group(1))}

    # "alle N Stunden"
    m = re.match(r"alle\s+(\d+)\s+stunden", s)
    if m:
        return {"type": "interval_hours", "hours": int(m.group(1))}

    # "Mo-Fr HH:MM"
    m = re.match(r"mo-fr\s+(\d{1,2}):(\d{2})", s)
    if m:
        return {"type": "weekdays", "hour": int(m.group(1)), "minute": int(m.group(2))}

    # "montags HH:MM" etc.
    for day_name, day_num in _WEEKDAY_MAP.items():
        m = re.match(rf"{day_name}\s+(\d{{1,2}}):(\d{{2}})", s)
        if m:
            return {"type": "weekly", "weekday": day_num, "hour": int(m.group(1)), "minute": int(m.group(2))}

    # "wöchentlich TAG HH:MM"
    m = re.match(r"wöchentlich\s+(\w+)\s+(\d{1,2}):(\d{2})", s)
    if m:
        day_str = m.group(1).lower()
        day_map = {"montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
                   "freitag": 4, "samstag": 5, "sonntag": 6}
        day_num = day_map.get(day_str, 0)
        return {"type": "weekly", "weekday": day_num, "hour": int(m.group(2)), "minute": int(m.group(3))}

    # "cron: EXPR"
    m = re.match(r"cron:\s*(.+)", s)
    if m:
        return {"type": "cron", "expr": m.group(1).strip()}

    return {"type": "interval_minutes", "minutes": 60}  # fallback: hourly


def next_run(schedule: dict, after: datetime.datetime) -> datetime.datetime:
    """Calculate the next run time after the given datetime."""
    t = schedule["type"]

    if t == "daily":
        candidate = after.replace(hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0)
        if candidate <= after:
            candidate += datetime.timedelta(days=1)
        return candidate

    if t == "hourly":
        candidate = after.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
        return candidate

    if t == "interval_minutes":
        mins = schedule["minutes"]
        # Align to interval from midnight
        midnight = after.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = (after - midnight).total_seconds() / 60
        next_slot = (int(elapsed / mins) + 1) * mins
        return midnight + datetime.timedelta(minutes=next_slot)

    if t == "interval_hours":
        hrs = schedule["hours"]
        midnight = after.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = (after - midnight).total_seconds() / 3600
        next_slot = (int(elapsed / hrs) + 1) * hrs
        return midnight + datetime.timedelta(hours=next_slot)

    if t == "weekdays":
        h, m = schedule["hour"], schedule.get("minute", 0)
        candidate = after.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= after or candidate.weekday() >= 5:
            candidate += datetime.timedelta(days=1)
        while candidate.weekday() >= 5:  # skip weekends
            candidate += datetime.timedelta(days=1)
        return candidate

    if t == "weekly":
        target_day = schedule["weekday"]
        h, m = schedule["hour"], schedule.get("minute", 0)
        candidate = after.replace(hour=h, minute=m, second=0, microsecond=0)
        days_ahead = target_day - after.weekday()
        if days_ahead < 0 or (days_ahead == 0 and candidate <= after):
            days_ahead += 7
        candidate = (after + datetime.timedelta(days=days_ahead)).replace(
            hour=h, minute=m, second=0, microsecond=0
        )
        return candidate

    if t == "cron":
        # Simple fallback: treat as hourly if croniter not available
        return after.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)

    # Fallback
    return after + datetime.timedelta(hours=1)
```

- [ ] **Step 4: Run tests**

Run: `source venv/bin/activate && python -m pytest tests/test_scheduler.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scheduler.py tests/test_scheduler.py
git commit -m "feat: schedule parser with human-readable German formats"
```

---

### Task 2: Scheduler Engine — Task Loader & Tick Loop

**Files:**
- Modify: `backend/scheduler.py`
- Test: `tests/test_scheduler.py` (extend)

- [ ] **Step 1: Write failing tests for task loading and tick logic**

Append to `tests/test_scheduler.py`:

```python
from backend.scheduler import ScheduledTask, Scheduler


@pytest.fixture
def tmp_schedules(tmp_path):
    """Create a Schedules directory with test task files."""
    sched_dir = tmp_path / "KI-Büro" / "Management" / "Schedules"
    sched_dir.mkdir(parents=True)
    (sched_dir / "test-task.md").write_text(
        "---\n"
        "name: Test Task\n"
        "schedule: täglich 07:00\n"
        "agent: researcher\n"
        "active: true\n"
        "active_hours: 06:00-22:00\n"
        "light_context: true\n"
        "---\n\n"
        "# Test Task\n\n"
        "Recherchiere aktuelle Nachrichten.\n"
    )
    (sched_dir / "inactive.md").write_text(
        "---\n"
        "name: Inactive Task\n"
        "schedule: stündlich\n"
        "active: false\n"
        "---\n\n"
        "Inaktiver Task.\n"
    )
    return tmp_path


def test_load_task_from_file(tmp_schedules):
    sched_dir = tmp_schedules / "KI-Büro" / "Management" / "Schedules"
    task = ScheduledTask.from_file(sched_dir / "test-task.md")
    assert task.name == "Test Task"
    assert task.agent == "researcher"
    assert task.active is True
    assert task.light_context is True
    assert "Recherchiere" in task.prompt
    assert task.active_hours == (6, 0, 22, 0)


def test_load_inactive_task(tmp_schedules):
    sched_dir = tmp_schedules / "KI-Büro" / "Management" / "Schedules"
    task = ScheduledTask.from_file(sched_dir / "inactive.md")
    assert task.active is False


def test_scheduler_loads_all_tasks(tmp_schedules):
    scheduler = Scheduler(vault_path=tmp_schedules)
    scheduler.load_tasks()
    assert len(scheduler.tasks) == 2


def test_scheduler_due_tasks():
    task = ScheduledTask(
        name="Due Task", schedule_str="alle 30 Minuten", agent="ops",
        active=True, prompt="test", file_path=Path("/fake.md"),
    )
    task._parsed = parse_schedule(task.schedule_str)
    # Set last_run to 31 minutes ago
    task.last_run = datetime.datetime.now() - datetime.timedelta(minutes=31)
    task._next_run = next_run(task._parsed, task.last_run)
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.tasks = {"due-task.md": task}
    scheduler._last_run_path = Path("/tmp/.last_run.json")
    due = scheduler.get_due_tasks()
    assert len(due) == 1


def test_scheduler_respects_active_hours():
    task = ScheduledTask(
        name="Night Task", schedule_str="alle 30 Minuten", agent="ops",
        active=True, prompt="test", file_path=Path("/fake.md"),
        active_hours=(8, 0, 20, 0),
    )
    task._parsed = parse_schedule(task.schedule_str)
    task.last_run = datetime.datetime(2026, 4, 4, 3, 0)  # 3 AM
    task._next_run = next_run(task._parsed, task.last_run)
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.tasks = {"night.md": task}
    scheduler._last_run_path = Path("/tmp/.last_run.json")
    # At 4 AM, outside active hours (8-20) -> not due
    due = scheduler.get_due_tasks(now=datetime.datetime(2026, 4, 4, 4, 0))
    assert len(due) == 0


def test_last_run_persistence(tmp_path):
    lr_path = tmp_path / ".last_run.json"
    from backend.scheduler import _save_last_runs, _load_last_runs
    runs = {"test.md": "2026-04-04T07:00:00"}
    _save_last_runs(lr_path, runs)
    loaded = _load_last_runs(lr_path)
    assert loaded["test.md"] == "2026-04-04T07:00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `ScheduledTask`, `Scheduler` not found

- [ ] **Step 3: Implement Scheduler engine**

Append to `backend/scheduler.py`:

```python
def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text. Returns (metadata, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Type coercion
            if val.lower() in ("true", "false"):
                val = val.lower() == "true"
            elif val.isdigit():
                val = int(val)
            meta[key] = val
    return meta, parts[2].strip()


def _parse_active_hours(s) -> tuple[int, int, int, int] | None:
    """Parse 'HH:MM-HH:MM' into (start_h, start_m, end_h, end_m)."""
    if not s or not isinstance(s, str):
        return None
    m = re.match(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return None


def _save_last_runs(path: Path, runs: dict[str, str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, indent=2), encoding="utf-8")


def _load_last_runs(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


class ScheduledTask:
    """A single scheduled task loaded from an Obsidian markdown file."""

    def __init__(self, name: str, schedule_str: str, agent: str, active: bool,
                 prompt: str, file_path: Path, active_hours=None, light_context: bool = False):
        self.name = name
        self.schedule_str = schedule_str
        self.agent = agent
        self.active = active
        self.prompt = prompt
        self.file_path = file_path
        self.active_hours = active_hours
        self.light_context = light_context
        self.last_run: datetime.datetime | None = None
        self._parsed = parse_schedule(schedule_str)
        self._next_run: datetime.datetime | None = None

    @classmethod
    def from_file(cls, path: Path) -> "ScheduledTask":
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        return cls(
            name=meta.get("name", path.stem),
            schedule_str=meta.get("schedule", "stündlich"),
            agent=meta.get("agent", "researcher"),
            active=meta.get("active", True),
            prompt=body,
            file_path=path,
            active_hours=_parse_active_hours(meta.get("active_hours")),
            light_context=meta.get("light_context", False),
        )

    def compute_next_run(self, after: datetime.datetime | None = None):
        ref = after or self.last_run or datetime.datetime.now()
        self._next_run = next_run(self._parsed, ref)

    def is_in_active_hours(self, now: datetime.datetime) -> bool:
        if self.active_hours is None:
            return True
        sh, sm, eh, em = self.active_hours
        start = now.replace(hour=sh, minute=sm, second=0)
        end = now.replace(hour=eh, minute=em, second=0)
        return start <= now <= end


VAULT_PREFIX = "KI-Büro"


class Scheduler:
    """Loads scheduled tasks from Obsidian and runs them on time."""

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.schedules_dir = self.vault / VAULT_PREFIX / "Management" / "Schedules"
        self._last_run_path = self.schedules_dir / ".last_run.json"
        self.tasks: dict[str, ScheduledTask] = {}
        self._on_task_due = None  # async callback: (ScheduledTask) -> None
        self._running = False

    def load_tasks(self):
        """Load all .md files from Schedules directory."""
        self.tasks.clear()
        if not self.schedules_dir.exists():
            self.schedules_dir.mkdir(parents=True, exist_ok=True)
            self._create_default_heartbeat()
        last_runs = _load_last_runs(self._last_run_path)
        for path in sorted(self.schedules_dir.glob("*.md")):
            try:
                task = ScheduledTask.from_file(path)
                lr = last_runs.get(path.name)
                if lr:
                    task.last_run = datetime.datetime.fromisoformat(lr)
                task.compute_next_run()
                self.tasks[path.name] = task
            except Exception as e:
                print(f"Scheduler: error loading {path.name}: {e}")

    def reload_tasks(self):
        """Reload tasks from disk (called when files change)."""
        self.load_tasks()

    def get_due_tasks(self, now: datetime.datetime | None = None) -> list[ScheduledTask]:
        """Return list of tasks that are due for execution."""
        now = now or datetime.datetime.now()
        due = []
        for task in self.tasks.values():
            if not task.active:
                continue
            if not task.is_in_active_hours(now):
                continue
            if task._next_run and task._next_run <= now:
                due.append(task)
        return due

    def mark_run(self, task: ScheduledTask):
        """Mark a task as just executed. Updates last_run and persists."""
        now = datetime.datetime.now()
        task.last_run = now
        task.compute_next_run(after=now)
        # Persist
        last_runs = _load_last_runs(self._last_run_path)
        last_runs[task.file_path.name] = now.isoformat()
        _save_last_runs(self._last_run_path, last_runs)

    async def start(self, on_task_due):
        """Start the scheduler tick loop. on_task_due is an async callback."""
        self._on_task_due = on_task_due
        self._running = True
        self.load_tasks()

        # Check for missed tasks on startup
        now = datetime.datetime.now()
        for task in self.tasks.values():
            if not task.active:
                continue
            if task._next_run and task._next_run <= now and task.is_in_active_hours(now):
                print(f"Scheduler: recovering missed task '{task.name}'")
                self.mark_run(task)
                if self._on_task_due:
                    await self._on_task_due(task)

        # Tick loop
        try:
            while self._running:
                await asyncio.sleep(60)
                due = self.get_due_tasks()
                for task in due:
                    print(f"Scheduler: triggering '{task.name}'")
                    self.mark_run(task)
                    if self._on_task_due:
                        try:
                            await asyncio.wait_for(self._on_task_due(task), timeout=300)
                        except asyncio.TimeoutError:
                            print(f"Scheduler: task '{task.name}' timed out after 5 min")
                        except Exception as e:
                            print(f"Scheduler: task '{task.name}' error: {e}")
        except asyncio.CancelledError:
            self._running = False

    async def stop(self):
        self._running = False

    def get_all_tasks_info(self) -> list[dict]:
        """Return task info for admin API."""
        now = datetime.datetime.now()
        result = []
        for filename, task in self.tasks.items():
            result.append({
                "filename": filename,
                "name": task.name,
                "schedule": task.schedule_str,
                "agent": task.agent,
                "active": task.active,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "next_run": task._next_run.isoformat() if task._next_run else None,
                "active_hours": f"{task.active_hours[0]:02d}:{task.active_hours[1]:02d}-{task.active_hours[2]:02d}:{task.active_hours[3]:02d}" if task.active_hours else None,
            })
        return result

    def toggle_task(self, filename: str) -> bool:
        """Toggle active state of a task. Writes to file. Returns new state."""
        task = self.tasks.get(filename)
        if not task:
            return False
        new_state = not task.active
        task.active = new_state
        # Update frontmatter in file
        if task.file_path.exists():
            content = task.file_path.read_text(encoding="utf-8")
            old = "active: true" if not new_state else "active: false"
            new = "active: true" if new_state else "active: false"
            content = content.replace(old, new, 1)
            task.file_path.write_text(content, encoding="utf-8")
        return new_state

    def _create_default_heartbeat(self):
        """Create default heartbeat.md if Schedules dir is empty."""
        hb = self.schedules_dir / "heartbeat.md"
        if hb.exists():
            return
        hb.write_text(
            "---\n"
            "name: Heartbeat\n"
            "schedule: alle 30 Minuten\n"
            "agent: ops\n"
            "active: true\n"
            "active_hours: 08:00-22:00\n"
            "light_context: true\n"
            "---\n\n"
            "# System Heartbeat\n\n"
            "Prüfe den Systemstatus:\n"
            "- Ist Ollama erreichbar?\n"
            "- Gibt es neue Einträge in der Obsidian Inbox?\n"
            "- Gibt es fehlgeschlagene Tasks?\n"
            "- Wie ist der CLI-Budget-Stand?\n\n"
            "Wenn alles in Ordnung ist, antworte NUR mit: HEARTBEAT_OK\n"
            "Wenn es Probleme oder wichtige Updates gibt, erstelle einen kurzen Statusbericht.\n",
            encoding="utf-8",
        )
```

- [ ] **Step 4: Run tests**

Run: `source venv/bin/activate && python -m pytest tests/test_scheduler.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/scheduler.py tests/test_scheduler.py
git commit -m "feat: Scheduler engine with task loader, tick loop, persistence"
```

---

### Task 3: MainAgent.handle_scheduled with HEARTBEAT_OK

**Files:**
- Modify: `backend/main_agent.py`
- Test: `tests/test_main_agent.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_main_agent.py`:

```python
@pytest.mark.asyncio
async def test_handle_scheduled_heartbeat_ok(agent, mock_llm, mock_telegram):
    """HEARTBEAT_OK response suppresses Telegram notification."""
    mock_llm.chat_with_tools = AsyncMock(return_value={
        "content": "HEARTBEAT_OK - alles in Ordnung",
    })
    from backend.scheduler import ScheduledTask
    from pathlib import Path
    task = ScheduledTask(
        name="Heartbeat", schedule_str="alle 30 Minuten", agent="ops",
        active=True, prompt="Prüfe Status", file_path=Path("/fake.md"),
        light_context=True,
    )
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="HEARTBEAT_OK - alles in Ordnung")
        mock_sub.agent_id = "sub_ops_abc"
        mock_sub.agent_type = "ops"
        MockSub.return_value = mock_sub
        await agent.handle_scheduled(task)
    # Telegram should NOT have been called (HEARTBEAT_OK suppresses)
    mock_telegram.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_scheduled_with_report(agent, mock_llm, mock_telegram, mock_db):
    """Non-HEARTBEAT_OK response sends Telegram notification."""
    from backend.scheduler import ScheduledTask
    from pathlib import Path
    task = ScheduledTask(
        name="Briefing", schedule_str="täglich 07:00", agent="researcher",
        active=True, prompt="Erstelle Briefing", file_path=Path("/fake.md"),
    )
    with patch("backend.main_agent.SubAgent") as MockSub:
        mock_sub = AsyncMock()
        mock_sub.run = AsyncMock(return_value="Hier ist dein Briefing: ...")
        mock_sub.agent_id = "sub_researcher_abc"
        mock_sub.agent_type = "researcher"
        MockSub.return_value = mock_sub
        await agent.handle_scheduled(task)
    # Telegram SHOULD have been called
    assert mock_telegram.send_message.call_count >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python -m pytest tests/test_main_agent.py::test_handle_scheduled_heartbeat_ok -v`
Expected: FAIL — `handle_scheduled` not found

- [ ] **Step 3: Implement handle_scheduled**

Add to `backend/main_agent.py`, before `get_status()`:

```python
    async def handle_scheduled(self, scheduled_task):
        """Execute a scheduled task. Suppresses notification if HEARTBEAT_OK."""
        from backend.scheduler import ScheduledTask

        title = scheduled_task.name
        agent_type = scheduled_task.agent
        prompt = scheduled_task.prompt

        # Build context if not light_context
        if not scheduled_task.light_context:
            context = await self._build_context()
            prompt = f"{prompt}\n\n## System-Status\n{context}"

        sub = SubAgent(
            agent_type=agent_type,
            task_description=prompt,
            llm=self.llm,
            tools=self.tools,
            db=self.db,
        )
        self.active_agents[sub.agent_id] = {
            "type": agent_type,
            "task": f"⏰ {title}",
            "sub_agent": sub,
        }

        if self.ws_callback:
            await self.ws_callback({
                "type": "agent_spawned",
                "agent_id": sub.agent_id,
                "agent_type": agent_type,
                "task": f"⏰ {title}",
            })

        try:
            result = await sub.run()

            # HEARTBEAT_OK check
            is_heartbeat_ok = result.strip().startswith("HEARTBEAT_OK")

            if not is_heartbeat_ok:
                # Write result to Obsidian
                self.obsidian_writer.write_result(
                    title=title, typ="report", content=result,
                )
                # Send Telegram notification
                if self.telegram:
                    summary = result[:500] if len(result) <= 500 else result[:497] + "..."
                    await self.telegram.send_message(
                        f"⏰ {title}\n\n{summary}",
                    )

            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_done",
                    "agent_id": sub.agent_id,
                    "agent_type": agent_type,
                    "task": f"⏰ {title}",
                })

        except Exception as e:
            if self.telegram:
                await self.telegram.send_message(f"❌ Scheduled Task '{title}' fehlgeschlagen: {str(e)[:300]}")
        finally:
            self.active_agents.pop(sub.agent_id, None)
```

- [ ] **Step 4: Run tests**

Run: `source venv/bin/activate && python -m pytest tests/test_main_agent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main_agent.py tests/test_main_agent.py
git commit -m "feat: MainAgent.handle_scheduled with HEARTBEAT_OK suppression"
```

---

### Task 4: Wire Scheduler into main.py

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tools/obsidian_manager.py` (add Schedules to vault structure)

- [ ] **Step 1: Add Schedules to vault structure**

In `backend/tools/obsidian_manager.py`, add `"Schedules": {}` under `"Management"` in `VAULT_STRUCTURE`:

```python
"Management": {
    "Inbox.md": "# Inbox\n\nHier landen neue Aufgaben und Ideen.\n",
    "Kanban.md": (
        "# Kanban Board\n\n"
        "## Backlog\n\n## In Progress\n\n## Done\n\n## Archiv\n"
    ),
    "Schedules": {},
},
```

- [ ] **Step 2: Add scheduler to main.py lifespan**

Add import at top of `backend/main.py`:

```python
from backend.scheduler import Scheduler
```

Add module-level variable:

```python
scheduler: Scheduler = None
scheduler_task: asyncio.Task = None
```

Inside `lifespan()`, update the global declaration:

```python
global db, telegram, telegram_task, main_agent, budget_tracker, watcher_task, scheduler, scheduler_task
```

After `print("Obsidian watcher active")` block and before `admin_api.init(...)`, add:

```python
    # Start Scheduler
    scheduler = Scheduler(vault_path=settings.obsidian_vault_path)

    async def on_scheduled_task(task):
        await main_agent.handle_scheduled(task)

    scheduler_task = asyncio.create_task(scheduler.start(on_task_due=on_scheduled_task))
    print(f"Scheduler active ({len(scheduler.tasks)} tasks loaded)")
```

In the shutdown section, before `await db.close()`, add:

```python
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 3: Run all tests**

Run: `source venv/bin/activate && python -m pytest tests/ --tb=short`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add backend/main.py backend/tools/obsidian_manager.py
git commit -m "feat: wire scheduler into server lifespan"
```

---

### Task 5: Admin API — Schedule Endpoints

**Files:**
- Modify: `backend/admin_api.py`
- Test: `tests/test_admin_api.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_admin_api.py`:

```python
def test_get_schedules(client):
    resp = client.get("/api/admin/schedules")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


def test_toggle_schedule(client):
    resp = client.get("/api/admin/schedules")
    tasks = resp.json()["tasks"]
    if tasks:
        name = tasks[0]["filename"]
        resp = client.put(f"/api/admin/schedules/{name}/toggle")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
```

- [ ] **Step 2: Add endpoints to admin_api.py**

Append to `backend/admin_api.py`:

```python
@router.get("/schedules")
async def get_schedules():
    from backend.main import scheduler
    if not scheduler:
        return {"tasks": []}
    return {"tasks": scheduler.get_all_tasks_info()}


@router.put("/schedules/{filename}/toggle")
async def toggle_schedule(filename: str):
    from backend.main import scheduler
    if not scheduler:
        return {"error": "Scheduler not initialized"}
    new_state = scheduler.toggle_task(filename)
    return {"active": new_state, "filename": filename}


@router.post("/schedules/{filename}/run")
async def run_schedule_now(filename: str):
    from backend.main import scheduler, main_agent
    if not scheduler or not main_agent:
        return {"error": "Not initialized"}
    task = scheduler.tasks.get(filename)
    if not task:
        return {"error": f"Task '{filename}' not found"}
    scheduler.mark_run(task)
    asyncio.create_task(main_agent.handle_scheduled(task))
    return {"triggered": True, "name": task.name}
```

Add `import asyncio` at top of admin_api.py if not already there.

- [ ] **Step 3: Run tests**

Run: `source venv/bin/activate && python -m pytest tests/test_admin_api.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/admin_api.py tests/test_admin_api.py
git commit -m "feat: admin API endpoints for scheduled tasks"
```

---

### Task 6: Admin UI — Schedules Section

**Files:**
- Modify: `frontend/admin.html`

- [ ] **Step 1: Add schedules section to admin.html**

After the settings section `</div>` in the HTML, add a new section. In the `<main>` tag, after `<div class="settings-section">...</div>`, add:

```html
        <!-- Scheduled Tasks -->
        <div class="settings-section">
            <h2>Scheduled Tasks</h2>
            <div id="schedules-container"></div>
        </div>
```

Add CSS for the schedule rows (append to `<style>` block):

```css
.schedule-row {
    display: flex; align-items: center; gap: 12px;
    padding: 12px; background: #1e293b; border: 1px solid #334155;
    border-radius: 6px; margin-bottom: 8px;
}
.schedule-name { font-weight: 600; min-width: 150px; }
.schedule-cron { color: #94a3b8; font-size: 13px; min-width: 140px; }
.schedule-next { color: #64748b; font-size: 12px; flex: 1; }
.schedule-toggle {
    background: none; border: 1px solid #334155; color: #94a3b8;
    padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;
}
.schedule-toggle.active { border-color: #4ade80; color: #4ade80; }
.schedule-run {
    background: #334155; border: none; color: #e2e8f0;
    padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;
}
.schedule-run:hover { background: #475569; }
```

Add JavaScript functions (append to `<script>` block):

```javascript
async function loadSchedules() {
    try {
        const resp = await fetch('/api/admin/schedules');
        const data = await resp.json();
        const container = document.getElementById('schedules-container');
        if (data.tasks.length === 0) {
            container.innerHTML = '<div style="color:#64748b;font-size:14px">Keine Scheduled Tasks.</div>';
            return;
        }
        container.innerHTML = data.tasks.map(t => {
            const lastRun = t.last_run ? new Date(t.last_run).toLocaleString('de') : 'nie';
            const nextRun = t.next_run ? new Date(t.next_run).toLocaleString('de') : '—';
            const activeClass = t.active ? ' active' : '';
            const activeLabel = t.active ? '● aktiv' : '○ inaktiv';
            const hours = t.active_hours ? ' (' + t.active_hours + ')' : '';
            return '<div class="schedule-row">' +
                '<span class="schedule-name">' + t.name + '</span>' +
                '<span class="schedule-cron">' + t.schedule + hours + '</span>' +
                '<span class="schedule-next">Nächste: ' + nextRun + '<br>Letzte: ' + lastRun + '</span>' +
                '<button class="schedule-toggle' + activeClass + '" onclick="toggleSchedule(\'' + t.filename + '\')">' + activeLabel + '</button>' +
                '<button class="schedule-run" onclick="runSchedule(\'' + t.filename + '\')">▶ Jetzt</button>' +
                '</div>';
        }).join('');
    } catch (e) { console.error('Schedules load error:', e); }
}

async function toggleSchedule(filename) {
    await fetch('/api/admin/schedules/' + filename + '/toggle', { method: 'PUT' });
    loadSchedules();
}

async function runSchedule(filename) {
    const resp = await fetch('/api/admin/schedules/' + filename + '/run', { method: 'POST' });
    const data = await resp.json();
    if (data.triggered) {
        alert('Task "' + data.name + '" gestartet!');
    }
    loadSchedules();
}
```

In the init section at the bottom of the script, add:

```javascript
loadSchedules();
```

And update the setInterval to also refresh schedules:

```javascript
setInterval(() => { loadDashboard(); loadSchedules(); }, 10000);
```

- [ ] **Step 2: Commit**

```bash
git add frontend/admin.html
git commit -m "feat: scheduled tasks section in admin UI"
```

---

### Task 7: End-to-End Test

- [ ] **Step 1: Run full test suite**

```bash
source venv/bin/activate && python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 2: Start server and verify**

```bash
python -m backend.main
```

Verify:
1. Console shows "Scheduler active (N tasks loaded)"
2. `http://localhost:8800/admin` shows Scheduled Tasks section
3. Heartbeat.md was auto-created in Obsidian Vault
4. "Jetzt ausführen" triggers a task
5. HEARTBEAT_OK responses don't spam Telegram

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "fix: end-to-end scheduler fixes"
```
