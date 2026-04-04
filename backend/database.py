import json
from pathlib import Path
from typing import Any

import aiosqlite

from backend.models import (
    AgentData, AgentRole, AgentState,
    MessageData, MessageType, Position,
    TaskData, TaskStatus,
)


class Database:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._create_tables()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def _create_tables(self):
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                role           TEXT NOT NULL,
                state          TEXT NOT NULL,
                position_x     INTEGER NOT NULL DEFAULT 0,
                position_y     INTEGER NOT NULL DEFAULT 0,
                traits         TEXT NOT NULL,
                mood           TEXT NOT NULL,
                current_task_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                title          TEXT NOT NULL,
                description    TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'open',
                assigned_to    TEXT,
                project        TEXT,
                parent_task_id INTEGER,
                result         TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent     TEXT NOT NULL,
                to_agent       TEXT NOT NULL,
                project        TEXT,
                type           TEXT NOT NULL,
                content        TEXT NOT NULL,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS relationships (
                agent_a    TEXT NOT NULL,
                agent_b    TEXT NOT NULL,
                trust      REAL NOT NULL DEFAULT 0.5,
                synergy    REAL NOT NULL DEFAULT 0.5,
                friendship REAL NOT NULL DEFAULT 0.5,
                respect    REAL NOT NULL DEFAULT 0.5,
                PRIMARY KEY (agent_a, agent_b)
            );

            CREATE TABLE IF NOT EXISTS tool_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id   TEXT NOT NULL,
                tool_name  TEXT NOT NULL,
                input      TEXT,
                output     TEXT,
                success    INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS personality_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id   TEXT NOT NULL,
                traits     TEXT NOT NULL,
                mood       TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL UNIQUE,
                schedule      TEXT NOT NULL,
                agent_type    TEXT DEFAULT 'researcher',
                prompt        TEXT NOT NULL,
                active        INTEGER DEFAULT 1,
                active_hours  TEXT,
                light_context INTEGER DEFAULT 0,
                last_run      TEXT,
                last_status   TEXT,
                last_error    TEXT,
                created_at    TEXT DEFAULT (datetime('now')),
                updated_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS config (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'general',
                description TEXT,
                updated_at  TEXT DEFAULT (datetime('now'))
            );
        """)
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    async def get_tables(self) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def upsert_agent(self, agent: AgentData):
        await self._conn.execute(
            """
            INSERT INTO agents
                (id, name, role, state, position_x, position_y, traits, mood, current_task_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name            = excluded.name,
                role            = excluded.role,
                state           = excluded.state,
                position_x      = excluded.position_x,
                position_y      = excluded.position_y,
                current_task_id = excluded.current_task_id
            """,
            (
                agent.id,
                agent.name,
                agent.role.value,
                agent.state.value,
                agent.position.x,
                agent.position.y,
                "{}",
                "{}",
                agent.current_task_id,
            ),
        )
        await self._conn.commit()

    def _row_to_agent(self, row: aiosqlite.Row) -> AgentData:
        return AgentData(
            id=row["id"],
            name=row["name"],
            role=AgentRole(row["role"]),
            state=AgentState(row["state"]),
            position=Position(x=row["position_x"], y=row["position_y"]),
            current_task_id=row["current_task_id"],
        )

    async def get_agent(self, agent_id: str) -> AgentData | None:
        cursor = await self._conn.execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_agent(row) if row else None

    async def get_all_agents(self) -> list[AgentData]:
        cursor = await self._conn.execute("SELECT * FROM agents")
        rows = await cursor.fetchall()
        return [self._row_to_agent(r) for r in rows]

    async def update_agent_state(self, agent_id: str, state: AgentState, x: int, y: int):
        await self._conn.execute(
            "UPDATE agents SET state = ?, position_x = ?, position_y = ? WHERE id = ?",
            (state.value, x, y, agent_id),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def create_task(self, task: TaskData) -> int:
        cursor = await self._conn.execute(
            """
            INSERT INTO tasks (title, description, status, assigned_to, project, parent_task_id, result)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.title,
                task.description,
                task.status.value,
                task.assigned_to,
                task.project,
                task.parent_task_id,
                task.result,
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid

    def _row_to_task(self, row: aiosqlite.Row) -> TaskData:
        return TaskData(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            assigned_to=row["assigned_to"],
            project=row["project"],
            parent_task_id=row["parent_task_id"],
            result=row["result"],
        )

    async def get_task(self, task_id: int) -> TaskData | None:
        cursor = await self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    async def update_task_status(
        self, task_id: int, status: TaskStatus, assigned_to: str | None = None
    ):
        await self._conn.execute(
            """
            UPDATE tasks
            SET status = ?, assigned_to = COALESCE(?, assigned_to),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status.value, assigned_to, task_id),
        )
        await self._conn.commit()

    async def get_open_tasks(self) -> list[TaskData]:
        cursor = await self._conn.execute(
            "SELECT * FROM tasks WHERE status = ?", (TaskStatus.OPEN.value,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def get_subtasks(self, parent_id: int) -> list[TaskData]:
        cursor = await self._conn.execute(
            "SELECT * FROM tasks WHERE parent_task_id = ? ORDER BY id", (parent_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def get_tasks_by_project(self, project: str) -> list[TaskData]:
        cursor = await self._conn.execute(
            "SELECT * FROM tasks WHERE project = ? ORDER BY id", (project,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def update_task_result(self, task_id: int, result: str):
        await self._conn.execute(
            "UPDATE tasks SET result = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (result, task_id),
        )
        await self._conn.commit()

    async def all_subtasks_done(self, parent_id: int) -> bool:
        cursor = await self._conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done "
            "FROM tasks WHERE parent_task_id = ?",
            (parent_id,),
        )
        row = await cursor.fetchone()
        total = row["total"]
        done = row["done"] or 0
        return total > 0 and total == done

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def create_message(self, msg: MessageData):
        await self._conn.execute(
            """
            INSERT INTO messages (from_agent, to_agent, project, type, content)
            VALUES (?, ?, ?, ?, ?)
            """,
            (msg.from_agent, msg.to_agent, msg.project, msg.type.value, msg.content),
        )
        await self._conn.commit()

    def _row_to_message(self, row: aiosqlite.Row) -> MessageData:
        return MessageData(
            id=row["id"],
            from_agent=row["from_agent"],
            to_agent=row["to_agent"],
            project=row["project"],
            type=MessageType(row["type"]),
            content=row["content"],
        )

    async def get_messages_for(self, agent_id: str, limit: int = 15) -> list[MessageData]:
        cursor = await self._conn.execute(
            """
            SELECT * FROM messages
            WHERE to_agent = ? OR to_agent = 'team'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (agent_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(r) for r in rows]

    # ------------------------------------------------------------------
    # Tool log
    # ------------------------------------------------------------------

    async def log_tool_use(
        self,
        agent_id: str,
        tool_name: str,
        input_data: Any,
        output_data: Any,
        success: bool,
    ):
        await self._conn.execute(
            """
            INSERT INTO tool_log (agent_id, tool_name, input, output, success)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                tool_name,
                json.dumps(input_data) if not isinstance(input_data, str) else input_data,
                json.dumps(output_data) if not isinstance(output_data, str) else output_data,
                int(success),
            ),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Schedules
    # ------------------------------------------------------------------

    async def create_schedule(
        self,
        name: str,
        schedule: str,
        agent_type: str,
        prompt: str,
        active: int = 1,
        active_hours: str | None = None,
        light_context: int = 0,
    ) -> int:
        cursor = await self._conn.execute(
            """
            INSERT INTO schedules (name, schedule, agent_type, prompt, active, active_hours, light_context)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, schedule, agent_type, prompt, active, active_hours, light_context),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_schedule(self, schedule_id: int) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_schedules(self) -> list[dict]:
        cursor = await self._conn.execute("SELECT * FROM schedules ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_active_schedules(self) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM schedules WHERE active = 1 ORDER BY id"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    _SCHEDULE_FIELDS = {"name", "schedule", "agent_type", "prompt", "active", "active_hours", "light_context"}

    async def update_schedule(self, schedule_id: int, **kwargs) -> None:
        fields = {k: v for k, v in kwargs.items() if k in self._SCHEDULE_FIELDS}
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values())
        values.append(schedule_id)
        await self._conn.execute(
            f"UPDATE schedules SET {sets}, updated_at = datetime('now') WHERE id = ?",
            values,
        )
        await self._conn.commit()

    async def delete_schedule(self, schedule_id: int) -> None:
        await self._conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        await self._conn.commit()

    async def toggle_schedule(self, schedule_id: int) -> bool:
        """Toggle active flag, return new state."""
        await self._conn.execute(
            "UPDATE schedules SET active = 1 - active, updated_at = datetime('now') WHERE id = ?",
            (schedule_id,),
        )
        await self._conn.commit()
        s = await self.get_schedule(schedule_id)
        return bool(s["active"])

    async def update_schedule_result(self, schedule_id: int, status: str, error: str | None = None) -> None:
        await self._conn.execute(
            "UPDATE schedules SET last_status = ?, last_error = ?, updated_at = datetime('now') WHERE id = ?",
            (status, error, schedule_id),
        )
        await self._conn.commit()

    async def mark_schedule_run(self, schedule_id: int) -> None:
        await self._conn.execute(
            "UPDATE schedules SET last_run = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (schedule_id,),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    async def set_config(
        self,
        key: str,
        value: str,
        category: str = "general",
        description: str | None = None,
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO config (key, value, category, description, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value       = excluded.value,
                category    = excluded.category,
                description = excluded.description,
                updated_at  = datetime('now')
            """,
            (key, value, category, description),
        )
        await self._conn.commit()

    async def get_config(self, key: str, default: str | None = None) -> str | None:
        cursor = await self._conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else default

    async def get_config_by_category(self, category: str) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM config WHERE category = ? ORDER BY key", (category,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all_config(self) -> list[dict]:
        cursor = await self._conn.execute("SELECT * FROM config ORDER BY key")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
