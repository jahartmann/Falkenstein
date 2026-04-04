"""Smart Scheduler — extends base scheduler with reminders, task chains, auto-prioritization."""
from __future__ import annotations
import asyncio
import datetime
from backend.scheduler import Scheduler, parse_schedule, next_run, _is_in_active_hours, _parse_active_hours


class SmartScheduler(Scheduler):
    """Extended scheduler with reminders, planned tasks, and intelligent timing."""

    def __init__(self, db):
        super().__init__(db)
        self._on_reminder_due = None
        self._on_step_due = None

    # ── Reminders ────────────────────────────────────────────

    async def add_reminder(self, chat_id: str, text: str, due_at: str, follow_up: bool = False) -> int:
        cursor = await self._db._conn.execute(
            "INSERT INTO reminders (chat_id, text, due_at, follow_up) VALUES (?, ?, ?, ?)",
            (chat_id, text, due_at, int(follow_up)),
        )
        await self._db._conn.commit()
        return cursor.lastrowid

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
                    await self.mark_reminder_delivered(reminder["id"])
                    if self._on_reminder_due:
                        asyncio.create_task(self._on_reminder_due(reminder))
                # Planned task steps
                due_steps = await self.get_due_steps()
                for step in due_steps:
                    if self._on_step_due:
                        asyncio.create_task(self._on_step_due(step))
            except Exception as e:
                print(f"SmartScheduler error: {e}")
            await asyncio.sleep(60)

    async def start(self, on_task_due=None, on_reminder_due=None, on_step_due=None) -> None:
        self._on_task_due = on_task_due
        self._on_reminder_due = on_reminder_due
        self._on_step_due = on_step_due
        self._running = True
        await self.load_tasks()
        self._task = asyncio.create_task(self._tick_loop())
