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


class Scheduler:
    """Loads scheduled tasks from Obsidian and runs them on time."""

    def __init__(self, vault_path: Path):
        self.vault = vault_path.resolve()
        self.schedules_dir = self.vault / "KI-Büro" / "Schedules"
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
        self._create_schedule_template()
        last_runs = _load_last_runs(self._last_run_path)
        for path in sorted(self.schedules_dir.glob("*.md")):
            if path.name.startswith("_"):
                continue  # skip templates
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

    def _create_schedule_template(self):
        """Create _vorlage.md template if it doesn't exist."""
        tpl = self.schedules_dir / "_vorlage.md"
        if tpl.exists():
            return
        tpl.write_text(
            "---\n"
            "name: Name des Jobs\n"
            "schedule: täglich 09:00\n"
            "agent: researcher\n"
            "active: true\n"
            "active_hours: 08:00-22:00\n"
            "light_context: false\n"
            "---\n\n"
            "<!-- Schedule-Formate:\n"
            "  täglich HH:MM | stündlich | alle N Minuten | alle N Stunden\n"
            "  Mo-Fr HH:MM | montags HH:MM ... sonntags HH:MM\n"
            "  wöchentlich TAG HH:MM | cron: EXPR\n"
            "\n"
            "  Agent-Typen: coder | researcher | writer | ops\n"
            "-->\n\n"
            "Dein Prompt hier. Was soll der Agent tun?\n",
            encoding="utf-8",
        )
