import asyncio
import datetime
import re

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


def _parse_active_hours(s) -> tuple[int, int, int, int] | None:
    """Parse 'HH:MM-HH:MM' into (start_h, start_m, end_h, end_m)."""
    if not s or not isinstance(s, str):
        return None
    m = re.match(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return None


def _is_in_active_hours(active_hours, now: datetime.datetime) -> bool:
    """Check if *now* falls within the active_hours window."""
    if active_hours is None:
        return True
    sh, sm, eh, em = active_hours
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end


class Scheduler:
    """Reads schedules from SQLite and dispatches due tasks."""

    def __init__(self, db):
        self._db = db
        self.tasks: list[dict] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._on_task_due = None

    # ── loading ─────────────────────────────────────────────────

    async def load_tasks(self) -> None:
        """Load all schedules from DB, compute next_run for each."""
        rows = await self._db.get_all_schedules()
        self.tasks = []
        for row in rows:
            parsed = parse_schedule(row["schedule"])
            # Warn and skip cron schedules (not supported)
            if parsed.get("type") == "cron":
                await self._db.update_schedule_result(
                    row["id"], "error",
                    "Cron-Syntax nicht unterstützt. Verwende deutsche Zeitangaben (z.B. 'täglich 09:00')."
                )
                continue
            last_run = (
                datetime.datetime.fromisoformat(row["last_run"])
                if row.get("last_run")
                else None
            )
            active_hours = _parse_active_hours(row.get("active_hours"))
            nr = (
                next_run(parsed, last_run or datetime.datetime.now())
                if row["active"]
                else None
            )
            task = {
                **row,
                "_parsed": parsed,
                "_last_run": last_run,
                "_active_hours": active_hours,
                "_next_run": nr,
            }
            self.tasks.append(task)

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

    # ── due check ───────────────────────────────────────────────

    def get_due_tasks(self, now: datetime.datetime | None = None) -> list[dict]:
        """Return tasks that are due now."""
        now = now or datetime.datetime.now()
        due = []
        for task in self.tasks:
            if not task.get("active"):
                continue
            if not _is_in_active_hours(task.get("_active_hours"), now):
                continue
            if task["_next_run"] is not None and task["_next_run"] <= now:
                due.append(task)
        return due

    # ── mark run ────────────────────────────────────────────────

    async def mark_run(self, task: dict) -> None:
        """Update last_run in DB and in-memory."""
        now = datetime.datetime.now()
        await self._db.mark_schedule_run(task["id"])
        # Update in-memory state
        task["_last_run"] = now
        task["_next_run"] = next_run(task["_parsed"], now)

    # ── lifecycle ───────────────────────────────────────────────

    async def start(self, on_task_due) -> None:
        """Start tick loop."""
        self._on_task_due = on_task_due
        self._running = True
        await self.load_tasks()
        self._task = asyncio.create_task(self._tick_loop())

    async def _tick_loop(self) -> None:
        """Every 60s, check for due tasks, dispatch via create_task."""
        while self._running:
            try:
                due = self.get_due_tasks()
                for task in due:
                    await self.mark_run(task)
                    if self._on_task_due:
                        asyncio.create_task(self._on_task_due(task))
            except Exception as e:
                print(f"Scheduler error: {e}")
            await asyncio.sleep(60)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    # ── info ────────────────────────────────────────────────────

    def get_all_tasks_info(self) -> list[dict]:
        """Return serializable list for API."""
        result = []
        for task in self.tasks:
            ah = task.get("_active_hours")
            result.append({
                "id": task["id"],
                "name": task["name"],
                "schedule": task["schedule"],
                "agent_type": task.get("agent_type", "researcher"),
                "active": bool(task.get("active")),
                "last_run": task["_last_run"].isoformat() if task.get("_last_run") else None,
                "last_status": task.get("last_status"),
                "last_error": task.get("last_error"),
                "next_run": task["_next_run"].isoformat() if task.get("_next_run") else None,
                "prompt": task.get("prompt", ""),
                "active_hours": (
                    f"{ah[0]:02d}:{ah[1]:02d}-{ah[2]:02d}:{ah[3]:02d}" if ah else None
                ),
            })
        return result
