# Falkenstein Phase 2a: Persönlichkeits-Entwicklung & Duo-System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agenten entwickeln dynamische Persönlichkeiten, bauen Beziehungen auf, bilden Duos, und die Sim-Engine nutzt all das für realistischeres Verhalten.

**Architecture:** Neues `personality.py` Modul trackt Trait-Änderungen basierend auf Events. Neues `relationships.py` erkennt Duos bei hoher Synergy. SimEngine und Orchestrator nutzen Beziehungsdaten für Entscheidungen. Database wird um nötige Queries erweitert.

**Tech Stack:** Python 3.11+, aiosqlite, Pydantic, pytest-asyncio

---

## File Structure

```
backend/
├── personality.py         # NEW: Trait-Updates, Mood-Decay, Daily Snapshots
├── relationships.py       # NEW: Beziehungs-Updates, Duo-Erkennung
├── sim_engine.py          # MODIFY: Beziehungen in IDLE-Verhalten einbeziehen
├── agent.py               # MODIFY: Event-Hooks für Persönlichkeits-Updates
├── orchestrator.py        # MODIFY: Duo-Aware Task-Zuweisung
├── database.py            # MODIFY: Neue Queries für Relationships & Personality Log
├── main.py                # MODIFY: Personality-Tick in Sim-Loop
tests/
├── test_personality.py    # NEW
├── test_relationships.py  # NEW
├── test_sim_engine.py     # MODIFY: Neue Tests für Beziehungs-gewichtetes Verhalten
├── test_orchestrator.py   # MODIFY: Tests für Duo-Zuweisung
```

---

### Task 1: Database erweitern — Relationship & Personality Queries

**Files:**
- Modify: `backend/database.py`
- Modify: `tests/test_database.py`

- [ ] **Step 1: Neue Tests schreiben**

Append to `tests/test_database.py`:

```python
@pytest.mark.asyncio
async def test_get_all_relationships(db):
    rel1 = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.9, trust=0.8)
    rel2 = RelationshipData(agent_a="coder_1", agent_b="researcher", synergy=0.4, trust=0.5)
    await db.upsert_relationship(rel1)
    await db.upsert_relationship(rel2)
    rels = await db.get_all_relationships()
    assert len(rels) == 2


@pytest.mark.asyncio
async def test_get_relationships_for_agent(db):
    rel1 = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.9)
    rel2 = RelationshipData(agent_a="coder_1", agent_b="researcher", synergy=0.4)
    rel3 = RelationshipData(agent_a="writer", agent_b="ops", synergy=0.3)
    await db.upsert_relationship(rel1)
    await db.upsert_relationship(rel2)
    await db.upsert_relationship(rel3)
    rels = await db.get_relationships_for("coder_1")
    assert len(rels) == 2
    agents = {r.agent_a for r in rels} | {r.agent_b for r in rels}
    assert "coder_1" in agents


@pytest.mark.asyncio
async def test_log_personality_snapshot(db):
    from backend.models import AgentTraits, AgentMood
    traits = AgentTraits(social=0.7, focus=0.8)
    mood = AgentMood(energy=0.9)
    await db.log_personality_snapshot("coder_1", traits, mood)
    snapshots = await db.get_personality_history("coder_1", limit=5)
    assert len(snapshots) == 1
    assert snapshots[0]["traits"]["social"] == 0.7
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_database.py -v -k "relationships_for or all_relationships or personality_snapshot"
```

Expected: AttributeError — Methoden existieren noch nicht.

- [ ] **Step 3: Neue Methoden in database.py implementieren**

Add to `Database` class in `backend/database.py`:

```python
async def get_all_relationships(self) -> list[RelationshipData]:
    cursor = await self._conn.execute("SELECT * FROM relationships")
    rows = await cursor.fetchall()
    return [
        RelationshipData(
            agent_a=row["agent_a"], agent_b=row["agent_b"],
            trust=row["trust"], synergy=row["synergy"],
            friendship=row["friendship"], respect=row["respect"],
        )
        for row in rows
    ]

async def get_relationships_for(self, agent_id: str) -> list[RelationshipData]:
    cursor = await self._conn.execute(
        "SELECT * FROM relationships WHERE agent_a = ? OR agent_b = ?",
        (agent_id, agent_id),
    )
    rows = await cursor.fetchall()
    return [
        RelationshipData(
            agent_a=row["agent_a"], agent_b=row["agent_b"],
            trust=row["trust"], synergy=row["synergy"],
            friendship=row["friendship"], respect=row["respect"],
        )
        for row in rows
    ]

async def log_personality_snapshot(self, agent_id: str, traits: "AgentTraits", mood: "AgentMood"):
    await self._conn.execute(
        "INSERT INTO personality_log (agent_id, traits, mood) VALUES (?, ?, ?)",
        (agent_id, traits.model_dump_json(), mood.model_dump_json()),
    )
    await self._conn.commit()

async def get_personality_history(self, agent_id: str, limit: int = 30) -> list[dict]:
    cursor = await self._conn.execute(
        "SELECT traits, mood, created_at FROM personality_log WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
        (agent_id, limit),
    )
    rows = await cursor.fetchall()
    return [
        {"traits": json.loads(row["traits"]), "mood": json.loads(row["mood"]), "created_at": row["created_at"]}
        for row in rows
    ]
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_database.py -v
```

Expected: Alle Tests PASS (9 total).

- [ ] **Step 5: Commit**

```bash
git add backend/database.py tests/test_database.py
git commit -m "feat: add relationship and personality history queries to database"
```

---

### Task 2: Personality Engine

**Files:**
- Create: `backend/personality.py`
- Test: `tests/test_personality.py`

- [ ] **Step 1: Tests schreiben**

```python
# tests/test_personality.py
import pytest
from backend.personality import PersonalityEngine, PersonalityEvent
from backend.models import AgentTraits, AgentMood


def test_task_success_boosts_confidence():
    traits = AgentTraits(confidence=0.5)
    mood = AgentMood(stress=0.3)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(
        traits, mood, PersonalityEvent.TASK_SUCCESS
    )
    assert new_traits.confidence > 0.5
    assert new_mood.stress < 0.3


def test_task_failure_increases_frustration():
    traits = AgentTraits(patience=0.5)
    mood = AgentMood(frustration=0.1)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(
        traits, mood, PersonalityEvent.TASK_FAILURE
    )
    assert new_mood.frustration > 0.1


def test_successful_collab_boosts_motivation():
    traits = AgentTraits()
    mood = AgentMood(motivation=0.5)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(
        traits, mood, PersonalityEvent.SUCCESSFUL_COLLAB
    )
    assert new_mood.motivation > 0.5


def test_cli_escalation_lowers_confidence():
    traits = AgentTraits(confidence=0.6)
    mood = AgentMood()
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(
        traits, mood, PersonalityEvent.CLI_ESCALATION
    )
    assert new_traits.confidence < 0.6


def test_received_praise_boosts_motivation_and_leadership():
    traits = AgentTraits(leadership=0.3)
    mood = AgentMood(motivation=0.5)
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(
        traits, mood, PersonalityEvent.RECEIVED_PRAISE
    )
    assert new_mood.motivation > 0.5
    assert new_traits.leadership > 0.3


def test_traits_clamp_to_0_1():
    traits = AgentTraits(confidence=0.99)
    mood = AgentMood()
    engine = PersonalityEngine()
    new_traits, _ = engine.apply_event(traits, mood, PersonalityEvent.TASK_SUCCESS)
    assert new_traits.confidence <= 1.0

    traits2 = AgentTraits(confidence=0.01)
    new_traits2, _ = engine.apply_event(traits2, AgentMood(), PersonalityEvent.CLI_ESCALATION)
    assert new_traits2.confidence >= 0.0


def test_mood_decay_towards_baseline():
    mood = AgentMood(stress=0.8, energy=0.3, frustration=0.7)
    engine = PersonalityEngine()
    decayed = engine.decay_mood(mood)
    assert decayed.stress < 0.8
    assert decayed.energy > 0.3
    assert decayed.frustration < 0.7


def test_idle_chat_no_trait_change():
    traits = AgentTraits(social=0.5)
    mood = AgentMood()
    engine = PersonalityEngine()
    new_traits, new_mood = engine.apply_event(
        traits, mood, PersonalityEvent.IDLE_CHAT
    )
    # Idle chat changes mood slightly but not traits
    assert new_traits.social == 0.5
    assert new_mood.energy >= mood.energy  # slight energy boost from socializing
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_personality.py -v
```

Expected: ImportError.

- [ ] **Step 3: PersonalityEngine implementieren**

```python
# backend/personality.py
from enum import Enum
from backend.models import AgentTraits, AgentMood


class PersonalityEvent(str, Enum):
    TASK_SUCCESS = "task_success"
    TASK_FAILURE = "task_failure"
    CLI_ESCALATION = "cli_escalation"
    SUCCESSFUL_COLLAB = "successful_collab"
    REVIEW_NEGATIVE = "review_negative"
    REVIEW_POSITIVE = "review_positive"
    RECEIVED_PRAISE = "received_praise"
    IDLE_CHAT = "idle_chat"
    SOLO_BUG_FIX = "solo_bug_fix"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


# Trait changes are small (0.01-0.05) — they accumulate over days
# Mood changes are larger (0.05-0.2) — they fluctuate within hours
EVENT_EFFECTS: dict[PersonalityEvent, dict] = {
    PersonalityEvent.TASK_SUCCESS: {
        "traits": {"confidence": 0.03},
        "mood": {"stress": -0.1, "motivation": 0.05},
    },
    PersonalityEvent.TASK_FAILURE: {
        "traits": {"patience": -0.02},
        "mood": {"frustration": 0.15, "stress": 0.1, "motivation": -0.05},
    },
    PersonalityEvent.CLI_ESCALATION: {
        "traits": {"confidence": -0.02},
        "mood": {"stress": 0.05},
    },
    PersonalityEvent.SUCCESSFUL_COLLAB: {
        "traits": {"social": 0.01},
        "mood": {"motivation": 0.1, "energy": 0.05},
    },
    PersonalityEvent.REVIEW_NEGATIVE: {
        "traits": {"patience": -0.01},
        "mood": {"frustration": 0.1, "stress": 0.05},
    },
    PersonalityEvent.REVIEW_POSITIVE: {
        "traits": {"confidence": 0.02},
        "mood": {"motivation": 0.05},
    },
    PersonalityEvent.RECEIVED_PRAISE: {
        "traits": {"leadership": 0.02, "confidence": 0.02},
        "mood": {"motivation": 0.15, "stress": -0.05},
    },
    PersonalityEvent.IDLE_CHAT: {
        "traits": {},
        "mood": {"energy": 0.02},
    },
    PersonalityEvent.SOLO_BUG_FIX: {
        "traits": {"confidence": 0.05, "focus": 0.01},
        "mood": {"motivation": 0.1},
    },
}

# Mood decays towards these baselines each tick
MOOD_BASELINE = {"energy": 0.7, "stress": 0.15, "motivation": 0.6, "frustration": 0.0}
MOOD_DECAY_RATE = 0.05


class PersonalityEngine:
    def apply_event(
        self, traits: AgentTraits, mood: AgentMood, event: PersonalityEvent
    ) -> tuple[AgentTraits, AgentMood]:
        effects = EVENT_EFFECTS.get(event, {"traits": {}, "mood": {}})

        trait_dict = traits.model_dump()
        for key, delta in effects.get("traits", {}).items():
            if key in trait_dict:
                trait_dict[key] = _clamp(trait_dict[key] + delta)
        new_traits = AgentTraits(**trait_dict)

        mood_dict = mood.model_dump()
        for key, delta in effects.get("mood", {}).items():
            if key in mood_dict:
                mood_dict[key] = _clamp(mood_dict[key] + delta)
        new_mood = AgentMood(**mood_dict)

        return new_traits, new_mood

    def decay_mood(self, mood: AgentMood) -> AgentMood:
        mood_dict = mood.model_dump()
        for key, baseline in MOOD_BASELINE.items():
            current = mood_dict[key]
            diff = baseline - current
            mood_dict[key] = _clamp(current + diff * MOOD_DECAY_RATE)
        return AgentMood(**mood_dict)
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_personality.py -v
```

Expected: Alle 8 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/personality.py tests/test_personality.py
git commit -m "feat: personality engine with event-driven trait/mood changes and decay"
```

---

### Task 3: Relationship Engine & Duo-Erkennung

**Files:**
- Create: `backend/relationships.py`
- Test: `tests/test_relationships.py`

- [ ] **Step 1: Tests schreiben**

```python
# tests/test_relationships.py
import pytest
import pytest_asyncio
from pathlib import Path
from backend.relationships import RelationshipEngine, RelationshipEvent
from backend.database import Database
from backend.models import RelationshipData


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_collab_success_increases_synergy(db):
    engine = RelationshipEngine(db)
    await engine.record_event("coder_1", "coder_2", RelationshipEvent.COLLAB_SUCCESS)
    rel = await db.get_relationship("coder_1", "coder_2")
    assert rel is not None
    assert rel.synergy > 0.5  # default is 0.5
    assert rel.trust > 0.5


@pytest.mark.asyncio
async def test_review_clean_increases_respect(db):
    engine = RelationshipEngine(db)
    await engine.record_event("coder_1", "team_lead", RelationshipEvent.REVIEW_CLEAN)
    rel = await db.get_relationship("coder_1", "team_lead")
    assert rel.respect > 0.5


@pytest.mark.asyncio
async def test_idle_chat_increases_friendship(db):
    engine = RelationshipEngine(db)
    await engine.record_event("coder_1", "coder_2", RelationshipEvent.IDLE_CHAT)
    rel = await db.get_relationship("coder_1", "coder_2")
    assert rel.friendship > 0.5


@pytest.mark.asyncio
async def test_duo_detection_at_high_synergy(db):
    engine = RelationshipEngine(db)
    # Manually set high synergy
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.9, trust=0.8, friendship=0.7, respect=0.8)
    await db.upsert_relationship(rel)
    duos = await engine.detect_duos()
    assert len(duos) == 1
    assert ("coder_1", "coder_2") in duos or ("coder_2", "coder_1") in duos


@pytest.mark.asyncio
async def test_no_duo_at_low_synergy(db):
    engine = RelationshipEngine(db)
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.5)
    await db.upsert_relationship(rel)
    duos = await engine.detect_duos()
    assert len(duos) == 0


@pytest.mark.asyncio
async def test_repeated_events_accumulate(db):
    engine = RelationshipEngine(db)
    for _ in range(5):
        await engine.record_event("coder_1", "coder_2", RelationshipEvent.COLLAB_SUCCESS)
    rel = await db.get_relationship("coder_1", "coder_2")
    assert rel.synergy > 0.7
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_relationships.py -v
```

Expected: ImportError.

- [ ] **Step 3: RelationshipEngine implementieren**

```python
# backend/relationships.py
from enum import Enum
from backend.database import Database
from backend.models import RelationshipData

DUO_SYNERGY_THRESHOLD = 0.85


class RelationshipEvent(str, Enum):
    COLLAB_SUCCESS = "collab_success"
    COLLAB_FAILURE = "collab_failure"
    REVIEW_CLEAN = "review_clean"
    REVIEW_ISSUES = "review_issues"
    IDLE_CHAT = "idle_chat"
    HELPED_WITH_BUG = "helped_with_bug"


EVENT_DELTAS: dict[RelationshipEvent, dict[str, float]] = {
    RelationshipEvent.COLLAB_SUCCESS: {"synergy": 0.05, "trust": 0.03, "respect": 0.02},
    RelationshipEvent.COLLAB_FAILURE: {"synergy": -0.02, "trust": -0.01},
    RelationshipEvent.REVIEW_CLEAN: {"respect": 0.05, "trust": 0.02},
    RelationshipEvent.REVIEW_ISSUES: {"respect": -0.02},
    RelationshipEvent.IDLE_CHAT: {"friendship": 0.03},
    RelationshipEvent.HELPED_WITH_BUG: {"synergy": 0.03, "trust": 0.05, "friendship": 0.02},
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class RelationshipEngine:
    def __init__(self, db: Database):
        self.db = db

    async def record_event(self, agent_a: str, agent_b: str, event: RelationshipEvent):
        rel = await self.db.get_relationship(agent_a, agent_b)
        if rel is None:
            rel = RelationshipData(agent_a=agent_a, agent_b=agent_b)

        deltas = EVENT_DELTAS.get(event, {})
        rel_dict = rel.model_dump()
        for key, delta in deltas.items():
            if key in rel_dict and isinstance(rel_dict[key], float):
                rel_dict[key] = _clamp(rel_dict[key] + delta)

        updated = RelationshipData(**rel_dict)
        await self.db.upsert_relationship(updated)

    async def detect_duos(self) -> list[tuple[str, str]]:
        all_rels = await self.db.get_all_relationships()
        duos = []
        for rel in all_rels:
            if rel.synergy >= DUO_SYNERGY_THRESHOLD:
                duos.append((rel.agent_a, rel.agent_b))
        return duos

    async def get_best_partner(self, agent_id: str) -> str | None:
        rels = await self.db.get_relationships_for(agent_id)
        if not rels:
            return None
        best = max(rels, key=lambda r: r.synergy + r.friendship)
        return best.agent_b if best.agent_a == agent_id else best.agent_a
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_relationships.py -v
```

Expected: Alle 6 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/relationships.py tests/test_relationships.py
git commit -m "feat: relationship engine with event tracking and duo detection"
```

---

### Task 4: Agent mit Personality-Events integrieren

**Files:**
- Modify: `backend/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Neue Tests anhängen**

Append to `tests/test_agent.py`:

```python
from backend.personality import PersonalityEngine


@pytest.mark.asyncio
async def test_complete_task_triggers_personality_event():
    data = make_agent_data(state=AgentState.WORK_TYPE, current_task_id=1)
    data.traits = AgentTraits(confidence=0.5)
    data.mood = AgentMood(stress=0.3)
    db = AsyncMock()
    agent = Agent(data=data, llm=AsyncMock(), db=db, tools=MagicMock(),
                  personality_engine=PersonalityEngine())
    await agent.complete_task(result="Done")
    assert agent.data.traits.confidence > 0.5
    assert agent.data.mood.stress < 0.3
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_agent.py::test_complete_task_triggers_personality_event -v
```

Expected: TypeError — `personality_engine` not accepted.

- [ ] **Step 3: Agent um PersonalityEngine erweitern**

In `backend/agent.py`, modify `__init__` and `complete_task`:

```python
from backend.personality import PersonalityEngine, PersonalityEvent

class Agent:
    def __init__(self, data: AgentData, llm: LLMClient, db: Database, tools: ToolRegistry,
                 personality_engine: PersonalityEngine | None = None):
        self.data = data
        self.llm = llm
        self.db = db
        self.tools = tools
        self.personality_engine = personality_engine or PersonalityEngine()
        self.session_messages: list[dict] = []

    async def complete_task(self, result: str):
        if self.data.current_task_id is not None:
            await self.db.update_task_status(self.data.current_task_id, TaskStatus.DONE)
            self.data.traits, self.data.mood = self.personality_engine.apply_event(
                self.data.traits, self.data.mood, PersonalityEvent.TASK_SUCCESS
            )
        self.data.current_task_id = None
        self.data.state = AgentState.IDLE_SIT
        self.session_messages = []

    async def fail_task(self, reason: str):
        if self.data.current_task_id is not None:
            await self.db.update_task_status(self.data.current_task_id, TaskStatus.FAILED)
            self.data.traits, self.data.mood = self.personality_engine.apply_event(
                self.data.traits, self.data.mood, PersonalityEvent.TASK_FAILURE
            )
        self.data.current_task_id = None
        self.data.state = AgentState.IDLE_SIT
        self.session_messages = []
```

- [ ] **Step 4: Bestehende Tests fixen (personality_engine default)**

Verify old tests still pass since `personality_engine` defaults to `PersonalityEngine()`:

```bash
python -m pytest tests/test_agent.py -v
```

Expected: Alle 5 Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agent.py tests/test_agent.py
git commit -m "feat: integrate personality engine into agent task completion"
```

---

### Task 5: SimEngine mit Beziehungs-gewichtetem IDLE-Verhalten

**Files:**
- Modify: `backend/sim_engine.py`
- Modify: `tests/test_sim_engine.py`

- [ ] **Step 1: Neue Tests anhängen**

Append to `tests/test_sim_engine.py`:

```python
from backend.relationships import RelationshipEngine
from backend.database import Database
import pytest_asyncio


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_talk_prefers_friends(db):
    """Agent should prefer talking to agents with higher friendship."""
    from backend.models import RelationshipData
    alex = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5, social=0.9)
    bob = make_agent("coder_2", "Bob", AgentRole.CODER_2, 6, 5)
    clara = make_agent("writer", "Clara", AgentRole.WRITER, 6, 6)

    # Alex and Bob are close friends
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", friendship=0.9, synergy=0.8)
    await db.upsert_relationship(rel)

    rel_engine = RelationshipEngine(db)
    alex.llm.generate_sim_action = AsyncMock(return_value="talk")
    alex.llm.generate_chat_message = AsyncMock(return_value="Hey!")
    bob.llm.generate_sim_action = AsyncMock(return_value="sit")
    clara.llm.generate_sim_action = AsyncMock(return_value="sit")

    sim = SimEngine(agents=[alex, bob, clara], llm=alex.llm, relationship_engine=rel_engine)
    # Run multiple ticks and count who Alex talks to
    bob_count = 0
    for _ in range(20):
        events = await sim.tick()
        for e in events:
            if e.get("type") == "talk" and e.get("agent") == "coder_1":
                if e.get("partner") == "coder_2":
                    bob_count += 1
        # Reset states for next tick
        alex.data.state = AgentState.IDLE_SIT
        bob.data.state = AgentState.IDLE_SIT
        clara.data.state = AgentState.IDLE_SIT

    # Bob should be preferred partner (most of the time)
    assert bob_count >= 10  # at least 50% of talks should be with Bob


@pytest.mark.asyncio
async def test_mood_decay_applied_each_tick():
    agent = make_agent("coder_1", "Alex", AgentRole.CODER_1, 5, 5)
    agent.data.mood.stress = 0.8
    agent.llm.generate_sim_action = AsyncMock(return_value="sit")
    sim = SimEngine(agents=[agent], llm=agent.llm)
    await sim.tick()
    assert agent.data.mood.stress < 0.8  # decay should lower stress
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_sim_engine.py -v -k "prefers_friends or mood_decay"
```

Expected: TypeError — `relationship_engine` parameter not accepted.

- [ ] **Step 3: SimEngine erweitern**

Modify `backend/sim_engine.py`:

```python
import random
from backend.agent import Agent
from backend.models import AgentState
from backend.llm_client import LLMClient
from backend.personality import PersonalityEngine, PersonalityEvent
from backend.relationships import RelationshipEngine, RelationshipEvent

ACTION_TO_STATE = {
    "wander": AgentState.IDLE_WANDER,
    "talk": AgentState.IDLE_TALK,
    "coffee": AgentState.IDLE_COFFEE,
    "phone": AgentState.IDLE_PHONE,
    "sit": AgentState.IDLE_SIT,
}


class SimEngine:
    def __init__(self, agents: list[Agent], llm: LLMClient,
                 relationship_engine: RelationshipEngine | None = None,
                 personality_engine: PersonalityEngine | None = None):
        self.agents = agents
        self.llm = llm
        self.rel_engine = relationship_engine
        self.personality_engine = personality_engine or PersonalityEngine()

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

    async def _pick_talk_partner(self, agent: Agent, nearby: list[Agent]) -> Agent:
        if not self.rel_engine or len(nearby) <= 1:
            return random.choice(nearby)

        # Weight by friendship + synergy
        weights = []
        for other in nearby:
            rel = await self.rel_engine.db.get_relationship(agent.data.id, other.data.id)
            if rel:
                weights.append(rel.friendship + rel.synergy + 0.1)
            else:
                weights.append(0.1)

        total = sum(weights)
        probs = [w / total for w in weights]
        return random.choices(nearby, weights=probs, k=1)[0]

    async def tick(self) -> list[dict]:
        events = []
        for agent in self.agents:
            if not agent.is_idle:
                continue
            # Apply mood decay each tick
            agent.data.mood = self.personality_engine.decay_mood(agent.data.mood)
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
            partner = await self._pick_talk_partner(agent, nearby)
            message = await self.llm.generate_chat_message(
                agent_name=agent.data.name,
                personality=agent.personality_description,
                partner_name=partner.data.name,
            )
            # Record relationship event
            if self.rel_engine:
                await self.rel_engine.record_event(
                    agent.data.id, partner.data.id, RelationshipEvent.IDLE_CHAT
                )
            # Apply personality event
            agent.data.traits, agent.data.mood = self.personality_engine.apply_event(
                agent.data.traits, agent.data.mood, PersonalityEvent.IDLE_CHAT
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
            return {"type": "coffee", "agent": agent.data.id}

        return {"type": "idle", "agent": agent.data.id, "action": action}
```

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_sim_engine.py -v
```

Expected: Alle 5 Tests PASS (3 old + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/sim_engine.py tests/test_sim_engine.py
git commit -m "feat: sim engine uses relationships for talk partner selection, applies mood decay"
```

---

### Task 6: Orchestrator mit Duo-Aware Task-Zuweisung

**Files:**
- Modify: `backend/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Neue Tests anhängen**

Append to `tests/test_orchestrator.py`:

```python
from backend.relationships import RelationshipEngine
from backend.models import RelationshipData
from backend.database import Database
import pytest_asyncio


@pytest_asyncio.fixture
async def real_db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.init()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_orchestrator_assigns_duo_partner(real_db):
    """When a duo partner is idle and task fits, prefer duo assignment."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value="coder_1")
    pool = AgentPool(llm=llm, db=real_db, tools=MagicMock())

    # Create high-synergy relationship between coder_1 and coder_2
    rel = RelationshipData(agent_a="coder_1", agent_b="coder_2", synergy=0.95, trust=0.8)
    await real_db.upsert_relationship(rel)

    rel_engine = RelationshipEngine(real_db)
    orch = Orchestrator(pool=pool, db=real_db, llm=llm, relationship_engine=rel_engine)

    # Assign first task to coder_1
    coder1 = pool.get_agent("coder_1")
    await coder1.assign_task(task_id=99, title="Part A", description="First part")

    # Submit second part of same project — should prefer coder_2 (duo partner)
    real_db.create_task = AsyncMock(return_value=2)
    real_db.get_task = AsyncMock(return_value=TaskData(
        id=2, title="Code part B", description="Code implementieren", project="website"
    ))
    await orch.submit_task("Code part B", "Code implementieren", project="website")
    event = await orch.assign_next_task()
    assert event is not None
    # Should pick coder_2 since coder_1 is busy and they're a duo
    assert event["agent"] == "coder_2"
```

- [ ] **Step 2: Tests ausführen, Fail verifizieren**

```bash
python -m pytest tests/test_orchestrator.py::test_orchestrator_assigns_duo_partner -v
```

Expected: TypeError — `relationship_engine` not accepted.

- [ ] **Step 3: Orchestrator erweitern**

Modify `backend/orchestrator.py`:

```python
from backend.agent_pool import AgentPool
from backend.database import Database
from backend.llm_client import LLMClient
from backend.models import TaskData, TaskStatus, AgentRole
from backend.relationships import RelationshipEngine

ROLE_KEYWORDS = {
    AgentRole.CODER_1: ["code", "implementier", "bug", "fix", "programm", "api", "endpoint"],
    AgentRole.CODER_2: ["test", "code", "implementier", "backend", "frontend"],
    AgentRole.RESEARCHER: ["recherch", "such", "find", "analys", "vergleich"],
    AgentRole.WRITER: ["schreib", "doku", "text", "report", "artikel", "zusammenfass"],
    AgentRole.OPS: ["deploy", "server", "docker", "pipeline", "install", "config", "shell"],
}


class Orchestrator:
    def __init__(self, pool: AgentPool, db: Database, llm: LLMClient,
                 relationship_engine: RelationshipEngine | None = None):
        self.pool = pool
        self.db = db
        self.llm = llm
        self.rel_engine = relationship_engine
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

    async def _find_duo_partner_idle(self, busy_agent_id: str) -> str | None:
        """If a busy agent has a duo partner who is idle, return their ID."""
        if not self.rel_engine:
            return None
        duos = await self.rel_engine.detect_duos()
        for a, b in duos:
            partner_id = None
            if a == busy_agent_id:
                partner_id = b
            elif b == busy_agent_id:
                partner_id = a
            if partner_id:
                partner = self.pool.get_agent(partner_id)
                if partner and partner.is_idle:
                    return partner_id
        return None

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

        # Check if any busy agent working on same project has an idle duo partner
        if task.project and self.rel_engine:
            for a in self.pool.agents:
                if a.is_working and a.data.current_task_id is not None:
                    current_task = await self.db.get_task(a.data.current_task_id)
                    if current_task and current_task.project == task.project:
                        duo_id = await self._find_duo_partner_idle(a.data.id)
                        if duo_id:
                            agent = self.pool.get_agent(duo_id)
                            break

        # Fallback: match by role
        if not agent:
            for a in idle:
                if a.data.role == best_role:
                    agent = a
                    break

        # Fallback: any idle agent
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

- [ ] **Step 4: Tests ausführen, Pass verifizieren**

```bash
python -m pytest tests/test_orchestrator.py -v
```

Expected: Alle 5 Tests PASS (4 old + 1 new).

- [ ] **Step 5: Commit**

```bash
git add backend/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator prefers duo partners for same-project tasks"
```

---

### Task 7: Main Server Integration

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: main.py mit PersonalityEngine und RelationshipEngine verdrahten**

Replace the lifespan and sim_loop in `backend/main.py`:

```python
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
from backend.personality import PersonalityEngine
from backend.relationships import RelationshipEngine

db: Database = None
pool: AgentPool = None
orchestrator: Orchestrator = None
sim: SimEngine = None
ws_mgr = WSManager()
sim_task: asyncio.Task = None
rel_engine: RelationshipEngine = None
personality_engine: PersonalityEngine = None


async def sim_loop():
    """Main simulation loop — ticks every 5 seconds."""
    tick_count = 0
    while True:
        try:
            events = await sim.tick()
            for event in events:
                await ws_mgr.broadcast(event)
            await ws_mgr.broadcast({
                "type": "state_update",
                "agents": pool.get_agents_state(),
            })
            # Every 60 ticks (~5 min), save personality snapshots
            tick_count += 1
            if tick_count % 60 == 0:
                for agent in pool.agents:
                    await db.log_personality_snapshot(
                        agent.data.id, agent.data.traits, agent.data.mood
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Sim loop error: {e}")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, pool, orchestrator, sim, sim_task, rel_engine, personality_engine

    db = Database(settings.db_path)
    await db.init()

    llm = LLMClient()

    tools = ToolRegistry()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    tools.register(FileManagerTool(workspace_path=settings.workspace_path))

    personality_engine = PersonalityEngine()
    rel_engine = RelationshipEngine(db)

    pool = AgentPool(llm=llm, db=db, tools=tools, personality_engine=personality_engine)
    await pool.save_all()

    orchestrator = Orchestrator(pool=pool, db=db, llm=llm, relationship_engine=rel_engine)
    sim = SimEngine(agents=pool.agents, llm=llm,
                    relationship_engine=rel_engine, personality_engine=personality_engine)

    sim_task = asyncio.create_task(sim_loop())

    print(f"Falkenstein running on port {settings.frontend_port}")
    yield

    sim_task.cancel()
    try:
        await sim_task
    except asyncio.CancelledError:
        pass
    await pool.save_all()
    await db.close()


app = FastAPI(title="Falkenstein", lifespan=lifespan)

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


@app.get("/api/duos")
async def get_duos():
    duos = await rel_engine.detect_duos()
    return {"duos": duos}


@app.get("/api/relationships/{agent_id}")
async def get_relationships(agent_id: str):
    rels = await db.get_relationships_for(agent_id)
    return [r.model_dump() for r in rels]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
```

- [ ] **Step 2: AgentPool muss personality_engine weiterreichen**

Modify `backend/agent_pool.py` — add `personality_engine` param to `__init__`:

```python
from backend.personality import PersonalityEngine

class AgentPool:
    def __init__(self, llm: LLMClient, db: Database, tools: ToolRegistry,
                 personality_engine: PersonalityEngine | None = None):
        self.agents: list[Agent] = []
        pe = personality_engine or PersonalityEngine()
        for spec in TEAM:
            data = AgentData(
                id=spec["id"], name=spec["name"], role=spec["role"],
                state=AgentState.IDLE_SIT, position=spec["position"],
                traits=spec["traits"], mood=AgentMood(),
            )
            self.agents.append(Agent(data=data, llm=llm, db=db, tools=tools, personality_engine=pe))
```

- [ ] **Step 3: Import-Test**

```bash
python -c "from backend.main import app; print(app.title)"
```

Expected: `Falkenstein`

- [ ] **Step 4: Alle Tests ausführen**

```bash
python -m pytest tests/ -v
```

Expected: Alle Tests PASS (30 old + 8 new personality + 6 relationships + 1 agent + 2 sim + 1 orchestrator = ~48 total).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/agent_pool.py
git commit -m "feat: integrate personality and relationship engines into main server"
```

---

### Task 8: Alle Tests & Smoke Test

- [ ] **Step 1: Alle Tests ausführen**

```bash
python -m pytest tests/ -v
```

Expected: Alle Tests PASS.

- [ ] **Step 2: Server starten und neue Endpoints testen**

```bash
python -m backend.main &
sleep 3
curl -s http://localhost:8080/api/duos | python3 -m json.tool
curl -s http://localhost:8080/api/relationships/coder_1 | python3 -m json.tool
curl -s http://localhost:8080/api/agents | python3 -c "import sys,json; agents=json.load(sys.stdin); [print(f'{a[\"id\"]}: mood={a[\"mood\"]}') for a in agents]"
kill %1
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: phase 2a complete — personality development and duo system"
```
