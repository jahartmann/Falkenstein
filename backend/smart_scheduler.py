"""Smart Scheduler — extends base scheduler with reminders, task chains, auto-prioritization."""
from __future__ import annotations
import asyncio
import datetime
import logging
from backend.scheduler import Scheduler, parse_schedule, next_run, _is_in_active_hours, _parse_active_hours

log = logging.getLogger(__name__)


class SmartScheduler(Scheduler):
    """Extended scheduler with reminders, planned tasks, and intelligent timing."""

    def __init__(self, db):
        super().__init__(db)
        self._on_reminder_due = None
        self._on_step_due = None

    # ── Reminders ────────────────────────────────────────────

    async def add_reminder(self, chat_id: str, text: str, due_at: str, follow_up: bool = False) -> int:
        # Normalize due_at to ISO format without timezone issues
        normalized = self._normalize_datetime(due_at)
        cursor = await self._db._conn.execute(
            "INSERT INTO reminders (chat_id, text, due_at, follow_up) VALUES (?, ?, ?, ?)",
            (chat_id, text, normalized, int(follow_up)),
        )
        await self._db._conn.commit()
        return cursor.lastrowid

    @staticmethod
    def _normalize_datetime(dt_str: str) -> str:
        """Parse various datetime formats and return consistent ISO string (local time, no tz)."""
        if not dt_str:
            return datetime.datetime.now().isoformat()
        # Try parsing common formats
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                dt = datetime.datetime.strptime(dt_str.replace("Z", "").split("+")[0], fmt)
                return dt.isoformat()
            except ValueError:
                continue
        # If ISO with timezone info, strip it
        try:
            dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.replace(tzinfo=None).isoformat()
        except (ValueError, TypeError):
            pass
        return dt_str  # Return as-is as last resort

    async def get_due_reminders(self, now: datetime.datetime | None = None) -> list[dict]:
        now = now or datetime.datetime.now()
        cursor = await self._db._conn.execute(
            "SELECT id, chat_id, text, due_at, follow_up FROM reminders "
            "WHERE delivered = 0 AND due_at <= ?",
            (now.isoformat(),),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_reminder_delivered(self, reminder_id: int):
        await self._db._conn.execute(
            "UPDATE reminders SET delivered = 1 WHERE id = ?", (reminder_id,),
        )
        await self._db._conn.commit()

    # ── Planned Tasks ────────────────────────────────────────

    async def add_planned_task(self, name: str, chat_id: str, steps: list[dict]) -> int:
        cursor = await self._db._conn.execute(
            "INSERT INTO planned_tasks (name, chat_id) VALUES (?, ?)",
            (name, chat_id),
        )
        ptid = cursor.lastrowid
        for i, step in enumerate(steps):
            await self._db._conn.execute(
                "INSERT INTO task_steps (planned_task_id, step_order, agent_prompt, scheduled_at) "
                "VALUES (?, ?, ?, ?)",
                (ptid, i + 1, step["agent_prompt"], step.get("scheduled_at")),
            )
        await self._db._conn.commit()
        return ptid

    async def get_planned_task_steps(self, planned_task_id: int) -> list[dict]:
        cursor = await self._db._conn.execute(
            "SELECT id, planned_task_id, step_order, agent_prompt, scheduled_at, "
            "depends_on_step, status, result, completed_at "
            "FROM task_steps WHERE planned_task_id = ? ORDER BY step_order",
            (planned_task_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_due_steps(self, now: datetime.datetime | None = None) -> list[dict]:
        now = now or datetime.datetime.now()
        cursor = await self._db._conn.execute(
            "SELECT ts.id, ts.planned_task_id, ts.step_order, ts.agent_prompt, "
            "ts.scheduled_at, ts.depends_on_step, pt.chat_id, pt.name "
            "FROM task_steps ts JOIN planned_tasks pt ON ts.planned_task_id = pt.id "
            "WHERE ts.status = 'pending' AND ts.scheduled_at IS NOT NULL AND ts.scheduled_at <= ?",
            (now.isoformat(),),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def mark_step_completed(self, step_id: int, result: str = ""):
        await self._db._conn.execute(
            "UPDATE task_steps SET status = 'completed', result = ?, "
            "completed_at = datetime('now') WHERE id = ?",
            (result, step_id),
        )
        await self._db._conn.commit()

    # ── Extended tick loop ───────────────────────────────────

    async def _tick_loop(self) -> None:
        log.info("SmartScheduler tick loop started")
        consecutive_errors = 0
        while self._running:
            try:
                # Original schedule checks
                due = self.get_due_tasks()
                for task in due:
                    await self.mark_run(task)
                    if self._on_task_due:
                        asyncio.create_task(self._on_task_due(task))
                # Reminders
                due_reminders = await self.get_due_reminders()
                for reminder in due_reminders:
                    # Mark delivered FIRST to prevent duplicate delivery on crash
                    await self.mark_reminder_delivered(reminder["id"])
                    if self._on_reminder_due:
                        try:
                            asyncio.create_task(self._on_reminder_due(reminder))
                        except Exception as e:
                            log.error(f"Reminder dispatch failed for #{reminder['id']}: {e}")
                # Planned task steps
                due_steps = await self.get_due_steps()
                for step in due_steps:
                    await self.mark_step_completed(step["id"], result="dispatched")
                    if self._on_step_due:
                        try:
                            asyncio.create_task(self._on_step_due(step))
                        except Exception as e:
                            log.error(f"Step dispatch failed for #{step['id']}: {e}")
                consecutive_errors = 0
            except asyncio.CancelledError:
                log.info("SmartScheduler tick loop cancelled")
                return
            except Exception as e:
                consecutive_errors += 1
                log.error(f"SmartScheduler tick error ({consecutive_errors}): {e}")
                if consecutive_errors >= 10:
                    log.critical("SmartScheduler: 10 consecutive errors, backing off")
            try:
                # Back off on repeated errors (max 5 min)
                sleep_time = min(60 * (2 ** min(consecutive_errors, 3)), 300) if consecutive_errors > 0 else 30
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                log.info("SmartScheduler sleep cancelled")
                return

    async def start(self, on_task_due=None, on_reminder_due=None, on_step_due=None) -> None:
        self._on_task_due = on_task_due
        self._on_reminder_due = on_reminder_due
        self._on_step_due = on_step_due
        self._running = True
        await self.load_tasks()
        self._task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("SmartScheduler stopped")
