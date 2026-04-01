import json
from pathlib import Path
from typing import Any

import aiosqlite

from backend.models import (
    AgentData, AgentMood, AgentRole, AgentState, AgentTraits,
    MessageData, MessageType, Position,
    RelationshipData, TaskData, TaskStatus,
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
                traits          = excluded.traits,
                mood            = excluded.mood,
                current_task_id = excluded.current_task_id
            """,
            (
                agent.id,
                agent.name,
                agent.role.value,
                agent.state.value,
                agent.position.x,
                agent.position.y,
                json.dumps(agent.traits.model_dump()),
                json.dumps(agent.mood.model_dump()),
                agent.current_task_id,
            ),
        )
        await self._conn.commit()

    def _row_to_agent(self, row: aiosqlite.Row) -> AgentData:
        traits_dict = json.loads(row["traits"])
        mood_dict = json.loads(row["mood"])
        return AgentData(
            id=row["id"],
            name=row["name"],
            role=AgentRole(row["role"]),
            state=AgentState(row["state"]),
            position=Position(x=row["position_x"], y=row["position_y"]),
            traits=AgentTraits(**traits_dict),
            mood=AgentMood(**mood_dict),
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
    # Relationships
    # ------------------------------------------------------------------

    @staticmethod
    def _sorted_pair(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    async def upsert_relationship(self, rel: RelationshipData):
        a, b = self._sorted_pair(rel.agent_a, rel.agent_b)
        await self._conn.execute(
            """
            INSERT INTO relationships (agent_a, agent_b, trust, synergy, friendship, respect)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_a, agent_b) DO UPDATE SET
                trust      = excluded.trust,
                synergy    = excluded.synergy,
                friendship = excluded.friendship,
                respect    = excluded.respect
            """,
            (a, b, rel.trust, rel.synergy, rel.friendship, rel.respect),
        )
        await self._conn.commit()

    async def get_relationship(self, agent_a: str, agent_b: str) -> RelationshipData | None:
        a, b = self._sorted_pair(agent_a, agent_b)
        cursor = await self._conn.execute(
            "SELECT * FROM relationships WHERE agent_a = ? AND agent_b = ?", (a, b)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return RelationshipData(
            agent_a=row["agent_a"],
            agent_b=row["agent_b"],
            trust=row["trust"],
            synergy=row["synergy"],
            friendship=row["friendship"],
            respect=row["respect"],
        )

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
