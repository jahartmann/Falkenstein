# Lebendiges Büro & Proaktive Agenten

**Datum**: 2026-04-03
**Status**: Approved

## Übersicht

Zwei Features die das KI-Büro lebendig machen:
1. **POI-basiertes Idle-Verhalten**: Agenten gehen zu echten Orten (Küche, Lounge) statt wahllos zu wandern
2. **Proaktive Initiativen**: Agenten generieren eigenständig Tasks (Trend-Recherche, Automatisierungsvorschläge)

---

## Teil 1: POI-System & Idle-Verhalten

### 1.1 Zonen aus Tilemap

Die `Benamung`-Objektlayer der Tilemap wird ausgelesen. Jede Zone bekommt einen Typ und walkable Tiles innerhalb ihres Rechtecks.

| Zone | Typ | Aktivität |
|---|---|---|
| Küche | `kitchen` | Kaffee holen, kurze Gespräche |
| Lounge | `lounge` | Chillen, lange Gespräche, Pause |
| Gemeinschaftsraum | `social` | Gruppengespräche, Brainstorming |
| Team Büro | `desk_area` | Arbeiten |
| Fokus-Büro | `focus` | Tiefe Arbeit, allein |
| Deep-Dive 1+2 | `focus` | Tiefe Arbeit, allein |
| Teamleitung | `desk_area` | Arbeiten |
| Büro Boss | `desk_area` | Arbeiten |

**Implementierung**:
- Backend: Neues Modul `backend/office_zones.py` parst die Tilemap-JSON, extrahiert Zone-Rechtecke aus `Benamung`-Layer
- Die Zone-Daten werden beim Start geladen und per WebSocket (`full_state`) ans Frontend gesendet
- Frontend: `agents.js` bekommt Zone-Koordinaten und wählt Ziel-Tiles innerhalb von Zonen statt random

### 1.2 Idle-Aktivitäten

Sechs mögliche Idle-Aktivitäten ersetzen das bisherige Random-Wandern:

| Aktivität | Ziel-Zone | Dauer am Ziel | Verhalten |
|---|---|---|---|
| `desk_sit` | Eigener Sitz | 15-60s | Sitz-Animation, gelegentlich Phone |
| `kitchen_coffee` | Küche | 5-15s | Stehen, evtl. kurzes Gespräch |
| `lounge_chill` | Lounge | 15-40s | Sitz-Animation, entspannt |
| `talk_colleague` | Position eines anderen idle Agents | 8-20s | Nebeneinander stehen, Speech-Bubbles |
| `wander_short` | Zufälliges Tile max 5 Tiles vom aktuellen Standort | 3-8s | Kurzer Spaziergang, dann weiter |
| `phone_call` | Aktueller Standort | 10-25s | Phone-Animation, stationär |

### 1.3 Persönlichkeitsgesteuerte Gewichtung

Basis-Gewichte pro Aktivität, moduliert durch Agent-Traits. Kein LLM-Call nötig.

**Basis-Gewichte** (normalisiert auf 100):

```
desk_sit: 25, kitchen_coffee: 15, lounge_chill: 15, talk_colleague: 20, wander_short: 15, phone_call: 10
```

**Trait-Modifikatoren** (additiv, auf Basis-Gewicht):

| Trait | desk_sit | kitchen | lounge | talk | wander | phone |
|---|---|---|---|---|---|---|
| focus > 0.7 | +15 | -5 | -10 | -5 | 0 | +5 |
| social > 0.6 | -10 | +5 | +10 | +15 | 0 | -5 |
| leadership > 0.7 | -5 | 0 | 0 | +15 | +5 | -5 |
| energy < 0.4 | +10 | +5 | +10 | -10 | -10 | -5 |

Ergebnis-Gewichte werden normalisiert und per Weighted-Random eine Aktivität gewählt.

**Beispiel-Ergebnisse**:
- Alex (focus=0.9, social=0.5): desk_sit=40%, kitchen=10%, lounge=5%, talk=15%, wander=15%, phone=15%
- Clara (social=0.7): desk_sit=15%, kitchen=20%, lounge=25%, talk=35%, wander=5%, phone=0%
- Star (PM, social=0.8, leadership=0.9): desk_sit=10%, kitchen=15%, lounge=10%, talk=50%, wander=10%, phone=5%

### 1.4 Tageszeit-Modifikatoren

Drei Phasen basierend auf echter Systemzeit:

| Phase | Stunden | kitchen | lounge | desk_sit | talk | wander | phone |
|---|---|---|---|---|---|---|---|
| Morgens | 8-11 | x2.0 | x0.5 | x1.0 | x1.5 | x1.0 | x0.5 |
| Mittags | 11-14 | x1.0 | x2.0 | x0.5 | x1.5 | x1.0 | x1.0 |
| Nachmittags | 14-18 | x1.5 | x1.0 | x1.5 | x0.8 | x0.8 | x1.0 |

Tageszeit-Multiplikatoren werden auf die Trait-modulierten Gewichte angewendet, dann normalisiert.

### 1.5 Frontend FSM-Änderungen

Der bestehende 3-State FSM (TYPE/IDLE/WALK) bleibt, aber IDLE-Logik ändert sich:

**Alt (IDLE → random tile):**
```
wanderTimer fires → pick random walkable tile → BFS → WALK
```

**Neu (IDLE → gezielte Aktivität):**
```
wanderTimer fires → weighted random Aktivität → resolve Ziel-Zone/Tile → BFS → WALK → Aktivität am Ziel
```

Neuer Sub-State in IDLE: `idleActivity` speichert was der Agent gerade tut (für Animation + Dauer):
- `null` = noch keine Aktivität gewählt, Timer läuft
- `kitchen_coffee` = steht in der Küche, Timer für Rückkehr
- `lounge_chill` = sitzt in der Lounge
- `talk_colleague` = steht neben Kollege, Speech-Bubble aktiv
- etc.

Wenn `idleActivity` abgelaufen: nächste Aktivität wählen oder zum Sitz zurückkehren.

### 1.6 Backend-Anpassung

`sim_engine.py` wird vereinfacht:
- Der LLM-Call für `generate_sim_action()` entfällt (spart Tokens!)
- Backend sendet nur noch State-Changes (`idle` / `work_*`) und die Zonen-Daten
- Alle Idle-Bewegungslogik läuft im Frontend (wie schon jetzt, aber mit POIs)
- `talk`-Events mit LLM-generierten Nachrichten bleiben: wenn das Frontend `talk_colleague` triggert, sendet es ein WebSocket-Event `{ type: "request_talk", agent: "coder_1", partner: "writer" }` ans Backend. Backend generiert per LLM eine Nachricht und antwortet mit `{ type: "talk", agent: "coder_1", partner: "writer", message: "..." }`. Frontend zeigt Speech-Bubble über beiden Agenten.

---

## Teil 2: Proaktive Agenten

### 2.1 Initiative-Loop

Neues Modul `backend/initiative_engine.py`. Läuft als asyncio-Task parallel zum Sim-Loop.

**Intervall**: Alle 15-30 Minuten (konfigurierbar) wird geprüft:
1. Gibt es idle Agenten? (nicht bereits arbeitend)
2. Tages-Limit nicht erreicht? (max 10/Tag)
3. Weighted-Random wählt einen Agent basierend auf Rolle + Motivation-Trait

### 2.2 Rollen-spezifische Initiativen

| Agent | Rolle | Initiative-Typen | Prompt-Fokus |
|---|---|---|---|
| Amelia | Researcher | Trend-Recherche | Neue AI-Tools, Tech-News, Paper |
| Max | Ops | Automatisierung | Shell-Scripts, Cron-Jobs, Workflows |
| Alex/Bob | Coder | Code-Verbesserung | Libraries, Refactoring, Performance |
| Clara | Writer | Content | Docs, Blog-Ideen, Zusammenfassungen |
| Star | PM | Strategie | Priorisierung, Roadmap |
| Nina | Team Lead | Prozess | Team-Effizienz, Bottlenecks |

### 2.3 Zwei-Stufen-System

**Stufe 1 — Klein (autonom)**:
- Nur LLM-Recherche, kein Tool-Einsatz (kein Shell/CLI/Web)
- Agent wird `active`, geht zum Desk, "arbeitet"
- LLM generiert Recherche-Ergebnis (model_heavy für Qualität)
- Ergebnis → Obsidian + Telegram-Notification
- Agent wird wieder idle

**Stufe 2 — Groß (Vorschlag)**:
- Würde Tools brauchen (Shell, CLI, Code-Ausführung, Web-Suche)
- Vorschlag → Telegram: "💡 Max schlägt vor: Dein Backup-Script automatisieren. Soll ich?"
- User antwortet "ja" → wird als normaler Task via `submit_task()` eingereicht
- User antwortet "nein" oder Timeout (2h) → verworfen
- Pending-Vorschläge werden in DB gespeichert (neue Tabelle `initiatives`)

### 2.4 Ideen-Generierung

Pro Initiative zwei LLM-Calls:

**Call 1 — Idee generieren** (model_light, ~50 tokens):
```
System: Du bist {name}, {rolle} im KI-Büro. Schlage EINE konkrete Initiative vor
die für den User nützlich wäre. Typ: {initiative_typ}.
Antworte mit: TITEL | BESCHREIBUNG | KLEIN oder GROSS
```

**Call 2 — Ausarbeitung** (nur bei KLEIN, model_heavy, ~500 tokens):
```
System: Recherchiere und erstelle einen kurzen Bericht zu: {titel}
Format: Markdown mit Zusammenfassung, Relevanz, Empfehlung.
```

### 2.5 Output

**Obsidian** — Pfad: `KI-Büro/Initiativen/YYYY-MM-DD-{slug}.md`

```markdown
# {Titel}
- **Agent**: {Name} ({Rolle})
- **Typ**: {Trend-Recherche | Automatisierung | ...}
- **Datum**: YYYY-MM-DD HH:MM
- **Status**: Abgeschlossen | Vorgeschlagen

## Zusammenfassung
...

## Relevanz für dich
...

## Empfehlung
...
```

**Telegram**:
- Klein: `🔍 {Name} hat recherchiert: "{Titel}". Details in Obsidian.`
- Groß: `💡 {Name} schlägt vor: "{Titel}" — {Kurzbeschreibung}. Soll ich das umsetzen? (ja/nein)`

### 2.6 Telegram-Antwort-Handling

Erweitert `handle_telegram_message()` in `main.py`:
- Antworten "ja"/"nein" auf einen pending Vorschlag werden erkannt
- "ja" → `orchestrator.submit_task()` mit der Beschreibung
- "nein" → Initiative als `rejected` markiert
- Timeout: Background-Task prüft alle 30min auf abgelaufene Vorschläge

### 2.7 DB-Schema

Neue Tabelle `initiatives`:
```sql
CREATE TABLE initiatives (
    id INTEGER PRIMARY KEY,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    initiative_type TEXT NOT NULL,  -- trend_research, automation, code, content, strategy, process
    size TEXT NOT NULL,             -- small, large
    status TEXT NOT NULL,           -- running, completed, proposed, approved, rejected, expired
    result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);
```

### 2.8 Konfiguration

```env
INITIATIVE_ENABLED=true
INITIATIVE_INTERVAL_MIN=900
INITIATIVE_INTERVAL_MAX=1800
INITIATIVE_MAX_PER_DAY=10
INITIATIVE_APPROVAL_TIMEOUT=7200
```

Neue Settings in `config.py`:
```python
initiative_enabled: bool = True
initiative_interval_min: int = 900
initiative_interval_max: int = 1800
initiative_max_per_day: int = 10
initiative_approval_timeout: int = 7200
```

---

## Dateien die geändert/erstellt werden

### Neue Dateien
- `backend/office_zones.py` — Tilemap-Parser für Zonen
- `backend/initiative_engine.py` — Proaktive Task-Generierung
- `backend/idle_behavior.py` — Persönlichkeits- + Tageszeit-gewichtete Aktivitätswahl
- `tests/test_office_zones.py`
- `tests/test_initiative_engine.py`
- `tests/test_idle_behavior.py`

### Geänderte Dateien
- `frontend/agents.js` — IDLE-FSM: Zonen-basiert statt random, Aktivitäten mit Dauer
- `frontend/game.js` — Zone-Daten aus `full_state` empfangen und an AgentSprites übergeben
- `backend/main.py` — Initiative-Loop starten, Telegram-Antwort-Handling, Zonen in `full_state`
- `backend/sim_engine.py` — LLM-Idle-Calls entfernen, vereinfachen
- `backend/config.py` — Initiative-Settings
- `backend/database.py` — `initiatives`-Tabelle
- `backend/notification_router.py` — Neue Events `initiative_completed`, `initiative_proposed`
- `.env` — Initiative-Config
