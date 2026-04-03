# Falkenstein Phase 1: Backend-Grundgerüst & Lebendiges Büro

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein lauffähiges System mit FastAPI-Backend, SQLite-Datenbank, 7 Agenten die im Phaser-Büro herumlaufen, miteinander reden (Ollama), und ein erstes Tool (file_manager) ausführen können.

**Architecture:** Async FastAPI-Monolith mit ThreadPoolExecutor für Ollama-Calls. SQLite für World State. WebSocket für Frontend-Kommunikation. Phaser.js mit vorhandener Tiled-Map (60x48, 48px Tiles) und Character-Sprites (Adam, Alex, Amelia, Bob + weitere).

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, websockets, ollama (Python lib), aiosqlite, Phaser 3, Easystar.js

---

## File Structure

```
/falkenstein
├── backend/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, startup, WebSocket endpoint
│   ├── config.py                # Settings from .env via pydantic-settings
│   ├── database.py              # SQLite schema, connection, CRUD helpers
│   ├── models.py                # Pydantic models (Agent, Task, Message, etc.)
│   ├── agent.py                 # Agent class with state machine (IDLE/WORK)
│   ├── agent_pool.py            # Manages 7 agents as async tasks
│   ├── orchestrator.py          # PM logic: receive task, decompose, assign
│   ├── sim_engine.py            # IDLE behavior: wander, talk, coffee
│   ├── llm_client.py            # Ollama wrapper with asyncio.to_thread
│   ├── ws_manager.py            # WebSocket connection manager, broadcast
│   └── tools/
│       ├── __init__.py
│       ├── base.py              # Tool base class & registry
│       └── file_manager.py      # Read/write/delete files in WORKSPACE_PATH
├── frontend/
│   ├── index.html               # Phaser container + UI overlays
│   ├── game.js                  # Phaser scene: tilemap, sprites, pathfinding
│   ├── agents.js                # Agent sprite management, animations, bubbles
│   ├── websocket.js             # WS client, event dispatch
│   └── assets/                  # Copied from Büro/: tileset PNGs, map JSON, sprites
├── tests/
│   ├── __init__.py
│   ├── test_database.py
│   ├── test_agent.py
│   ├── test_llm_client.py
│   ├── test_file_manager.py
│   ├── test_orchestrator.py
│   ├── test_sim_engine.py
│   └── test_ws_manager.py
├── data/                        # Runtime data (gitignored)
├── workspace/                   # Agent work directory (gitignored)
├── .env.example
├── .gitignore
├── requirements.txt
└── CLAUDE.md
```

---

### Task 1: Projekt-Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `backend/__init__.py`
- Create: `backend/tools/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Git-Repository initialisieren**

```bash
cd /Users/janikhartmann/Falkenstein
git init
```

- [ ] **Step 2: requirements.txt erstellen**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
websockets==12.0
aiosqlite==0.20.0
pydantic-settings==2.5.0
ollama==0.4.0
python-dotenv==1.0.1
httpx==0.27.0
duckduckgo-search==6.3.0
beautifulsoup4==4.12.3
pytest==8.3.0
pytest-asyncio==0.24.0
```

- [ ] **Step 3: .env.example erstellen**

```
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
WORKSPACE_PATH=./workspace
OBSIDIAN_VAULT_PATH=~/Obsidian
DB_PATH=./data/falkenstein.db
FRONTEND_PORT=8080
```

- [ ] **Step 4: .gitignore erstellen**

```
__pycache__/
*.pyc
.env
data/
workspace/
.DS_Store
.superpowers/
node_modules/
```

- [ ] **Step 5: Leere __init__.py Dateien erstellen**

```bash
mkdir -p backend/tools tests data workspace frontend/assets
touch backend/__init__.py backend/tools/__init__.py tests/__init__.py
```

- [ ] **Step 6: .env aus Example kopieren**

```bash
cp .env.example .env
```

- [ ] **Step 7: Virtualenv erstellen und Dependencies installieren**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example .gitignore backend/__init__.py backend/tools/__init__.py tests/__init__.py
git commit -m "chore: project scaffolding with dependencies and directory structure"
```

---

### Task 2: Config & Settings

**Files:**
- Create: `backend/config.py`
- Test: `tests/test_config.py` (kein separater Test nötig — wird implizit über andere Tests geprüft)

- [ ] **Step 1: Config-Modul schreiben**

```python
# backend/config.py
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    workspace_path: Path = Path("./workspace")
    obsidian_vault_path: Path = Path.home() / "Obsidian"
    db_path: Path = Path("./data/falkenstein.db")
    frontend_port: int = 8080

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 2: Commit**

```bash
git add backend/config.py
git commit -m "feat: add pydantic-settings config from .env"
```

---

### Task 3: Datenbank-Schema & CRUD

**Files:**
- Create: `backend/database.py`
- Create: `backend/models.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Pydantic Models schreiben**

```python
# backend/models.py
from pydantic import BaseModel
from enum import Enum


class AgentRole(str, Enum):
    PM = "pm"
    TEAM_LEAD = "team_lead"
    CODER_1 = "coder_1"
    CODER_2 = "coder_2"
    RESEARCHER = "researcher"
    WRITER = "writer"
    OPS = "ops"


class AgentState(str, Enum):
    IDLE_WANDER = "idle_wander"
    IDLE_TALK = "idle_talk"
    IDLE_COFFEE = "idle_coffee"
    IDLE_PHONE = "idle_phone"
    IDLE_SIT = "idle_sit"
    WORK_SIT = "work_sit"
    WORK_TYPE = "work_type"
    WORK_TOOL = "work_tool"
    WORK_REVIEW = "work_review"


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class MessageType(str, Enum):
    HANDOFF = "handoff"
    QUESTION = "question"
    REVIEW = "review"
    CHAT = "chat"


class AgentTraits(BaseModel):
    social: float = 0.5
    focus: float = 0.5
    confidence: float = 0.5
    patience: float = 0.5
    curiosity: float = 0.5
    leadership: float = 0.3


class AgentMood(BaseModel):
    energy: float = 0.8
    stress: float = 0.1
    motivation: float = 0.7
    frustration: float = 0.0


class Position(BaseModel):
    x: int = 0
    y: int = 0


class AgentData(BaseModel):
    id: str
    name: str
    role: AgentRole
    state: AgentState = AgentState.IDLE_SIT
    position: Position = Position()
    traits: AgentTraits = AgentTraits()
    mood: AgentMood = AgentMood()
    current_task_id: int | None = None


class TaskData(BaseModel):
    id: int | None = None
    title: str
    description: str
    status: TaskStatus = TaskStatus.OPEN
    assigned_to: str | None = None
    project: str | None = None
    parent_task_id: int | None = None
    result: str | None = None


class MessageData(BaseModel):
    id: int | None = None
    from_agent: str
    to_agent: str
    project: str | None = None
    type: MessageType
    content: str


class RelationshipData(BaseModel):
    agent_a: str
    agent_b: str
    trust: float = 0.5
    synergy: float = 0.5
    friendship: float = 0.5
    respect: float = 0.5
```

- [ ] **Step 2: Failing test für Datenbank schreiben**

```python
# tests/test_database.py
import pytest
import pytest_asyncio
from pathlib import Path
from backend.database import Database
from backend.models import (
    AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position,
    TaskData, TaskStatus, MessageData, MessageType, RelationshipData,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    tables = await db.get_tables()
    assert "agents" in tables
    assert "tasks" in tables
    assert "messages" in tables
    assert "relationships" in tables
    assert "tool_log" in tables


@pytest.mark.asyncio
async def test_upsert_and_get_agent(db):
    agent = AgentData(
        id="coder_1", name="Alex", role=AgentRole.CODER_1,
        state=AgentState.IDLE_SIT, position=Position(x=10, y=20),
        traits=AgentTraits(social=0.7, focus=0.8),
        mood=AgentMood(energy=0.9),
    )
    await db.upsert_agent(agent)
    loaded = await db.get_agent("coder_1")
    assert loaded is not None
    assert loaded.name == "Alex"
    assert loaded.traits.social == 0.7
    assert loaded.position.x == 10


@pytest.mark.asyncio
async def test_create_and_get_task(db):
    task = TaskData(title="Build API", description="REST endpoints", project="website")
    task_id = await db.create_task(task)
    loaded = await db.get_task(task_id)
    assert loaded is not None
    assert loaded.title == "Build API"
    assert loaded.status == TaskStatus.OPEN


@pytest.mark.asyncio
async def test_update_task_status(db):
    task = TaskData(title="Test", description="desc")
    task_id = await db.create_task(task)
    await db.update_task_status(task_id, TaskStatus.IN_PROGRESS, assigned_to="coder_1")
    loaded = await db.get_task(task_id)
    assert loaded.status == TaskStatus.IN_PROGRESS
    assert loaded.assigned_to == "coder_1"


@pytest.mark.asyncio
async def test_create_and_get_messages(db):
    msg = MessageData(
        from_agent="researcher", to_agent="coder_1",
        type=MessageType.HANDOFF, content="API docs found",
    )
    await db.create_message(msg)
    msgs = await db.get_messages_for("coder_1")
    assert len(msgs) == 1
    assert msgs[0].content == "API docs found"


@pytest.mark.asyncio
async def test_upsert_and_get_relationship(db):
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.9)
    await db.upsert_relationship(rel)
    loaded = await db.get_relationship("coder_1", "coder_2")
    assert loaded is not None
    assert loaded.synergy == 0.9
    # Reverse lookup should also work
    loaded_rev = await db.get_relationship("coder_2", "coder_1")
    assert loaded_rev is not None
    assert loaded_rev.synergy == 0.9
```

- [ ] **Step 3: Tests ausführen, Fail verifizieren**

```bash
cd /Users/janikhartmann/Falkenstein
source venv/bin/activate
python -m pytest tests/test_database.py -v
```

Expected: ImportError — `backend.database` existiert noch nicht.

- [ ] **Step 4: Database-Modul implementieren**

```python
# backend/database.py
import aiosqlite
import json
from pathlib import Path
from backend.models import (
    AgentData, AgentTraits, AgentMood, Position, AgentRole, AgentState,
    TaskData, TaskStatus, MessageData, MessageType, RelationshipData,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'idle_sit',
    position_x INTEGER NOT NULL DEFAULT 0,
    position_y INTEGER NOT NULL DEFAULT 0,
    traits TEXT NOT NULL DEFAULT '{}',
    mood TEXT NOT NULL DEFAULT '{}',
    current_task_id INTEGER
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    assigned_to TEXT,
    project TEXT,
    parent_task_id INTEGER,
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    project TEXT,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS relationships (
    agent_a TEXT NOT NULL,
    agent_b TEXT NOT NULL,
    trust REAL NOT NULL DEFAULT 0.5,
    synergy REAL NOT NULL DEFAULT 0.5,
    friendship REAL NOT NULL DEFAULT 0.5,
    respect REAL NOT NULL DEFAULT 0.5,
    PRIMARY KEY (agent_a, agent_b)
);

CREATE TABLE IF NOT EXISTS tool_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT,
    success INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personality_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    traits TEXT NOT NULL,
    mood TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def get_tables(self) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    # --- Agents ---

    async def upsert_agent(self, agent: AgentData):
        await self._conn.execute(
            """INSERT INTO agents (id, name, role, state, position_x, position_y, traits, mood, current_task_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, role=excluded.role, state=excluded.state,
                 position_x=excluded.position_x, position_y=excluded.position_y,
                 traits=excluded.traits, mood=excluded.mood,
                 current_task_id=excluded.current_task_id""",
            (
                agent.id, agent.name, agent.role.value, agent.state.value,
                agent.position.x, agent.position.y,
                agent.traits.model_dump_json(), agent.mood.model_dump_json(),
                agent.current_task_id,
            ),
        )
        await self._conn.commit()

    async def get_agent(self, agent_id: str) -> AgentData | None:
        cursor = await self._conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return AgentData(
            id=row["id"], name=row["name"],
            role=AgentRole(row["role"]), state=AgentState(row["state"]),
            position=Position(x=row["position_x"], y=row["position_y"]),
            traits=AgentTraits(**json.loads(row["traits"])),
            mood=AgentMood(**json.loads(row["mood"])),
            current_task_id=row["current_task_id"],
        )

    async def get_all_agents(self) -> list[AgentData]:
        cursor = await self._conn.execute("SELECT * FROM agents")
        rows = await cursor.fetchall()
        return [
            AgentData(
                id=row["id"], name=row["name"],
                role=AgentRole(row["role"]), state=AgentState(row["state"]),
                position=Position(x=row["position_x"], y=row["position_y"]),
                traits=AgentTraits(**json.loads(row["traits"])),
                mood=AgentMood(**json.loads(row["mood"])),
                current_task_id=row["current_task_id"],
            )
            for row in rows
        ]

    async def update_agent_state(self, agent_id: str, state: AgentState, x: int, y: int):
        await self._conn.execute(
            "UPDATE agents SET state = ?, position_x = ?, position_y = ? WHERE id = ?",
            (state.value, x, y, agent_id),
        )
        await self._conn.commit()

    # --- Tasks ---

    async def create_task(self, task: TaskData) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO tasks (title, description, status, assigned_to, project, parent_task_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task.title, task.description, task.status.value,
             task.assigned_to, task.project, task.parent_task_id),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_task(self, task_id: int) -> TaskData | None:
        cursor = await self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return TaskData(
            id=row["id"], title=row["title"], description=row["description"],
            status=TaskStatus(row["status"]), assigned_to=row["assigned_to"],
            project=row["project"], parent_task_id=row["parent_task_id"],
            result=row["result"],
        )

    async def update_task_status(self, task_id: int, status: TaskStatus, assigned_to: str | None = None):
        if assigned_to is not None:
            await self._conn.execute(
                "UPDATE tasks SET status = ?, assigned_to = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status.value, assigned_to, task_id),
            )
        else:
            await self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status.value, task_id),
            )
        await self._conn.commit()

    async def get_open_tasks(self) -> list[TaskData]:
        cursor = await self._conn.execute(
            "SELECT * FROM tasks WHERE status IN ('open', 'in_progress') ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [
            TaskData(
                id=row["id"], title=row["title"], description=row["description"],
                status=TaskStatus(row["status"]), assigned_to=row["assigned_to"],
                project=row["project"], parent_task_id=row["parent_task_id"],
                result=row["result"],
            )
            for row in rows
        ]

    # --- Messages ---

    async def create_message(self, msg: MessageData):
        await self._conn.execute(
            "INSERT INTO messages (from_agent, to_agent, project, type, content) VALUES (?, ?, ?, ?, ?)",
            (msg.from_agent, msg.to_agent, msg.project, msg.type.value, msg.content),
        )
        await self._conn.commit()

    async def get_messages_for(self, agent_id: str, limit: int = 15) -> list[MessageData]:
        cursor = await self._conn.execute(
            "SELECT * FROM messages WHERE to_agent = ? OR to_agent = 'team' ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            MessageData(
                id=row["id"], from_agent=row["from_agent"], to_agent=row["to_agent"],
                project=row["project"], type=MessageType(row["type"]), content=row["content"],
            )
            for row in rows
        ]

    # --- Relationships ---

    async def upsert_relationship(self, rel: RelationshipData):
        a, b = sorted([rel.agent_a, rel.agent_b])
        await self._conn.execute(
            """INSERT INTO relationships (agent_a, agent_b, trust, synergy, friendship, respect)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_a, agent_b) DO UPDATE SET
                 trust=excluded.trust, synergy=excluded.synergy,
                 friendship=excluded.friendship, respect=excluded.respect""",
            (a, b, rel.trust, rel.synergy, rel.friendship, rel.respect),
        )
        await self._conn.commit()

    async def get_relationship(self, agent_a: str, agent_b: str) -> RelationshipData | None:
        a, b = sorted([agent_a, agent_b])
        cursor = await self._conn.execute(
            "SELECT * FROM relationships WHERE agent_a = ? AND agent_b = ?", (a, b)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return RelationshipData(
            agent_a=row["agent_a"], agent_b=row["agent_b"],
            trust=row["trust"], synergy=row["synergy"],
            friendship=row["friendship"], respect=row["respect"],
        )

    # --- Tool Log ---

    async def log_tool_use(self, agent_id: str, tool_name: str, input_data: str, output_data: str | None, success: bool):
        await self._conn.execute(
            "INSERT INTO tool_log (agent_id, tool_name, input, output, success) VALUES (?, ?, ?, ?, ?)",
            (agent_id, tool_name, input_data, output_data, int(success)),
        )
        await self._conn.commit()
```

- [ ] **Step 5: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_database.py -v
```

Expected: Alle 6 Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/database.py tests/test_database.py
git commit -m "feat: SQLite database with agent, task, message, relationship CRUD"
```

---

### Task 4: Ollama LLM Client

**Files:**
- Create: `backend/llm_client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_llm_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from backend.llm_client import LLMClient


@pytest.mark.asyncio
async def test_chat_returns_response():
    mock_response = {"message": {"content": "Hello from Ollama"}}
    with patch("backend.llm_client.ollama_chat") as mock_chat:
        mock_chat.return_value = mock_response
        client = LLMClient()
        result = await client.chat(
            system_prompt="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert result == "Hello from Ollama"
        mock_chat.assert_called_once()


@pytest.mark.asyncio
async def test_chat_with_tools_returns_tool_call():
    mock_response = {
        "message": {
            "content": "",
            "tool_calls": [
                {"function": {"name": "web_surfer", "arguments": {"query": "python"}}}
            ],
        }
    }
    with patch("backend.llm_client.ollama_chat") as mock_chat:
        mock_chat.return_value = mock_response
        client = LLMClient()
        result = await client.chat_with_tools(
            system_prompt="You have tools.",
            messages=[{"role": "user", "content": "Search for python"}],
            tools=[{"type": "function", "function": {"name": "web_surfer", "parameters": {}}}],
        )
        assert result["tool_calls"][0]["function"]["name"] == "web_surfer"


@pytest.mark.asyncio
async def test_generate_sim_action_returns_string():
    mock_response = {"message": {"content": "wander"}}
    with patch("backend.llm_client.ollama_chat") as mock_chat:
        mock_chat.return_value = mock_response
        client = LLMClient()
        result = await client.generate_sim_action(
            agent_name="Alex",
            personality="social and curious",
            nearby_agents=["Bob", "Amelia"],
        )
        assert isinstance(result, str)
        assert len(result) > 0
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_llm_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: LLM Client implementieren**

```python
# backend/llm_client.py
import asyncio
from ollama import chat as ollama_chat
from backend.config import settings


class LLMClient:
    def __init__(self):
        self.model = settings.ollama_model
        self.host = settings.ollama_host

    async def chat(self, system_prompt: str, messages: list[dict]) -> str:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await asyncio.to_thread(
            ollama_chat, model=self.model, messages=full_messages
        )
        return response["message"]["content"]

    async def chat_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict]
    ) -> dict:
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await asyncio.to_thread(
            ollama_chat, model=self.model, messages=full_messages, tools=tools
        )
        return response["message"]

    async def generate_sim_action(
        self, agent_name: str, personality: str, nearby_agents: list[str]
    ) -> str:
        nearby = ", ".join(nearby_agents) if nearby_agents else "niemand"
        prompt = (
            f"Du bist {agent_name}, ein Büro-Mitarbeiter. "
            f"Deine Persönlichkeit: {personality}. "
            f"In deiner Nähe: {nearby}. "
            f"Du hast gerade nichts zu tun. Was machst du? "
            f"Antworte mit GENAU EINEM Wort: wander, talk, coffee, phone, sit"
        )
        return await self.chat(
            system_prompt="Du simulierst einen Büro-Mitarbeiter. Antworte immer mit genau einem Wort.",
            messages=[{"role": "user", "content": prompt}],
        )

    async def generate_chat_message(
        self, agent_name: str, personality: str, partner_name: str, topic: str | None = None
    ) -> str:
        prompt = (
            f"Du bist {agent_name} und redest gerade mit {partner_name} im Büro. "
            f"Deine Persönlichkeit: {personality}. "
        )
        if topic:
            prompt += f"Thema: {topic}. "
        prompt += "Sag etwas Kurzes und Natürliches (max 15 Wörter, auf Deutsch)."
        return await self.chat(
            system_prompt="Du bist ein Büro-Mitarbeiter in einer Simulation. Rede natürlich und kurz.",
            messages=[{"role": "user", "content": prompt}],
        )
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_llm_client.py -v
```

Expected: Alle 3 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/llm_client.py tests/test_llm_client.py
git commit -m "feat: Ollama LLM client with async thread pool, sim action generation"
```

---

### Task 5: Tool Base Class & File Manager

**Files:**
- Create: `backend/tools/base.py`
- Create: `backend/tools/file_manager.py`
- Test: `tests/test_file_manager.py`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_file_manager.py
import pytest
import pytest_asyncio
from pathlib import Path
from backend.tools.file_manager import FileManagerTool


@pytest_asyncio.fixture
async def tool(tmp_path):
    return FileManagerTool(workspace_path=tmp_path)


@pytest.mark.asyncio
async def test_write_and_read_file(tool, tmp_path):
    result = await tool.execute({"action": "write", "path": "test.txt", "content": "hello world"})
    assert result.success is True
    assert (tmp_path / "test.txt").read_text() == "hello world"

    result = await tool.execute({"action": "read", "path": "test.txt"})
    assert result.success is True
    assert result.output == "hello world"


@pytest.mark.asyncio
async def test_write_creates_subdirectories(tool, tmp_path):
    result = await tool.execute({"action": "write", "path": "sub/dir/file.py", "content": "print('hi')"})
    assert result.success is True
    assert (tmp_path / "sub" / "dir" / "file.py").read_text() == "print('hi')"


@pytest.mark.asyncio
async def test_list_files(tool, tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    result = await tool.execute({"action": "list", "path": "."})
    assert result.success is True
    assert "a.txt" in result.output
    assert "b.txt" in result.output


@pytest.mark.asyncio
async def test_delete_file(tool, tmp_path):
    (tmp_path / "delete_me.txt").write_text("bye")
    result = await tool.execute({"action": "delete", "path": "delete_me.txt"})
    assert result.success is True
    assert not (tmp_path / "delete_me.txt").exists()


@pytest.mark.asyncio
async def test_path_traversal_blocked(tool):
    result = await tool.execute({"action": "read", "path": "../../etc/passwd"})
    assert result.success is False
    assert "outside" in result.output.lower() or "nicht erlaubt" in result.output.lower()


@pytest.mark.asyncio
async def test_read_nonexistent_file(tool):
    result = await tool.execute({"action": "read", "path": "nope.txt"})
    assert result.success is False


@pytest.mark.asyncio
async def test_schema_returns_dict(tool):
    schema = tool.schema()
    assert "properties" in schema
    assert "action" in schema["properties"]
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_file_manager.py -v
```

Expected: ImportError.

- [ ] **Step 3: Tool Base Class implementieren**

```python
# backend/tools/base.py
from dataclasses import dataclass


@dataclass
class ToolResult:
    success: bool
    output: str


class Tool:
    name: str = ""
    description: str = ""

    async def execute(self, params: dict) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas_for_ollama(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema(),
                },
            }
            for t in self._tools.values()
        ]
```

- [ ] **Step 4: File Manager implementieren**

```python
# backend/tools/file_manager.py
from pathlib import Path
from backend.tools.base import Tool, ToolResult


class FileManagerTool(Tool):
    name = "file_manager"
    description = (
        "Dateien im Workspace lesen, schreiben, auflisten und löschen. "
        "Actions: read, write, list, delete. "
        "Pfade sind relativ zum Workspace-Verzeichnis."
    )

    def __init__(self, workspace_path: Path):
        self.workspace = workspace_path.resolve()

    def _resolve_safe(self, path_str: str) -> Path | None:
        target = (self.workspace / path_str).resolve()
        if not str(target).startswith(str(self.workspace)):
            return None
        return target

    async def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "")
        path_str = params.get("path", ".")

        target = self._resolve_safe(path_str)
        if target is None:
            return ToolResult(success=False, output="Pfad außerhalb des Workspace nicht erlaubt.")

        if action == "read":
            return await self._read(target)
        elif action == "write":
            content = params.get("content", "")
            return await self._write(target, content)
        elif action == "list":
            return await self._list(target)
        elif action == "delete":
            return await self._delete(target)
        else:
            return ToolResult(success=False, output=f"Unbekannte Action: {action}")

    async def _read(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output=f"Datei nicht gefunden: {path.name}")
        try:
            content = path.read_text(encoding="utf-8")
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _write(self, path: Path, content: str) -> ToolResult:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Geschrieben: {path.name}")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _list(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output=f"Verzeichnis nicht gefunden: {path.name}")
        try:
            entries = sorted(p.name for p in path.iterdir())
            return ToolResult(success=True, output="\n".join(entries))
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    async def _delete(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output=f"Datei nicht gefunden: {path.name}")
        try:
            path.unlink()
            return ToolResult(success=True, output=f"Gelöscht: {path.name}")
        except Exception as e:
            return ToolResult(success=False, output=str(e))

    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "list", "delete"],
                    "description": "Die auszuführende Aktion",
                },
                "path": {
                    "type": "string",
                    "description": "Relativer Pfad im Workspace",
                },
                "content": {
                    "type": "string",
                    "description": "Inhalt zum Schreiben (nur bei action=write)",
                },
            },
            "required": ["action", "path"],
        }
```

- [ ] **Step 5: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_file_manager.py -v
```

Expected: Alle 7 Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/tools/base.py backend/tools/file_manager.py tests/test_file_manager.py
git commit -m "feat: tool base class with registry, file_manager tool with path safety"
```

---

### Task 6: Agent State Machine

**Files:**
- Create: `backend/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.agent import Agent
from backend.models import AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position


def make_agent_data(**overrides) -> AgentData:
    defaults = dict(
        id="coder_1", name="Alex", role=AgentRole.CODER_1,
        state=AgentState.IDLE_SIT, position=Position(x=5, y=5),
        traits=AgentTraits(social=0.7, focus=0.8),
        mood=AgentMood(energy=0.9),
    )
    defaults.update(overrides)
    return AgentData(**defaults)


@pytest.mark.asyncio
async def test_agent_starts_idle():
    data = make_agent_data()
    agent = Agent(data=data, llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    assert agent.is_idle


@pytest.mark.asyncio
async def test_assign_task_switches_to_work():
    data = make_agent_data()
    db = AsyncMock()
    agent = Agent(data=data, llm=AsyncMock(), db=db, tools=MagicMock())
    await agent.assign_task(task_id=1, title="Build API", description="REST endpoints")
    assert agent.data.state == AgentState.WORK_SIT
    assert agent.data.current_task_id == 1


@pytest.mark.asyncio
async def test_complete_task_returns_to_idle():
    data = make_agent_data(state=AgentState.WORK_TYPE, current_task_id=1)
    db = AsyncMock()
    agent = Agent(data=data, llm=AsyncMock(), db=db, tools=MagicMock())
    await agent.complete_task(result="Done")
    assert agent.is_idle
    assert agent.data.current_task_id is None
    db.update_task_status.assert_called_once()


@pytest.mark.asyncio
async def test_personality_description():
    data = make_agent_data(traits=AgentTraits(social=0.9, focus=0.3, curiosity=0.8))
    agent = Agent(data=data, llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    desc = agent.personality_description
    assert "Alex" in desc
    assert isinstance(desc, str)
    assert len(desc) > 10
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_agent.py -v
```

Expected: ImportError.

- [ ] **Step 3: Agent implementieren**

```python
# backend/agent.py
from backend.models import (
    AgentData, AgentState, TaskStatus, AgentTraits,
)
from backend.llm_client import LLMClient
from backend.database import Database
from backend.tools.base import ToolRegistry


IDLE_STATES = {
    AgentState.IDLE_WANDER, AgentState.IDLE_TALK, AgentState.IDLE_COFFEE,
    AgentState.IDLE_PHONE, AgentState.IDLE_SIT,
}

WORK_STATES = {
    AgentState.WORK_SIT, AgentState.WORK_TYPE, AgentState.WORK_TOOL, AgentState.WORK_REVIEW,
}


def _trait_label(value: float) -> str:
    if value >= 0.8:
        return "sehr hoch"
    if value >= 0.6:
        return "hoch"
    if value >= 0.4:
        return "mittel"
    if value >= 0.2:
        return "niedrig"
    return "sehr niedrig"


class Agent:
    def __init__(self, data: AgentData, llm: LLMClient, db: Database, tools: ToolRegistry):
        self.data = data
        self.llm = llm
        self.db = db
        self.tools = tools
        self.session_messages: list[dict] = []

    @property
    def is_idle(self) -> bool:
        return self.data.state in IDLE_STATES

    @property
    def is_working(self) -> bool:
        return self.data.state in WORK_STATES

    @property
    def personality_description(self) -> str:
        t = self.data.traits
        parts = [
            f"{self.data.name} ist {self.data.role.value}.",
            f"Sozial: {_trait_label(t.social)},",
            f"Fokus: {_trait_label(t.focus)},",
            f"Selbstvertrauen: {_trait_label(t.confidence)},",
            f"Geduld: {_trait_label(t.patience)},",
            f"Neugier: {_trait_label(t.curiosity)},",
            f"Führung: {_trait_label(t.leadership)}.",
        ]
        m = self.data.mood
        if m.stress > 0.6:
            parts.append("Ist gerade gestresst.")
        if m.energy < 0.3:
            parts.append("Ist müde.")
        if m.motivation > 0.7:
            parts.append("Ist motiviert.")
        if m.frustration > 0.5:
            parts.append("Ist frustriert.")
        return " ".join(parts)

    async def assign_task(self, task_id: int, title: str, description: str):
        self.data.current_task_id = task_id
        self.data.state = AgentState.WORK_SIT
        self.session_messages = [
            {"role": "user", "content": f"Neuer Task: {title}\n\n{description}"}
        ]
        await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, assigned_to=self.data.id)

    async def complete_task(self, result: str):
        if self.data.current_task_id is not None:
            await self.db.update_task_status(self.data.current_task_id, TaskStatus.DONE)
        self.data.current_task_id = None
        self.data.state = AgentState.IDLE_SIT
        self.session_messages = []

    async def work_step(self) -> dict:
        """Execute one step of work. Returns event dict for WebSocket."""
        self.data.state = AgentState.WORK_TYPE
        system_prompt = (
            f"Du bist {self.data.name}, Rolle: {self.data.role.value}. "
            f"{self.personality_description} "
            f"Du hast Zugriff auf Tools. Nutze sie um den Task zu erledigen."
        )
        tool_schemas = self.tools.schemas_for_ollama()
        response = await self.llm.chat_with_tools(
            system_prompt=system_prompt,
            messages=self.session_messages,
            tools=tool_schemas,
        )

        # Check for tool calls
        tool_calls = response.get("tool_calls", [])
        if tool_calls:
            self.data.state = AgentState.WORK_TOOL
            call = tool_calls[0]
            func = call["function"]
            tool = self.tools.get(func["name"])
            if tool:
                result = await tool.execute(func.get("arguments", {}))
                await self.db.log_tool_use(
                    self.data.id, func["name"],
                    str(func.get("arguments", {})), result.output, result.success,
                )
                self.session_messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
                self.session_messages.append({"role": "tool", "content": result.output})
                return {
                    "type": "tool_use",
                    "agent": self.data.id,
                    "tool": func["name"],
                    "success": result.success,
                    "output_preview": result.output[:100],
                }

        # No tool call — text response means work step complete
        content = response.get("content", "")
        self.session_messages.append({"role": "assistant", "content": content})
        return {
            "type": "work_response",
            "agent": self.data.id,
            "content": content[:200],
        }
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_agent.py -v
```

Expected: Alle 4 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agent.py tests/test_agent.py
git commit -m "feat: agent class with state machine, tool execution, personality"
```

---

### Task 7: Sim Engine (IDLE-Verhalten)

**Files:**
- Create: `backend/sim_engine.py`
- Test: `tests/test_sim_engine.py`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_sim_engine.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.sim_engine import SimEngine
from backend.agent import Agent
from backend.models import (
    AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position,
)


def make_agent(agent_id: str, name: str, role: AgentRole, x: int, y: int, **trait_overrides) -> Agent:
    traits = AgentTraits(**{**{"social": 0.5, "focus": 0.5}, **trait_overrides})
    data = AgentData(
        id=agent_id, name=name, role=role,
        state=AgentState.IDLE_SIT, position=Position(x=x, y=y),
        traits=traits, mood=AgentMood(),
    )
    return Agent(data=data, llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())


@pytest.mark.asyncio
async def test_tick_idle_agent_gets_action():
    agent = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5, social=0.9)
    agent.llm.generate_sim_action = AsyncMock(return_value="wander")
    sim = SimEngine(agents=[agent], llm=agent.llm)
    events = await sim.tick()
    assert len(events) >= 1
    assert events[0]["agent"] == "coder_1"


@pytest.mark.asyncio
async def test_tick_skips_working_agents():
    agent = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5)
    agent.data.state = AgentState.WORK_TYPE
    sim = SimEngine(agents=[agent], llm=AsyncMock())
    events = await sim.tick()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_talk_action_generates_chat_message():
    alex = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5, social=0.9)
    bob = make_agent("coder_2", "Bob", AgentRole.CODER_2, 6, 5)
    alex.llm.generate_sim_action = AsyncMock(return_value="talk")
    alex.llm.generate_chat_message = AsyncMock(return_value="Hey Bob, wie läuft's?")
    bob.llm.generate_sim_action = AsyncMock(return_value="sit")
    sim = SimEngine(agents=[alex, bob], llm=alex.llm)
    events = await sim.tick()
    talk_events = [e for e in events if e.get("type") == "talk"]
    assert len(talk_events) >= 1
    assert "Hey Bob" in talk_events[0]["message"]
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_sim_engine.py -v
```

Expected: ImportError.

- [ ] **Step 3: SimEngine implementieren**

```python
# backend/sim_engine.py
import random
from backend.agent import Agent
from backend.models import AgentState
from backend.llm_client import LLMClient

ACTION_TO_STATE = {
    "wander": AgentState.IDLE_WANDER,
    "talk": AgentState.IDLE_TALK,
    "coffee": AgentState.IDLE_COFFEE,
    "phone": AgentState.IDLE_PHONE,
    "sit": AgentState.IDLE_SIT,
}


class SimEngine:
    def __init__(self, agents: list[Agent], llm: LLMClient):
        self.agents = agents
        self.llm = llm

    def _nearby_agents(self, agent: Agent, radius: int = 5) -> list[Agent]:
        result = []
        for other in self.agents:
            if other.data.id == agent.data.id:
                continue
            dx = abs(other.data.position.x - agent.data.position.x)
            dy = abs(other.data.position.y - agent.data.position.y)
            if dx <= radius and dy <= radius:
                result.append(other)
        return result

    async def tick(self) -> list[dict]:
        events = []
        for agent in self.agents:
            if not agent.is_idle:
                continue
            event = await self._tick_agent(agent)
            if event:
                events.append(event)
        return events

    async def _tick_agent(self, agent: Agent) -> dict | None:
        nearby = self._nearby_agents(agent)
        nearby_names = [a.data.name for a in nearby]

        action_str = await self.llm.generate_sim_action(
            agent_name=agent.data.name,
            personality=agent.personality_description,
            nearby_agents=nearby_names,
        )

        action = action_str.strip().lower().rstrip(".")
        if action not in ACTION_TO_STATE:
            action = "sit"

        new_state = ACTION_TO_STATE[action]
        agent.data.state = new_state

        if action == "talk" and nearby:
            partner = random.choice(nearby)
            message = await self.llm.generate_chat_message(
                agent_name=agent.data.name,
                personality=agent.personality_description,
                partner_name=partner.data.name,
            )
            return {
                "type": "talk",
                "agent": agent.data.id,
                "partner": partner.data.id,
                "message": message,
                "x": agent.data.position.x,
                "y": agent.data.position.y,
            }

        if action == "wander":
            dx = random.randint(-3, 3)
            dy = random.randint(-3, 3)
            agent.data.position.x = max(0, min(59, agent.data.position.x + dx))
            agent.data.position.y = max(0, min(47, agent.data.position.y + dy))
            return {
                "type": "move",
                "agent": agent.data.id,
                "x": agent.data.position.x,
                "y": agent.data.position.y,
            }

        if action == "coffee":
            return {
                "type": "coffee",
                "agent": agent.data.id,
            }

        return {
            "type": "idle",
            "agent": agent.data.id,
            "action": action,
        }
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_sim_engine.py -v
```

Expected: Alle 3 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/sim_engine.py tests/test_sim_engine.py
git commit -m "feat: sim engine with idle behaviors - wander, talk, coffee, phone, sit"
```

---

### Task 8: WebSocket Manager

**Files:**
- Create: `backend/ws_manager.py`
- Test: `tests/test_ws_manager.py`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ws_manager.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from backend.ws_manager import WSManager


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    mgr = WSManager()
    ws = AsyncMock()
    await mgr.connect(ws)
    assert len(mgr.connections) == 1
    mgr.disconnect(ws)
    assert len(mgr.connections) == 0


@pytest.mark.asyncio
async def test_broadcast_sends_to_all():
    mgr = WSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    await mgr.connect(ws1)
    await mgr.connect(ws2)
    await mgr.broadcast({"type": "move", "agent": "coder_1", "x": 10, "y": 20})
    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()
    sent = json.loads(ws1.send_text.call_args[0][0])
    assert sent["type"] == "move"


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections():
    mgr = WSManager()
    ws_alive = AsyncMock()
    ws_dead = AsyncMock()
    ws_dead.send_text.side_effect = Exception("connection closed")
    await mgr.connect(ws_alive)
    await mgr.connect(ws_dead)
    await mgr.broadcast({"type": "test"})
    assert ws_dead not in mgr.connections
    assert ws_alive in mgr.connections
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_ws_manager.py -v
```

Expected: ImportError.

- [ ] **Step 3: WSManager implementieren**

```python
# backend/ws_manager.py
import json
from fastapi import WebSocket


class WSManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        if hasattr(ws, "accept"):
            try:
                await ws.accept()
            except Exception:
                pass
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: dict):
        message = json.dumps(data, ensure_ascii=False)
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)

    async def send_full_state(self, ws: WebSocket, agents: list[dict]):
        await ws.send_text(json.dumps({
            "type": "full_state",
            "agents": agents,
        }, ensure_ascii=False))
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_ws_manager.py -v
```

Expected: Alle 3 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ws_manager.py tests/test_ws_manager.py
git commit -m "feat: WebSocket manager with broadcast and dead connection cleanup"
```

---

### Task 9: Agent Pool & Orchestrator

**Files:**
- Create: `backend/agent_pool.py`
- Create: `backend/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.orchestrator import Orchestrator
from backend.agent_pool import AgentPool
from backend.models import AgentRole, TaskData


@pytest.mark.asyncio
async def test_pool_creates_seven_agents():
    pool = AgentPool(llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    assert len(pool.agents) == 7
    roles = {a.data.role for a in pool.agents}
    assert AgentRole.PM in roles
    assert AgentRole.TEAM_LEAD in roles
    assert AgentRole.CODER_1 in roles
    assert AgentRole.CODER_2 in roles
    assert AgentRole.RESEARCHER in roles
    assert AgentRole.WRITER in roles
    assert AgentRole.OPS in roles


@pytest.mark.asyncio
async def test_pool_get_idle_agents():
    pool = AgentPool(llm=AsyncMock(), db=AsyncMock(), tools=MagicMock())
    idle = pool.get_idle_agents()
    assert len(idle) == 7  # all start idle


@pytest.mark.asyncio
async def test_orchestrator_submit_task():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    pool = AgentPool(llm=AsyncMock(), db=db, tools=MagicMock())
    orch = Orchestrator(pool=pool, db=db, llm=AsyncMock())
    task_id = await orch.submit_task("Build API", "Create REST endpoints")
    assert task_id == 1
    db.create_task.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_assign_picks_matching_role():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value="coder_1")
    pool = AgentPool(llm=llm, db=db, tools=MagicMock())
    orch = Orchestrator(pool=pool, db=db, llm=llm)
    task_id = await orch.submit_task("Build API", "Create REST endpoints")
    assigned = await orch.assign_next_task()
    assert assigned is not None
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_orchestrator.py -v
```

Expected: ImportError.

- [ ] **Step 3: AgentPool implementieren**

```python
# backend/agent_pool.py
from backend.agent import Agent
from backend.models import (
    AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position,
)
from backend.llm_client import LLMClient
from backend.database import Database
from backend.tools.base import ToolRegistry

TEAM = [
    {"id": "pm", "name": "Star", "role": AgentRole.PM,
     "traits": AgentTraits(social=0.8, focus=0.6, confidence=0.7, patience=0.7, curiosity=0.6, leadership=0.9),
     "position": Position(x=30, y=10)},
    {"id": "team_lead", "name": "Nina", "role": AgentRole.TEAM_LEAD,
     "traits": AgentTraits(social=0.7, focus=0.7, confidence=0.8, patience=0.6, curiosity=0.5, leadership=0.8),
     "position": Position(x=28, y=15)},
    {"id": "coder_1", "name": "Alex", "role": AgentRole.CODER_1,
     "traits": AgentTraits(social=0.5, focus=0.9, confidence=0.6, patience=0.5, curiosity=0.7, leadership=0.3),
     "position": Position(x=10, y=20)},
    {"id": "coder_2", "name": "Bob", "role": AgentRole.CODER_2,
     "traits": AgentTraits(social=0.6, focus=0.8, confidence=0.5, patience=0.6, curiosity=0.8, leadership=0.2),
     "position": Position(x=15, y=20)},
    {"id": "researcher", "name": "Amelia", "role": AgentRole.RESEARCHER,
     "traits": AgentTraits(social=0.6, focus=0.7, confidence=0.6, patience=0.8, curiosity=0.9, leadership=0.2),
     "position": Position(x=20, y=25)},
    {"id": "writer", "name": "Clara", "role": AgentRole.WRITER,
     "traits": AgentTraits(social=0.7, focus=0.6, confidence=0.7, patience=0.7, curiosity=0.6, leadership=0.3),
     "position": Position(x=25, y=25)},
    {"id": "ops", "name": "Max", "role": AgentRole.OPS,
     "traits": AgentTraits(social=0.4, focus=0.8, confidence=0.7, patience=0.5, curiosity=0.5, leadership=0.4),
     "position": Position(x=40, y=15)},
]


class AgentPool:
    def __init__(self, llm: LLMClient, db: Database, tools: ToolRegistry):
        self.agents: list[Agent] = []
        for spec in TEAM:
            data = AgentData(
                id=spec["id"], name=spec["name"], role=spec["role"],
                state=AgentState.IDLE_SIT, position=spec["position"],
                traits=spec["traits"], mood=AgentMood(),
            )
            self.agents.append(Agent(data=data, llm=llm, db=db, tools=tools))

    def get_agent(self, agent_id: str) -> Agent | None:
        for a in self.agents:
            if a.data.id == agent_id:
                return a
        return None

    def get_idle_agents(self) -> list[Agent]:
        return [a for a in self.agents if a.is_idle]

    def get_agents_state(self) -> list[dict]:
        return [
            {
                "id": a.data.id,
                "name": a.data.name,
                "role": a.data.role.value,
                "state": a.data.state.value,
                "x": a.data.position.x,
                "y": a.data.position.y,
                "mood": a.data.mood.model_dump(),
                "current_task_id": a.data.current_task_id,
            }
            for a in self.agents
        ]

    async def save_all(self):
        for agent in self.agents:
            await agent.db.upsert_agent(agent.data)
```

- [ ] **Step 4: Orchestrator implementieren**

```python
# backend/orchestrator.py
from backend.agent_pool import AgentPool
from backend.database import Database
from backend.llm_client import LLMClient
from backend.models import TaskData, TaskStatus, AgentRole

ROLE_KEYWORDS = {
    AgentRole.CODER_1: ["code", "implementier", "bug", "fix", "programm", "api", "endpoint"],
    AgentRole.CODER_2: ["test", "code", "implementier", "backend", "frontend"],
    AgentRole.RESEARCHER: ["recherch", "such", "find", "analys", "vergleich"],
    AgentRole.WRITER: ["schreib", "doku", "text", "report", "artikel", "zusammenfass"],
    AgentRole.OPS: ["deploy", "server", "docker", "pipeline", "install", "config", "shell"],
}


class Orchestrator:
    def __init__(self, pool: AgentPool, db: Database, llm: LLMClient):
        self.pool = pool
        self.db = db
        self.llm = llm
        self._pending_task_ids: list[int] = []

    async def submit_task(self, title: str, description: str, project: str | None = None) -> int:
        task = TaskData(title=title, description=description, project=project)
        task_id = await self.db.create_task(task)
        self._pending_task_ids.append(task_id)
        return task_id

    def _best_role_for_task(self, title: str, description: str) -> AgentRole:
        text = (title + " " + description).lower()
        scores: dict[AgentRole, int] = {}
        for role, keywords in ROLE_KEYWORDS.items():
            scores[role] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return AgentRole.CODER_1
        return best

    async def assign_next_task(self) -> dict | None:
        if not self._pending_task_ids:
            return None

        task_id = self._pending_task_ids[0]
        task = await self.db.get_task(task_id)
        if not task:
            self._pending_task_ids.pop(0)
            return None

        best_role = self._best_role_for_task(task.title, task.description)
        idle = self.pool.get_idle_agents()
        agent = None
        for a in idle:
            if a.data.role == best_role:
                agent = a
                break
        if not agent and idle:
            agent = idle[0]
        if not agent:
            return None

        self._pending_task_ids.pop(0)
        await agent.assign_task(task_id=task.id, title=task.title, description=task.description)
        return {
            "type": "task_assigned",
            "agent": agent.data.id,
            "task_id": task.id,
            "task_title": task.title,
        }
```

- [ ] **Step 5: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_orchestrator.py -v
```

Expected: Alle 4 Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/agent_pool.py backend/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: agent pool with 7-agent team, orchestrator with task routing"
```

---

### Task 10: FastAPI Main Server

**Files:**
- Create: `backend/main.py`

- [ ] **Step 1: Main Server implementieren**

```python
# backend/main.py
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.config import settings
from backend.database import Database
from backend.llm_client import LLMClient
from backend.agent_pool import AgentPool
from backend.orchestrator import Orchestrator
from backend.sim_engine import SimEngine
from backend.ws_manager import WSManager
from backend.tools.base import ToolRegistry
from backend.tools.file_manager import FileManagerTool

db: Database = None
pool: AgentPool = None
orchestrator: Orchestrator = None
sim: SimEngine = None
ws_mgr = WSManager()
sim_task: asyncio.Task = None


async def sim_loop():
    """Main simulation loop — ticks every 5 seconds."""
    while True:
        try:
            events = await sim.tick()
            for event in events:
                await ws_mgr.broadcast(event)
            # Broadcast full state every tick for newly connected clients
            await ws_mgr.broadcast({
                "type": "state_update",
                "agents": pool.get_agents_state(),
            })
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Sim loop error: {e}")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, pool, orchestrator, sim, sim_task

    # Init database
    db = Database(settings.db_path)
    await db.init()

    # Init LLM client
    llm = LLMClient()

    # Init tools
    tools = ToolRegistry()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    tools.register(FileManagerTool(workspace_path=settings.workspace_path))

    # Init agent pool
    pool = AgentPool(llm=llm, db=db, tools=tools)
    await pool.save_all()

    # Init orchestrator
    orchestrator = Orchestrator(pool=pool, db=db, llm=llm)

    # Init sim engine
    sim = SimEngine(agents=pool.agents, llm=llm)

    # Start sim loop
    sim_task = asyncio.create_task(sim_loop())

    print(f"Falkenstein running on port {settings.frontend_port}")
    yield

    # Shutdown
    sim_task.cancel()
    try:
        await sim_task
    except asyncio.CancelledError:
        pass
    await pool.save_all()
    await db.close()


app = FastAPI(title="Falkenstein", lifespan=lifespan)

# Serve frontend static files
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def index():
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"status": "Falkenstein backend running", "agents": pool.get_agents_state()}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    # Send current state on connect
    await ws_mgr.send_full_state(ws, pool.get_agents_state())
    try:
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data)
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)


async def handle_ws_message(data: dict):
    msg_type = data.get("type", "")

    if msg_type == "submit_task":
        task_id = await orchestrator.submit_task(
            title=data["title"],
            description=data.get("description", ""),
            project=data.get("project"),
        )
        event = await orchestrator.assign_next_task()
        await ws_mgr.broadcast({"type": "task_submitted", "task_id": task_id})
        if event:
            await ws_mgr.broadcast(event)

    elif msg_type == "get_state":
        await ws_mgr.broadcast({
            "type": "state_update",
            "agents": pool.get_agents_state(),
        })


@app.post("/api/task")
async def create_task(title: str, description: str = "", project: str | None = None):
    task_id = await orchestrator.submit_task(title, description, project)
    event = await orchestrator.assign_next_task()
    if event:
        await ws_mgr.broadcast(event)
    return {"task_id": task_id}


@app.get("/api/agents")
async def get_agents():
    return pool.get_agents_state()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
```

- [ ] **Step 2: Manuell testen**

```bash
cd /Users/janikhartmann/Falkenstein
source venv/bin/activate
python -m backend.main
```

Expected: Server startet auf Port 8080. `http://localhost:8080` zeigt Agent-State JSON. WebSocket unter `ws://localhost:8080/ws` erreichbar.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: FastAPI server with WebSocket, sim loop, REST API for tasks"
```

---

### Task 11: Frontend — Assets vorbereiten & Phaser Grundgerüst

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/websocket.js`
- Create: `frontend/agents.js`
- Create: `frontend/game.js`
- Copy: Assets aus `Büro/` nach `frontend/assets/`

- [ ] **Step 1: Assets kopieren**

```bash
cd /Users/janikhartmann/Falkenstein

# Tiled Map
cp "Büro/Neues_Office.tmj" frontend/assets/office.tmj

# Tilesets (48x48 Version)
cp "Büro/Modern_Office_Revamped_v1/1_Room_Builder_Office/Room_Builder_Office_48x48.png" frontend/assets/Room_Builder_Office_48x48.png
cp "Büro/Modern_Office_Revamped_v1/2_Modern_Office_Black_Shadow/Modern_Office_Black_Shadow_48x48.png" frontend/assets/Modern_Office_Black_Shadow_48x48.png
cp "Büro/Modern_Office_Revamped_v1/2_Modern_Office_Black_Shadow/Modern_Office_Black_Shadow.png" frontend/assets/Modern_Office_Black_Shadow.png

# Character Sprites
mkdir -p frontend/assets/characters
cp "Büro/Modern tiles_Free/Characters_free/Adam_run_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Adam_idle_anim_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Adam_sit_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Adam_phone_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Alex_run_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Alex_idle_anim_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Alex_sit_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Alex_phone_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Amelia_run_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Amelia_idle_anim_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Amelia_sit_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Amelia_phone_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Bob_run_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Bob_idle_anim_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Bob_sit_16x16.png" frontend/assets/characters/
cp "Büro/Modern tiles_Free/Characters_free/Bob_phone_16x16.png" frontend/assets/characters/
```

- [ ] **Step 2: WebSocket Client erstellen**

```javascript
// frontend/websocket.js
class FalkensteinWS {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.handlers = {};
        this.reconnectDelay = 2000;
    }

    connect() {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            console.log('WS connected');
            this.emit('connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.emit(data.type, data);
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };

        this.ws.onclose = () => {
            console.log('WS closed, reconnecting...');
            setTimeout(() => this.connect(), this.reconnectDelay);
        };
    }

    on(type, handler) {
        if (!this.handlers[type]) this.handlers[type] = [];
        this.handlers[type].push(handler);
    }

    emit(type, data) {
        const handlers = this.handlers[type] || [];
        handlers.forEach(h => h(data));
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    submitTask(title, description, project) {
        this.send({ type: 'submit_task', title, description, project });
    }
}
```

- [ ] **Step 3: Agent Sprite Manager erstellen**

```javascript
// frontend/agents.js
// Manages agent sprites, animations, speech bubbles, and name labels

const SPRITE_MAP = {
    pm:         'Adam',
    team_lead:  'Alex',
    coder_1:    'Amelia',
    coder_2:    'Bob',
    researcher: 'Adam',   // reuse with tint
    writer:     'Amelia',  // reuse with tint
    ops:        'Bob',     // reuse with tint
};

const TINT_MAP = {
    researcher: 0x88ccff,
    writer:     0xffcc88,
    ops:        0xcc88ff,
};

const TILE_SIZE = 48;
const SPRITE_SCALE = 2.5;

class AgentSprites {
    constructor(scene) {
        this.scene = scene;
        this.sprites = {};   // agentId -> sprite
        this.nameLabels = {};
        this.bubbles = {};
    }

    preload(scene) {
        const chars = ['Adam', 'Alex', 'Amelia', 'Bob'];
        const anims = ['run', 'idle_anim', 'sit', 'phone'];
        chars.forEach(name => {
            anims.forEach(anim => {
                const key = `${name}_${anim}`;
                // 16x16 sprites, 4 directions, variable frame counts
                const frameH = 16;
                const frameW = 16;
                scene.load.spritesheet(key, `static/assets/characters/${name}_${anim}_16x16.png`, {
                    frameWidth: frameW,
                    frameHeight: frameH,
                });
            });
        });
    }

    createAgents(agentList) {
        agentList.forEach(agent => {
            this.createAgent(agent);
        });
    }

    createAgent(agent) {
        const charName = SPRITE_MAP[agent.id] || 'Adam';
        const key = `${charName}_idle_anim`;
        const x = agent.x * TILE_SIZE + TILE_SIZE / 2;
        const y = agent.y * TILE_SIZE + TILE_SIZE / 2;

        const sprite = this.scene.add.sprite(x, y, key);
        sprite.setScale(SPRITE_SCALE);
        sprite.setDepth(100);

        if (TINT_MAP[agent.id]) {
            sprite.setTint(TINT_MAP[agent.id]);
        }

        // Name label
        const label = this.scene.add.text(x, y - 28, agent.name, {
            fontSize: '11px',
            fontFamily: 'monospace',
            color: '#ffffff',
            backgroundColor: '#00000088',
            padding: { x: 3, y: 1 },
        });
        label.setOrigin(0.5);
        label.setDepth(200);

        this.sprites[agent.id] = sprite;
        this.nameLabels[agent.id] = label;
    }

    updateAgent(agent) {
        const sprite = this.sprites[agent.id];
        if (!sprite) return;

        const targetX = agent.x * TILE_SIZE + TILE_SIZE / 2;
        const targetY = agent.y * TILE_SIZE + TILE_SIZE / 2;

        // Smooth movement via tween
        this.scene.tweens.add({
            targets: sprite,
            x: targetX,
            y: targetY,
            duration: 400,
            ease: 'Linear',
        });

        // Move label too
        const label = this.nameLabels[agent.id];
        if (label) {
            this.scene.tweens.add({
                targets: label,
                x: targetX,
                y: targetY - 28,
                duration: 400,
                ease: 'Linear',
            });
        }
    }

    showBubble(agentId, text, duration = 4000) {
        const sprite = this.sprites[agentId];
        if (!sprite) return;

        // Remove existing bubble
        if (this.bubbles[agentId]) {
            this.bubbles[agentId].destroy();
        }

        const bubble = this.scene.add.text(sprite.x, sprite.y - 50, text, {
            fontSize: '10px',
            fontFamily: 'monospace',
            color: '#ffffff',
            backgroundColor: '#333333cc',
            padding: { x: 6, y: 4 },
            wordWrap: { width: 160 },
        });
        bubble.setOrigin(0.5);
        bubble.setDepth(300);
        this.bubbles[agentId] = bubble;

        this.scene.time.delayedCall(duration, () => {
            if (this.bubbles[agentId] === bubble) {
                bubble.destroy();
                delete this.bubbles[agentId];
            }
        });
    }

    updateAllAgents(agents) {
        agents.forEach(agent => {
            if (this.sprites[agent.id]) {
                this.updateAgent(agent);
            } else {
                this.createAgent(agent);
            }
        });
    }
}
```

- [ ] **Step 4: Phaser Game erstellen**

```javascript
// frontend/game.js
let ws, agentSprites;

const config = {
    type: Phaser.AUTO,
    width: 1280,
    height: 720,
    parent: 'game-container',
    pixelArt: true,
    scene: {
        preload: preload,
        create: create,
        update: update,
    },
    scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
    },
};

function preload() {
    // Load tilemap
    this.load.tilemapTiledJSON('office', 'static/assets/office.tmj');
    this.load.image('Room_Builder_Office_48x48', 'static/assets/Room_Builder_Office_48x48.png');
    this.load.image('Modern_Office_Black_Shadow', 'static/assets/Modern_Office_Black_Shadow.png');
    this.load.image('Modern_Office_Black_Shadow_48x48', 'static/assets/Modern_Office_Black_Shadow_48x48.png');

    // Load character sprites
    agentSprites = new AgentSprites(this);
    agentSprites.preload(this);
}

function create() {
    // Create tilemap
    const map = this.make.tilemap({ key: 'office' });
    const tilesetRB = map.addTilesetImage('Room_Builder_Office_48x48', 'Room_Builder_Office_48x48');
    const tilesetMS = map.addTilesetImage('Modern_Office_Black_Shadow', 'Modern_Office_Black_Shadow');
    const tilesetMS48 = map.addTilesetImage('Modern_Office_Black_Shadow_48x48', 'Modern_Office_Black_Shadow_48x48');
    const allTilesets = [tilesetRB, tilesetMS, tilesetMS48].filter(Boolean);

    // Create layers from Tiled
    const layerNames = ['Walkable', 'Blocked', 'Furniture', 'WalkableFurniture', 'Stühle'];
    layerNames.forEach(name => {
        const layer = map.createLayer(name, allTilesets);
        if (layer) {
            layer.setDepth(name === 'Stühle' ? 50 : 0);
        }
    });

    // Camera setup
    this.cameras.main.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    this.cameras.main.setZoom(0.5);

    // Mouse drag to pan camera
    this.input.on('pointermove', (pointer) => {
        if (pointer.isDown) {
            this.cameras.main.scrollX -= (pointer.x - pointer.prevPosition.x) / this.cameras.main.zoom;
            this.cameras.main.scrollY -= (pointer.y - pointer.prevPosition.y) / this.cameras.main.zoom;
        }
    });

    // Mouse wheel to zoom
    this.input.on('wheel', (pointer, gameObjects, deltaX, deltaY) => {
        const zoom = this.cameras.main.zoom;
        this.cameras.main.setZoom(Phaser.Math.Clamp(zoom - deltaY * 0.001, 0.25, 2));
    });

    // Connect WebSocket
    const wsUrl = `ws://${window.location.hostname}:${window.location.port}/ws`;
    ws = new FalkensteinWS(wsUrl);

    ws.on('full_state', (data) => {
        agentSprites.createAgents(data.agents);
    });

    ws.on('state_update', (data) => {
        agentSprites.updateAllAgents(data.agents);
    });

    ws.on('move', (data) => {
        agentSprites.updateAgent(data);
    });

    ws.on('talk', (data) => {
        agentSprites.showBubble(data.agent, data.message);
    });

    ws.on('coffee', (data) => {
        agentSprites.showBubble(data.agent, '☕ Kaffeepause...');
    });

    ws.on('task_assigned', (data) => {
        agentSprites.showBubble(data.agent, `📋 ${data.task_title}`);
    });

    ws.on('tool_use', (data) => {
        const icons = {
            file_manager: '💾',
            web_surfer: '🔍',
            shell_runner: '💻',
            code_executor: '⚡',
            obsidian_manager: '📝',
        };
        const icon = icons[data.tool] || '🔧';
        agentSprites.showBubble(data.agent, `${icon} ${data.tool}`);
    });

    ws.connect();
}

function update() {
    // Future: smooth animations, pathfinding updates
}

// Init
const game = new Phaser.Game(config);
```

- [ ] **Step 5: index.html erstellen**

```html
<!-- frontend/index.html -->
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Falkenstein — KI Büro</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #1a1a2e;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
            font-family: 'Courier New', monospace;
            color: #eee;
        }
        h1 {
            margin: 16px 0 8px;
            font-size: 18px;
            color: #ffd700;
            letter-spacing: 2px;
        }
        #game-container {
            border: 2px solid #333;
            border-radius: 4px;
        }
        #task-panel {
            margin-top: 12px;
            display: flex;
            gap: 8px;
            align-items: center;
        }
        #task-panel input {
            background: #222;
            border: 1px solid #444;
            color: #eee;
            padding: 6px 12px;
            font-family: inherit;
            font-size: 14px;
            width: 400px;
            border-radius: 3px;
        }
        #task-panel button {
            background: #ffd700;
            color: #1a1a2e;
            border: none;
            padding: 6px 16px;
            font-family: inherit;
            font-size: 14px;
            cursor: pointer;
            border-radius: 3px;
            font-weight: bold;
        }
        #task-panel button:hover { background: #ffed4a; }
    </style>
</head>
<body>
    <h1>FALKENSTEIN</h1>
    <div id="game-container"></div>
    <div id="task-panel">
        <input id="task-input" type="text" placeholder="Neuen Task eingeben..." />
        <button onclick="submitTask()">Absenden</button>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/phaser@3.80.1/dist/phaser.min.js"></script>
    <script src="static/websocket.js"></script>
    <script src="static/agents.js"></script>
    <script src="static/game.js"></script>
    <script>
        function submitTask() {
            const input = document.getElementById('task-input');
            const title = input.value.trim();
            if (title && ws) {
                ws.submitTask(title, title);
                input.value = '';
            }
        }
        document.getElementById('task-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitTask();
        });
    </script>
</body>
</html>
```

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat: Phaser frontend with tilemap, agent sprites, WebSocket, task input"
```

---

### Task 12: Alle Tests ausführen & CLAUDE.md aktualisieren

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Alle Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein
source venv/bin/activate
python -m pytest tests/ -v
```

Expected: Alle Tests PASS (database: 6, llm_client: 3, file_manager: 7, agent: 4, sim_engine: 3, ws_manager: 3, orchestrator: 4 = 30 Tests).

- [ ] **Step 2: CLAUDE.md mit Build-Commands aktualisieren**

Füge folgende Abschnitte zur bestehenden CLAUDE.md hinzu:

```markdown
## Entwicklung

### Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

### Server starten
python -m backend.main

### Tests
python -m pytest tests/ -v               # alle Tests
python -m pytest tests/test_agent.py -v   # einzelner Test

### Voraussetzungen
- Python 3.11+
- Ollama lokal installiert und laufend (http://localhost:11434)
- Ein Modell geladen: ollama pull llama3
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with development commands"
```

---

### Task 13: End-to-End Smoke Test

- [ ] **Step 1: Ollama prüfen**

```bash
ollama list
```

Expected: Mindestens ein Modell installiert. Falls nicht: `ollama pull llama3`

- [ ] **Step 2: Server starten und prüfen**

```bash
cd /Users/janikhartmann/Falkenstein
source venv/bin/activate
python -m backend.main &
sleep 3
curl http://localhost:8080/api/agents | python -m json.tool
```

Expected: JSON mit 7 Agenten, jeder hat id, name, role, state, x, y.

- [ ] **Step 3: Task via REST API einreichen**

```bash
curl -X POST "http://localhost:8080/api/task?title=Hello%20World&description=Schreibe%20eine%20hello.py%20Datei"
```

Expected: `{"task_id": 1}`. Im Terminal sieht man den Agent, der den Task bekommt.

- [ ] **Step 4: Frontend im Browser öffnen**

Öffne `http://localhost:8080` — die Tiled-Map sollte erscheinen mit 7 Agent-Sprites die sich alle 5 Sekunden bewegen/reden.

- [ ] **Step 5: Server stoppen**

```bash
kill %1
```
