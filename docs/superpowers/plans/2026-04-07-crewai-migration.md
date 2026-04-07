# CrewAI-Migration & Native Ollama Integration — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Falkenstein's custom Agent-System (MainAgent/SubAgent/DynamicAgent) durch CrewAI ersetzen mit nativem Ollama Tool-Calling, 9 spezialisierten Crews, EventBus fuer Live-Dashboard, und intelligenter Obsidian-Integration.

**Architecture:** CrewAI als Library unter FastAPI. Ein CrewAI Flow ersetzt MainAgent — Rule-Engine + LLM-Classify routet zu spezialisierten Crews. NativeOllamaClient fuer schnelle Einzelcalls ohne Crew-Overhead. FalkensteinEventBus verbindet CrewAI-Callbacks mit WebSocket, Telegram und DB.

**Tech Stack:** Python 3.11+, FastAPI, CrewAI, Ollama (Gemma 4 e4b/26b), aiosqlite, httpx, Phaser.js

**Spec:** `docs/superpowers/specs/2026-04-07-crewai-migration-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `backend/native_ollama.py` | Async Ollama client fuer classify + quick_reply (structured output, kein Crew-Overhead) |
| `backend/event_bus.py` | Zentraler Event-Hub: CrewAI Callbacks → WebSocket + Telegram + DB |
| `backend/vault_index.py` | Scannt Obsidian-Vault, findet passende Ordner/Notizen, verhindert wilde Ordner-Erstellung |
| `backend/flow/` | Package |
| `backend/flow/__init__.py` | Package init |
| `backend/flow/falkenstein_flow.py` | CrewAI Flow — Entry Point, Router, Crew-Dispatch |
| `backend/flow/rule_engine.py` | Regex/Keyword-Router: Quick-Reply vs. Crew-Dispatch |
| `backend/crews/` | Package |
| `backend/crews/__init__.py` | Package init |
| `backend/crews/base_crew.py` | Gemeinsame Crew-Config: Callbacks, EventBus-Hook, Tool-Setup |
| `backend/crews/coder_crew.py` | CoderCrew |
| `backend/crews/researcher_crew.py` | ResearcherCrew |
| `backend/crews/writer_crew.py` | WriterCrew |
| `backend/crews/ops_crew.py` | OpsCrew |
| `backend/crews/web_design_crew.py` | WebDesignCrew (2 Agents) |
| `backend/crews/swift_crew.py` | SwiftCrew |
| `backend/crews/ki_expert_crew.py` | KI-ExpertCrew |
| `backend/crews/analyst_crew.py` | AnalystCrew |
| `backend/crews/premium_crew.py` | PremiumCrew (Claude/Gemini API) |
| `backend/tools/crewai_wrappers.py` | BaseTool-Wrapper fuer eigene Tools |
| `backend/config/agents.yaml` | CrewAI Agent-Definitionen |
| `backend/config/tasks.yaml` | CrewAI Task-Templates |
| `tests/test_native_ollama.py` | Tests fuer NativeOllamaClient |
| `tests/test_rule_engine.py` | Tests fuer Rule-Engine |
| `tests/test_event_bus.py` | Tests fuer EventBus |
| `tests/test_vault_index.py` | Tests fuer VaultIndex |
| `tests/test_crewai_wrappers.py` | Tests fuer Tool-Wrapper |
| `tests/test_flow.py` | Tests fuer FalkensteinFlow |
| `tests/test_crews.py` | Tests fuer Crew-Konfiguration |

### Modified Files
| File | Changes |
|---|---|
| `backend/config.py` | OllamaSettings erweitern, CrewAI-Config hinzufuegen |
| `backend/database.py` | Neues Schema: `crews`, `knowledge_log`, erweiterte `tool_log` |
| `backend/main.py` | Startup umbauen: Flow statt MainAgent, EventBus verdrahten |
| `backend/telegram_bot.py` | Handler ruft Flow statt MainAgent |
| `backend/ws_manager.py` | Neue Event-Types fuer Crew-Tracking |
| `backend/models.py` | Neue Pydantic-Models fuer Crews |
| `backend/tools/obsidian_manager.py` | SmartObsidianTool mit VaultIndex |
| `backend/scheduler.py` / `backend/smart_scheduler.py` | Crews statt SubAgents spawnen |
| `requirements.txt` | crewai + crewai-tools hinzufuegen |
| `frontend/office/agents.js` | Neue WS-Events + Crew-Animationen |
| `frontend/office/ws.js` | Neue Event-Handler |

### Deleted Files (Task 13)
`main_agent.py`, `sub_agent.py`, `dynamic_agent.py`, `llm_client.py`, `llm_router.py`, `intent_engine.py`, `intent_prefilter.py`, `cli_llm_client.py`, `agent_identity.py`, `tools/web_surfer.py`, `tools/file_manager.py`, `tools/vision.py`, `tools/cli_bridge.py`, `prompts/classify.py`, `prompts/subagent.py`, `output_router.py`, `review_gate.py`

---

## Task 1: Dependencies & Config

**Files:**
- Modify: `requirements.txt`
- Modify: `backend/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Update requirements.txt**

```
# Add to requirements.txt (after existing entries):
crewai>=0.108.0
crewai-tools>=0.36.0
```

Remove:
```
ollama>=0.6.0
```

- [ ] **Step 2: Install dependencies**

Run: `source venv/bin/activate && pip install -r requirements.txt`
Expected: Successfully installed crewai, crewai-tools

- [ ] **Step 3: Write failing test for OllamaSettings**

Create `tests/test_config.py`:

```python
import pytest
from backend.config import Settings


def test_settings_has_ollama_keep_alive():
    s = Settings(
        ollama_host="http://localhost:11434",
        ollama_model="gemma4:26b",
    )
    assert s.ollama_keep_alive == "30m"


def test_settings_has_stream_tools_default():
    s = Settings(
        ollama_host="http://localhost:11434",
        ollama_model="gemma4:26b",
    )
    assert s.ollama_stream_tools is False
    assert s.ollama_stream_text is True


def test_settings_crewai_serper_key():
    s = Settings(
        ollama_host="http://localhost:11434",
        ollama_model="gemma4:26b",
        serper_api_key="test-key",
    )
    assert s.serper_api_key == "test-key"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ollama_keep_alive` not found

- [ ] **Step 5: Extend Settings in config.py**

Add to `backend/config.py` inside the `Settings` class:

```python
    # Ollama Performance
    ollama_keep_alive: str = "30m"
    ollama_stream_tools: bool = False
    ollama_stream_text: bool = True

    # CrewAI / External APIs
    serper_api_key: str = ""
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add requirements.txt backend/config.py tests/test_config.py
git commit -m "feat: add CrewAI dependencies and extend OllamaSettings"
```

---

## Task 2: NativeOllamaClient

**Files:**
- Create: `backend/native_ollama.py`
- Test: `tests/test_native_ollama.py`

- [ ] **Step 1: Write failing test for classify**

Create `tests/test_native_ollama.py`:

```python
import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch

from backend.native_ollama import NativeOllamaClient


@pytest.fixture
def client():
    return NativeOllamaClient(
        host="http://localhost:11434",
        model_light="gemma4:e4b",
        model_heavy="gemma4:26b",
    )


@pytest.mark.asyncio
async def test_classify_returns_structured_output(client):
    mock_response = httpx.Response(
        200,
        json={
            "message": {
                "content": json.dumps({
                    "crew_type": "researcher",
                    "task_description": "Search for CrewAI docs",
                    "priority": "normal",
                })
            }
        },
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await client.classify("Recherchiere CrewAI Dokumentation")

    assert result["crew_type"] == "researcher"
    assert result["priority"] == "normal"
    assert "task_description" in result


@pytest.mark.asyncio
async def test_classify_uses_light_model(client):
    mock_response = httpx.Response(
        200,
        json={"message": {"content": json.dumps({"crew_type": "coder", "task_description": "x", "priority": "normal"})}},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
        await client.classify("Fix the bug")
        call_payload = mock_post.call_args[1]["json"] if "json" in mock_post.call_args[1] else json.loads(mock_post.call_args[0][1])
        assert call_payload["model"] == "gemma4:e4b"


@pytest.mark.asyncio
async def test_quick_reply_returns_text(client):
    mock_response = httpx.Response(
        200,
        json={"message": {"content": "Alles klar!"}},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await client.quick_reply("Danke!")

    assert result == "Alles klar!"


@pytest.mark.asyncio
async def test_chat_with_tools_sends_tools_param(client):
    tool_call_response = httpx.Response(
        200,
        json={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_weather",
                            "arguments": {"city": "Berlin"},
                        }
                    }
                ],
            }
        },
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=tool_call_response) as mock_post:
        result = await client.chat_with_tools(
            messages=[{"role": "user", "content": "Weather in Berlin?"}],
            tools=tools,
            model="heavy",
        )

    assert result["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
    call_payload = mock_post.call_args[1]["json"]
    assert "tools" in call_payload
    assert call_payload["stream"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_native_ollama.py -v`
Expected: FAIL — `backend.native_ollama` not found

- [ ] **Step 3: Implement NativeOllamaClient**

Create `backend/native_ollama.py`:

```python
"""Async Ollama client for fast calls without CrewAI overhead."""

import json
import httpx


CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "crew_type": {
            "type": "string",
            "enum": [
                "coder", "researcher", "writer", "ops",
                "web_design", "swift", "ki_expert", "analyst",
            ],
        },
        "task_description": {"type": "string"},
        "priority": {"type": "string", "enum": ["normal", "premium"]},
    },
    "required": ["crew_type", "task_description", "priority"],
}


class NativeOllamaClient:
    """Direct Ollama /api/chat client — bypasses CrewAI for speed."""

    def __init__(self, host: str, model_light: str, model_heavy: str,
                 keep_alive: str = "30m", timeout: float = 120.0):
        self.host = host.rstrip("/")
        self.model_light = model_light
        self.model_heavy = model_heavy
        self.keep_alive = keep_alive
        self.timeout = timeout

    async def classify(self, message: str) -> dict:
        """Classify a message into a crew_type using structured output."""
        system = (
            "Classify the user message into the best matching crew_type. "
            "Respond ONLY with the required JSON."
        )
        raw = await self._chat(
            model=self.model_light,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            format=CLASSIFY_SCHEMA,
        )
        return json.loads(raw)

    async def quick_reply(self, message: str, context: str = "") -> str:
        """Fast direct reply without spawning a Crew."""
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": message})
        return await self._chat(model=self.model_light, messages=messages)

    async def chat_with_tools(self, messages: list[dict], tools: list[dict],
                              model: str = "heavy") -> dict:
        """Single Ollama call with native tool definitions."""
        chosen = self.model_heavy if model == "heavy" else self.model_light
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            payload = {
                "model": chosen,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "keep_alive": self.keep_alive,
            }
            r = await http.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()

    async def _chat(self, model: str, messages: list[dict],
                    format: dict | None = None) -> str:
        """Low-level async Ollama chat call."""
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            payload: dict = {
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": self.keep_alive,
            }
            if format is not None:
                payload["format"] = format
            r = await http.post(f"{self.host}/api/chat", json=payload)
            r.raise_for_status()
            return r.json()["message"]["content"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_native_ollama.py -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/native_ollama.py tests/test_native_ollama.py
git commit -m "feat: add NativeOllamaClient for fast classify and quick_reply"
```

---

## Task 3: Database Schema Migration

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/models.py`
- Test: `tests/test_database_migration.py`

- [ ] **Step 1: Write failing test for new tables**

Create `tests/test_database_migration.py`:

```python
import pytest
import aiosqlite
from backend.database import Database


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_crews_table_exists(db):
    async with aiosqlite.connect(db.path) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='crews'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_knowledge_log_table_exists(db):
    async with aiosqlite.connect(db.path) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_log'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_create_crew(db):
    crew_id = await db.create_crew(
        crew_type="researcher",
        trigger_source="telegram",
        chat_id="12345",
        task_description="Search for X",
    )
    assert crew_id is not None

    crew = await db.get_crew(crew_id)
    assert crew["crew_type"] == "researcher"
    assert crew["status"] == "active"
    assert crew["trigger_source"] == "telegram"


@pytest.mark.asyncio
async def test_update_crew_status(db):
    crew_id = await db.create_crew(
        crew_type="coder",
        trigger_source="api",
        chat_id=None,
        task_description="Fix bug",
    )
    await db.update_crew(crew_id, status="done", token_count=4200, result_path="KI-Buero/Code/fix.md")

    crew = await db.get_crew(crew_id)
    assert crew["status"] == "done"
    assert crew["token_count"] == 4200
    assert crew["result_path"] == "KI-Buero/Code/fix.md"


@pytest.mark.asyncio
async def test_log_crew_tool_use(db):
    crew_id = await db.create_crew(
        crew_type="ops", trigger_source="scheduler",
        chat_id=None, task_description="Backup",
    )
    await db.log_crew_tool(
        crew_id=crew_id,
        agent_name="ops",
        tool_name="system_shell",
        tool_input="ls -la",
        tool_output="total 42",
        duration_ms=150,
    )

    async with aiosqlite.connect(db.path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM tool_log WHERE crew_id = ?", (crew_id,)
        )
        row = await cursor.fetchone()
    assert row["tool_name"] == "system_shell"
    assert row["duration_ms"] == 150


@pytest.mark.asyncio
async def test_log_knowledge(db):
    crew_id = await db.create_crew(
        crew_type="researcher", trigger_source="telegram",
        chat_id="123", task_description="Research",
    )
    await db.log_knowledge(
        crew_id=crew_id,
        vault_path="Agenten-Wissensbasis/Gelerntes/crewai.md",
        knowledge_type="gelerntes",
        topic="CrewAI best practices",
    )

    async with aiosqlite.connect(db.path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM knowledge_log WHERE crew_id = ?", (crew_id,)
        )
        row = await cursor.fetchone()
    assert row["knowledge_type"] == "gelerntes"
    assert "crewai" in row["vault_path"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database_migration.py -v`
Expected: FAIL — `create_crew` not found

- [ ] **Step 3: Add new tables and methods to database.py**

Add to `backend/database.py` inside `_create_tables()`:

```python
        await db.execute("""
            CREATE TABLE IF NOT EXISTS crews (
                id TEXT PRIMARY KEY,
                crew_type TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                trigger_source TEXT,
                chat_id TEXT,
                task_description TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                token_count INTEGER DEFAULT 0,
                result_path TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_log (
                id TEXT PRIMARY KEY,
                crew_id TEXT REFERENCES crews(id),
                vault_path TEXT,
                knowledge_type TEXT,
                topic TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
```

Add new methods to the `Database` class:

```python
    async def create_crew(self, crew_type: str, trigger_source: str,
                          chat_id: str | None, task_description: str) -> str:
        import uuid
        crew_id = str(uuid.uuid4())[:8]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO crews (id, crew_type, trigger_source, chat_id, task_description) "
                "VALUES (?, ?, ?, ?, ?)",
                (crew_id, crew_type, trigger_source, chat_id, task_description),
            )
            await db.commit()
        return crew_id

    async def get_crew(self, crew_id: str) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM crews WHERE id = ?", (crew_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_crew(self, crew_id: str, **kwargs) -> None:
        allowed = {"status", "finished_at", "token_count", "result_path"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [crew_id]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                f"UPDATE crews SET {set_clause} WHERE id = ?", values
            )
            await db.commit()

    async def log_crew_tool(self, crew_id: str, agent_name: str,
                            tool_name: str, tool_input: str,
                            tool_output: str, duration_ms: int) -> None:
        import uuid
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO tool_log (id, crew_id, agent_name, tool_name, "
                "tool_input, tool_output, duration_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (str(uuid.uuid4())[:8], crew_id, agent_name, tool_name,
                 tool_input[:2000], tool_output[:2000], duration_ms),
            )
            await db.commit()

    async def log_knowledge(self, crew_id: str, vault_path: str,
                            knowledge_type: str, topic: str) -> None:
        import uuid
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO knowledge_log (id, crew_id, vault_path, knowledge_type, topic) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4())[:8], crew_id, vault_path, knowledge_type, topic),
            )
            await db.commit()

    async def get_active_crews(self) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM crews WHERE status = 'active' ORDER BY started_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Extend tool_log table with new columns**

Add to `_migrate()` in `backend/database.py`:

```python
        # Migration: add crew_id, agent_name, duration_ms to tool_log
        try:
            await db.execute("ALTER TABLE tool_log ADD COLUMN crew_id TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE tool_log ADD COLUMN agent_name TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE tool_log ADD COLUMN duration_ms INTEGER")
        except Exception:
            pass
```

- [ ] **Step 5: Add Crew models to models.py**

Add to `backend/models.py`:

```python
class CrewType(str, Enum):
    coder = "coder"
    researcher = "researcher"
    writer = "writer"
    ops = "ops"
    web_design = "web_design"
    swift = "swift"
    ki_expert = "ki_expert"
    analyst = "analyst"
    premium = "premium"


class CrewStatus(str, Enum):
    active = "active"
    done = "done"
    error = "error"


class CrewData(BaseModel):
    id: str
    crew_type: CrewType
    status: CrewStatus = CrewStatus.active
    trigger_source: str = ""
    chat_id: str | None = None
    task_description: str = ""
    started_at: str = ""
    finished_at: str | None = None
    token_count: int = 0
    result_path: str | None = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_database_migration.py -v`
Expected: All 6 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/database.py backend/models.py tests/test_database_migration.py
git commit -m "feat: add crews table, knowledge_log, and DB methods for CrewAI migration"
```

---

## Task 4: Rule Engine

**Files:**
- Create: `backend/flow/__init__.py`
- Create: `backend/flow/rule_engine.py`
- Test: `tests/test_rule_engine.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_rule_engine.py`:

```python
import pytest
from backend.flow.rule_engine import RuleEngine, RouteResult


@pytest.fixture
def engine():
    return RuleEngine()


def test_quick_reply_greeting(engine):
    result = engine.route("Hallo!")
    assert result.action == "quick_reply"


def test_quick_reply_thanks(engine):
    result = engine.route("Danke dir!")
    assert result.action == "quick_reply"


def test_quick_reply_status_question(engine):
    result = engine.route("Was machst du gerade?")
    assert result.action == "quick_reply"


def test_crew_match_researcher(engine):
    result = engine.route("Recherchiere mir alles ueber CrewAI")
    assert result.action == "crew"
    assert result.crew_type == "researcher"


def test_crew_match_coder(engine):
    result = engine.route("Schreib mir ein Python Script das Dateien sortiert")
    assert result.action == "crew"
    assert result.crew_type == "coder"


def test_crew_match_web_design(engine):
    result = engine.route("Bau mir eine Landing Page mit Tailwind")
    assert result.action == "crew"
    assert result.crew_type == "web_design"


def test_crew_match_swift(engine):
    result = engine.route("Erstell eine SwiftUI App fuer iOS")
    assert result.action == "crew"
    assert result.crew_type == "swift"


def test_crew_match_ki_expert(engine):
    result = engine.route("Wie kann ich ein Modell fine-tunen?")
    assert result.action == "crew"
    assert result.crew_type == "ki_expert"


def test_crew_match_analyst(engine):
    result = engine.route("Analysiere diese CSV Daten")
    assert result.action == "crew"
    assert result.crew_type == "analyst"


def test_crew_match_ops(engine):
    result = engine.route("Deploy das auf dem Server")
    assert result.action == "crew"
    assert result.crew_type == "ops"


def test_crew_match_writer(engine):
    result = engine.route("Schreib mir einen Guide ueber Docker")
    assert result.action == "crew"
    assert result.crew_type == "writer"


def test_no_match_falls_through_to_classify(engine):
    result = engine.route("Kannst du mir bei meinem Projekt helfen?")
    assert result.action == "classify"


def test_crew_keywords_case_insensitive(engine):
    result = engine.route("RECHERCHIERE das fuer mich")
    assert result.action == "crew"
    assert result.crew_type == "researcher"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rule_engine.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create flow package**

Create `backend/flow/__init__.py`:

```python
```

- [ ] **Step 4: Implement RuleEngine**

Create `backend/flow/rule_engine.py`:

```python
"""Regex/keyword router — decides quick_reply vs crew vs classify."""

import re
from dataclasses import dataclass


@dataclass
class RouteResult:
    action: str  # "quick_reply", "crew", or "classify"
    crew_type: str | None = None


QUICK_REPLY_PATTERNS = [
    re.compile(r"^(hallo|hi|hey|moin|servus|guten\s*(morgen|tag|abend))[\s!.]*$", re.I),
    re.compile(r"^(danke|vielen\s*dank|thx|thanks|merci)[\s!.]*", re.I),
    re.compile(r"^(ja|nein|ok|alles\s*klar|passt|genau|stimmt)[\s!.]*$", re.I),
    re.compile(r"^was\s+(machst|tust)\s+du\s*(gerade)?", re.I),
    re.compile(r"^wie\s+geht('?s|\s+es)\s*(dir)?", re.I),
    re.compile(r"^(gute\s*nacht|bis\s*(dann|morgen|spaeter)|tschuess|ciao)[\s!.]*$", re.I),
]

CREW_KEYWORDS: dict[str, list[str]] = {
    "web_design": [
        "website", "landing page", "html", "css", "tailwind",
        "responsive", "frontend", "webpage", "webseite",
    ],
    "swift": [
        "swift", "swiftui", "ios", "macos", "xcode", "app store",
        "iphone app", "ipad app", "apple app",
    ],
    "ki_expert": [
        "fine-tun", "training", "embedding", "neural",
        "ml pipeline", "modell trainier", "prompt engineer",
        "machine learning", "deep learning",
    ],
    "analyst": [
        "csv", "statistik", "chart", "visualisier", "datenanalyse",
        "pandas", "diagramm", "auswert",
    ],
    "ops": [
        "server", "docker", "deploy", "systemd", "backup",
        "nginx", "ssh", "kubernetes", "k8s",
    ],
    "researcher": [
        "recherchier", "herausfind", "vergleich",
        "zusammenfass", "informier dich", "such mir",
        "was ist", "erklaer mir",
    ],
    "coder": [
        "code", "python", "script", "debug", "fix", "implementier",
        "programmier", "funktion", "klasse", "refactor", "bug",
    ],
    "writer": [
        "schreib", "text", "doku", "guide", "artikel",
        "zusammenfassung", "bericht", "notiz",
    ],
}

# Higher priority crew types are checked first (more specific keywords)
CREW_PRIORITY = [
    "web_design", "swift", "ki_expert", "analyst", "ops",
    "researcher", "coder", "writer",
]


class RuleEngine:
    """Fast, deterministic message router — no LLM calls."""

    def route(self, message: str) -> RouteResult:
        text = message.strip()

        # 1. Quick-reply patterns
        for pattern in QUICK_REPLY_PATTERNS:
            if pattern.search(text):
                return RouteResult(action="quick_reply")

        # 2. Crew keyword matching
        text_lower = text.lower()
        for crew_type in CREW_PRIORITY:
            keywords = CREW_KEYWORDS[crew_type]
            for kw in keywords:
                if kw in text_lower:
                    return RouteResult(action="crew", crew_type=crew_type)

        # 3. No match — needs LLM classify
        return RouteResult(action="classify")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_rule_engine.py -v`
Expected: All 14 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/flow/__init__.py backend/flow/rule_engine.py tests/test_rule_engine.py
git commit -m "feat: add RuleEngine for deterministic message routing"
```

---

## Task 5: EventBus

**Files:**
- Create: `backend/event_bus.py`
- Test: `tests/test_event_bus.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_event_bus.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.event_bus import FalkensteinEventBus


@pytest.fixture
def event_bus():
    ws = AsyncMock()
    tg = AsyncMock()
    db = AsyncMock()
    db.create_crew = AsyncMock(return_value="crew-123")
    return FalkensteinEventBus(ws_manager=ws, telegram_bot=tg, db=db)


@pytest.mark.asyncio
async def test_on_crew_start_broadcasts_ws(event_bus):
    await event_bus.on_crew_start("researcher", "Find info", "chat-1")

    event_bus.ws_manager.broadcast.assert_called_once()
    call_data = event_bus.ws_manager.broadcast.call_args[0][0]
    assert call_data["type"] == "agent_spawn"
    assert call_data["crew"] == "researcher"


@pytest.mark.asyncio
async def test_on_crew_start_sends_telegram(event_bus):
    await event_bus.on_crew_start("coder", "Fix bug", "chat-1")

    event_bus.telegram_bot.send_message.assert_called_once()
    msg = event_bus.telegram_bot.send_message.call_args[0][0]
    assert "coder" in msg.lower() or "Fix bug" in msg


@pytest.mark.asyncio
async def test_on_crew_start_creates_db_entry(event_bus):
    crew_id = await event_bus.on_crew_start("ops", "Backup", "chat-2")

    event_bus.db.create_crew.assert_called_once()
    assert crew_id == "crew-123"


@pytest.mark.asyncio
async def test_on_tool_call_broadcasts_ws(event_bus):
    event_bus._current_crew_id = "crew-1"
    await event_bus.on_tool_call("researcher", "web_search", '{"query": "test"}', "Results here")

    event_bus.ws_manager.broadcast.assert_called_once()
    call_data = event_bus.ws_manager.broadcast.call_args[0][0]
    assert call_data["type"] == "tool_use"
    assert call_data["tool"] == "web_search"


@pytest.mark.asyncio
async def test_on_tool_call_streams_to_telegram_for_web_search(event_bus):
    event_bus._current_crew_id = "crew-1"
    event_bus._current_chat_id = "chat-1"
    await event_bus.on_tool_call("researcher", "web_search", "{}", "Found 5 results")

    event_bus.telegram_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_on_tool_call_does_not_stream_file_reads(event_bus):
    event_bus._current_crew_id = "crew-1"
    event_bus._current_chat_id = "chat-1"
    await event_bus.on_tool_call("coder", "file_read", "{}", "file content")

    event_bus.telegram_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_crew_done_sends_final_telegram(event_bus):
    event_bus._current_crew_id = "crew-1"
    await event_bus.on_crew_done("researcher", "Here are the results", "chat-1")

    event_bus.telegram_bot.send_message.assert_called_once_with(
        "Here are the results", chat_id="chat-1"
    )


@pytest.mark.asyncio
async def test_on_crew_done_updates_db(event_bus):
    event_bus._current_crew_id = "crew-1"
    await event_bus.on_crew_done("researcher", "Done", "chat-1")

    event_bus.db.update_crew.assert_called_once()
    call_kwargs = event_bus.db.update_crew.call_args
    assert call_kwargs[0][0] == "crew-1"  # crew_id


@pytest.mark.asyncio
async def test_on_crew_done_broadcasts_agent_done(event_bus):
    event_bus._current_crew_id = "crew-1"
    await event_bus.on_crew_done("coder", "Fixed", "chat-1")

    call_data = event_bus.ws_manager.broadcast.call_args[0][0]
    assert call_data["type"] == "agent_done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_event_bus.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement FalkensteinEventBus**

Create `backend/event_bus.py`:

```python
"""Central event hub: CrewAI callbacks -> WebSocket + Telegram + DB."""

import logging

log = logging.getLogger(__name__)

# Tools whose results get streamed to Telegram
STREAM_TO_TELEGRAM = {
    "web_search", "scrape_website", "obsidian_manager", "obsidian",
    "shell_runner", "system_shell", "code_executor",
}

# Tools that are silent on Telegram
SILENT_ON_TELEGRAM = {
    "file_read", "file_write", "directory_read",
}

TOOL_TO_ANIMATION = {
    "code_executor": "typing",
    "shell_runner": "typing",
    "system_shell": "typing",
    "file_read": "typing",
    "file_write": "typing",
    "web_search": "reading",
    "scrape_website": "reading",
    "obsidian_manager": "reading",
    "obsidian": "reading",
    "vision": "thinking",
}


class FalkensteinEventBus:
    """Bridges CrewAI callbacks to WebSocket, Telegram, and DB."""

    def __init__(self, ws_manager, telegram_bot, db):
        self.ws_manager = ws_manager
        self.telegram_bot = telegram_bot
        self.db = db
        self._current_crew_id: str | None = None
        self._current_chat_id: str | None = None

    async def on_crew_start(self, crew_name: str, task_description: str,
                            chat_id: str | None) -> str:
        """Called when a Crew kicks off. Returns crew_id."""
        self._current_chat_id = chat_id

        # DB
        crew_id = await self.db.create_crew(
            crew_type=crew_name,
            trigger_source="telegram" if chat_id else "api",
            chat_id=chat_id,
            task_description=task_description,
        )
        self._current_crew_id = crew_id

        # Telegram: immediate feedback
        if chat_id and self.telegram_bot:
            await self.telegram_bot.send_message(
                f"{crew_name} arbeitet: {task_description}",
                chat_id=chat_id,
            )

        # WebSocket: agent appears in office
        await self.ws_manager.broadcast({
            "type": "agent_spawn",
            "crew": crew_name,
            "crew_id": crew_id,
            "task": task_description,
        })

        log.info("Crew started: %s (%s) — %s", crew_name, crew_id, task_description)
        return crew_id

    async def on_tool_call(self, agent_name: str, tool_name: str,
                           tool_input: str, tool_output: str,
                           duration_ms: int = 0) -> None:
        """Called on every tool invocation within a Crew."""
        animation = TOOL_TO_ANIMATION.get(tool_name, "thinking")

        # WebSocket: update animation
        await self.ws_manager.broadcast({
            "type": "tool_use",
            "agent": agent_name,
            "tool": tool_name,
            "animation": animation,
            "crew_id": self._current_crew_id,
        })

        # Telegram: stream if appropriate
        if tool_name in STREAM_TO_TELEGRAM and self._current_chat_id and self.telegram_bot:
            truncated = tool_output[:500] if tool_output else ""
            if truncated:
                await self.telegram_bot.send_message(
                    f"🔧 {tool_name}: {truncated}",
                    chat_id=self._current_chat_id,
                )

        # DB: tool_log
        if self._current_crew_id:
            try:
                await self.db.log_crew_tool(
                    crew_id=self._current_crew_id,
                    agent_name=agent_name,
                    tool_name=tool_name,
                    tool_input=tool_input[:2000] if tool_input else "",
                    tool_output=tool_output[:2000] if tool_output else "",
                    duration_ms=duration_ms,
                )
            except Exception as e:
                log.warning("Failed to log tool use: %s", e)

    async def on_crew_done(self, crew_name: str, result: str,
                           chat_id: str | None) -> None:
        """Called when a Crew completes."""
        # Telegram: final result
        if chat_id and self.telegram_bot:
            await self.telegram_bot.send_message(result, chat_id=chat_id)

        # DB: mark done
        if self._current_crew_id:
            await self.db.update_crew(self._current_crew_id, status="done")

        # WebSocket: agent done
        await self.ws_manager.broadcast({
            "type": "agent_done",
            "crew": crew_name,
            "crew_id": self._current_crew_id,
        })

        log.info("Crew done: %s (%s)", crew_name, self._current_crew_id)
        self._current_crew_id = None
        self._current_chat_id = None

    async def on_crew_error(self, crew_name: str, error: str,
                            chat_id: str | None) -> None:
        """Called when a Crew fails."""
        if chat_id and self.telegram_bot:
            await self.telegram_bot.send_message(
                f"❌ {crew_name} fehlgeschlagen: {error}",
                chat_id=chat_id,
            )

        if self._current_crew_id:
            await self.db.update_crew(self._current_crew_id, status="error")

        await self.ws_manager.broadcast({
            "type": "agent_error",
            "crew": crew_name,
            "crew_id": self._current_crew_id,
            "error": error,
        })

        log.error("Crew error: %s — %s", crew_name, error)
        self._current_crew_id = None
        self._current_chat_id = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_event_bus.py -v`
Expected: All 9 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/event_bus.py tests/test_event_bus.py
git commit -m "feat: add FalkensteinEventBus for CrewAI callback routing"
```

---

## Task 6: CrewAI Tool Wrappers

**Files:**
- Create: `backend/tools/crewai_wrappers.py`
- Test: `tests/test_crewai_wrappers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_crewai_wrappers.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.tools.crewai_wrappers import (
    CodeExecutorTool,
    ShellRunnerTool,
    ObsidianTool,
    OllamaManagerTool,
    SelfConfigTool,
    OpsExecutorTool,
    SystemShellTool,
)


def test_code_executor_tool_has_name():
    tool = CodeExecutorTool()
    assert tool.name == "code_executor"
    assert "code" in tool.description.lower() or "python" in tool.description.lower()


def test_shell_runner_tool_has_name():
    tool = ShellRunnerTool()
    assert tool.name == "shell_runner"


def test_obsidian_tool_has_name():
    tool = ObsidianTool()
    assert tool.name == "obsidian"


def test_ollama_manager_tool_has_name():
    tool = OllamaManagerTool()
    assert tool.name == "ollama_manager"


def test_self_config_tool_has_name():
    tool = SelfConfigTool()
    assert tool.name == "self_config"


def test_ops_executor_tool_has_name():
    tool = OpsExecutorTool()
    assert tool.name == "ops_executor"


def test_system_shell_tool_has_name():
    tool = SystemShellTool()
    assert tool.name == "system_shell"


def test_all_tools_are_crewai_base_tool():
    from crewai.tools import BaseTool
    for cls in [CodeExecutorTool, ShellRunnerTool, ObsidianTool,
                OllamaManagerTool, SelfConfigTool, OpsExecutorTool, SystemShellTool]:
        tool = cls()
        assert isinstance(tool, BaseTool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_crewai_wrappers.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement wrappers**

Create `backend/tools/crewai_wrappers.py`:

```python
"""CrewAI BaseTool wrappers for Falkenstein-specific tools."""

import asyncio
from crewai.tools import BaseTool
from pydantic import Field


def _run_async(coro):
    """Run async tool in sync context (CrewAI _run is sync)."""
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return loop.run_in_executor(pool, asyncio.run, coro)
    except RuntimeError:
        return asyncio.run(coro)


class CodeExecutorTool(BaseTool):
    name: str = "code_executor"
    description: str = (
        "Execute Python code in a sandboxed environment. "
        "Input: Python code as a string. Returns stdout/stderr."
    )
    _executor: object = None

    def set_executor(self, executor):
        self._executor = executor

    def _run(self, code: str) -> str:
        if not self._executor:
            return "Error: code_executor not initialized"
        result = asyncio.run(self._executor.execute({"code": code}))
        return result.output if result.success else f"Error: {result.output}"


class ShellRunnerTool(BaseTool):
    name: str = "shell_runner"
    description: str = (
        "Run a whitelisted shell command. "
        "Input: command string. Returns stdout/stderr."
    )
    _executor: object = None

    def set_executor(self, executor):
        self._executor = executor

    def _run(self, command: str) -> str:
        if not self._executor:
            return "Error: shell_runner not initialized"
        result = asyncio.run(self._executor.execute({"command": command}))
        return result.output if result.success else f"Error: {result.output}"


class SystemShellTool(BaseTool):
    name: str = "system_shell"
    description: str = (
        "Run any system shell command (unrestricted). Only for ops tasks. "
        "Input: command string. Returns stdout/stderr."
    )
    _executor: object = None

    def set_executor(self, executor):
        self._executor = executor

    def _run(self, command: str) -> str:
        if not self._executor:
            return "Error: system_shell not initialized"
        result = asyncio.run(self._executor.execute({"command": command}))
        return result.output if result.success else f"Error: {result.output}"


class ObsidianTool(BaseTool):
    name: str = "obsidian"
    description: str = (
        "Read and write notes in the Obsidian knowledge base. "
        "Actions: 'read' (path), 'write' (path, content), 'search' (query), "
        "'list' (folder). Always uses existing folder structure."
    )
    _executor: object = None

    def set_executor(self, executor):
        self._executor = executor

    def _run(self, action: str, path: str = "", content: str = "",
             query: str = "") -> str:
        if not self._executor:
            return "Error: obsidian not initialized"
        params = {"action": action, "path": path, "content": content, "query": query}
        result = asyncio.run(self._executor.execute(params))
        return result.output if result.success else f"Error: {result.output}"


class OllamaManagerTool(BaseTool):
    name: str = "ollama_manager"
    description: str = (
        "Manage local Ollama models. "
        "Actions: 'list', 'pull' (model), 'delete' (model), 'status'."
    )
    _executor: object = None

    def set_executor(self, executor):
        self._executor = executor

    def _run(self, action: str, model: str = "") -> str:
        if not self._executor:
            return "Error: ollama_manager not initialized"
        result = asyncio.run(self._executor.execute({"action": action, "model": model}))
        return result.output if result.success else f"Error: {result.output}"


class SelfConfigTool(BaseTool):
    name: str = "self_config"
    description: str = (
        "Read or update Falkenstein runtime configuration. "
        "Actions: 'get' (key), 'set' (key, value), 'list'."
    )
    _executor: object = None

    def set_executor(self, executor):
        self._executor = executor

    def _run(self, action: str, key: str = "", value: str = "") -> str:
        if not self._executor:
            return "Error: self_config not initialized"
        result = asyncio.run(
            self._executor.execute({"action": action, "key": key, "value": value})
        )
        return result.output if result.success else f"Error: {result.output}"


class OpsExecutorTool(BaseTool):
    name: str = "ops_executor"
    description: str = (
        "Execute an ops plan with confirmation gate. "
        "Input: plan description. Returns execution result."
    )
    _executor: object = None

    def set_executor(self, executor):
        self._executor = executor

    def _run(self, plan: str) -> str:
        if not self._executor:
            return "Error: ops_executor not initialized"
        result = asyncio.run(self._executor.execute({"plan": plan}))
        return result.output if result.success else f"Error: {result.output}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_crewai_wrappers.py -v`
Expected: All 8 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tools/crewai_wrappers.py tests/test_crewai_wrappers.py
git commit -m "feat: add CrewAI BaseTool wrappers for Falkenstein tools"
```

---

## Task 7: VaultIndex & SmartObsidianTool

**Files:**
- Create: `backend/vault_index.py`
- Test: `tests/test_vault_index.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_vault_index.py`:

```python
import pytest
import os
from pathlib import Path
from backend.vault_index import VaultIndex


@pytest.fixture
def vault(tmp_path):
    """Create a mock Obsidian vault structure."""
    # KI-Buero
    (tmp_path / "KI-Buero" / "Recherchen").mkdir(parents=True)
    (tmp_path / "KI-Buero" / "Guides").mkdir(parents=True)
    (tmp_path / "KI-Buero" / "Code").mkdir(parents=True)
    (tmp_path / "KI-Buero" / "Reports").mkdir(parents=True)
    (tmp_path / "KI-Buero" / "Ideen").mkdir(parents=True)
    (tmp_path / "KI-Buero" / "Daily").mkdir(parents=True)
    (tmp_path / "KI-Buero" / "Projekte" / "Falkenstein").mkdir(parents=True)

    # Agenten-Wissensbasis
    (tmp_path / "Agenten-Wissensbasis" / "Kontext").mkdir(parents=True)
    (tmp_path / "Agenten-Wissensbasis" / "Gelerntes").mkdir(parents=True)
    (tmp_path / "Agenten-Wissensbasis" / "Referenzen").mkdir(parents=True)
    (tmp_path / "Agenten-Wissensbasis" / "Fehler-Log").mkdir(parents=True)

    # Some existing notes
    (tmp_path / "KI-Buero" / "Recherchen" / "crewai-overview.md").write_text("# CrewAI\nBasic info")
    (tmp_path / "KI-Buero" / "Recherchen" / "ollama-tools.md").write_text("# Ollama Tools\nInfo")
    (tmp_path / "KI-Buero" / "Kanban.md").write_text("# Kanban")
    (tmp_path / "Agenten-Wissensbasis" / "Kontext" / "user-profil.md").write_text("# Janik")

    return tmp_path


@pytest.fixture
def index(vault):
    vi = VaultIndex(str(vault))
    vi.scan()
    return vi


def test_scan_finds_all_folders(index):
    folders = index.list_folders()
    assert "KI-Buero/Recherchen" in folders
    assert "KI-Buero/Guides" in folders
    assert "Agenten-Wissensbasis/Kontext" in folders


def test_scan_finds_existing_notes(index):
    notes = index.list_notes("KI-Buero/Recherchen")
    assert "crewai-overview.md" in notes
    assert "ollama-tools.md" in notes


def test_find_best_folder_for_researcher(index):
    folder = index.find_best_folder("researcher", "Python web scraping")
    assert folder == "KI-Buero/Recherchen"


def test_find_best_folder_for_coder(index):
    folder = index.find_best_folder("coder", "API endpoint")
    assert folder == "KI-Buero/Code"


def test_find_best_folder_for_writer(index):
    folder = index.find_best_folder("writer", "Docker tutorial")
    assert folder == "KI-Buero/Guides"


def test_find_best_folder_for_analyst(index):
    folder = index.find_best_folder("analyst", "Sales data")
    assert folder == "KI-Buero/Reports"


def test_find_related_note_by_topic(index):
    note = index.find_related_note("crewai")
    assert note is not None
    assert "crewai-overview.md" in note


def test_find_related_note_returns_none_for_unknown(index):
    note = index.find_related_note("quantum computing")
    assert note is None


def test_as_context_returns_tree_string(index):
    ctx = index.as_context()
    assert "KI-Buero" in ctx
    assert "Agenten-Wissensbasis" in ctx
    assert "Recherchen" in ctx


def test_knowledge_folder_mapping(index):
    assert index.get_knowledge_folder("kontext") == "Agenten-Wissensbasis/Kontext"
    assert index.get_knowledge_folder("gelerntes") == "Agenten-Wissensbasis/Gelerntes"
    assert index.get_knowledge_folder("referenz") == "Agenten-Wissensbasis/Referenzen"
    assert index.get_knowledge_folder("fehler") == "Agenten-Wissensbasis/Fehler-Log"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vault_index.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement VaultIndex**

Create `backend/vault_index.py`:

```python
"""Obsidian Vault index — knows the structure, finds the right place to write."""

import os
from pathlib import Path


CREW_TO_FOLDER = {
    "researcher": "KI-Buero/Recherchen",
    "writer": "KI-Buero/Guides",
    "coder": "KI-Buero/Code",
    "ki_expert": "KI-Buero/Recherchen",
    "analyst": "KI-Buero/Reports",
    "web_design": "KI-Buero/Code",
    "swift": "KI-Buero/Code",
    "ops": "KI-Buero/Reports",
    "premium": "KI-Buero/Recherchen",
}

KNOWLEDGE_FOLDERS = {
    "kontext": "Agenten-Wissensbasis/Kontext",
    "gelerntes": "Agenten-Wissensbasis/Gelerntes",
    "referenz": "Agenten-Wissensbasis/Referenzen",
    "fehler": "Agenten-Wissensbasis/Fehler-Log",
}


class VaultIndex:
    """Scans and indexes an Obsidian vault for smart file placement."""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self._folders: list[str] = []
        self._notes: dict[str, list[str]] = {}  # folder -> [note filenames]

    def scan(self) -> None:
        """Walk the vault and build the index."""
        self._folders = []
        self._notes = {}

        for dirpath, dirnames, filenames in os.walk(self.vault_path):
            # Skip hidden dirs (.obsidian, .git, etc.)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            rel = os.path.relpath(dirpath, self.vault_path)
            if rel == ".":
                continue

            self._folders.append(rel)
            md_files = [f for f in filenames if f.endswith(".md")]
            if md_files:
                self._notes[rel] = md_files

    def list_folders(self) -> list[str]:
        """Return all indexed folder paths (relative to vault root)."""
        return list(self._folders)

    def list_notes(self, folder: str) -> list[str]:
        """Return note filenames in a specific folder."""
        return self._notes.get(folder, [])

    def find_best_folder(self, crew_type: str, topic: str) -> str:
        """Find the best existing folder for a crew's output."""
        return CREW_TO_FOLDER.get(crew_type, "KI-Buero/Recherchen")

    def find_related_note(self, topic: str) -> str | None:
        """Find an existing note whose filename matches the topic."""
        topic_lower = topic.lower().strip()
        for folder, notes in self._notes.items():
            for note in notes:
                name_lower = note.lower().replace(".md", "").replace("-", " ").replace("_", " ")
                if topic_lower in name_lower or name_lower in topic_lower:
                    return str(Path(folder) / note)
        return None

    def get_knowledge_folder(self, category: str) -> str:
        """Map a knowledge category to its vault folder."""
        return KNOWLEDGE_FOLDERS.get(category, "Agenten-Wissensbasis/Gelerntes")

    def as_context(self) -> str:
        """Return the vault structure as a text tree for agent prompts."""
        lines = ["Obsidian Vault Struktur:"]
        for folder in sorted(self._folders):
            depth = folder.count(os.sep)
            indent = "  " * depth
            name = os.path.basename(folder)
            lines.append(f"{indent}{name}/")
            for note in self._notes.get(folder, []):
                lines.append(f"{indent}  {note}")
        return "\n".join(lines)

    def full_path(self, rel_path: str) -> Path:
        """Resolve a relative vault path to absolute."""
        return self.vault_path / rel_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vault_index.py -v`
Expected: All 11 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/vault_index.py tests/test_vault_index.py
git commit -m "feat: add VaultIndex for smart Obsidian file placement"
```

---

## Task 8: YAML Config & Base Crew

**Files:**
- Create: `backend/config/agents.yaml`
- Create: `backend/config/tasks.yaml`
- Create: `backend/crews/__init__.py`
- Create: `backend/crews/base_crew.py`
- Test: `tests/test_crews.py`

- [ ] **Step 1: Create config directory and agents.yaml**

Run: `mkdir -p /Users/janikhartmann/Falkenstein/backend/config`

Create `backend/config/agents.yaml`:

```yaml
coder:
  role: "Senior Developer"
  goal: "Write, debug, and execute code. Use shell and file tools."
  backstory: "Experienced developer with access to shell, code executor, and file system."
  max_iter: 10
  verbose: true

web_designer:
  role: "UI/UX Designer"
  goal: "Design modern, responsive web interfaces with clean UI."
  backstory: "Experienced designer focused on Tailwind CSS and modern web standards."
  max_iter: 8
  verbose: true

web_coder:
  role: "Frontend Developer"
  goal: "Implement designs pixel-perfect in HTML/CSS/JS."
  backstory: "Frontend specialist for modern web standards and frameworks."
  max_iter: 10
  verbose: true

researcher:
  role: "Web Researcher"
  goal: "Find information, summarize it, and store results in Obsidian."
  backstory: "Research specialist with web access and knowledge base integration."
  max_iter: 8
  verbose: true

swift_dev:
  role: "Swift Developer"
  goal: "Build SwiftUI apps for iOS and macOS."
  backstory: "Apple platform specialist with SwiftUI and SwiftData expertise."
  max_iter: 10
  verbose: true

ki_expert:
  role: "AI/ML Engineer"
  goal: "Build ML pipelines, evaluate models, and do prompt engineering."
  backstory: "AI specialist experienced with local models, fine-tuning, and MLOps."
  max_iter: 10
  verbose: true

analyst:
  role: "Data Analyst"
  goal: "Analyze data, create visualizations, and write reports."
  backstory: "Data analyst with Python, Pandas, and visualization expertise."
  max_iter: 8
  verbose: true

writer:
  role: "Technical Writer"
  goal: "Write clear, structured documentation and guides."
  backstory: "Technical writer focused on understandable communication."
  max_iter: 6
  verbose: true

ops:
  role: "DevOps Engineer"
  goal: "Manage servers, deploy applications, monitor systems."
  backstory: "Ops specialist with server and container experience."
  max_iter: 8
  verbose: true

premium:
  role: "Senior AI Assistant"
  goal: "Solve complex tasks that exceed local model capabilities."
  backstory: "Premium agent with access to Claude and Gemini APIs."
  max_iter: 12
  verbose: true
```

- [ ] **Step 2: Create tasks.yaml**

Create `backend/config/tasks.yaml`:

```yaml
default:
  expected_output: "A clear, actionable result in German."
  human_input: false

code_task:
  expected_output: "Working code with explanation of changes made."
  human_input: false

research_task:
  expected_output: "Structured summary with sources and key findings."
  human_input: false

writing_task:
  expected_output: "Well-structured text in German, ready for Obsidian."
  human_input: false

analysis_task:
  expected_output: "Data analysis with insights and optional visualization code."
  human_input: false

ops_task:
  expected_output: "Execution report with status of each operation."
  human_input: false
```

- [ ] **Step 3: Write failing test for base_crew**

Create `tests/test_crews.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from backend.crews.base_crew import (
    load_agent_configs,
    create_crewai_agent,
    BaseFalkensteinCrew,
)


def test_load_agent_configs():
    configs = load_agent_configs()
    assert "coder" in configs
    assert "researcher" in configs
    assert "web_designer" in configs
    assert configs["coder"]["role"] == "Senior Developer"


def test_create_crewai_agent():
    configs = load_agent_configs()
    agent = create_crewai_agent(
        agent_key="coder",
        config=configs["coder"],
        llm_model="ollama_chat/gemma4:26b",
        function_calling_llm="ollama_chat/gemma4:e4b",
        tools=[],
    )
    assert agent.role == "Senior Developer"


def test_base_crew_has_event_bus_callbacks():
    event_bus = MagicMock()
    crew = BaseFalkensteinCrew(
        crew_type="coder",
        task_description="Fix bug",
        event_bus=event_bus,
        chat_id="123",
    )
    assert crew.crew_type == "coder"
    assert crew.event_bus is event_bus
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_crews.py -v`
Expected: FAIL — module not found

- [ ] **Step 5: Create crews package**

Create `backend/crews/__init__.py`:

```python
```

- [ ] **Step 6: Implement base_crew.py**

Create `backend/crews/base_crew.py`:

```python
"""Base crew configuration and helpers for all Falkenstein crews."""

from pathlib import Path

import yaml
from crewai import Agent, Task, Crew, LLM


CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_agent_configs() -> dict:
    """Load agent definitions from agents.yaml."""
    path = CONFIG_DIR / "agents.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def load_task_configs() -> dict:
    """Load task templates from tasks.yaml."""
    path = CONFIG_DIR / "tasks.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def create_crewai_agent(
    agent_key: str,
    config: dict,
    llm_model: str,
    function_calling_llm: str | None = None,
    tools: list | None = None,
    vault_context: str = "",
) -> Agent:
    """Create a CrewAI Agent from YAML config."""
    backstory = config["backstory"]
    if vault_context:
        backstory += (
            "\n\nWICHTIG: Du hast Zugriff auf eine Obsidian-Wissensbasis. "
            "Lege NIEMALS eigene Ordner an. Nutze nur die bestehende Struktur:\n"
            + vault_context
        )

    llm = LLM(model=llm_model)
    fc_llm = LLM(model=function_calling_llm) if function_calling_llm else None

    return Agent(
        role=config["role"],
        goal=config["goal"],
        backstory=backstory,
        llm=llm,
        function_calling_llm=fc_llm,
        tools=tools or [],
        max_iter=config.get("max_iter", 10),
        verbose=config.get("verbose", True),
    )


class BaseFalkensteinCrew:
    """Base class for all Falkenstein crews — wires up EventBus callbacks."""

    def __init__(self, crew_type: str, task_description: str,
                 event_bus, chat_id: str | None = None,
                 vault_context: str = ""):
        self.crew_type = crew_type
        self.task_description = task_description
        self.event_bus = event_bus
        self.chat_id = chat_id
        self.vault_context = vault_context
        self._configs = load_agent_configs()
        self._task_configs = load_task_configs()

    def _make_agent(self, agent_key: str, llm_model: str,
                    fc_llm: str | None = None,
                    tools: list | None = None) -> Agent:
        """Create an agent from YAML config with vault context."""
        return create_crewai_agent(
            agent_key=agent_key,
            config=self._configs[agent_key],
            llm_model=llm_model,
            function_calling_llm=fc_llm,
            tools=tools,
            vault_context=self.vault_context,
        )

    def _step_callback(self, step_output) -> None:
        """CrewAI step callback — fires on every tool call."""
        import asyncio
        agent_name = getattr(step_output, "agent", self.crew_type)
        tool_name = getattr(step_output, "tool", "unknown")
        tool_input = str(getattr(step_output, "tool_input", ""))
        result = str(getattr(step_output, "result", ""))

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.event_bus.on_tool_call(
                    str(agent_name), str(tool_name), tool_input, result
                )
            )
        except RuntimeError:
            pass  # No event loop — skip WS broadcast

    def build_crew(self) -> Crew:
        """Override in subclasses. Must return a configured Crew."""
        raise NotImplementedError

    async def run(self) -> str:
        """Execute the crew with EventBus lifecycle hooks."""
        crew_id = await self.event_bus.on_crew_start(
            self.crew_type, self.task_description, self.chat_id
        )

        try:
            crew = self.build_crew()
            result = crew.kickoff()
            output = str(result)
            await self.event_bus.on_crew_done(
                self.crew_type, output, self.chat_id
            )
            return output
        except Exception as e:
            await self.event_bus.on_crew_error(
                self.crew_type, str(e), self.chat_id
            )
            raise
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_crews.py -v`
Expected: All 3 PASS

- [ ] **Step 8: Commit**

```bash
git add backend/config/agents.yaml backend/config/tasks.yaml \
    backend/crews/__init__.py backend/crews/base_crew.py tests/test_crews.py
git commit -m "feat: add YAML agent configs and BaseFalkensteinCrew"
```

---

## Task 9: Individual Crews

**Files:**
- Create: `backend/crews/coder_crew.py`
- Create: `backend/crews/researcher_crew.py`
- Create: `backend/crews/writer_crew.py`
- Create: `backend/crews/ops_crew.py`
- Create: `backend/crews/web_design_crew.py`
- Create: `backend/crews/swift_crew.py`
- Create: `backend/crews/ki_expert_crew.py`
- Create: `backend/crews/analyst_crew.py`
- Create: `backend/crews/premium_crew.py`

All crews follow the same pattern. Each overrides `build_crew()` from `BaseFalkensteinCrew`.

- [ ] **Step 1: Implement CoderCrew**

Create `backend/crews/coder_crew.py`:

```python
"""CoderCrew — code writing, debugging, shell execution."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class CoderCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:26b",
                 fc_llm="ollama_chat/gemma4:e4b"):
        super().__init__("coder", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "coder", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=self.task_description,
            expected_output=self._task_configs["code_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 2: Implement ResearcherCrew**

Create `backend/crews/researcher_crew.py`:

```python
"""ResearcherCrew — web research, summarization, Obsidian storage."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class ResearcherCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:26b",
                 fc_llm="ollama_chat/gemma4:e4b"):
        super().__init__("researcher", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "researcher", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=(
                f"{self.task_description}\n\n"
                "Speichere das Ergebnis in der Obsidian-Wissensbasis unter dem passenden Ordner."
            ),
            expected_output=self._task_configs["research_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 3: Implement WriterCrew**

Create `backend/crews/writer_crew.py`:

```python
"""WriterCrew — documentation, guides, text creation."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class WriterCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:26b",
                 fc_llm=None):
        super().__init__("writer", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "writer", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=self.task_description,
            expected_output=self._task_configs["writing_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 4: Implement OpsCrew**

Create `backend/crews/ops_crew.py`:

```python
"""OpsCrew — server management, deployment, system operations."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class OpsCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:e4b",
                 fc_llm=None):
        super().__init__("ops", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "ops", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=self.task_description,
            expected_output=self._task_configs["ops_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 5: Implement WebDesignCrew (2 agents)**

Create `backend/crews/web_design_crew.py`:

```python
"""WebDesignCrew — two agents: designer specs, coder implements."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class WebDesignCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:26b",
                 fc_llm="ollama_chat/gemma4:e4b"):
        super().__init__("web_design", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        designer = self._make_agent(
            "web_designer", self.llm_model, None, []
        )
        coder = self._make_agent(
            "web_coder", self.llm_model, self.fc_llm, self.tools
        )

        design_task = Task(
            description=(
                f"Design a web interface for: {self.task_description}\n\n"
                "Output a detailed spec: layout, colors, typography, components, responsive breakpoints."
            ),
            expected_output="A detailed web design specification with layout, colors, and component list.",
            agent=designer,
        )
        implement_task = Task(
            description=(
                "Implement the design from the previous task as HTML/CSS/JS. "
                "Use Tailwind CSS where appropriate. Write clean, production-ready code."
            ),
            expected_output=self._task_configs["code_task"]["expected_output"],
            agent=coder,
            context=[design_task],
        )

        return Crew(
            agents=[designer, coder],
            tasks=[design_task, implement_task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 6: Implement SwiftCrew**

Create `backend/crews/swift_crew.py`:

```python
"""SwiftCrew — SwiftUI app development for iOS/macOS."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class SwiftCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:26b",
                 fc_llm="ollama_chat/gemma4:e4b"):
        super().__init__("swift", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "swift_dev", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=self.task_description,
            expected_output=self._task_configs["code_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 7: Implement KIExpertCrew**

Create `backend/crews/ki_expert_crew.py`:

```python
"""KI-ExpertCrew — ML pipelines, model evaluation, prompt engineering."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class KIExpertCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:26b",
                 fc_llm="ollama_chat/gemma4:e4b"):
        super().__init__("ki_expert", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "ki_expert", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=self.task_description,
            expected_output=self._task_configs["research_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 8: Implement AnalystCrew**

Create `backend/crews/analyst_crew.py`:

```python
"""AnalystCrew — data analysis, visualization, reporting."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class AnalystCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="ollama_chat/gemma4:26b",
                 fc_llm="ollama_chat/gemma4:e4b"):
        super().__init__("analyst", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "analyst", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=self.task_description,
            expected_output=self._task_configs["analysis_task"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 9: Implement PremiumCrew**

Create `backend/crews/premium_crew.py`:

```python
"""PremiumCrew — uses Claude/Gemini API for complex tasks."""

from crewai import Task, Crew, Process

from backend.crews.base_crew import BaseFalkensteinCrew


class PremiumCrew(BaseFalkensteinCrew):
    def __init__(self, task_description: str, event_bus, chat_id=None,
                 vault_context="", tools=None,
                 llm_model="anthropic/claude-sonnet-4-20250514",
                 fc_llm=None):
        super().__init__("premium", task_description, event_bus, chat_id, vault_context)
        self.tools = tools or []
        self.llm_model = llm_model
        self.fc_llm = fc_llm

    def build_crew(self) -> Crew:
        agent = self._make_agent(
            "premium", self.llm_model, self.fc_llm, self.tools
        )
        task = Task(
            description=self.task_description,
            expected_output=self._task_configs["default"]["expected_output"],
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
            step_callback=self._step_callback,
        )
```

- [ ] **Step 10: Commit**

```bash
git add backend/crews/
git commit -m "feat: add 9 specialized CrewAI crews"
```

---

## Task 10: FalkensteinFlow

**Files:**
- Create: `backend/flow/falkenstein_flow.py`
- Test: `tests/test_flow.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_flow.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.flow.falkenstein_flow import FalkensteinFlow


@pytest.fixture
def flow_deps():
    return {
        "event_bus": AsyncMock(),
        "native_ollama": AsyncMock(),
        "vault_index": MagicMock(),
        "settings": MagicMock(),
        "tools": {},
    }


def test_flow_can_be_created(flow_deps):
    flow = FalkensteinFlow(**flow_deps)
    assert flow is not None


def test_flow_has_crew_registry(flow_deps):
    flow = FalkensteinFlow(**flow_deps)
    assert "coder" in flow.crew_registry
    assert "researcher" in flow.crew_registry
    assert "web_design" in flow.crew_registry
    assert "swift" in flow.crew_registry
    assert "ki_expert" in flow.crew_registry
    assert "analyst" in flow.crew_registry
    assert "writer" in flow.crew_registry
    assert "ops" in flow.crew_registry
    assert "premium" in flow.crew_registry


@pytest.mark.asyncio
async def test_flow_quick_reply(flow_deps):
    flow_deps["native_ollama"].quick_reply = AsyncMock(return_value="Hallo!")
    flow = FalkensteinFlow(**flow_deps)

    result = await flow.handle_message("Hallo!", chat_id="123")
    assert result == "Hallo!"
    flow_deps["native_ollama"].quick_reply.assert_called_once()


@pytest.mark.asyncio
async def test_flow_routes_to_crew_by_keyword(flow_deps):
    flow_deps["event_bus"].on_crew_start = AsyncMock(return_value="crew-1")
    flow = FalkensteinFlow(**flow_deps)

    with patch.object(flow, "_run_crew", new_callable=AsyncMock, return_value="Done"):
        result = await flow.handle_message(
            "Recherchiere CrewAI fuer mich", chat_id="123"
        )
    assert result == "Done"


@pytest.mark.asyncio
async def test_flow_classifies_when_no_keyword_match(flow_deps):
    flow_deps["native_ollama"].classify = AsyncMock(
        return_value={"crew_type": "coder", "task_description": "help", "priority": "normal"}
    )
    flow_deps["event_bus"].on_crew_start = AsyncMock(return_value="crew-1")
    flow = FalkensteinFlow(**flow_deps)

    with patch.object(flow, "_run_crew", new_callable=AsyncMock, return_value="Code done"):
        result = await flow.handle_message(
            "Kannst du mir bei meinem Projekt helfen?", chat_id="123"
        )

    flow_deps["native_ollama"].classify.assert_called_once()
    assert result == "Code done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_flow.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement FalkensteinFlow**

Create `backend/flow/falkenstein_flow.py`:

```python
"""FalkensteinFlow — main entry point replacing MainAgent."""

import logging
from backend.flow.rule_engine import RuleEngine
from backend.security.input_guard import InputGuard
from backend.prompt_consolidator import PromptConsolidator

from backend.crews.coder_crew import CoderCrew
from backend.crews.researcher_crew import ResearcherCrew
from backend.crews.writer_crew import WriterCrew
from backend.crews.ops_crew import OpsCrew
from backend.crews.web_design_crew import WebDesignCrew
from backend.crews.swift_crew import SwiftCrew
from backend.crews.ki_expert_crew import KIExpertCrew
from backend.crews.analyst_crew import AnalystCrew
from backend.crews.premium_crew import PremiumCrew

log = logging.getLogger(__name__)


CREW_CLASSES = {
    "coder": CoderCrew,
    "researcher": ResearcherCrew,
    "writer": WriterCrew,
    "ops": OpsCrew,
    "web_design": WebDesignCrew,
    "swift": SwiftCrew,
    "ki_expert": KIExpertCrew,
    "analyst": AnalystCrew,
    "premium": PremiumCrew,
}


class FalkensteinFlow:
    """Replaces MainAgent — routes messages to Crews via Rule-Engine + LLM classify."""

    def __init__(self, event_bus, native_ollama, vault_index, settings, tools: dict):
        self.event_bus = event_bus
        self.ollama = native_ollama
        self.vault_index = vault_index
        self.settings = settings
        self.tools = tools  # dict of crew_type -> list of CrewAI tool instances
        self.rule_engine = RuleEngine()
        self.input_guard = InputGuard()
        self.consolidator = PromptConsolidator()
        self.crew_registry = dict(CREW_CLASSES)

    async def handle_message(self, message: str, chat_id: str | None = None,
                             image_path: str | None = None) -> str:
        """Main entry point — replaces MainAgent.handle_message()."""

        # 1. Security check
        guard_result = self.input_guard.check_patterns(message)
        if guard_result.action == "BLOCK":
            return "Nachricht blockiert: Sicherheitsfilter."

        # 2. Consolidate (merge numbered lists, etc.)
        message = self.consolidator.consolidate(message)

        # 3. Rule-Engine: quick_reply / crew / classify
        route = self.rule_engine.route(message)

        if route.action == "quick_reply":
            vault_ctx = self.vault_index.as_context() if self.vault_index else ""
            return await self.ollama.quick_reply(message, context=vault_ctx)

        if route.action == "crew" and route.crew_type:
            crew_type = route.crew_type
        else:
            # LLM classify
            classification = await self.ollama.classify(message)
            crew_type = classification.get("crew_type", "coder")
            if classification.get("priority") == "premium":
                crew_type = "premium"

        log.info("Routing to crew: %s", crew_type)
        return await self._run_crew(crew_type, message, chat_id)

    async def _run_crew(self, crew_type: str, task_description: str,
                        chat_id: str | None) -> str:
        """Instantiate and run a crew."""
        crew_cls = self.crew_registry.get(crew_type)
        if not crew_cls:
            log.warning("Unknown crew type: %s, falling back to coder", crew_type)
            crew_cls = CoderCrew

        vault_ctx = self.vault_index.as_context() if self.vault_index else ""
        crew_tools = self.tools.get(crew_type, [])

        llm_model = f"ollama_chat/{self.settings.ollama_model}"
        fc_llm = f"ollama_chat/{self.settings.model_light}"

        # Ops uses light model for everything
        if crew_type == "ops":
            llm_model = fc_llm

        crew = crew_cls(
            task_description=task_description,
            event_bus=self.event_bus,
            chat_id=chat_id,
            vault_context=vault_ctx,
            tools=crew_tools,
            llm_model=llm_model,
            fc_llm=fc_llm if crew_type != "writer" else None,
        )

        return await crew.run()

    async def handle_scheduled(self, task: dict) -> str:
        """Handle a scheduled task — same as handle_message but with scheduler context."""
        description = task.get("prompt", task.get("title", ""))
        chat_id = task.get("chat_id")
        return await self.handle_message(description, chat_id=chat_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_flow.py -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/flow/falkenstein_flow.py tests/test_flow.py
git commit -m "feat: add FalkensteinFlow — main entry point replacing MainAgent"
```

---

## Task 11: Rewire main.py

**Files:**
- Modify: `backend/main.py`

This is the critical integration task — replacing MainAgent with FalkensteinFlow in the startup sequence.

- [ ] **Step 1: Add new imports to main.py**

Add at the top of `backend/main.py`:

```python
from backend.native_ollama import NativeOllamaClient
from backend.event_bus import FalkensteinEventBus
from backend.vault_index import VaultIndex
from backend.flow.falkenstein_flow import FalkensteinFlow
from backend.tools.crewai_wrappers import (
    CodeExecutorTool, ShellRunnerTool, SystemShellTool,
    ObsidianTool, OllamaManagerTool, SelfConfigTool, OpsExecutorTool,
)
```

- [ ] **Step 2: Replace startup sequence in lifespan**

Replace the MainAgent creation block in the `lifespan` function. Remove:
- `LLMClient` creation
- `LLMRouter` creation
- `ToolRegistry` creation with old tool registrations
- `MainAgent` creation
- `ReviewGate`, `IntentEngine` creation

Add instead:

```python
    # Native Ollama Client
    native_ollama = NativeOllamaClient(
        host=settings.ollama_host,
        model_light=settings.model_light,
        model_heavy=settings.model_heavy,
        keep_alive=settings.ollama_keep_alive,
    )

    # VaultIndex
    vault_index = None
    if settings.obsidian_vault_path:
        vault_index = VaultIndex(settings.obsidian_vault_path)
        vault_index.scan()

    # EventBus
    event_bus = FalkensteinEventBus(
        ws_manager=ws_manager,
        telegram_bot=telegram,
        db=db,
    )

    # CrewAI Tool instances (wrap existing tools)
    code_exec_tool = CodeExecutorTool()
    # ... set_executor for each tool from existing tool instances

    # Tool sets per crew type
    from crewai_tools import SerperDevTool, ScrapeWebsiteTool, FileReadTool, FileWriterTool
    crew_tools = {
        "coder": [code_exec_tool, ShellRunnerTool(), FileReadTool(), FileWriterTool()],
        "researcher": [SerperDevTool(), ScrapeWebsiteTool(), ObsidianTool()],
        "writer": [ObsidianTool(), FileReadTool(), FileWriterTool()],
        "ops": [OllamaManagerTool(), SelfConfigTool(), SystemShellTool()],
        "web_design": [FileReadTool(), FileWriterTool(), ScrapeWebsiteTool(), ShellRunnerTool()],
        "swift": [FileReadTool(), FileWriterTool(), ShellRunnerTool(), code_exec_tool],
        "ki_expert": [ShellRunnerTool(), code_exec_tool, SerperDevTool(), OllamaManagerTool()],
        "analyst": [code_exec_tool, FileReadTool()],
        "premium": [],  # gets all tools
    }

    # FalkensteinFlow (replaces MainAgent)
    flow = FalkensteinFlow(
        event_bus=event_bus,
        native_ollama=native_ollama,
        vault_index=vault_index,
        settings=settings,
        tools=crew_tools,
    )

    app.state.flow = flow
    app.state.event_bus = event_bus
```

- [ ] **Step 3: Update Telegram handler**

Replace `handle_telegram_message` to call flow instead of main_agent:

```python
async def handle_telegram_message(msg: dict):
    text = msg.get("text", "")
    chat_id = msg.get("chat_id", TELEGRAM_CHAT_ID)
    image_path = msg.get("image_path")

    if not text and not image_path:
        return

    flow = app.state.flow
    result = await flow.handle_message(text, chat_id=str(chat_id), image_path=image_path)
    # Result is already sent to Telegram by EventBus — no double-send needed
```

- [ ] **Step 4: Update API routes**

Replace `POST /api/task` handler:

```python
@app.post("/api/task")
async def create_task(request: Request):
    data = await request.json()
    description = data.get("description") or data.get("title", "")
    flow = app.state.flow
    result = await flow.handle_message(description)
    return {"status": "ok", "result": result}
```

- [ ] **Step 5: Update WebSocket handler**

Replace `submit_task` handling in the WS route:

```python
        elif msg_type == "submit_task":
            desc = data.get("description", "")
            flow = app.state.flow
            asyncio.create_task(flow.handle_message(desc))
```

- [ ] **Step 6: Update scheduler callbacks**

Replace `on_task_due` to call flow:

```python
async def on_task_due(task):
    flow = app.state.flow
    await flow.handle_scheduled(task)
```

- [ ] **Step 7: Test the server starts**

Run: `cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && timeout 10 python -m backend.main || true`
Expected: Server starts on port 8800 without import errors

- [ ] **Step 8: Commit**

```bash
git add backend/main.py
git commit -m "feat: rewire main.py — FalkensteinFlow replaces MainAgent"
```

---

## Task 12: Frontend Dashboard Updates

**Files:**
- Modify: `frontend/office/ws.js`
- Modify: `frontend/office/agents.js`

- [ ] **Step 1: Update ws.js to handle new event types**

Add handlers in `frontend/office/ws.js` for the new EventBus events:

```javascript
// Add to the message handler switch/if block:
case 'agent_spawn':
    onAgentSpawn(data.crew, data.crew_id, data.task);
    break;
case 'tool_use':
    onToolUse(data.agent, data.tool, data.animation, data.crew_id);
    break;
case 'agent_done':
    onAgentDone(data.crew, data.crew_id);
    break;
case 'agent_error':
    onAgentError(data.crew, data.crew_id, data.error);
    break;
```

- [ ] **Step 2: Update agents.js with crew-based animations**

Add to `frontend/office/agents.js`:

```javascript
const CREW_SKINS = {
    coder: 'Adam',
    researcher: 'Alex',
    writer: 'Amelia',
    ops: 'Bob',
    web_design: 'Adam',
    swift: 'Alex',
    ki_expert: 'Bob',
    analyst: 'Amelia',
    premium: 'Adam',
};

const ANIMATION_MAP = {
    typing: 'sit',     // sitting at desk, typing
    reading: 'phone',  // looking at screen
    thinking: 'idle_anim', // idle animation
    running: 'run',    // moving to desk
};

function onAgentSpawn(crewType, crewId, task) {
    const skin = CREW_SKINS[crewType] || 'Adam';
    // Create a new agent sprite at the crew's designated desk
    spawnAgent(crewId, skin, crewType, task);
}

function onToolUse(agentName, toolName, animation, crewId) {
    const anim = ANIMATION_MAP[animation] || 'idle_anim';
    setAgentAnimation(crewId, anim);
}

function onAgentDone(crewType, crewId) {
    // Play celebration animation, then remove after delay
    setAgentAnimation(crewId, 'idle_anim');
    setTimeout(() => removeAgent(crewId), 5000);
}

function onAgentError(crewType, crewId, error) {
    // Show error bubble, then remove
    showBubble(crewId, '❌ ' + error.substring(0, 50));
    setTimeout(() => removeAgent(crewId), 8000);
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/office/ws.js frontend/office/agents.js
git commit -m "feat: update dashboard for CrewAI event types"
```

---

## Task 13: Cleanup — Delete Old Files

**Files to delete** (all replaced by CrewAI equivalents):

- [ ] **Step 1: Remove old agent files**

```bash
git rm backend/main_agent.py
git rm backend/sub_agent.py
git rm backend/dynamic_agent.py
git rm backend/llm_client.py
git rm backend/llm_router.py
git rm backend/cli_llm_client.py
git rm backend/intent_engine.py
git rm backend/intent_prefilter.py
git rm backend/agent_identity.py
git rm backend/review_gate.py
git rm backend/output_router.py
git rm backend/prompts/classify.py
git rm backend/prompts/subagent.py
```

- [ ] **Step 2: Remove replaced tools**

```bash
git rm backend/tools/web_surfer.py
git rm backend/tools/file_manager.py
git rm backend/tools/vision.py
git rm backend/tools/cli_bridge.py
```

- [ ] **Step 3: Remove stale imports from remaining files**

Search all `.py` files for imports from deleted modules and remove them:

```bash
# Check for stale imports (informational — fix manually):
grep -rn "from backend.main_agent" backend/
grep -rn "from backend.sub_agent" backend/
grep -rn "from backend.dynamic_agent" backend/
grep -rn "from backend.llm_client" backend/
grep -rn "from backend.llm_router" backend/
grep -rn "from backend.cli_llm_client" backend/
grep -rn "from backend.intent_engine" backend/
grep -rn "from backend.review_gate" backend/
grep -rn "from backend.output_router" backend/
```

Fix each stale import found.

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Test server starts cleanly**

Run: `cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && timeout 10 python -m backend.main || true`
Expected: No import errors, server starts on port 8800

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove old agent system (MainAgent, SubAgent, DynamicAgent, LLMClient, LLMRouter)"
```

---

## Task 14: Integration Test — End-to-End

- [ ] **Step 1: Manual smoke test via API**

Start the server and test via curl:

```bash
# Quick reply
curl -X POST http://localhost:8800/api/task -H "Content-Type: application/json" \
  -d '{"description": "Hallo!"}'

# Crew dispatch (should hit researcher)
curl -X POST http://localhost:8800/api/task -H "Content-Type: application/json" \
  -d '{"description": "Recherchiere was CrewAI ist"}'

# Check active crews
curl http://localhost:8800/api/agents
```

- [ ] **Step 2: Verify WebSocket events in browser**

Open `http://localhost:8800/office` and trigger a task. Verify:
- Agent sprite appears when crew starts
- Animation changes during tool use
- Agent disappears/goes idle when crew finishes

- [ ] **Step 3: Verify Telegram (if configured)**

Send a message to the Telegram bot. Verify:
- Immediate acknowledgment message
- Streaming updates for web searches
- Final result message

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test: verify end-to-end CrewAI migration"
```

---

## Summary

| Task | Description | Estimated Steps |
|---|---|---|
| 1 | Dependencies & Config | 7 |
| 2 | NativeOllamaClient | 5 |
| 3 | Database Schema Migration | 7 |
| 4 | Rule Engine | 6 |
| 5 | EventBus | 5 |
| 6 | CrewAI Tool Wrappers | 5 |
| 7 | VaultIndex | 5 |
| 8 | YAML Config & Base Crew | 8 |
| 9 | Individual Crews (9 Crews) | 10 |
| 10 | FalkensteinFlow | 5 |
| 11 | Rewire main.py | 8 |
| 12 | Frontend Dashboard Updates | 3 |
| 13 | Cleanup — Delete Old Files | 6 |
| 14 | Integration Test | 4 |
| **Total** | | **84 Steps** |
