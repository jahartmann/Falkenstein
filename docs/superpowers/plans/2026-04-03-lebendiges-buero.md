# Lebendiges Büro & Proaktive Agenten — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agents behave like real coworkers (go to kitchen, lounge, chat) and proactively generate research/automation suggestions.

**Architecture:** Two independent systems. (1) Frontend-driven POI idle behavior using zone data from tilemap, personality-weighted activity selection, no LLM calls for movement. (2) Backend initiative engine that periodically triggers idle agents to research or propose tasks, with two-tier approval (small=auto, large=telegram confirmation).

**Tech Stack:** Python 3.11+ / FastAPI / aiosqlite / Phaser.js 3.80 / Ollama LLM

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `backend/office_zones.py` | Parse tilemap JSON, extract named zones as tile-coordinate rectangles |
| `backend/idle_behavior.py` | Personality + time-of-day weighted activity selection (no LLM) |
| `backend/initiative_engine.py` | Proactive task generation loop, two-tier approval |
| `tests/test_office_zones.py` | Zone parsing tests |
| `tests/test_idle_behavior.py` | Activity weight calculation tests |
| `tests/test_initiative_engine.py` | Initiative loop tests |

### Modified Files
| File | Changes |
|---|---|
| `backend/config.py` | Add initiative settings |
| `backend/database.py` | Add `initiatives` table |
| `backend/notification_router.py` | Add `initiative_completed`, `initiative_proposed` events |
| `backend/sim_engine.py` | Remove LLM idle calls, simplify to mood decay only |
| `backend/main.py` | Wire initiative loop, zones in full_state, talk request WS handler, telegram ja/nein |
| `frontend/agents.js` | Replace random-wander IDLE with zone-based activities |
| `frontend/game.js` | Pass zone data from full_state to AgentSprites |

---

### Task 1: Office Zone Parser

**Files:**
- Create: `backend/office_zones.py`
- Create: `tests/test_office_zones.py`
- Read: `frontend/assets/office.tmj`

- [ ] **Step 1: Write failing tests for zone parsing**

```python
# tests/test_office_zones.py
import pytest
from backend.office_zones import parse_zones, Zone


MOCK_TILEMAP = {
    "tilewidth": 48,
    "tileheight": 48,
    "layers": [
        {"name": "Walkable", "type": "tilelayer"},
        {
            "name": "Benamung",
            "type": "objectgroup",
            "objects": [
                {"id": 5, "name": "Küche", "x": 816.0, "y": 1730.0, "width": 101.0, "height": 42.0},
                {"id": 9, "name": "Lounge", "x": 1927.0, "y": 148.0, "width": 119.0, "height": 47.0},
                {"id": 12, "name": "Gemienschaftsraum", "x": 980.0, "y": 613.0, "width": 154.0, "height": 51.0},
            ],
        },
    ],
}


def test_parse_zones_extracts_named_zones():
    zones = parse_zones(MOCK_TILEMAP)
    assert len(zones) == 3
    names = {z.name for z in zones}
    assert "Küche" in names
    assert "Lounge" in names


def test_zone_coordinates_are_tile_based():
    zones = parse_zones(MOCK_TILEMAP)
    kitchen = next(z for z in zones if z.name == "Küche")
    # 816/48 = 17, 1730/48 ≈ 36
    assert kitchen.tile_x == 17
    assert kitchen.tile_y == 36
    assert kitchen.tile_w >= 2  # 101/48 ≈ 2
    assert kitchen.tile_h >= 1


def test_zone_type_mapping():
    zones = parse_zones(MOCK_TILEMAP)
    kitchen = next(z for z in zones if z.name == "Küche")
    assert kitchen.zone_type == "kitchen"
    lounge = next(z for z in zones if z.name == "Lounge")
    assert lounge.zone_type == "lounge"


def test_zone_center_tile():
    zones = parse_zones(MOCK_TILEMAP)
    kitchen = next(z for z in zones if z.name == "Küche")
    cx, cy = kitchen.center_tile()
    assert cx == kitchen.tile_x + kitchen.tile_w // 2
    assert cy == kitchen.tile_y + kitchen.tile_h // 2


def test_parse_zones_skips_non_object_layers():
    tilemap = {"tilewidth": 48, "tileheight": 48, "layers": [
        {"name": "Walkable", "type": "tilelayer"},
    ]}
    zones = parse_zones(tilemap)
    assert zones == []


def test_parse_zones_from_file(tmp_path):
    import json
    p = tmp_path / "test.tmj"
    p.write_text(json.dumps(MOCK_TILEMAP))
    from backend.office_zones import load_zones
    zones = load_zones(p)
    assert len(zones) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_office_zones.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.office_zones'`

- [ ] **Step 3: Implement office_zones.py**

```python
# backend/office_zones.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ZONE_TYPE_MAP = {
    "Küche": "kitchen",
    "Lounge": "lounge",
    "Gemienschaftsraum": "social",  # typo in tilemap, keep as-is
    "Team Büro": "desk_area",
    "Fokus-Büro": "focus",
    "Deep-Dive 1": "focus",
    "Deep-Dive 2": "focus",
    "Teamleitung": "desk_area",
    "Büro Boss": "desk_area",
}


@dataclass
class Zone:
    name: str
    zone_type: str
    tile_x: int
    tile_y: int
    tile_w: int
    tile_h: int

    def center_tile(self) -> tuple[int, int]:
        return self.tile_x + self.tile_w // 2, self.tile_y + self.tile_h // 2

    def to_dict(self) -> dict:
        cx, cy = self.center_tile()
        return {
            "name": self.name,
            "type": self.zone_type,
            "x": self.tile_x,
            "y": self.tile_y,
            "w": self.tile_w,
            "h": self.tile_h,
            "cx": cx,
            "cy": cy,
        }


def parse_zones(tilemap: dict) -> list[Zone]:
    tw = tilemap.get("tilewidth", 48)
    th = tilemap.get("tileheight", 48)
    zones = []
    for layer in tilemap.get("layers", []):
        if layer.get("type") != "objectgroup":
            continue
        if layer.get("name") != "Benamung":
            continue
        for obj in layer.get("objects", []):
            name = obj.get("name", "").strip()
            if not name:
                continue
            zone_type = ZONE_TYPE_MAP.get(name, "unknown")
            zones.append(Zone(
                name=name,
                zone_type=zone_type,
                tile_x=int(obj["x"] / tw),
                tile_y=int(obj["y"] / th),
                tile_w=max(1, int(obj["width"] / tw)),
                tile_h=max(1, int(obj["height"] / th)),
            ))
    return zones


def load_zones(tilemap_path: Path) -> list[Zone]:
    with open(tilemap_path) as f:
        tilemap = json.load(f)
    return parse_zones(tilemap)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_office_zones.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/office_zones.py tests/test_office_zones.py
git commit -m "feat: office zone parser — extracts named zones from tilemap"
```

---

### Task 2: Idle Behavior Engine

**Files:**
- Create: `backend/idle_behavior.py`
- Create: `tests/test_idle_behavior.py`

- [ ] **Step 1: Write failing tests for activity selection**

```python
# tests/test_idle_behavior.py
import pytest
from unittest.mock import patch
from backend.idle_behavior import (
    select_activity,
    Activity,
    BASE_WEIGHTS,
    compute_weights,
)
from backend.models import AgentTraits, AgentMood


def test_all_activities_defined():
    assert set(Activity) == {
        Activity.DESK_SIT,
        Activity.KITCHEN_COFFEE,
        Activity.LOUNGE_CHILL,
        Activity.TALK_COLLEAGUE,
        Activity.WANDER_SHORT,
        Activity.PHONE_CALL,
    }


def test_base_weights_sum_to_100():
    assert sum(BASE_WEIGHTS.values()) == 100


def test_high_focus_increases_desk_sit():
    traits = AgentTraits(focus=0.9, social=0.3)
    mood = AgentMood()
    weights = compute_weights(traits, mood, hour=15)
    # High focus agent should prefer desk
    assert weights[Activity.DESK_SIT] > weights[Activity.LOUNGE_CHILL]


def test_high_social_increases_talk():
    traits = AgentTraits(social=0.9, focus=0.3)
    mood = AgentMood()
    weights = compute_weights(traits, mood, hour=15)
    assert weights[Activity.TALK_COLLEAGUE] > weights[Activity.DESK_SIT]


def test_morning_boosts_kitchen():
    traits = AgentTraits()
    mood = AgentMood()
    morning = compute_weights(traits, mood, hour=9)
    afternoon = compute_weights(traits, mood, hour=15)
    assert morning[Activity.KITCHEN_COFFEE] > afternoon[Activity.KITCHEN_COFFEE]


def test_midday_boosts_lounge():
    traits = AgentTraits()
    mood = AgentMood()
    midday = compute_weights(traits, mood, hour=12)
    morning = compute_weights(traits, mood, hour=9)
    assert midday[Activity.LOUNGE_CHILL] > morning[Activity.LOUNGE_CHILL]


def test_select_activity_returns_valid():
    traits = AgentTraits()
    mood = AgentMood()
    activity = select_activity(traits, mood, hour=14)
    assert isinstance(activity, Activity)


def test_low_energy_avoids_wander():
    traits = AgentTraits()
    mood = AgentMood(energy=0.2)
    weights = compute_weights(traits, mood, hour=15)
    assert weights[Activity.WANDER_SHORT] < weights[Activity.DESK_SIT]


def test_weights_never_negative():
    traits = AgentTraits(focus=1.0, social=0.0)
    mood = AgentMood(energy=0.1)
    weights = compute_weights(traits, mood, hour=9)
    for w in weights.values():
        assert w >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_idle_behavior.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement idle_behavior.py**

```python
# backend/idle_behavior.py
from __future__ import annotations

import random
from enum import Enum

from backend.models import AgentTraits, AgentMood


class Activity(str, Enum):
    DESK_SIT = "desk_sit"
    KITCHEN_COFFEE = "kitchen_coffee"
    LOUNGE_CHILL = "lounge_chill"
    TALK_COLLEAGUE = "talk_colleague"
    WANDER_SHORT = "wander_short"
    PHONE_CALL = "phone_call"


# Base weights (sum = 100)
BASE_WEIGHTS: dict[Activity, int] = {
    Activity.DESK_SIT: 25,
    Activity.KITCHEN_COFFEE: 15,
    Activity.LOUNGE_CHILL: 15,
    Activity.TALK_COLLEAGUE: 20,
    Activity.WANDER_SHORT: 15,
    Activity.PHONE_CALL: 10,
}

# Trait modifiers: trait_condition -> {activity: delta}
TRAIT_MODIFIERS = [
    # (trait_name, threshold, above_or_below, deltas)
    ("focus", 0.7, "above", {
        Activity.DESK_SIT: 15, Activity.KITCHEN_COFFEE: -5,
        Activity.LOUNGE_CHILL: -10, Activity.TALK_COLLEAGUE: -5,
        Activity.WANDER_SHORT: 0, Activity.PHONE_CALL: 5,
    }),
    ("social", 0.6, "above", {
        Activity.DESK_SIT: -10, Activity.KITCHEN_COFFEE: 5,
        Activity.LOUNGE_CHILL: 10, Activity.TALK_COLLEAGUE: 15,
        Activity.WANDER_SHORT: 0, Activity.PHONE_CALL: -5,
    }),
    ("leadership", 0.7, "above", {
        Activity.DESK_SIT: -5, Activity.KITCHEN_COFFEE: 0,
        Activity.LOUNGE_CHILL: 0, Activity.TALK_COLLEAGUE: 15,
        Activity.WANDER_SHORT: 5, Activity.PHONE_CALL: -5,
    }),
]

# Mood modifier: low energy
ENERGY_LOW_MODIFIER = {
    Activity.DESK_SIT: 10, Activity.KITCHEN_COFFEE: 5,
    Activity.LOUNGE_CHILL: 10, Activity.TALK_COLLEAGUE: -10,
    Activity.WANDER_SHORT: -10, Activity.PHONE_CALL: -5,
}

# Time-of-day multipliers: hour_range -> {activity: multiplier}
TIME_PHASES = [
    (range(8, 11), {  # Morning
        Activity.DESK_SIT: 1.0, Activity.KITCHEN_COFFEE: 2.0,
        Activity.LOUNGE_CHILL: 0.5, Activity.TALK_COLLEAGUE: 1.5,
        Activity.WANDER_SHORT: 1.0, Activity.PHONE_CALL: 0.5,
    }),
    (range(11, 14), {  # Midday
        Activity.DESK_SIT: 0.5, Activity.KITCHEN_COFFEE: 1.0,
        Activity.LOUNGE_CHILL: 2.0, Activity.TALK_COLLEAGUE: 1.5,
        Activity.WANDER_SHORT: 1.0, Activity.PHONE_CALL: 1.0,
    }),
    (range(14, 19), {  # Afternoon
        Activity.DESK_SIT: 1.5, Activity.KITCHEN_COFFEE: 1.5,
        Activity.LOUNGE_CHILL: 1.0, Activity.TALK_COLLEAGUE: 0.8,
        Activity.WANDER_SHORT: 0.8, Activity.PHONE_CALL: 1.0,
    }),
]


def compute_weights(traits: AgentTraits, mood: AgentMood, hour: int) -> dict[Activity, float]:
    weights = {a: float(w) for a, w in BASE_WEIGHTS.items()}

    # Apply trait modifiers
    for trait_name, threshold, direction, deltas in TRAIT_MODIFIERS:
        val = getattr(traits, trait_name, 0.5)
        applies = val > threshold if direction == "above" else val < threshold
        if applies:
            for act, delta in deltas.items():
                weights[act] += delta

    # Apply mood modifier (low energy)
    if mood.energy < 0.4:
        for act, delta in ENERGY_LOW_MODIFIER.items():
            weights[act] += delta

    # Apply time-of-day multipliers
    time_mult = None
    for hour_range, mults in TIME_PHASES:
        if hour in hour_range:
            time_mult = mults
            break

    if time_mult:
        for act in weights:
            weights[act] *= time_mult.get(act, 1.0)

    # Clamp negatives to 0
    for act in weights:
        if weights[act] < 0:
            weights[act] = 0

    return weights


def select_activity(traits: AgentTraits, mood: AgentMood, hour: int) -> Activity:
    weights = compute_weights(traits, mood, hour)
    activities = list(weights.keys())
    w = [weights[a] for a in activities]
    total = sum(w)
    if total == 0:
        return Activity.DESK_SIT
    return random.choices(activities, weights=w, k=1)[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_idle_behavior.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/idle_behavior.py tests/test_idle_behavior.py
git commit -m "feat: personality + time-of-day weighted idle activity selection"
```

---

### Task 3: Config, DB, and Notification Router Updates

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/database.py`
- Modify: `backend/notification_router.py`
- Modify: `.env`

- [ ] **Step 1: Add initiative settings to config.py**

Add after line 31 (`llm_routing_enabled`):

```python
    # Initiative Engine
    initiative_enabled: bool = True
    initiative_interval_min: int = 900
    initiative_interval_max: int = 1800
    initiative_max_per_day: int = 10
    initiative_approval_timeout: int = 7200
```

- [ ] **Step 2: Add initiatives table to database.py**

In `_create_tables()`, add after the `personality_log` CREATE TABLE:

```python
            CREATE TABLE IF NOT EXISTS initiatives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                initiative_type TEXT NOT NULL,
                size TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            );
```

Add two helper methods to the Database class:

```python
    async def create_initiative(self, agent_id: str, title: str, description: str,
                                 initiative_type: str, size: str) -> int:
        async with self.db.execute(
            "INSERT INTO initiatives (agent_id, title, description, initiative_type, size, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, title, description, initiative_type, size,
             "running" if size == "small" else "proposed"),
        ) as cursor:
            await self.db.commit()
            return cursor.lastrowid

    async def update_initiative(self, initiative_id: int, status: str, result: str | None = None) -> None:
        if result:
            await self.db.execute(
                "UPDATE initiatives SET status = ?, result = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, result, initiative_id),
            )
        else:
            await self.db.execute(
                "UPDATE initiatives SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, initiative_id),
            )
        await self.db.commit()

    async def get_pending_initiatives(self) -> list[dict]:
        async with self.db.execute(
            "SELECT id, agent_id, title, description, initiative_type, size, status, created_at "
            "FROM initiatives WHERE status = 'proposed'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {"id": r[0], "agent_id": r[1], "title": r[2], "description": r[3],
                 "initiative_type": r[4], "size": r[5], "status": r[6], "created_at": r[7]}
                for r in rows
            ]

    async def count_today_initiatives(self) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) FROM initiatives WHERE date(created_at) = date('now')"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
```

- [ ] **Step 3: Add initiative events to notification_router.py**

Add to `ROUTING_TABLE`:

```python
    "initiative_completed": RoutingRule(telegram=True,  obsidian=True,  hybrid_check=False),
    "initiative_proposed":  RoutingRule(telegram=True,  obsidian=False, hybrid_check=False),
```

Add cases to `_format_telegram`:

```python
            case "initiative_completed":
                return f"🔍 *{name}* hat recherchiert: \"{title}\". Details in Obsidian."
            case "initiative_proposed":
                return f"💡 *{name}* schlägt vor: \"{title}\" — {content[:200]}. Soll ich das umsetzen? (ja/nein)"
```

Add case to `_write_obsidian`:

```python
            case "initiative_completed":
                ini_type = payload.get("initiative_type", "")
                md = (
                    f"# {title}\n"
                    f"- **Agent**: {agent}\n"
                    f"- **Typ**: {ini_type}\n"
                    f"- **Datum**: {timestamp}\n"
                    f"- **Status**: Abgeschlossen\n\n"
                    f"{result}\n"
                )
                slug = title[:50].lower().replace(" ", "-").replace("/", "-")
                await self.obsidian.execute({
                    "action": "write",
                    "path": f"KI-Büro/Initiativen/{timestamp[:10]}-{slug}.md",
                    "content": md,
                })
```

- [ ] **Step 4: Add config to .env**

Append to `.env`:

```env
INITIATIVE_ENABLED=true
INITIATIVE_INTERVAL_MIN=900
INITIATIVE_INTERVAL_MAX=1800
INITIATIVE_MAX_PER_DAY=10
```

- [ ] **Step 5: Run all existing tests to verify nothing broke**

Run: `python -m pytest tests/ -v -x`
Expected: All 243+ tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/database.py backend/notification_router.py .env
git commit -m "feat: config, DB schema, and routing for initiatives"
```

---

### Task 4: Simplify Sim Engine

**Files:**
- Modify: `backend/sim_engine.py`

- [ ] **Step 1: Remove LLM idle calls from sim_engine.py**

Replace the entire `_tick_agent` method and the `tick` method. The sim engine should now only:
1. Apply mood decay to idle agents
2. No longer generate actions or move agents

Replace `backend/sim_engine.py` entirely:

```python
# backend/sim_engine.py
from __future__ import annotations

from backend.models import AgentState

MOOD_BASELINE = {
    "energy": 0.7,
    "stress": 0.15,
    "motivation": 0.6,
    "frustration": 0.0,
}


class SimEngine:
    """Minimal sim engine — mood decay for idle agents.

    Movement and idle behavior are handled by the frontend FSM.
    Proactive work is handled by the initiative engine.
    """

    def __init__(self, agents, llm, relationship_engine=None, personality_engine=None):
        self.agents = agents
        self.llm = llm
        self.relationship_engine = relationship_engine
        self.personality_engine = personality_engine

    async def tick(self) -> list[dict]:
        # Mood decay for idle agents
        for agent in self.agents:
            if agent.data.state.value.startswith("idle"):
                self._decay_mood(agent)
        return []

    def _decay_mood(self, agent):
        mood = agent.data.mood
        rate = 0.05
        for field, baseline in MOOD_BASELINE.items():
            current = getattr(mood, field)
            new_val = current + (baseline - current) * rate
            setattr(mood, field, round(new_val, 4))
```

- [ ] **Step 2: Run sim_engine tests**

Run: `python -m pytest tests/test_sim_engine.py -v`
Expected: Some tests may fail because they test the old LLM-based behavior. Fix or replace them:

```python
# tests/test_sim_engine.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.sim_engine import SimEngine, MOOD_BASELINE
from backend.models import AgentData, AgentState, AgentTraits, AgentMood, AgentRole, Position


def make_agent(state=AgentState.IDLE_SIT, energy=0.5):
    data = AgentData(
        id="test", name="Test", role=AgentRole.CODER_1,
        state=state, position=Position(x=10, y=10),
        traits=AgentTraits(), mood=AgentMood(energy=energy),
    )
    agent = MagicMock()
    agent.data = data
    agent.personality_description = "test agent"
    return agent


@pytest.mark.asyncio
async def test_tick_returns_empty_events():
    agent = make_agent()
    engine = SimEngine(agents=[agent], llm=MagicMock())
    events = await engine.tick()
    assert events == []


@pytest.mark.asyncio
async def test_mood_decay_toward_baseline():
    agent = make_agent(energy=0.3)
    engine = SimEngine(agents=[agent], llm=MagicMock())
    await engine.tick()
    # energy should move toward 0.7 baseline
    assert agent.data.mood.energy > 0.3


@pytest.mark.asyncio
async def test_no_mood_decay_for_working_agents():
    agent = make_agent(state=AgentState.WORK_TYPE, energy=0.3)
    engine = SimEngine(agents=[agent], llm=MagicMock())
    await engine.tick()
    assert agent.data.mood.energy == 0.3
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_sim_engine.py -v`
Expected: All PASS

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v -x`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/sim_engine.py tests/test_sim_engine.py
git commit -m "refactor: simplify sim engine — remove LLM idle calls, mood decay only"
```

---

### Task 5: Backend Wiring — Zones in full_state + Talk Request

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Load zones at startup and include in full_state**

In `lifespan()`, after `agentSprites.initPathfinder(map)` equivalent (after `pool` is created), add zone loading:

```python
    # Load office zones from tilemap
    from backend.office_zones import load_zones
    tilemap_path = Path(__file__).parent.parent / "frontend" / "assets" / "office.tmj"
    office_zones = load_zones(tilemap_path) if tilemap_path.exists() else []
```

Store as module-level variable:

```python
office_zones: list = []  # Add near other globals at top of file
```

Modify `websocket_endpoint` to include zones:

```python
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    from backend.office_zones import Zone
    zones_data = [z.to_dict() for z in office_zones]
    await ws.send_json({
        "type": "full_state",
        "agents": pool.get_agents_state(),
        "zones": zones_data,
    })
    try:
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data, ws)
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)
```

- [ ] **Step 2: Add talk request handler**

Add WS message handler for talk requests from the frontend:

```python
async def handle_ws_message(data: dict, ws: WebSocket = None):
    msg_type = data.get("type", "")

    if msg_type == "request_talk":
        agent_id = data.get("agent", "")
        partner_id = data.get("partner", "")
        agent = pool.get_agent(agent_id)
        partner = pool.get_agent(partner_id)
        if agent and partner:
            try:
                message = await llm_client.chat(
                    system_prompt=(
                        f"Du bist {agent.data.name}, {agent.data.role.value} im KI-Büro. "
                        f"Sage einen kurzen, lockeren Satz zu {partner.data.name}. "
                        f"Max 15 Wörter. Deutsch. Kein Anführungszeichen."
                    ),
                    messages=[{"role": "user", "content": "Sag was."}],
                    model=llm_client.model_light,
                    temperature=0.9,
                )
                await ws_mgr.broadcast({
                    "type": "talk",
                    "agent": agent_id,
                    "partner": partner_id,
                    "message": message[:100],
                })
            except Exception:
                pass  # LLM failure is non-critical for chat

    elif msg_type == "submit_task":
        # Existing task submission from UI
        title = data.get("title", "")
        desc = data.get("description", title)
        if title:
            task_id = await orchestrator.submit_task(title=title[:100], description=desc)
            event = await orchestrator.assign_next_task()
            if event:
                await ws_mgr.broadcast(event)
```

- [ ] **Step 3: Update existing handle_ws_message calls**

Find the existing `await handle_ws_message(data)` call in `websocket_endpoint` and update to pass `ws`:

```python
            await handle_ws_message(data, ws)
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v -x`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: zones in full_state, talk request WS handler"
```

---

### Task 6: Frontend — Zone-Based Idle Behavior

**Files:**
- Modify: `frontend/agents.js`
- Modify: `frontend/game.js`

- [ ] **Step 1: Pass zone data to AgentSprites in game.js**

In the `full_state` WebSocket handler, pass zones:

```javascript
    window.ws.on('full_state', (data) => {
        console.log('Agents:', data.agents.length);
        if (data.zones) {
            agentSprites.setZones(data.zones);
            console.log('Zones:', data.zones.length);
        }
        agentSprites.createAgents(data.agents);
    });
```

Add handling for `talk` events with partner (the new format):

```javascript
    window.ws.on('talk', (data) => {
        if (data.x !== undefined) agentSprites.updateAgent(data);
        agentSprites.showBubble(data.agent, data.message);
        if (data.partner) {
            agentSprites.showBubble(data.partner, '🗣️', 2000);
        }
    });
```

- [ ] **Step 2: Add zone storage and activity system to agents.js**

Add these constants and the `setZones` method after the existing constants block:

```javascript
// ── Idle activities with durations (seconds) ─────────────────
const ACTIVITY = {
    DESK_SIT:        { zone: null,      durMin: 15, durMax: 60, anim: 'sit' },
    KITCHEN_COFFEE:  { zone: 'kitchen', durMin: 5,  durMax: 15, anim: 'idle_anim' },
    LOUNGE_CHILL:    { zone: 'lounge',  durMin: 15, durMax: 40, anim: 'sit' },
    TALK_COLLEAGUE:  { zone: null,      durMin: 8,  durMax: 20, anim: 'idle_anim' },
    WANDER_SHORT:    { zone: null,      durMin: 3,  durMax: 8,  anim: 'idle_anim' },
    PHONE_CALL:      { zone: null,      durMin: 10, durMax: 25, anim: 'phone' },
};

// ── Personality weights (matches backend idle_behavior.py) ───
const BASE_WEIGHTS = {
    DESK_SIT: 25, KITCHEN_COFFEE: 15, LOUNGE_CHILL: 15,
    TALK_COLLEAGUE: 20, WANDER_SHORT: 15, PHONE_CALL: 10,
};

const TRAIT_MODS = [
    { trait: 'focus',      threshold: 0.7, deltas: { DESK_SIT: 15, KITCHEN_COFFEE: -5, LOUNGE_CHILL: -10, TALK_COLLEAGUE: -5, WANDER_SHORT: 0, PHONE_CALL: 5 } },
    { trait: 'social',     threshold: 0.6, deltas: { DESK_SIT: -10, KITCHEN_COFFEE: 5, LOUNGE_CHILL: 10, TALK_COLLEAGUE: 15, WANDER_SHORT: 0, PHONE_CALL: -5 } },
    { trait: 'leadership', threshold: 0.7, deltas: { DESK_SIT: -5, KITCHEN_COFFEE: 0, LOUNGE_CHILL: 0, TALK_COLLEAGUE: 15, WANDER_SHORT: 5, PHONE_CALL: -5 } },
];

const ENERGY_MOD = { DESK_SIT: 10, KITCHEN_COFFEE: 5, LOUNGE_CHILL: 10, TALK_COLLEAGUE: -10, WANDER_SHORT: -10, PHONE_CALL: -5 };

const TIME_MULTS = [
    { hours: [8,9,10],       mults: { DESK_SIT: 1.0, KITCHEN_COFFEE: 2.0, LOUNGE_CHILL: 0.5, TALK_COLLEAGUE: 1.5, WANDER_SHORT: 1.0, PHONE_CALL: 0.5 } },
    { hours: [11,12,13],     mults: { DESK_SIT: 0.5, KITCHEN_COFFEE: 1.0, LOUNGE_CHILL: 2.0, TALK_COLLEAGUE: 1.5, WANDER_SHORT: 1.0, PHONE_CALL: 1.0 } },
    { hours: [14,15,16,17,18], mults: { DESK_SIT: 1.5, KITCHEN_COFFEE: 1.5, LOUNGE_CHILL: 1.0, TALK_COLLEAGUE: 0.8, WANDER_SHORT: 0.8, PHONE_CALL: 1.0 } },
];

function selectActivity(traits, mood, hour) {
    const w = { ...BASE_WEIGHTS };
    for (const { trait, threshold, deltas } of TRAIT_MODS) {
        if ((traits?.[trait] || 0.5) > threshold) {
            for (const [act, d] of Object.entries(deltas)) w[act] += d;
        }
    }
    if ((mood?.energy || 0.7) < 0.4) {
        for (const [act, d] of Object.entries(ENERGY_MOD)) w[act] += d;
    }
    const phase = TIME_MULTS.find(p => p.hours.includes(hour));
    if (phase) {
        for (const act of Object.keys(w)) w[act] *= (phase.mults[act] || 1.0);
    }
    for (const act of Object.keys(w)) { if (w[act] < 0) w[act] = 0; }
    const total = Object.values(w).reduce((s, v) => s + v, 0);
    if (total === 0) return 'DESK_SIT';
    let r = Math.random() * total;
    for (const [act, wt] of Object.entries(w)) {
        r -= wt;
        if (r <= 0) return act;
    }
    return 'DESK_SIT';
}
```

Add `setZones` method and zone tile picker to the class:

```javascript
    setZones(zones) {
        this.zones = {};
        for (const z of zones) {
            if (!this.zones[z.type]) this.zones[z.type] = [];
            this.zones[z.type].push(z);
        }
    }

    _pickZoneTile(zoneType) {
        const zoneList = this.zones?.[zoneType];
        if (!zoneList || zoneList.length === 0) return null;
        const zone = zoneList[Math.floor(Math.random() * zoneList.length)];
        // Pick random tile within zone bounds
        const col = zone.x + Math.floor(Math.random() * Math.max(1, zone.w));
        const row = zone.y + Math.floor(Math.random() * Math.max(1, zone.h));
        return { col, row };
    }

    _findIdlePartner(excludeId) {
        for (const [id, ch] of Object.entries(this.chars)) {
            if (id === excludeId) continue;
            if (ch.state === State.IDLE || ch.state === State.TYPE) return id;
        }
        return null;
    }
```

- [ ] **Step 3: Replace _updateIdle with zone-based activity system**

Replace the `_updateIdle` method entirely:

```javascript
    _updateIdle(id, ch, dt) {
        if (ch.seatTimer < 0) ch.seatTimer = 0;

        // If became active → pathfind to seat
        if (ch.isActive) {
            const ub = this._seatUnblock(ch);
            const path = findPath(ch.tileCol, ch.tileRow, ch.seatCol, ch.seatRow, this.grid, this.mapW, this.mapH, ub);
            if (path && path.length > 0) {
                ch.path = path;
                ch.moveProgress = 0;
                ch.state = State.WALK;
                this._applyAnimation(id, ch);
            } else {
                ch.state = State.TYPE;
                ch.dir = ch.seatDir;
                this._applyAnimation(id, ch);
                this._syncSpritePosition(id, ch);
            }
            return;
        }

        // Currently doing an activity at destination?
        if (ch.idleActivity) {
            ch.activityTimer -= dt;
            if (ch.activityTimer <= 0) {
                ch.idleActivity = null;
                ch.wanderCount++;
                // After enough activities, go rest at seat
                if (ch.wanderCount >= ch.wanderLimit) {
                    const ub = this._seatUnblock(ch);
                    const path = findPath(ch.tileCol, ch.tileRow, ch.seatCol, ch.seatRow, this.grid, this.mapW, this.mapH, ub);
                    if (path && path.length > 0) {
                        ch.path = path;
                        ch.moveProgress = 0;
                        ch.state = State.WALK;
                        this._applyAnimation(id, ch);
                        return;
                    }
                }
            } else {
                return; // Still doing activity
            }
        }

        // Choose next activity
        ch.wanderTimer -= dt;
        if (ch.wanderTimer <= 0) {
            const hour = new Date().getHours();
            const act = selectActivity(ch.traits, ch.mood, hour);
            const actDef = ACTIVITY[act];
            let targetTile = null;

            if (act === 'DESK_SIT') {
                targetTile = { col: ch.seatCol, row: ch.seatRow };
            } else if (act === 'TALK_COLLEAGUE') {
                const partnerId = this._findIdlePartner(id);
                if (partnerId) {
                    const partner = this.chars[partnerId];
                    targetTile = { col: partner.tileCol, row: partner.tileRow };
                    // Request talk message from backend
                    if (window.ws?.send) {
                        window.ws.send(JSON.stringify({
                            type: 'request_talk', agent: id, partner: partnerId,
                        }));
                    }
                }
            } else if (act === 'WANDER_SHORT') {
                const dx = Math.round((Math.random() - 0.5) * 10);
                const dy = Math.round((Math.random() - 0.5) * 10);
                targetTile = {
                    col: Math.max(0, Math.min(this.mapW - 1, ch.tileCol + dx)),
                    row: Math.max(0, Math.min(this.mapH - 1, ch.tileRow + dy)),
                };
            } else if (act === 'PHONE_CALL') {
                // Stay in place
                ch.idleActivity = act;
                ch.activityTimer = randomRange(actDef.durMin, actDef.durMax);
                ch.backendState = 'idle_phone';
                this._applyAnimation(id, ch);
                ch.wanderTimer = randomRange(WANDER_PAUSE_MIN_SEC, WANDER_PAUSE_MAX_SEC);
                return;
            } else if (actDef.zone) {
                targetTile = this._pickZoneTile(actDef.zone);
            }

            if (targetTile) {
                const ub = this._seatUnblock(ch);
                const path = findPath(ch.tileCol, ch.tileRow, targetTile.col, targetTile.row, this.grid, this.mapW, this.mapH, ub);
                if (path && path.length > 0) {
                    ch.path = path;
                    ch.moveProgress = 0;
                    ch.state = State.WALK;
                    ch.pendingActivity = act;
                    this._applyAnimation(id, ch);
                }
            }

            ch.wanderTimer = randomRange(WANDER_PAUSE_MIN_SEC, WANDER_PAUSE_MAX_SEC);
        }
    }
```

- [ ] **Step 4: Update _arriveAtTile to handle pending activities**

Replace `_arriveAtTile`:

```javascript
    _arriveAtTile(id, ch) {
        const center = tileCenter(ch.tileCol, ch.tileRow);
        ch.x = center.x;
        ch.y = center.y;

        if (ch.isActive) {
            if (ch.tileCol === ch.seatCol && ch.tileRow === ch.seatRow) {
                ch.state = State.TYPE;
                ch.dir = ch.seatDir;
            } else {
                ch.state = State.IDLE;
            }
            ch.pendingActivity = null;
        } else if (ch.pendingActivity) {
            // Arrived at activity destination
            const act = ch.pendingActivity;
            const actDef = ACTIVITY[act];
            ch.pendingActivity = null;
            ch.idleActivity = act;
            ch.activityTimer = randomRange(actDef.durMin, actDef.durMax);

            // Set appropriate animation
            if (act === 'DESK_SIT' || act === 'LOUNGE_CHILL') {
                ch.backendState = 'idle_sit';
            } else if (act === 'KITCHEN_COFFEE') {
                ch.backendState = 'idle_coffee';
            } else if (act === 'TALK_COLLEAGUE') {
                ch.backendState = 'idle_talk';
            } else {
                ch.backendState = 'idle_wander';
            }
            ch.state = State.IDLE;

            // Check if arrived at seat for rest
            if (ch.tileCol === ch.seatCol && ch.tileRow === ch.seatRow && !ch.idleActivity) {
                ch.state = State.TYPE;
                ch.dir = ch.seatDir;
                ch.seatTimer = randomRange(SEAT_REST_MIN_SEC, SEAT_REST_MAX_SEC);
                ch.wanderCount = 0;
                ch.wanderLimit = randomInt(WANDER_MOVES_BEFORE_REST_MIN, WANDER_MOVES_BEFORE_REST_MAX);
            }
        } else {
            // No pending activity — returning to seat or generic arrival
            if (ch.tileCol === ch.seatCol && ch.tileRow === ch.seatRow) {
                ch.state = State.TYPE;
                ch.dir = ch.seatDir;
                if (ch.seatTimer < 0) {
                    ch.seatTimer = 0;
                } else {
                    ch.seatTimer = randomRange(SEAT_REST_MIN_SEC, SEAT_REST_MAX_SEC);
                }
                ch.wanderCount = 0;
                ch.wanderLimit = randomInt(WANDER_MOVES_BEFORE_REST_MIN, WANDER_MOVES_BEFORE_REST_MAX);
            } else {
                ch.state = State.IDLE;
                ch.wanderTimer = randomRange(WANDER_PAUSE_MIN_SEC, WANDER_PAUSE_MAX_SEC);
            }
        }

        this._applyAnimation(id, ch);
        this._syncSpritePosition(id, ch);
    }
```

- [ ] **Step 5: Add traits/mood to character state in createAgent**

In `createAgent`, add traits and mood to the `ch` object (after the `currentTool` field):

```javascript
            traits: agent.traits || {},
            mood: agent.mood || {},
            // Activity system
            idleActivity: null,
            activityTimer: 0,
            pendingActivity: null,
```

- [ ] **Step 6: Initialize zones to empty in constructor**

In the `AgentSprites` constructor, add:

```javascript
        this.zones = {};
```

- [ ] **Step 7: Manual test — verify agents go to zones**

Start the server (`python -m backend.main`), open browser, observe:
- Agents should walk to Küche, Lounge, etc. instead of random tiles
- Agents should sit at their desk periodically
- `talk_colleague` should trigger speech bubbles on both agents
- Agents should not walk into walls

- [ ] **Step 8: Commit**

```bash
git add frontend/agents.js frontend/game.js
git commit -m "feat: zone-based idle behavior with personality + time-of-day weights"
```

---

### Task 7: Initiative Engine

**Files:**
- Create: `backend/initiative_engine.py`
- Create: `tests/test_initiative_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_initiative_engine.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from backend.initiative_engine import InitiativeEngine, ROLE_INITIATIVES, classify_size


def test_role_initiatives_cover_all_roles():
    from backend.models import AgentRole
    for role in AgentRole:
        assert role.value in ROLE_INITIATIVES


def test_classify_size_small():
    assert classify_size("KLEIN") == "small"
    assert classify_size("klein") == "small"


def test_classify_size_large():
    assert classify_size("GROSS") == "large"
    assert classify_size("gross") == "large"
    assert classify_size("unknown") == "large"  # default to large (safer)


@pytest.mark.asyncio
async def test_pick_agent_selects_idle():
    idle_agent = MagicMock()
    idle_agent.data.state.value = "idle_sit"
    idle_agent.data.role.value = "researcher"
    idle_agent.data.mood.motivation = 0.8

    busy_agent = MagicMock()
    busy_agent.data.state.value = "work_type"
    busy_agent.data.role.value = "coder_1"

    engine = InitiativeEngine(
        agents=[idle_agent, busy_agent],
        llm=MagicMock(), db=MagicMock(), pool=MagicMock(),
        orchestrator=MagicMock(), router=MagicMock(), ws_mgr=MagicMock(),
    )
    agent = engine._pick_agent()
    assert agent == idle_agent


@pytest.mark.asyncio
async def test_pick_agent_returns_none_if_all_busy():
    busy = MagicMock()
    busy.data.state.value = "work_type"
    engine = InitiativeEngine(
        agents=[busy], llm=MagicMock(), db=MagicMock(), pool=MagicMock(),
        orchestrator=MagicMock(), router=MagicMock(), ws_mgr=MagicMock(),
    )
    assert engine._pick_agent() is None


@pytest.mark.asyncio
async def test_generate_idea_parses_response():
    engine = InitiativeEngine(
        agents=[], llm=MagicMock(), db=MagicMock(), pool=MagicMock(),
        orchestrator=MagicMock(), router=MagicMock(), ws_mgr=MagicMock(),
    )
    engine.llm.chat = AsyncMock(return_value="Neuer AI-Trend | Cursor hat Background Agents | KLEIN")
    agent = MagicMock()
    agent.data.name = "Amelia"
    agent.data.role.value = "researcher"
    title, desc, size = await engine._generate_idea(agent)
    assert title == "Neuer AI-Trend"
    assert "Cursor" in desc
    assert size == "small"


@pytest.mark.asyncio
async def test_generate_idea_handles_bad_format():
    engine = InitiativeEngine(
        agents=[], llm=MagicMock(), db=MagicMock(), pool=MagicMock(),
        orchestrator=MagicMock(), router=MagicMock(), ws_mgr=MagicMock(),
    )
    engine.llm.chat = AsyncMock(return_value="Just a plain string without pipes")
    agent = MagicMock()
    agent.data.name = "Test"
    agent.data.role.value = "ops"
    title, desc, size = await engine._generate_idea(agent)
    assert title  # should still produce something
    assert size == "large"  # default to large when unparseable
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_initiative_engine.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement initiative_engine.py**

```python
# backend/initiative_engine.py
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime

from backend.config import settings
from backend.models import AgentState

logger = logging.getLogger(__name__)

ROLE_INITIATIVES: dict[str, dict] = {
    "pm":        {"type": "strategy",    "focus": "Projekt-Priorisierung, Roadmap-Vorschläge, Ressourcen-Planung"},
    "team_lead": {"type": "process",     "focus": "Team-Effizienz, Bottleneck-Analyse, Prozessverbesserung"},
    "coder_1":   {"type": "code",        "focus": "Neue Libraries, Refactoring-Ideen, Performance-Optimierung"},
    "coder_2":   {"type": "code",        "focus": "Neue Libraries, Refactoring-Ideen, Performance-Optimierung"},
    "researcher":{"type": "trend_research","focus": "Neue AI-Tools, Tech-Trends, Paper-Zusammenfassungen"},
    "writer":    {"type": "content",     "focus": "Dokumentation, Blog-Ideen, Zusammenfassungen, Content-Strategie"},
    "ops":       {"type": "automation",  "focus": "Shell-Scripts, Cron-Jobs, Workflow-Optimierung, Automatisierung"},
}


def classify_size(raw: str) -> str:
    if "klein" in raw.strip().lower():
        return "small"
    return "large"


class InitiativeEngine:
    def __init__(self, agents, llm, db, pool, orchestrator, router, ws_mgr):
        self.agents = agents
        self.llm = llm
        self.db = db
        self.pool = pool
        self.orchestrator = orchestrator
        self.router = router
        self.ws_mgr = ws_mgr

    def _pick_agent(self):
        idle = [a for a in self.agents if a.data.state.value.startswith("idle")]
        if not idle:
            return None
        # Weight by motivation trait
        weights = [max(0.1, a.data.mood.motivation) for a in idle]
        return random.choices(idle, weights=weights, k=1)[0]

    async def _generate_idea(self, agent) -> tuple[str, str, str]:
        role = agent.data.role.value
        info = ROLE_INITIATIVES.get(role, {"type": "general", "focus": "Allgemeine Verbesserungen"})
        prompt = (
            f"Du bist {agent.data.name}, {role} im KI-Büro. "
            f"Schlage EINE konkrete Initiative vor die für den User nützlich wäre. "
            f"Fokus: {info['focus']}. "
            f"Antworte EXAKT im Format: TITEL | BESCHREIBUNG | KLEIN oder GROSS\n"
            f"KLEIN = nur Recherche nötig, GROSS = braucht Tools/Implementierung."
        )
        try:
            response = await self.llm.chat(
                system_prompt=prompt,
                messages=[{"role": "user", "content": "Schlage eine Initiative vor."}],
                model=self.llm.model_light,
                temperature=0.9,
            )
            parts = response.split("|")
            if len(parts) >= 3:
                title = parts[0].strip()
                desc = parts[1].strip()
                size = classify_size(parts[2])
            elif len(parts) == 2:
                title = parts[0].strip()
                desc = parts[1].strip()
                size = "large"
            else:
                title = response.strip()[:80]
                desc = response.strip()
                size = "large"
            return title, desc, size
        except Exception as e:
            logger.warning("Initiative idea generation failed: %s", e)
            return "", "", "large"

    async def _execute_small(self, agent, initiative_id: int, title: str, desc: str, ini_type: str):
        # Set agent to working state
        agent.data.state = AgentState.WORK_TYPE
        try:
            result = await self.llm.chat(
                system_prompt=(
                    f"Du bist {agent.data.name}. Recherchiere und erstelle einen kurzen Bericht zu: {title}\n"
                    f"Beschreibung: {desc}\n"
                    f"Format: Markdown mit ## Zusammenfassung, ## Relevanz für dich, ## Empfehlung.\n"
                    f"Max 500 Wörter. Deutsch."
                ),
                messages=[{"role": "user", "content": f"Erstelle den Bericht zu: {title}"}],
                model=self.llm.model_heavy,
                temperature=0.7,
            )
            await self.db.update_initiative(initiative_id, "completed", result)

            # Route to Obsidian + Telegram
            await self.router.route_event("initiative_completed", {
                "agent_name": agent.data.name,
                "task_title": title,
                "result": result,
                "initiative_type": ini_type,
            })

            # Broadcast to frontend
            await self.ws_mgr.broadcast({
                "type": "task_completed",
                "agent": agent.data.id,
            })
        except Exception as e:
            logger.error("Initiative execution failed: %s", e)
            await self.db.update_initiative(initiative_id, "failed")
        finally:
            agent.data.state = AgentState.IDLE_SIT

    async def _propose_large(self, agent, initiative_id: int, title: str, desc: str):
        await self.router.route_event("initiative_proposed", {
            "agent_name": agent.data.name,
            "task_title": title,
            "content": desc,
            "initiative_id": initiative_id,
        })

    async def run_once(self):
        if not settings.initiative_enabled:
            return

        count = await self.db.count_today_initiatives()
        if count >= settings.initiative_max_per_day:
            return

        agent = self._pick_agent()
        if not agent:
            return

        title, desc, size = await self._generate_idea(agent)
        if not title:
            return

        role = agent.data.role.value
        ini_type = ROLE_INITIATIVES.get(role, {}).get("type", "general")

        initiative_id = await self.db.create_initiative(
            agent_id=agent.data.id,
            title=title,
            description=desc,
            initiative_type=ini_type,
            size=size,
        )

        if size == "small":
            await self._execute_small(agent, initiative_id, title, desc, ini_type)
        else:
            await self._propose_large(agent, initiative_id, title, desc)

    async def loop(self):
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Initiative loop error: %s", e)
            interval = random.randint(settings.initiative_interval_min, settings.initiative_interval_max)
            await asyncio.sleep(interval)

    async def expire_stale(self):
        """Expire proposals that have been pending too long."""
        pending = await self.db.get_pending_initiatives()
        for ini in pending:
            created = datetime.fromisoformat(ini["created_at"])
            age = (datetime.now() - created).total_seconds()
            if age > settings.initiative_approval_timeout:
                await self.db.update_initiative(ini["id"], "expired")

    async def approve(self, initiative_id: int):
        pending = await self.db.get_pending_initiatives()
        ini = next((i for i in pending if i["id"] == initiative_id), None)
        if not ini:
            return
        await self.db.update_initiative(initiative_id, "approved")
        await self.orchestrator.submit_task(
            title=ini["title"][:100],
            description=ini["description"],
        )
        event = await self.orchestrator.assign_next_task()
        if event:
            await self.ws_mgr.broadcast(event)

    async def reject(self, initiative_id: int):
        await self.db.update_initiative(initiative_id, "rejected")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_initiative_engine.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/initiative_engine.py tests/test_initiative_engine.py
git commit -m "feat: initiative engine — proactive task generation with two-tier approval"
```

---

### Task 8: Wire Initiative Engine + Telegram Handling

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Start initiative loop in lifespan**

Add after the obsidian watcher block in `lifespan()`:

```python
    # Initiative Engine
    from backend.initiative_engine import InitiativeEngine
    initiative_engine = InitiativeEngine(
        agents=pool.agents, llm=llm, db=db, pool=pool,
        orchestrator=orchestrator, router=notification_router, ws_mgr=ws_mgr,
    )
    initiative_task = None
    if settings.initiative_enabled:
        initiative_task = asyncio.create_task(initiative_engine.loop())
        print("Initiative engine active")
```

Add `initiative_engine` and `initiative_task` to module globals. Add cleanup in shutdown:

```python
    if initiative_task:
        initiative_task.cancel()
        try:
            await initiative_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 2: Add telegram ja/nein handling**

In `handle_telegram_message`, add a check before the chat fallback (`else` block at line 221):

```python
    # --- Initiative approval (ja/nein) ---
    elif text.lower() in ("ja", "nein", "yes", "no"):
        if initiative_engine:
            pending = await db.get_pending_initiatives()
            if pending:
                latest = pending[-1]  # Most recent proposal
                if text.lower() in ("ja", "yes"):
                    await initiative_engine.approve(latest["id"])
                    await telegram.send_message(f"✅ Initiative genehmigt: {latest['title']}")
                else:
                    await initiative_engine.reject(latest["id"])
                    await telegram.send_message(f"❌ Initiative abgelehnt: {latest['title']}")
            else:
                await _chat_with_gemma(text, chat_id)
```

- [ ] **Step 3: Add periodic stale-expiry to sim_loop**

In `sim_loop`, after the daily report check, add:

```python
            # Expire stale initiative proposals every 100 ticks (~5 min)
            if initiative_engine and tick_count % 100 == 0:
                await initiative_engine.expire_stale()
```

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v -x`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: wire initiative engine, telegram approval, stale expiry"
```

---

### Task 9: Integration Smoke Test

**Files:**
- Create: `tests/test_integration_initiative.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_initiative.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from backend.initiative_engine import InitiativeEngine
from backend.models import AgentData, AgentState, AgentTraits, AgentMood, AgentRole, Position


def make_idle_agent(agent_id="researcher", name="Amelia", role=AgentRole.RESEARCHER):
    data = AgentData(
        id=agent_id, name=name, role=role,
        state=AgentState.IDLE_SIT, position=Position(x=20, y=25),
        traits=AgentTraits(curiosity=0.9), mood=AgentMood(motivation=0.8),
    )
    agent = MagicMock()
    agent.data = data
    return agent


@pytest.mark.asyncio
async def test_small_initiative_full_flow():
    agent = make_idle_agent()
    db = MagicMock()
    db.count_today_initiatives = AsyncMock(return_value=0)
    db.create_initiative = AsyncMock(return_value=1)
    db.update_initiative = AsyncMock()

    llm = MagicMock()
    llm.model_light = "test"
    llm.model_heavy = "test"
    # First call: idea generation
    # Second call: report generation
    llm.chat = AsyncMock(side_effect=[
        "AI Trend Update | Neue Modelle von Anthropic | KLEIN",
        "## Zusammenfassung\nAnthropic hat Claude 4 released.\n## Relevanz\nSehr relevant.\n## Empfehlung\nTesten.",
    ])

    router = MagicMock()
    router.route_event = AsyncMock()
    ws_mgr = MagicMock()
    ws_mgr.broadcast = AsyncMock()

    engine = InitiativeEngine(
        agents=[agent], llm=llm, db=db, pool=MagicMock(),
        orchestrator=MagicMock(), router=router, ws_mgr=ws_mgr,
    )

    await engine.run_once()

    db.create_initiative.assert_called_once()
    assert db.create_initiative.call_args[1]["size"] == "small"
    db.update_initiative.assert_called_once_with(1, "completed", pytest.approx(str, abs=True))
    router.route_event.assert_called_once_with("initiative_completed", pytest.approx(dict, abs=True))
    # Agent should be back to idle
    assert agent.data.state == AgentState.IDLE_SIT


@pytest.mark.asyncio
async def test_large_initiative_creates_proposal():
    agent = make_idle_agent(agent_id="ops", name="Max", role=AgentRole.OPS)
    db = MagicMock()
    db.count_today_initiatives = AsyncMock(return_value=0)
    db.create_initiative = AsyncMock(return_value=2)

    llm = MagicMock()
    llm.model_light = "test"
    llm.chat = AsyncMock(return_value="Backup Automatisieren | Cron-Job für tägliche Backups | GROSS")

    router = MagicMock()
    router.route_event = AsyncMock()

    engine = InitiativeEngine(
        agents=[agent], llm=llm, db=db, pool=MagicMock(),
        orchestrator=MagicMock(), router=router, ws_mgr=MagicMock(),
    )

    await engine.run_once()

    db.create_initiative.assert_called_once()
    assert db.create_initiative.call_args[1]["size"] == "large"
    router.route_event.assert_called_once_with("initiative_proposed", pytest.approx(dict, abs=True))


@pytest.mark.asyncio
async def test_daily_limit_prevents_initiative():
    agent = make_idle_agent()
    db = MagicMock()
    db.count_today_initiatives = AsyncMock(return_value=10)

    engine = InitiativeEngine(
        agents=[agent], llm=MagicMock(), db=db, pool=MagicMock(),
        orchestrator=MagicMock(), router=MagicMock(), ws_mgr=MagicMock(),
    )

    await engine.run_once()
    # Should not call create_initiative
    db.create_initiative.assert_not_called()
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_integration_initiative.py -v`
Expected: All 3 PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_initiative.py
git commit -m "test: integration tests for initiative engine flow"
```
