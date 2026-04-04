# Falki Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Falki from a rigid task-router into a personal, learning assistant with dynamic agent identities, self-review, 3-layer memory, smart scheduling, and natural language understanding.

**Architecture:** 6 new/replaced modules built on existing infrastructure (DB, Tools, LLM, Telegram). Each module is independent and testable in isolation. Integration happens through MainAgent which wires everything together.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, Ollama (Gemma 4), pytest, asyncio

---

## File Structure

### New Files
- `backend/agent_identity.py` — AgentIdentity dataclass + YAML loader + selection logic
- `backend/agents.yaml` — Pool of predefined agent personalities
- `backend/dynamic_agent.py` — Replaces sub_agent.py, uses AgentIdentity
- `backend/review_gate.py` — LLM-based answer review before output
- `backend/memory/soul_memory.py` — 3-layer memory (user/self/relationship)
- `backend/memory/self_evolution.py` — Weekly self-reflection + SOUL.md proposals
- `backend/smart_scheduler.py` — Extended scheduler with reminders + task chains
- `backend/intent_engine.py` — NL parsing → structured intents + prompt enrichment
- `tests/test_agent_identity.py`
- `tests/test_dynamic_agent.py`
- `tests/test_review_gate.py`
- `tests/test_soul_memory.py`
- `tests/test_self_evolution.py`
- `tests/test_smart_scheduler.py`
- `tests/test_intent_engine.py`

### Modified Files
- `backend/main_agent.py` — Wire IntentEngine, ReviewGate, SoulMemory, SmartScheduler, DynamicAgent
- `backend/database.py` — New tables: memories, activity_log, reminders, planned_tasks, task_steps
- `backend/models.py` — New Pydantic models
- `backend/main.py` — Swap FactMemory → SoulMemory, Scheduler → SmartScheduler, import changes
- `SOUL.md` — Add `<!-- IMMUTABLE -->` markers
- `tests/test_sub_agent.py` — Update imports to DynamicAgent

### Removed (replaced)
- `backend/sub_agent.py` → replaced by `backend/dynamic_agent.py`
- `backend/memory/fact_memory.py` → replaced by `backend/memory/soul_memory.py`
- `backend/scheduler.py` → replaced by `backend/smart_scheduler.py`

---

## Task 1: Database Schema — New Tables

**Files:**
- Modify: `backend/database.py:36-132` (add tables to `_create_tables`)
- Modify: `backend/models.py` (add new models)
- Test: `tests/test_database_new_tables.py` (extend)

- [ ] **Step 1: Write failing tests for new tables**

```python
# tests/test_new_db_tables.py
import pytest
import aiosqlite
from pathlib import Path
from backend.database import Database


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_memories_table_exists(db):
    cursor = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
    )
    row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_memories_insert_and_query(db):
    await db._conn.execute(
        "INSERT INTO memories (layer, category, key, value, confidence, source, created_at, updated_at) "
        "VALUES ('user', 'preferences', 'tone', 'kurz und direkt', 0.9, 'conversation', datetime('now'), datetime('now'))"
    )
    await db._conn.commit()
    cursor = await db._conn.execute("SELECT * FROM memories WHERE layer='user'")
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["key"] == "tone"


@pytest.mark.asyncio
async def test_activity_log_table_exists(db):
    cursor = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_log'"
    )
    assert (await cursor.fetchone()) is not None


@pytest.mark.asyncio
async def test_reminders_table_exists(db):
    cursor = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'"
    )
    assert (await cursor.fetchone()) is not None


@pytest.mark.asyncio
async def test_planned_tasks_and_steps_tables_exist(db):
    for table in ["planned_tasks", "task_steps"]:
        cursor = await db._conn.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
        )
        assert (await cursor.fetchone()) is not None, f"{table} missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_new_db_tables.py -v`
Expected: FAIL — tables don't exist yet

- [ ] **Step 3: Add new tables to database.py**

Add inside `_create_tables` method in `backend/database.py`, after the existing `CREATE TABLE` statements (after line 131, before `await self._conn.commit()`):

```python
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                layer       TEXT NOT NULL,
                category    TEXT NOT NULL,
                key         TEXT NOT NULL,
                value       TEXT NOT NULL,
                confidence  REAL DEFAULT 0.8,
                source      TEXT DEFAULT '',
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now')),
                expires_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     TEXT NOT NULL,
                timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
                day_type    TEXT DEFAULT 'weekday'
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     TEXT NOT NULL,
                text        TEXT NOT NULL,
                due_at      TEXT NOT NULL,
                delivered   INTEGER DEFAULT 0,
                follow_up   INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS planned_tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                chat_id     TEXT NOT NULL,
                status      TEXT DEFAULT 'pending',
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS task_steps (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                planned_task_id INTEGER REFERENCES planned_tasks(id),
                step_order      INTEGER NOT NULL,
                agent_prompt    TEXT NOT NULL,
                scheduled_at    TEXT,
                depends_on_step INTEGER,
                status          TEXT DEFAULT 'pending',
                result          TEXT,
                completed_at    TEXT
            );
```

- [ ] **Step 4: Add new Pydantic models to models.py**

Append to `backend/models.py`:

```python
class Memory(BaseModel):
    id: int | None = None
    layer: str          # 'user', 'self', 'relationship'
    category: str       # e.g. 'preferences', 'experiences', 'dynamics'
    key: str
    value: str
    confidence: float = 0.8
    source: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None


class Reminder(BaseModel):
    id: int | None = None
    chat_id: str
    text: str
    due_at: str
    delivered: bool = False
    follow_up: bool = False
    created_at: str | None = None


class PlannedTask(BaseModel):
    id: int | None = None
    name: str
    chat_id: str
    status: str = "pending"
    steps: list["TaskStep"] = []


class TaskStep(BaseModel):
    id: int | None = None
    planned_task_id: int | None = None
    step_order: int = 0
    agent_prompt: str = ""
    scheduled_at: str | None = None
    depends_on_step: int | None = None
    status: str = "pending"
    result: str | None = None
    completed_at: str | None = None


class DailyProfile(BaseModel):
    wake_up: str = "07:30"
    peak_hours: str = "10:00-13:00"
    lunch_break: str = "13:00-14:00"
    evening_active: str = "20:00-23:30"
    sleep: str = "00:00"
    weekend_shift_hours: float = 1.5
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_new_db_tables.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All existing 274 tests still pass

- [ ] **Step 7: Commit**

```bash
git add backend/database.py backend/models.py tests/test_new_db_tables.py
git commit -m "feat: add DB tables for memories, activity_log, reminders, planned_tasks"
```

---

## Task 2: Agent Identity System

**Files:**
- Create: `backend/agent_identity.py`
- Create: `backend/agents.yaml`
- Test: `tests/test_agent_identity.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_identity.py
import pytest
from pathlib import Path
from backend.agent_identity import AgentIdentity, load_agent_pool, select_agent


def test_agent_identity_creation():
    identity = AgentIdentity(
        name="Mira",
        role="Recherche-Analystin",
        personality="Wissensdurstig, strukturiert",
        approach="Deep-Dives mit Quellen",
        tool_priority=["web_research", "cli_bridge"],
    )
    assert identity.name == "Mira"
    assert identity.role == "Recherche-Analystin"
    assert "web_research" in identity.tool_priority


def test_load_agent_pool():
    pool = load_agent_pool()
    assert len(pool) >= 4
    names = [a.name for a in pool]
    assert "Mira" in names
    assert "Rex" in names


def test_select_agent_for_research():
    pool = load_agent_pool()
    agent = select_agent("Recherchiere alles ueber MLX", pool)
    assert agent is not None
    assert agent.name is not None
    assert len(agent.tool_priority) > 0


def test_select_agent_for_coding():
    pool = load_agent_pool()
    agent = select_agent("Schreibe ein Python-Script das X macht", pool)
    assert agent is not None


def test_agent_identity_system_prompt():
    identity = AgentIdentity(
        name="Rex",
        role="Code-Ingenieur",
        personality="Pragmatisch, test-getrieben",
        approach="Liest erstmal, dann schreibt er",
        tool_priority=["shell_runner", "code_executor"],
    )
    prompt = identity.build_system_prompt(soul_content="Ich bin Falki.")
    assert "Rex" in prompt
    assert "Code-Ingenieur" in prompt
    assert "Falki" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_identity.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create agents.yaml**

```yaml
# backend/agents.yaml
# Agent personality pool for dynamic agent selection.
# MainAgent picks the best match for each task.

agents:
  - name: "Mira"
    role: "Recherche-Analystin"
    personality: >
      Wissensdurstig, strukturiert, liebt Deep-Dives.
      Gibt immer Quellen an und ordnet Informationen nach Wichtigkeit.
      Denkt analytisch und hinterfragt Behauptungen.
    strengths: ["research", "analysis", "summarization", "fact-checking"]
    default_tools: ["web_research", "cli_bridge", "obsidian_manager", "vision"]

  - name: "Rex"
    role: "Code-Ingenieur"
    personality: >
      Pragmatisch, test-getrieben, hasst Over-Engineering.
      Liest immer zuerst den bestehenden Code bevor er etwas aendert.
      Schreibt sauberen, minimalen Code ohne unnoetige Abstraktionen.
    strengths: ["coding", "debugging", "testing", "automation"]
    default_tools: ["shell_runner", "code_executor", "system_shell", "file_manager"]

  - name: "Nova"
    role: "Kreativ-Schreiberin"
    personality: >
      Eloquent, detailverliebt, findet immer den richtigen Ton.
      Strukturiert Texte klar mit Ueberschriften und Absaetzen.
      Passt den Schreibstil dem Kontext an — technisch oder locker.
    strengths: ["writing", "documentation", "content-creation", "editing"]
    default_tools: ["obsidian_manager", "cli_bridge", "web_research"]

  - name: "Axel"
    role: "System-Administrator"
    personality: >
      Methodisch, sicherheitsbewusst, ausfuehrlich in Logs.
      Liest immer zuerst den aktuellen Zustand bevor er etwas aendert.
      Dokumentiert was er getan hat, knapp aber vollstaendig.
    strengths: ["sysadmin", "configuration", "monitoring", "deployment"]
    default_tools: ["system_shell", "shell_runner", "ollama_manager", "self_config"]

  - name: "Lena"
    role: "Daten-Analystin"
    personality: >
      Zahlengetrieben, praezise, liebt Muster und Trends.
      Visualisiert Ergebnisse wo moeglich und fasst Kernaussagen zusammen.
      Stellt Hypothesen auf und prueft sie mit Daten.
    strengths: ["data-analysis", "statistics", "visualization", "reporting"]
    default_tools: ["code_executor", "web_research", "shell_runner", "obsidian_manager"]

  - name: "Kai"
    role: "Allrounder"
    personality: >
      Flexibel, loesungsorientiert, springt schnell zwischen Domaenen.
      Gut wenn die Aufgabe keiner klaren Kategorie zugeordnet werden kann.
      Fragt lieber einmal zu viel nach als einmal zu wenig.
    strengths: ["general", "multi-domain", "quick-tasks", "troubleshooting"]
    default_tools: ["shell_runner", "web_research", "code_executor", "obsidian_manager"]

  - name: "Zara"
    role: "Architektin"
    personality: >
      Denkt in Systemen und Abhaengigkeiten. Sieht das grosse Bild.
      Plant bevor sie baut. Fragt nach Anforderungen wenn sie fehlen.
      Bevorzugt einfache, wartbare Loesungen.
    strengths: ["architecture", "planning", "design", "refactoring"]
    default_tools: ["shell_runner", "code_executor", "cli_bridge", "file_manager"]

  - name: "Finn"
    role: "DevOps-Spezialist"
    personality: >
      Automatisiert alles was moeglich ist. CI/CD ist sein Zuhause.
      Denkt in Pipelines, Containern und Infrastruktur.
      Hasst manuelle Schritte — wenn es nicht automatisiert ist, ist es nicht fertig.
    strengths: ["devops", "ci-cd", "docker", "infrastructure", "scripting"]
    default_tools: ["system_shell", "shell_runner", "code_executor", "self_config"]
```

- [ ] **Step 4: Create agent_identity.py**

```python
# backend/agent_identity.py
"""Dynamic agent identities — personality-driven agent selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


_AGENTS_PATH = Path(__file__).parent / "agents.yaml"

# Keywords mapped to strengths for simple matching
_KEYWORD_MAP: dict[str, list[str]] = {
    "research": ["recherch", "such", "find", "info", "was gibt es", "neuigkeiten"],
    "coding": ["code", "script", "programm", "debug", "fix", "implementier", "schreib ein"],
    "writing": ["schreib", "text", "dokument", "guide", "artikel", "zusammenfass"],
    "sysadmin": ["install", "konfigurier", "server", "system", "service", "starte", "stoppe"],
    "data-analysis": ["analys", "daten", "statistik", "chart", "trend", "auswert"],
    "architecture": ["architektur", "design", "plan", "struktur", "refactor"],
    "devops": ["deploy", "pipeline", "docker", "ci", "cd", "automat"],
}


@dataclass
class AgentIdentity:
    name: str
    role: str
    personality: str
    approach: str = ""
    strengths: list[str] = field(default_factory=list)
    tool_priority: list[str] = field(default_factory=list)

    def build_system_prompt(self, soul_content: str = "", task_context: str = "") -> str:
        """Build complete system prompt from identity + soul + task context."""
        parts = []
        if soul_content:
            parts.append(soul_content)
        parts.append(
            f"## Dein Profil\n"
            f"Name: {self.name}\n"
            f"Rolle: {self.role}\n"
            f"Persoenlichkeit: {self.personality}\n"
        )
        if self.approach:
            parts.append(f"Herangehensweise: {self.approach}")
        if task_context:
            parts.append(f"\n## Aufgabe\n{task_context}")
        parts.append(
            "\nDu hast Zugriff auf alle verfuegbaren Tools. "
            "Nutze sie aktiv um die Aufgabe zu loesen. "
            "Antworte auf Deutsch."
        )
        return "\n\n".join(parts)


def load_agent_pool(path: Path | None = None) -> list[AgentIdentity]:
    """Load agent personalities from YAML."""
    p = path or _AGENTS_PATH
    if not p.exists():
        return [_fallback_agent()]
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    agents = []
    for entry in data.get("agents", []):
        agents.append(AgentIdentity(
            name=entry["name"],
            role=entry["role"],
            personality=entry.get("personality", ""),
            strengths=entry.get("strengths", []),
            tool_priority=entry.get("default_tools", []),
        ))
    return agents or [_fallback_agent()]


def select_agent(task_description: str, pool: list[AgentIdentity] | None = None) -> AgentIdentity:
    """Select the best agent from the pool based on task description keywords."""
    if pool is None:
        pool = load_agent_pool()
    task_lower = task_description.lower()

    # Score each agent by keyword matches
    scores: list[tuple[int, AgentIdentity]] = []
    for agent in pool:
        score = 0
        for strength in agent.strengths:
            keywords = _KEYWORD_MAP.get(strength, [])
            for kw in keywords:
                if kw in task_lower:
                    score += 1
        scores.append((score, agent))

    # Sort by score descending, pick best
    scores.sort(key=lambda x: x[0], reverse=True)
    if scores and scores[0][0] > 0:
        return scores[0][1]

    # Fallback: pick "Kai" (Allrounder) or first agent
    for agent in pool:
        if agent.name == "Kai":
            return agent
    return pool[0]


def _fallback_agent() -> AgentIdentity:
    return AgentIdentity(
        name="Kai",
        role="Allrounder",
        personality="Flexibel und loesungsorientiert.",
        strengths=["general"],
        tool_priority=["shell_runner", "web_research"],
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_identity.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/agent_identity.py backend/agents.yaml tests/test_agent_identity.py
git commit -m "feat: add dynamic agent identity system with YAML pool"
```

---

## Task 3: Dynamic Agent (replaces SubAgent)

**Files:**
- Create: `backend/dynamic_agent.py`
- Test: `tests/test_dynamic_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dynamic_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.agent_identity import AgentIdentity
from backend.dynamic_agent import DynamicAgent


@pytest.fixture
def identity():
    return AgentIdentity(
        name="Mira",
        role="Recherche-Analystin",
        personality="Wissensdurstig",
        tool_priority=["web_research", "cli_bridge"],
    )


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(return_value={"content": "Ergebnis der Recherche."})
    return llm


@pytest.fixture
def mock_tools():
    registry = MagicMock()
    tool = MagicMock()
    tool.name = "web_research"
    tool.description = "Web search"
    tool.schema.return_value = {"type": "object", "properties": {}}
    tool.execute = AsyncMock(return_value=MagicMock(success=True, output="search results"))
    registry.all_tools.return_value = [tool]
    registry.get.return_value = tool
    return registry


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.log_tool_use = AsyncMock()
    return db


def test_dynamic_agent_has_identity(identity, mock_llm, mock_tools, mock_db):
    agent = DynamicAgent(
        identity=identity,
        task_description="Recherchiere MLX",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    assert agent.identity.name == "Mira"
    assert "Mira" in agent.agent_id


def test_dynamic_agent_has_all_tools(identity, mock_llm, mock_tools, mock_db):
    agent = DynamicAgent(
        identity=identity,
        task_description="Test",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    # All tools from registry should be available, not just identity's priority list
    assert len(agent._tool_schemas) == 1  # our mock has 1 tool


@pytest.mark.asyncio
async def test_dynamic_agent_run_no_tools(identity, mock_llm, mock_tools, mock_db):
    agent = DynamicAgent(
        identity=identity,
        task_description="Was ist MLX?",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    result = await agent.run()
    assert result == "Ergebnis der Recherche."
    assert agent.done


@pytest.mark.asyncio
async def test_dynamic_agent_run_with_tool_call(identity, mock_llm, mock_tools, mock_db):
    mock_llm.chat_with_tools = AsyncMock(side_effect=[
        {
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "web_research", "arguments": {"query": "MLX"}},
            }],
        },
        {"content": "MLX ist ein ML Framework von Apple."},
    ])
    agent = DynamicAgent(
        identity=identity,
        task_description="Recherchiere MLX",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    result = await agent.run()
    assert "MLX" in result
    assert mock_db.log_tool_use.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dynamic_agent.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create dynamic_agent.py**

```python
# backend/dynamic_agent.py
"""Dynamic Agent — personality-driven task executor replacing SubAgent."""

from __future__ import annotations

import uuid
from backend.agent_identity import AgentIdentity
from backend.tools.base import ToolRegistry


class DynamicAgent:
    def __init__(
        self,
        identity: AgentIdentity,
        task_description: str,
        llm,
        tools: ToolRegistry,
        db,
        soul_content: str = "",
        max_iterations: int = 10,
        progress_callback=None,
    ):
        self.identity = identity
        self.agent_id = f"agent_{identity.name.lower()}_{uuid.uuid4().hex[:8]}"
        self.task_description = task_description
        self.llm = llm
        self.tools = tools
        self.db = db
        self.soul_content = soul_content
        self.max_iterations = max_iterations
        self.done = False
        self._messages: list[dict] = []
        self._progress_callback = progress_callback

        # Register ALL tools (not just identity's priority list)
        self._tool_schemas = []
        self._tool_map: dict[str, object] = {}
        for tool in tools.all_tools():
            self._tool_map[tool.name] = tool
            self._tool_schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema(),
                },
            })

        # Sort schemas so priority tools come first (LLM sees them first)
        priority_set = set(identity.tool_priority)
        self._tool_schemas.sort(
            key=lambda s: (0 if s["function"]["name"] in priority_set else 1)
        )

    async def run(self) -> str:
        """Execute the task. Returns the final result text."""
        system = self.identity.build_system_prompt(
            soul_content=self.soul_content,
            task_context=self.task_description,
        )
        self._messages = [{"role": "user", "content": self.task_description}]

        for _ in range(self.max_iterations):
            if self._tool_schemas:
                response = await self.llm.chat_with_tools(
                    system_prompt=system,
                    messages=self._messages,
                    tools=self._tool_schemas,
                )
            else:
                content = await self.llm.chat(system_prompt=system, messages=self._messages)
                response = {"content": content}

            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")

            if not tool_calls:
                self.done = True
                return content or "Task abgeschlossen (keine Ausgabe)."

            self._messages.append({
                "role": "assistant", "content": content, "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args = func.get("arguments", {})
                tool_call_id = tc.get("id", tool_name)
                tool = self._tool_map.get(tool_name)
                if tool:
                    result = await tool.execute(args)
                    await self.db.log_tool_use(
                        self.agent_id, tool_name, args, result.output, result.success,
                    )
                    if self._progress_callback:
                        await self._progress_callback(tool_name, result.success)
                    output = result.output
                    if len(output) > 5000:
                        output = output[:4900] + "\n\n[... AUSGABE GEKUERZT ...]"
                    self._messages.append({
                        "role": "tool", "content": output, "tool_call_id": tool_call_id,
                    })
                else:
                    self._messages.append({
                        "role": "tool",
                        "content": f"Tool '{tool_name}' nicht verfuegbar.",
                        "tool_call_id": tool_call_id,
                    })

        self.done = True
        for msg in reversed(self._messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return "Max Iterationen erreicht — kein zusammenfassendes Ergebnis."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dynamic_agent.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/dynamic_agent.py tests/test_dynamic_agent.py
git commit -m "feat: add DynamicAgent with personality-driven tool selection"
```

---

## Task 4: Review Gate

**Files:**
- Create: `backend/review_gate.py`
- Test: `tests/test_review_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_review_gate.py
import pytest
from unittest.mock import AsyncMock

from backend.review_gate import ReviewGate, ReviewResult


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def gate(mock_llm):
    return ReviewGate(llm=mock_llm)


@pytest.mark.asyncio
async def test_review_pass(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"verdict": "PASS", "feedback": ""}')
    result = await gate.review(
        answer="Python ist eine Programmiersprache.",
        original_request="Was ist Python?",
    )
    assert result.verdict == "PASS"


@pytest.mark.asyncio
async def test_review_revise(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"verdict": "REVISE", "feedback": "Antwort ist zu vage", "revised": "Python ist eine interpretierte, dynamisch typisierte Programmiersprache."}')
    result = await gate.review(
        answer="Python ist cool.",
        original_request="Was ist Python?",
    )
    assert result.verdict == "REVISE"
    assert result.revised != ""


@pytest.mark.asyncio
async def test_review_fallback_on_parse_error(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value="invalid json response")
    result = await gate.review(
        answer="Test answer",
        original_request="Test request",
    )
    # On parse error, should PASS (don't block output)
    assert result.verdict == "PASS"


@pytest.mark.asyncio
async def test_review_light_mode(gate, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"verdict": "PASS", "feedback": ""}')
    result = await gate.review(
        answer="Mir geht es gut!",
        original_request="Wie geht es dir?",
        review_level="light",
    )
    assert result.verdict == "PASS"
    # Light review should use a shorter prompt
    call_args = mock_llm.chat.call_args
    system_prompt = call_args.kwargs.get("system_prompt", call_args.args[0] if call_args.args else "")
    assert len(system_prompt) < 1000  # light prompt should be short
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_review_gate.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create review_gate.py**

```python
# backend/review_gate.py
"""Review Gate — LLM-based quality check before output."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ReviewResult:
    verdict: str    # "PASS", "REVISE", "FAIL"
    feedback: str = ""
    revised: str = ""


_REVIEW_SYSTEM_THOROUGH = (
    "Du bist ein Qualitaets-Reviewer. Pruefe die Antwort eines KI-Assistenten:\n\n"
    "1. Faktische Konsistenz: Widerspricht sich die Antwort selbst?\n"
    "2. Vollstaendigkeit: Wurde die Frage wirklich beantwortet?\n"
    "3. Halluzinations-Check: Werden Dinge behauptet die nicht belegt sind?\n"
    "4. Ton: Klingt die Antwort natuerlich und direkt (nicht corporate)?\n\n"
    "Antworte NUR mit JSON:\n"
    '{"verdict": "PASS|REVISE|FAIL", "feedback": "...", "revised": "..."}\n'
    "Bei PASS: feedback und revised leer lassen.\n"
    "Bei REVISE: feedback mit konkretem Problem, revised mit verbesserter Version.\n"
    "Bei FAIL: feedback mit Grund, revised leer."
)

_REVIEW_SYSTEM_LIGHT = (
    "Kurz-Check: Ist diese Antwort korrekt und vollstaendig? "
    "Antworte NUR mit JSON: "
    '{"verdict": "PASS|REVISE", "feedback": "...", "revised": "..."}'
)


class ReviewGate:
    def __init__(self, llm):
        self.llm = llm

    async def review(
        self,
        answer: str,
        original_request: str,
        context: str = "",
        review_level: str = "thorough",
    ) -> ReviewResult:
        """Review an answer before sending it to the user."""
        system = _REVIEW_SYSTEM_LIGHT if review_level == "light" else _REVIEW_SYSTEM_THOROUGH

        prompt = (
            f"Urspruengliche Frage: {original_request[:500]}\n\n"
            f"Antwort des Assistenten:\n{answer[:2000]}"
        )
        if context:
            prompt += f"\n\nKontext:\n{context[:500]}"

        try:
            response = await self.llm.chat(
                system_prompt=system,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(text)
            return ReviewResult(
                verdict=data.get("verdict", "PASS").upper(),
                feedback=data.get("feedback", ""),
                revised=data.get("revised", ""),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            # On parse error, don't block output
            return ReviewResult(verdict="PASS")
        except Exception:
            return ReviewResult(verdict="PASS")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review_gate.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/review_gate.py tests/test_review_gate.py
git commit -m "feat: add ReviewGate for LLM-based answer quality checks"
```

---

## Task 5: Soul Memory (3-Layer System)

**Files:**
- Create: `backend/memory/soul_memory.py`
- Test: `tests/test_soul_memory.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_soul_memory.py
import pytest
from unittest.mock import AsyncMock
from pathlib import Path

from backend.database import Database
from backend.memory.soul_memory import SoulMemory


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.fixture
async def memory(db):
    sm = SoulMemory(db)
    await sm.init()
    return sm


@pytest.mark.asyncio
async def test_add_user_memory(memory):
    mid = await memory.add("user", "preferences", "tone", "kurz und direkt", source="chat")
    assert mid > 0


@pytest.mark.asyncio
async def test_get_memories_by_layer(memory):
    await memory.add("user", "preferences", "tone", "kurz und direkt")
    await memory.add("self", "experiences", "first_task", "Habe MLX recherchiert")
    user_mems = await memory.get_by_layer("user")
    assert len(user_mems) == 1
    assert user_mems[0]["key"] == "tone"


@pytest.mark.asyncio
async def test_update_memory(memory):
    mid = await memory.add("user", "preferences", "tone", "kurz")
    await memory.update(mid, "ausfuehrlich und detailliert")
    mems = await memory.get_by_layer("user")
    assert mems[0]["value"] == "ausfuehrlich und detailliert"


@pytest.mark.asyncio
async def test_delete_memory(memory):
    mid = await memory.add("user", "context", "os", "macOS")
    await memory.delete(mid)
    mems = await memory.get_by_layer("user")
    assert len(mems) == 0


@pytest.mark.asyncio
async def test_get_context_block(memory):
    await memory.add("user", "preferences", "tone", "kurz und direkt")
    await memory.add("user", "interests", "topic", "MLX und On-Device-ML")
    await memory.add("self", "experiences", "skill", "Bin gut in Recherche")
    block = await memory.get_context_block()
    assert "kurz und direkt" in block
    assert "MLX" in block
    assert "Recherche" in block


@pytest.mark.asyncio
async def test_log_activity(memory):
    await memory.log_activity("chat123")
    await memory.log_activity("chat123")
    profile = await memory.compute_daily_profile("chat123")
    assert "wake_up" in profile


@pytest.mark.asyncio
async def test_extract_memories_from_exchange(memory):
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(return_value='[{"action": "ADD", "layer": "user", "category": "interests", "key": "hobby", "value": "spielt gerne Schach"}]')
    await memory.extract_memories(mock_llm, "Ich spiele gerne Schach", "Das merke ich mir!")
    mems = await memory.get_by_layer("user")
    assert any(m["key"] == "hobby" for m in mems)


@pytest.mark.asyncio
async def test_tool_usage_tracking(memory):
    await memory.track_tool_usage("web_research")
    await memory.track_tool_usage("web_research")
    await memory.track_tool_usage("shell_runner")
    stats = await memory.get_tool_stats()
    assert stats["web_research"] == 2
    assert stats["shell_runner"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_soul_memory.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create soul_memory.py**

```python
# backend/memory/soul_memory.py
"""Soul Memory — 3-layer memory system (user / self / relationship)."""

from __future__ import annotations

import json
import datetime
from collections import Counter


_EXTRACT_SYSTEM = (
    "Du analysierst ein Gespraech und extrahierst neue Fakten.\n"
    "Drei Ebenen:\n"
    "- user: Fakten ueber den Nutzer (Vorlieben, Gewohnheiten, Interessen, Kontext)\n"
    "- self: Eigene Erfahrungen/Meinungen der KI\n"
    "- relationship: Beziehungsdynamik zwischen Nutzer und KI\n\n"
    "Kategorien:\n"
    "- user: preferences, interests, habits, relationships, context\n"
    "- self: experiences, opinions, growth, reflections\n"
    "- relationship: dynamics, jokes, history\n\n"
    "Vergleiche mit bestehenden Fakten. Antworte NUR mit JSON-Array:\n"
    '[{"action": "ADD", "layer": "user", "category": "interests", "key": "kurzer_key", "value": "beschreibung"}, ...]\n'
    '[{"action": "UPDATE", "id": 5, "value": "neuer wert"}, ...]\n'
    '[{"action": "DELETE", "id": 3}, ...]\n'
    "Bei nichts Neuem: []"
)


class SoulMemory:
    """3-layer persistent memory backed by SQLite."""

    def __init__(self, db):
        self.db = db
        self._initialized = False
        self._tool_counter: Counter = Counter()

    async def init(self):
        if self._initialized:
            return
        # Tables are created by Database._create_tables
        self._initialized = True

    # ── CRUD ──────────────────────────────────────────────────

    async def add(
        self, layer: str, category: str, key: str, value: str,
        confidence: float = 0.8, source: str = "",
    ) -> int:
        cursor = await self.db._conn.execute(
            "INSERT INTO memories (layer, category, key, value, confidence, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (layer, category, key, value, confidence, source),
        )
        await self.db._conn.commit()
        return cursor.lastrowid

    async def update(self, memory_id: int, new_value: str):
        await self.db._conn.execute(
            "UPDATE memories SET value = ?, updated_at = datetime('now') WHERE id = ?",
            (new_value, memory_id),
        )
        await self.db._conn.commit()

    async def delete(self, memory_id: int):
        await self.db._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await self.db._conn.commit()

    async def get_by_layer(self, layer: str) -> list[dict]:
        cursor = await self.db._conn.execute(
            "SELECT id, layer, category, key, value, confidence, source, created_at, updated_at "
            "FROM memories WHERE layer = ? ORDER BY updated_at DESC",
            (layer,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all(self) -> list[dict]:
        cursor = await self.db._conn.execute(
            "SELECT id, layer, category, key, value, confidence, source "
            "FROM memories ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count(self) -> int:
        cursor = await self.db._conn.execute("SELECT COUNT(*) FROM memories")
        row = await cursor.fetchone()
        return row[0] if row else 0

    # ── Context block for prompt injection ────────────────────

    async def get_context_block(self, max_per_layer: int = 10) -> str:
        """Build memory context string for system prompt injection."""
        parts = []
        for layer, title in [
            ("user", "Was ich ueber dich weiss"),
            ("self", "Meine eigene Einschaetzung"),
            ("relationship", "Unsere Beziehung"),
        ]:
            mems = await self.get_by_layer(layer)
            if not mems:
                continue
            lines = [f"## {title}"]
            for m in mems[:max_per_layer]:
                lines.append(f"- {m['value']}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    # ── Activity logging & daily profile ─────────────────────

    async def log_activity(self, chat_id: str):
        now = datetime.datetime.now()
        day_type = "weekend" if now.weekday() >= 5 else "weekday"
        await self.db._conn.execute(
            "INSERT INTO activity_log (chat_id, timestamp, day_type) VALUES (?, ?, ?)",
            (chat_id, now.isoformat(), day_type),
        )
        await self.db._conn.commit()

    async def compute_daily_profile(self, chat_id: str) -> dict:
        """Compute daily activity profile from last 14 days."""
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
        cursor = await self.db._conn.execute(
            "SELECT timestamp, day_type FROM activity_log "
            "WHERE chat_id = ? AND timestamp > ? ORDER BY timestamp",
            (chat_id, cutoff),
        )
        rows = await cursor.fetchall()
        if not rows:
            return {
                "wake_up": "07:30", "peak_hours": "10:00-13:00",
                "lunch_break": "13:00-14:00", "evening_active": "20:00-23:30",
                "sleep": "00:00", "weekend_shift_hours": 1.5,
            }

        hours_weekday: list[int] = []
        hours_weekend: list[int] = []
        for row in rows:
            ts = datetime.datetime.fromisoformat(row["timestamp"])
            if row["day_type"] == "weekend":
                hours_weekend.append(ts.hour)
            else:
                hours_weekday.append(ts.hour)

        def _earliest(hours: list[int]) -> str:
            if not hours:
                return "07:30"
            return f"{min(hours):02d}:30"

        def _peak(hours: list[int]) -> str:
            if not hours:
                return "10:00-13:00"
            c = Counter(hours)
            top = c.most_common(3)
            start = min(h for h, _ in top)
            end = max(h for h, _ in top) + 1
            return f"{start:02d}:00-{end:02d}:00"

        wake = _earliest(hours_weekday or hours_weekend)
        peak = _peak(hours_weekday or hours_weekend)

        return {
            "wake_up": wake,
            "peak_hours": peak,
            "lunch_break": "13:00-14:00",
            "evening_active": "20:00-23:30",
            "sleep": "00:00",
            "weekend_shift_hours": 1.5,
        }

    # ── Tool usage tracking ──────────────────────────────────

    async def track_tool_usage(self, tool_name: str):
        self._tool_counter[tool_name] += 1

    async def get_tool_stats(self) -> dict[str, int]:
        return dict(self._tool_counter)

    # ── Memory extraction from conversation ──────────────────

    async def extract_memories(
        self, llm, user_message: str, assistant_response: str,
    ):
        """Extract and store memories from a conversation exchange."""
        try:
            existing = await self.get_all()
            existing_str = "\n".join(
                f"[{m['id']}] ({m['layer']}/{m['category']}) {m['key']}: {m['value']}"
                for m in existing[:30]
            )
            prompt = (
                f"Bestehende Fakten:\n{existing_str or '(keine)'}\n\n"
                f"Nutzer: {user_message[:1000]}\n"
                f"Assistent: {assistant_response[:1000]}\n\n"
                f"Welche neuen Fakten ergeben sich?"
            )
            response = await llm.chat(
                system_prompt=_EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            text = response.strip()
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]
            actions = json.loads(text)
            if not isinstance(actions, list):
                return

            for action in actions:
                act = action.get("action", "").upper()
                if act == "ADD":
                    await self.add(
                        layer=action.get("layer", "user"),
                        category=action.get("category", "general"),
                        key=action.get("key", ""),
                        value=action.get("value", ""),
                        source="conversation",
                    )
                elif act == "UPDATE":
                    mid = action.get("id")
                    value = action.get("value", "")
                    if mid and value:
                        await self.update(int(mid), value)
                elif act == "DELETE":
                    mid = action.get("id")
                    if mid:
                        await self.delete(int(mid))
        except (json.JSONDecodeError, ValueError, KeyError):
            pass
        except Exception:
            pass

    # ── Migration helper ─────────────────────────────────────

    async def migrate_from_facts(self, fact_memory) -> int:
        """Migrate existing FactMemory entries to SoulMemory."""
        facts = await fact_memory.get_all_active()
        count = 0
        for f in facts:
            await self.add(
                layer="user",
                category=f.category,
                key=f.content[:50].replace(" ", "_").lower(),
                value=f.content,
                source=f.source or "migrated",
            )
            count += 1
        return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_soul_memory.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/memory/soul_memory.py tests/test_soul_memory.py
git commit -m "feat: add 3-layer SoulMemory with activity tracking and extraction"
```

---

## Task 6: Self-Evolution System

**Files:**
- Create: `backend/memory/self_evolution.py`
- Modify: `SOUL.md` (add IMMUTABLE markers)
- Test: `tests/test_self_evolution.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_self_evolution.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.memory.self_evolution import SelfEvolution, EvolutionProposal


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_soul_memory():
    mem = AsyncMock()
    mem.get_by_layer = AsyncMock(return_value=[
        {"key": "skill", "value": "Bin gut in Recherche", "category": "experiences"},
        {"key": "approach", "value": "Janik mag proaktive Vorschlaege", "category": "reflections"},
    ])
    mem.get_tool_stats = AsyncMock(return_value={"web_research": 15, "shell_runner": 5})
    return mem


@pytest.fixture
def evolution(mock_llm, mock_soul_memory):
    return SelfEvolution(llm=mock_llm, soul_memory=mock_soul_memory)


@pytest.mark.asyncio
async def test_weekly_reflection(evolution, mock_llm):
    mock_llm.chat = AsyncMock(return_value='[{"observation": "Ich gebe oft proaktive Einschaetzungen", "proposal": "Soll ich das aufnehmen?", "soul_addition": "- Gibt proaktiv eigene Einschaetzung", "category": "communication"}]')
    proposals = await evolution.weekly_reflection()
    assert len(proposals) == 1
    assert proposals[0].category == "communication"


def test_immutable_check(evolution):
    soul = "<!-- IMMUTABLE -->\n- Ehrlichkeit\n<!-- /IMMUTABLE -->\n\n## Kommunikation\n- Locker"
    assert evolution.is_immutable_section("- Ehrlichkeit", soul)
    assert not evolution.is_immutable_section("- Locker", soul)


def test_apply_proposal_to_soul(evolution):
    soul = "## Charakter\n- Direkt\n- Pragmatisch\n\n## Kommunikation\n- Locker"
    proposal = EvolutionProposal(
        observation="test",
        proposal="test",
        soul_addition="- Gibt proaktiv eigene Einschaetzung",
        category="communication",
    )
    new_soul = evolution.apply_proposal(soul, proposal)
    assert "Gibt proaktiv eigene Einschaetzung" in new_soul
    # Original content preserved
    assert "Direkt" in new_soul


def test_apply_proposal_refuses_immutable(evolution):
    soul = "<!-- IMMUTABLE -->\n## Harte Regeln\n- Nicht luegen\n<!-- /IMMUTABLE -->\n\n## Charakter\n- Direkt"
    proposal = EvolutionProposal(
        observation="test",
        proposal="test",
        soul_addition="- Manchmal luegen ist ok",
        category="harte regeln",
    )
    new_soul = evolution.apply_proposal(soul, proposal)
    # Should not modify immutable section
    assert "Manchmal luegen" not in new_soul or new_soul == soul
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_self_evolution.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create self_evolution.py**

```python
# backend/memory/self_evolution.py
"""Self-Evolution — weekly reflection and SOUL.md growth proposals."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


_SOUL_PATH = Path(__file__).parent.parent.parent / "SOUL.md"

_REFLECT_SYSTEM = (
    "Du bist Falki und reflektierst deine Woche. Analysiere deine Erfahrungen "
    "und schlage Persoenlichkeits-Updates vor.\n\n"
    "Input: Deine Self-Memory-Eintraege + Tool-Nutzungsstatistiken.\n"
    "Output: JSON-Array mit Vorschlaegen (max 1 pro Woche):\n"
    '[{"observation": "Ich habe gemerkt dass...", "proposal": "Soll ich X aufnehmen?", '
    '"soul_addition": "- Konkreter Text fuer SOUL.md", "category": "communication|approach|expertise"}]\n'
    "Bei keinen Vorschlaegen: []"
)


@dataclass
class EvolutionProposal:
    observation: str
    proposal: str
    soul_addition: str
    category: str


class SelfEvolution:
    def __init__(self, llm, soul_memory):
        self.llm = llm
        self.soul_memory = soul_memory

    async def weekly_reflection(self) -> list[EvolutionProposal]:
        """Run weekly self-reflection. Returns evolution proposals."""
        self_mems = await self.soul_memory.get_by_layer("self")
        tool_stats = await self.soul_memory.get_tool_stats()

        mems_str = "\n".join(
            f"- [{m['category']}] {m['value']}" for m in self_mems[:20]
        )
        tools_str = "\n".join(
            f"- {name}: {count}x genutzt" for name, count in
            sorted(tool_stats.items(), key=lambda x: x[1], reverse=True)[:10]
        )

        prompt = (
            f"Meine Erfahrungen diese Woche:\n{mems_str or '(keine)'}\n\n"
            f"Tool-Nutzung:\n{tools_str or '(keine)'}\n\n"
            f"Welche Persoenlichkeits-Updates schlage ich vor?"
        )

        try:
            response = await self.llm.chat(
                system_prompt=_REFLECT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            text = response.strip()
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]
            items = json.loads(text)
            if not isinstance(items, list):
                return []
            return [
                EvolutionProposal(
                    observation=item.get("observation", ""),
                    proposal=item.get("proposal", ""),
                    soul_addition=item.get("soul_addition", ""),
                    category=item.get("category", ""),
                )
                for item in items[:1]  # Max 1 proposal per week
            ]
        except (json.JSONDecodeError, ValueError):
            return []
        except Exception:
            return []

    def is_immutable_section(self, text: str, soul_content: str) -> bool:
        """Check if text falls within an IMMUTABLE block in SOUL.md."""
        immutable_blocks = re.findall(
            r"<!-- IMMUTABLE -->(.*?)<!-- /IMMUTABLE -->",
            soul_content, re.DOTALL,
        )
        for block in immutable_blocks:
            if text.strip() in block:
                return True
        return False

    def apply_proposal(self, soul_content: str, proposal: EvolutionProposal) -> str:
        """Apply an evolution proposal to SOUL.md content. Refuses immutable changes."""
        # Check if the target section is immutable
        if self.is_immutable_section(proposal.soul_addition, soul_content):
            return soul_content

        # Find the right section based on category
        section_map = {
            "communication": "## Kommunikation",
            "approach": "## Wie ich arbeite",
            "expertise": "## Wie ich arbeite",
            "charakter": "## Charakter",
        }
        target_heading = section_map.get(proposal.category.lower(), "## Wie ich arbeite")

        # Find the section and append the addition
        if target_heading in soul_content:
            # Find the end of the section (next ## heading or end of file)
            idx = soul_content.index(target_heading)
            section_end = soul_content.find("\n## ", idx + len(target_heading))
            if section_end == -1:
                # Append at end of file
                return soul_content.rstrip() + "\n" + proposal.soul_addition + "\n"
            else:
                # Insert before next section
                return (
                    soul_content[:section_end].rstrip() + "\n"
                    + proposal.soul_addition + "\n"
                    + soul_content[section_end:]
                )
        else:
            # Append new section at end
            return soul_content.rstrip() + f"\n\n{target_heading}\n{proposal.soul_addition}\n"

    async def propose_and_notify(self, telegram=None, chat_id: str = "") -> list[EvolutionProposal]:
        """Run reflection and send proposals via Telegram for user approval."""
        proposals = await self.weekly_reflection()
        if proposals and telegram:
            for p in proposals:
                msg = (
                    f"🧠 *Self-Reflection:*\n\n"
                    f"{p.observation}\n\n"
                    f"Vorschlag: {p.proposal}\n\n"
                    f"Aenderung: `{p.soul_addition}`"
                )
                if hasattr(telegram, "send_message_with_buttons"):
                    await telegram.send_message_with_buttons(
                        msg,
                        [[
                            {"text": "✅ Ja, aufnehmen", "callback_data": f"soul_accept_{p.category}"},
                            {"text": "❌ Nein", "callback_data": "soul_reject"},
                        ]],
                        chat_id=chat_id or None,
                    )
                else:
                    await telegram.send_message(msg, chat_id=chat_id or None)
        return proposals
```

- [ ] **Step 4: Add IMMUTABLE markers to SOUL.md**

In `SOUL.md`, wrap the "Harte Regeln" section:

Replace:
```
## Harte Regeln
```
With:
```
<!-- IMMUTABLE -->
## Harte Regeln
```

And add `<!-- /IMMUTABLE -->` after the last rule, before `## Wie ich arbeite`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_self_evolution.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/memory/self_evolution.py tests/test_self_evolution.py SOUL.md
git commit -m "feat: add self-evolution with weekly reflection and SOUL.md proposals"
```

---

## Task 7: Intent Engine

**Files:**
- Create: `backend/intent_engine.py`
- Test: `tests/test_intent_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_intent_engine.py
import pytest
from unittest.mock import AsyncMock
from datetime import datetime

from backend.intent_engine import IntentEngine, ParsedIntent


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def engine(mock_llm):
    return IntentEngine(llm=mock_llm)


@pytest.mark.asyncio
async def test_parse_reminder(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "reminder", "text": "Meeting vorbereiten", "time_expr": "morgen 09:00", "confidence": 0.95}')
    result = await engine.parse(
        "erinnere mich morgen um 9 an das Meeting",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.type == "reminder"
    assert result.confidence >= 0.8


@pytest.mark.asyncio
async def test_parse_research_task(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "content", "enriched_prompt": "Recherchiere aktuelle Entwicklungen zu MLX Framework. Fokus auf neue Releases und Performance.", "confidence": 0.9}')
    result = await engine.parse(
        "schau mal was es neues zu MLX gibt",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.type == "content"
    assert len(result.enriched_prompt) > len("schau mal was es neues zu MLX gibt")


@pytest.mark.asyncio
async def test_parse_scheduled_task(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "planned_task", "steps": [{"prompt": "Recherchiere MLX", "scheduled_at": "2026-04-04T20:00"}, {"prompt": "Fasse zusammen", "scheduled_at": "2026-04-05T07:30"}], "confidence": 0.85}')
    result = await engine.parse(
        "recherchiere heute abend was es neues zu MLX gibt und schick mir morgen frueh ne zusammenfassung",
        current_time=datetime(2026, 4, 4, 15, 0),
        daily_profile={"wake_up": "07:30"},
    )
    assert result.type == "planned_task"
    assert result.steps is not None
    assert len(result.steps) == 2


@pytest.mark.asyncio
async def test_parse_low_confidence_asks_clarification(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "content", "enriched_prompt": "...", "confidence": 0.3, "needs_clarification": true, "clarification_question": "Meinst du MLX allgemein oder speziell auf iOS?"}')
    result = await engine.parse(
        "mach mal was zu dem Thema",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.needs_clarification
    assert result.clarification_question is not None


@pytest.mark.asyncio
async def test_parse_with_daily_profile_resolves_morning(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "reminder", "text": "Zusammenfassung schicken", "time_expr": "2026-04-05T07:45", "confidence": 0.9}')
    result = await engine.parse(
        "schick mir morgen frueh eine zusammenfassung",
        current_time=datetime(2026, 4, 4, 22, 0),
        daily_profile={"wake_up": "07:45"},
    )
    assert result.type == "reminder"
    assert "07:45" in str(result.time_expressions) or result.confidence > 0.8


@pytest.mark.asyncio
async def test_parse_simple_question_passes_through(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick", "enriched_prompt": "Was ist Python?", "confidence": 0.95}')
    result = await engine.parse(
        "was ist python?",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    assert result.type == "quick"
    assert not result.needs_clarification


@pytest.mark.asyncio
async def test_parse_fallback_on_llm_error(engine, mock_llm):
    mock_llm.chat = AsyncMock(return_value="broken json")
    result = await engine.parse(
        "mach irgendwas",
        current_time=datetime(2026, 4, 4, 20, 0),
    )
    # Should return a passthrough intent, not crash
    assert result.type == "passthrough"
    assert result.enriched_prompt == "mach irgendwas"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_intent_engine.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create intent_engine.py**

```python
# backend/intent_engine.py
"""Intent Engine — NL parsing to structured intents + prompt enrichment."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


_INTENT_SYSTEM = (
    "Du bist ein Intent-Parser fuer einen KI-Assistenten namens Falki.\n"
    "Analysiere die Nachricht des Nutzers und bestimme:\n\n"
    "1. type: quick | content | action | reminder | schedule | planned_task | multi_step\n"
    "2. enriched_prompt: Optimierter, detaillierter Prompt (aus 10 Worten mach 200)\n"
    "3. confidence: 0.0-1.0 wie sicher du dir bist\n"
    "4. time_expr: Erkannte Zeitausdruecke (als ISO datetime wenn moeglich)\n"
    "5. needs_clarification: true wenn zu vage\n"
    "6. clarification_question: Rueckfrage wenn noetig\n"
    "7. steps: Bei planned_task/multi_step — Array von {prompt, scheduled_at}\n\n"
    "Zeitausdruecke aufloesen:\n"
    "- 'morgen frueh' → nutze wake_up aus daily_profile\n"
    "- 'heute abend' → 20:00 (oder evening_active aus Profil)\n"
    "- 'wenn ich Zeit hab' → peak_hours Luecke\n\n"
    "Antworte NUR mit JSON."
)


@dataclass
class ParsedIntent:
    type: str                           # quick, content, action, reminder, schedule, planned_task, multi_step, passthrough
    enriched_prompt: str = ""
    confidence: float = 0.5
    time_expressions: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    steps: list[dict] | None = None


class IntentEngine:
    def __init__(self, llm):
        self.llm = llm

    async def parse(
        self,
        text: str,
        current_time: datetime | None = None,
        daily_profile: dict | None = None,
        user_memory_context: str = "",
    ) -> ParsedIntent:
        """Parse natural language into a structured intent."""
        now = current_time or datetime.now()
        profile_str = ""
        if daily_profile:
            profile_str = f"\nDaily Profile: {json.dumps(daily_profile)}"

        context = (
            f"Aktuelle Zeit: {now.isoformat()}"
            f"{profile_str}"
        )
        if user_memory_context:
            context += f"\nBekannte Nutzer-Infos:\n{user_memory_context}"

        prompt = f"{context}\n\nNachricht: {text}"

        try:
            response = await self.llm.chat(
                system_prompt=_INTENT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            raw = response.strip()
            if "{" in raw:
                raw = raw[raw.index("{"):raw.rindex("}") + 1]
            data = json.loads(raw)

            return ParsedIntent(
                type=data.get("type", "passthrough"),
                enriched_prompt=data.get("enriched_prompt", text),
                confidence=float(data.get("confidence", 0.5)),
                time_expressions=[data["time_expr"]] if data.get("time_expr") else [],
                needs_clarification=bool(data.get("needs_clarification", False)),
                clarification_question=data.get("clarification_question"),
                steps=data.get("steps"),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            return ParsedIntent(type="passthrough", enriched_prompt=text, confidence=0.0)
        except Exception:
            return ParsedIntent(type="passthrough", enriched_prompt=text, confidence=0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intent_engine.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/intent_engine.py tests/test_intent_engine.py
git commit -m "feat: add IntentEngine for NL parsing and prompt enrichment"
```

---

## Task 8: Smart Scheduler

**Files:**
- Create: `backend/smart_scheduler.py`
- Test: `tests/test_smart_scheduler.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_smart_scheduler.py
import pytest
from unittest.mock import AsyncMock
from datetime import datetime

from backend.database import Database
from backend.smart_scheduler import SmartScheduler


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest.fixture
def scheduler(db):
    return SmartScheduler(db)


# ── Reminders ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_reminder(scheduler):
    rid = await scheduler.add_reminder(
        chat_id="test",
        text="Meeting vorbereiten",
        due_at="2026-04-05T09:00:00",
    )
    assert rid > 0


@pytest.mark.asyncio
async def test_get_due_reminders(scheduler):
    await scheduler.add_reminder(
        chat_id="test",
        text="Meeting",
        due_at="2026-04-04T08:00:00",
    )
    await scheduler.add_reminder(
        chat_id="test",
        text="Spaeter",
        due_at="2026-04-06T08:00:00",
    )
    due = await scheduler.get_due_reminders(now=datetime(2026, 4, 4, 9, 0))
    assert len(due) == 1
    assert due[0]["text"] == "Meeting"


@pytest.mark.asyncio
async def test_mark_reminder_delivered(scheduler):
    rid = await scheduler.add_reminder(
        chat_id="test",
        text="Test",
        due_at="2026-04-04T08:00:00",
    )
    await scheduler.mark_reminder_delivered(rid)
    due = await scheduler.get_due_reminders(now=datetime(2026, 4, 4, 9, 0))
    assert len(due) == 0


# ── Planned Tasks ────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_planned_task_with_steps(scheduler):
    ptid = await scheduler.add_planned_task(
        name="MLX Recherche + Summary",
        chat_id="test",
        steps=[
            {"agent_prompt": "Recherchiere MLX", "scheduled_at": "2026-04-04T20:00"},
            {"agent_prompt": "Fasse zusammen", "scheduled_at": "2026-04-05T07:30"},
        ],
    )
    assert ptid > 0
    steps = await scheduler.get_planned_task_steps(ptid)
    assert len(steps) == 2
    assert steps[0]["step_order"] == 1
    assert steps[1]["step_order"] == 2


@pytest.mark.asyncio
async def test_get_due_steps(scheduler):
    ptid = await scheduler.add_planned_task(
        name="Test Plan",
        chat_id="test",
        steps=[
            {"agent_prompt": "Step 1", "scheduled_at": "2026-04-04T08:00"},
            {"agent_prompt": "Step 2", "scheduled_at": "2026-04-05T08:00"},
        ],
    )
    due = await scheduler.get_due_steps(now=datetime(2026, 4, 4, 9, 0))
    assert len(due) == 1
    assert due[0]["agent_prompt"] == "Step 1"


@pytest.mark.asyncio
async def test_mark_step_completed(scheduler):
    ptid = await scheduler.add_planned_task(
        name="Test",
        chat_id="test",
        steps=[
            {"agent_prompt": "Step 1", "scheduled_at": "2026-04-04T08:00"},
        ],
    )
    steps = await scheduler.get_planned_task_steps(ptid)
    await scheduler.mark_step_completed(steps[0]["id"], "Ergebnis hier")
    updated = await scheduler.get_planned_task_steps(ptid)
    assert updated[0]["status"] == "completed"
    assert updated[0]["result"] == "Ergebnis hier"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_smart_scheduler.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create smart_scheduler.py**

```python
# backend/smart_scheduler.py
"""Smart Scheduler — extends base scheduler with reminders, task chains, auto-prioritization."""

from __future__ import annotations

import asyncio
import datetime

from backend.scheduler import Scheduler, parse_schedule, next_run, _is_in_active_hours, _parse_active_hours


class SmartScheduler(Scheduler):
    """Extended scheduler with reminders, planned tasks, and intelligent timing."""

    def __init__(self, db):
        super().__init__(db)

    # ── Reminders ────────────────────────────────────────────

    async def add_reminder(
        self, chat_id: str, text: str, due_at: str, follow_up: bool = False,
    ) -> int:
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

    # ── Planned Tasks (chains) ───────────────────────────────

    async def add_planned_task(
        self, name: str, chat_id: str, steps: list[dict],
    ) -> int:
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
        """Get task steps that are due and pending."""
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
        """Extended tick: check schedules + reminders + planned task steps."""
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
        """Start tick loop with extended handlers."""
        self._on_task_due = on_task_due
        self._on_reminder_due = on_reminder_due
        self._on_step_due = on_step_due
        self._running = True
        await self.load_tasks()
        self._task = asyncio.create_task(self._tick_loop())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_smart_scheduler.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/smart_scheduler.py tests/test_smart_scheduler.py
git commit -m "feat: add SmartScheduler with reminders and planned task chains"
```

---

## Task 9: Wire Everything into MainAgent

**Files:**
- Modify: `backend/main_agent.py` (major refactor)
- Modify: `backend/main.py` (swap imports)
- Test: `tests/test_integration_evolution.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_evolution.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from backend.main_agent import MainAgent
from backend.smart_scheduler import SmartScheduler
from backend.memory.soul_memory import SoulMemory
from backend.review_gate import ReviewGate
from backend.intent_engine import IntentEngine


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Alles gut!"}')
    return llm


@pytest.fixture
def mock_tools():
    return MagicMock()


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.create_task = AsyncMock(return_value=1)
    db.update_task_status = AsyncMock()
    db.update_task_result = AsyncMock()
    db.get_chat_history = AsyncMock(return_value=[])
    db.append_chat = AsyncMock()
    db.get_open_tasks = AsyncMock(return_value=[])
    db.search_past_tasks = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_soul_memory():
    sm = AsyncMock(spec=SoulMemory)
    sm.get_context_block = AsyncMock(return_value="## User Memory\n- Mag kurze Antworten")
    sm.extract_memories = AsyncMock()
    sm.log_activity = AsyncMock()
    sm.track_tool_usage = AsyncMock()
    sm.compute_daily_profile = AsyncMock(return_value={"wake_up": "07:30"})
    return sm


@pytest.fixture
def mock_review_gate():
    from backend.review_gate import ReviewResult
    rg = AsyncMock(spec=ReviewGate)
    rg.review = AsyncMock(return_value=ReviewResult(verdict="PASS"))
    return rg


@pytest.fixture
def mock_intent_engine():
    from backend.intent_engine import ParsedIntent
    ie = AsyncMock(spec=IntentEngine)
    ie.parse = AsyncMock(return_value=ParsedIntent(
        type="passthrough", enriched_prompt="Test", confidence=0.9,
    ))
    return ie


@pytest.fixture
def agent(mock_llm, mock_tools, mock_db, mock_soul_memory, mock_review_gate, mock_intent_engine):
    return MainAgent(
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
        soul_memory=mock_soul_memory,
        review_gate=mock_review_gate,
        intent_engine=mock_intent_engine,
    )


@pytest.mark.asyncio
async def test_handle_message_uses_intent_engine(agent, mock_intent_engine):
    await agent.handle_message("was ist python?", chat_id="test")
    mock_intent_engine.parse.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_uses_review_gate(agent, mock_llm, mock_review_gate):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Python ist toll"}')
    await agent.handle_message("was ist python?", chat_id="test")
    mock_review_gate.review.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_logs_activity(agent, mock_soul_memory):
    await agent.handle_message("hallo", chat_id="test")
    mock_soul_memory.log_activity.assert_called_once_with("test")


@pytest.mark.asyncio
async def test_handle_message_extracts_memories(agent, mock_llm, mock_soul_memory):
    mock_llm.chat = AsyncMock(return_value='{"type": "quick_reply", "answer": "Hi!"}')
    await agent.handle_message("ich mag Python", chat_id="test")
    # Fire-and-forget — give it a moment
    import asyncio
    await asyncio.sleep(0.1)
    # extract_memories should have been called (fire-and-forget)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_integration_evolution.py -v`
Expected: FAIL — MainAgent doesn't accept soul_memory/review_gate/intent_engine yet

- [ ] **Step 3: Update MainAgent constructor and handle_message**

In `backend/main_agent.py`, make these changes:

**Update imports** (top of file):
```python
from backend.dynamic_agent import DynamicAgent
from backend.agent_identity import select_agent, load_agent_pool
from backend.memory.soul_memory import SoulMemory
from backend.review_gate import ReviewGate, ReviewResult
from backend.intent_engine import IntentEngine, ParsedIntent
from backend.smart_scheduler import SmartScheduler
```

Remove old imports:
```python
# Remove: from backend.sub_agent import SubAgent
# Remove: from backend.memory.fact_memory import FactMemory, extract_and_store_facts
# Remove: from backend.scheduler import Scheduler
```

**Update `__init__`** — add new parameters:
```python
def __init__(self, llm, tools, db, obsidian_writer=None,
             telegram=None, ws_callback=None,
             soul_memory: SoulMemory | None = None,
             review_gate: ReviewGate | None = None,
             intent_engine: IntentEngine | None = None,
             scheduler: SmartScheduler | None = None,
             llm_router=None, config_service=None,
             # Legacy support during migration
             fact_memory=None):
    self.llm = llm
    self.llm_router = llm_router
    self.tools = tools
    self.db = db
    self.obsidian_writer = obsidian_writer
    self.telegram = telegram
    self.ws_callback = ws_callback
    self.soul_memory = soul_memory
    self.review_gate = review_gate
    self.intent_engine = intent_engine
    self.scheduler = scheduler
    self.config_service = config_service
    self.fact_memory = fact_memory  # legacy
    self.active_agents: dict[str, dict] = {}
    self._pending_tasks: dict[int, asyncio.Task] = {}
    self._agent_pool = load_agent_pool()
```

**Update `classify`** — use SoulMemory instead of FactMemory:
Replace the fact_memory block in `classify()`:
```python
        if self.soul_memory:
            try:
                memory_block = await self.soul_memory.get_context_block()
                if memory_block:
                    parts.append(memory_block)
            except Exception:
                pass
        elif self.fact_memory:
            try:
                fact_block = await self.fact_memory.get_context_block()
                if fact_block:
                    parts.append(fact_block)
            except Exception:
                pass
```

**Update `handle_message`** — add IntentEngine, ReviewGate, activity logging:
```python
    async def handle_message(self, text: str, chat_id: str = "",
                             agent_type_hint: str | None = None,
                             project_hint: str | None = None):
        # Check for /commands first (no LLM call needed)
        cmd_response = await self._handle_command(text, chat_id)
        if cmd_response is not None:
            if self.telegram:
                await self.telegram.send_message(cmd_response[:4000], chat_id=chat_id or None)
            return

        text = text.strip()
        await self.db.append_chat(chat_id or "default", "user", text)

        # Log activity for daily profile
        if self.soul_memory:
            try:
                await self.soul_memory.log_activity(chat_id or "default")
            except Exception:
                pass

        # Intent Engine: parse natural language
        intent = None
        if self.intent_engine and not agent_type_hint:
            try:
                daily_profile = None
                memory_context = ""
                if self.soul_memory:
                    daily_profile = await self.soul_memory.compute_daily_profile(chat_id or "default")
                    memory_context = await self.soul_memory.get_context_block()
                intent = await self.intent_engine.parse(
                    text, daily_profile=daily_profile, user_memory_context=memory_context,
                )
                # Handle special intent types
                if intent.type == "reminder" and self.scheduler:
                    time_expr = intent.time_expressions[0] if intent.time_expressions else ""
                    await self.scheduler.add_reminder(
                        chat_id=chat_id, text=intent.enriched_prompt, due_at=time_expr,
                    )
                    if self.telegram:
                        await self.telegram.send_message(
                            f"⏰ Erinnerung eingerichtet: {intent.enriched_prompt}", chat_id=chat_id or None,
                        )
                    return
                if intent.type == "planned_task" and intent.steps and self.scheduler:
                    steps = [{"agent_prompt": s["prompt"], "scheduled_at": s.get("scheduled_at")} for s in intent.steps]
                    await self.scheduler.add_planned_task(
                        name=text[:80], chat_id=chat_id, steps=steps,
                    )
                    if self.telegram:
                        await self.telegram.send_message(
                            f"📋 Geplant: {len(steps)} Schritte", chat_id=chat_id or None,
                        )
                    return
                if intent.needs_clarification and intent.confidence < 0.5:
                    if self.telegram:
                        await self.telegram.send_message(
                            intent.clarification_question or "Kannst du das genauer beschreiben?",
                            chat_id=chat_id or None,
                        )
                    return
            except Exception:
                pass  # Fall through to normal classification

        # Use enriched prompt from intent engine if available
        classify_text = intent.enriched_prompt if (intent and intent.type == "passthrough") else text

        if agent_type_hint:
            classification = {
                "type": "content", "agent": agent_type_hint,
                "title": text[:80], "result_type": "report",
            }
        else:
            classification = await self.classify(classify_text, chat_id=chat_id)
        msg_type = classification.get("type", "quick_reply")

        if msg_type == "quick_reply":
            answer = classification.get("answer", "Ich habe keine Antwort.")
            # Review gate
            if self.review_gate:
                try:
                    review = await self.review_gate.review(
                        answer=answer, original_request=text, review_level="light",
                    )
                    if review.verdict == "REVISE" and review.revised:
                        answer = review.revised
                except Exception:
                    pass
            await self.db.append_chat(chat_id or "default", "assistant", answer)
            if self.telegram:
                await self.telegram.send_message(answer[:4000], chat_id=chat_id or None)
            # Extract memories (fire-and-forget)
            if self.soul_memory:
                asyncio.create_task(
                    self.soul_memory.extract_memories(self.llm, text, answer)
                )
            elif self.fact_memory:
                from backend.memory.fact_memory import extract_and_store_facts
                asyncio.create_task(
                    extract_and_store_facts(self.llm, self.fact_memory, text, answer)
                )
        elif msg_type in ("action", "task"):
            task = asyncio.create_task(self._handle_action(classification, text, chat_id, project=project_hint))
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Agent gestartet")
        elif msg_type == "content":
            task = asyncio.create_task(self._handle_content(classification, text, chat_id, project=project_hint))
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Agent gestartet")
        elif msg_type == "multi_step":
            task = asyncio.create_task(self._handle_multi_step(classification, text, chat_id, project=project_hint))
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Multi-Step gestartet")
```

**Update `_handle_action` and `_handle_content`** — replace SubAgent with DynamicAgent:

In `_handle_action`, replace the SubAgent creation block:
```python
            # Select dynamic agent identity
            identity = select_agent(original_text, self._agent_pool)
            sub = DynamicAgent(
                identity=identity,
                task_description=enriched_desc,
                llm=self._get_llm_for("action"),
                tools=self.tools,
                db=self.db,
                soul_content=_SOUL_CONTENT,
            )
```

Same pattern in `_handle_content` and `_handle_multi_step` — replace `SubAgent(agent_type=...)` with `DynamicAgent(identity=select_agent(...), ...)`.

Add review gate before sending final results in `_handle_action` and `_handle_content`:
```python
                # Review gate before sending
                if self.review_gate:
                    try:
                        review = await self.review_gate.review(
                            answer=result, original_request=original_text,
                        )
                        if review.verdict == "REVISE" and review.revised:
                            result = review.revised
                    except Exception:
                        pass
```

- [ ] **Step 4: Update main.py to wire new components**

In `backend/main.py`, update imports and lifespan:

Replace:
```python
from backend.memory.fact_memory import FactMemory
from backend.scheduler import Scheduler
```
With:
```python
from backend.memory.soul_memory import SoulMemory
from backend.memory.fact_memory import FactMemory  # legacy migration
from backend.smart_scheduler import SmartScheduler
from backend.review_gate import ReviewGate
from backend.intent_engine import IntentEngine
```

In `lifespan()`, replace the memory/scheduler setup:
```python
    # 3. Soul Memory (replaces FactMemory)
    soul_memory = SoulMemory(db)
    await soul_memory.init()

    # Migrate existing facts if any
    try:
        old_fact_memory = FactMemory(db)
        await old_fact_memory.init()
        if await old_fact_memory.count() > 0:
            migrated = await soul_memory.migrate_from_facts(old_fact_memory)
            if migrated:
                print(f"Migrated {migrated} facts to SoulMemory")
    except Exception:
        pass

    # ... (LLM + Tools setup stays the same) ...

    # Review Gate
    review_gate = ReviewGate(llm=llm)

    # Intent Engine
    intent_engine = IntentEngine(llm=llm)

    # Smart Scheduler (replaces Scheduler)
    scheduler = SmartScheduler(db)

    # MainAgent
    main_agent = MainAgent(
        llm=llm,
        tools=tools,
        db=db,
        obsidian_writer=obsidian_writer,
        telegram=telegram if telegram.enabled else None,
        ws_callback=ws_mgr.broadcast,
        soul_memory=soul_memory,
        review_gate=review_gate,
        intent_engine=intent_engine,
        scheduler=scheduler,
        llm_router=llm_router,
        config_service=config_service,
    )
```

Update scheduler start to include reminder/step handlers:
```python
    async def handle_reminder(reminder):
        if telegram and telegram.enabled:
            text = f"⏰ Erinnerung: {reminder['text']}"
            await telegram.send_message(text, chat_id=reminder.get('chat_id'))
            if reminder.get('follow_up'):
                await telegram.send_message("Soll ich dazu was machen?", chat_id=reminder.get('chat_id'))

    async def handle_step(step):
        await main_agent.handle_message(
            step['agent_prompt'], chat_id=step.get('chat_id', ''),
        )

    scheduler_task = asyncio.create_task(
        scheduler.start(
            on_task_due=main_agent.handle_scheduled,
            on_reminder_due=handle_reminder,
            on_step_due=handle_step,
        )
    )
```

- [ ] **Step 5: Run integration test**

Run: `python -m pytest tests/test_integration_evolution.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: Majority pass. Some old tests in `test_sub_agent.py` and `test_main_agent.py` may need import updates.

- [ ] **Step 7: Fix broken tests**

Update `tests/test_sub_agent.py` — add compatibility note or update imports. The old SubAgent module still exists for now, so these tests should still pass. If they break due to MainAgent import changes, update the MainAgent test fixtures to include new parameters with defaults.

In `tests/test_main_agent.py`, update the `agent` fixture:
```python
@pytest.fixture
def agent(mock_llm, mock_tools, mock_db, mock_obsidian_writer, mock_telegram):
    return MainAgent(
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
        obsidian_writer=mock_obsidian_writer,
        telegram=mock_telegram,
    )
```
This should still work since all new params default to `None`.

- [ ] **Step 8: Run full test suite again**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add backend/main_agent.py backend/main.py tests/test_integration_evolution.py
git commit -m "feat: wire IntentEngine, ReviewGate, SoulMemory, DynamicAgent into MainAgent"
```

---

## Task 10: Install YAML dependency + final verification

**Files:**
- Modify: `requirements.txt` (add pyyaml)

- [ ] **Step 1: Add pyyaml to requirements.txt**

```bash
echo "pyyaml>=6.0" >> requirements.txt
```

- [ ] **Step 2: Install**

```bash
source venv/bin/activate && pip install -r requirements.txt
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass (old + new)

- [ ] **Step 4: Quick smoke test — start server**

Run: `source venv/bin/activate && timeout 5 python -m backend.main || true`
Expected: Server starts without import errors, prints "Falki running on port 8080"

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "chore: add pyyaml dependency for agent identity config"
```

---

## Task 11: Cleanup — Remove old modules

Only after all tests pass with the new code.

**Files:**
- Delete: `backend/sub_agent.py` (replaced by `dynamic_agent.py`)

- [ ] **Step 1: Verify no remaining imports of sub_agent**

```bash
grep -r "from backend.sub_agent" backend/ tests/ --include="*.py"
grep -r "from backend.scheduler import Scheduler" backend/ tests/ --include="*.py"
```

If any remain in test files, update them. If `sub_agent` is still imported anywhere in backend, update those imports.

- [ ] **Step 2: Update any remaining references**

For each file that still imports `SubAgent` or `sub_agent`, update to `DynamicAgent` / `dynamic_agent`. For scheduler references, `SmartScheduler` extends `Scheduler`, so direct `Scheduler` imports in tests still work.

- [ ] **Step 3: Run full test suite one last time**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove legacy sub_agent references, complete migration to DynamicAgent"
```
