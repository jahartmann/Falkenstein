# Falkenstein Smart Assistant — Refactor Design

**Datum:** 2026-04-04
**Ansatz:** Refactor Core (Ansatz B) — bestehendes umbauen, radikal vereinfachen

## Zusammenfassung

Umbau von "gamifiziertes 7-Agenten-Büro" zu "1 smarter Assistent mit SubAgents on demand".
Telegram als Steuerung & Alerts, Obsidian als Wissens- & Ergebnisbasis, Büro-UI als passiver Live-Monitor.

## Architektur

```
Telegram ──→ MainAgent ──→ Obsidian (Ergebnisse, Kanban, Tasks)
Obsidian Inbox ──→ MainAgent      ↑
                      │            │
                      ├─ quick_reply (direkt via Telegram)
                      └─ task (SubAgent spawnen)
                            ├─ CoderAgent (Shell, CodeExecutor)
                            ├─ ResearcherAgent (WebSurfer, Vision)
                            ├─ WriterAgent (Obsidian)
                            └─ OpsAgent (Shell, System)

Büro-UI ←── WebSocket ←── Nur aktive Agents anzeigen
```

### MainAgent (`main_agent.py`)

Das Gehirn des Systems. Ein einzelner Agent der:

1. **Input empfängt** von Telegram oder Obsidian-Watcher
2. **Klassifiziert** per LLM-Call:
   - `quick_reply` — Direkt beantwortbar (Fragen, Status, Smalltalk)
   - `task` — Braucht Arbeit + SubAgent-Typ (coder/researcher/writer/ops)
3. **Quick Reply:** Antwort direkt via Telegram
4. **Task:**
   - Sofortige Telegram-Bestätigung
   - Task-Note in Obsidian erstellen, Kanban auf "In Progress"
   - SubAgent spawnen
   - Ergebnis in Obsidian (passender Ordner), Kanban auf "Done"
   - Kurze Zusammenfassung + Link via Telegram

**LLM:** Gemma 4 via Ollama (Default), Gemini CLI oder Claude CLI per `.env`-Config.

### SubAgents (`sub_agent.py`)

Leichtgewichtige, kurzlebige Agenten:

- Werden on-demand erstellt, nicht permanent am Laufen
- Jeder hat ein fokussiertes Tool-Set:
  - **CoderAgent:** `shell_runner`, `code_executor`
  - **ResearcherAgent:** `web_surfer`, `vision`
  - **WriterAgent:** `obsidian_manager`
  - **OpsAgent:** `shell_runner`
- Laufen async, melden Ergebnis an MainAgent zurück
- Werden im Büro sichtbar solange sie arbeiten, verschwinden danach
- **Keine Subtask-Zerlegung.** Ein Task = ein SubAgent = ein Ergebnis = eine Telegram-Nachricht.

### Telegram-Bot (`telegram_bot.py` — überarbeitet)

Vereinfacht auf:
- **Freitext** → an MainAgent weiterleiten
- `/status` — Aktive SubAgents + deren Tasks
- `/stop` — Laufenden Task abbrechen
- Alles andere → MainAgent

Kein eigener LLM-Chat mehr im Bot. Alles geht durch MainAgent.

### Obsidian-Watcher (`obsidian_watcher.py` — überarbeitet)

- Hört weiterhin auf `Inbox.md` und `Tasks.md` per watchdog
- Neue Einträge gehen direkt an MainAgent (statt über NotificationRouter)
- `obsidian_auto_submit_tasks` Default auf `True`

## Obsidian-Struktur

```
KI-Büro/
├── Management/
│   ├── Inbox.md              ← User-Input (Watcher hört zu)
│   └── Kanban.md             ← Task-Board
├── Falkenstein/
│   ├── Tasks/
│   │   └── 2026-04-04-recherche-xyz.md
│   ├── Ergebnisse/
│   │   ├── Recherchen/
│   │   ├── Guides/
│   │   ├── Cheat-Sheets/
│   │   ├── Reports/
│   │   └── Code/
│   ├── Projekte/
│   │   └── <projekt-name>/
│   │       ├── README.md
│   │       ├── Tasks.md
│   │       └── Notizen.md
│   └── Daily Reports/
│       └── 2026-04-04.md
```

### Kanban-Flow (`Kanban.md`)

```markdown
## Backlog
- [ ] [[Tasks/2026-04-04-recherche-xyz|Recherche XYZ]] #recherche

## In Progress
- [ ] [[Tasks/2026-04-04-script-backup|Backup Script]] #code 🤖 coder

## Done
- [x] [[Tasks/2026-04-03-vergleich-docker|Docker vs Podman]] #recherche ✅
```

Schritte:
1. Task rein → Note in `Tasks/`, Eintrag in Kanban unter `## Backlog`
2. SubAgent startet → Kanban-Eintrag zu `## In Progress`
3. Fertig → Ergebnis in passenden `Ergebnisse/`-Unterordner, Kanban zu `## Done`

### Task-Notes (YAML-Frontmatter)

```yaml
---
typ: recherche|code|guide|cheat-sheet|report
status: backlog|in_progress|done
agent: researcher|coder|writer|ops
erstellt: 2026-04-04
---
```

### Ergebnis-Typ-Routing

MainAgent entscheidet anhand des Tasks:
- "Recherchiere X" → `Ergebnisse/Recherchen/`
- "Wie macht man X" → `Ergebnisse/Guides/`
- "Gib mir eine Übersicht zu X" → `Ergebnisse/Cheat-Sheets/`
- "Schreib ein Script für X" → `Ergebnisse/Code/`
- Daily Report → `Daily Reports/`

## Büro-UI (passives Dashboard)

### Was sich ändert:
- **Kein Sim-Loop** — keine 3-Sekunden-Ticks, kein Idle-Wandern
- **MainAgent** sitzt immer an seinem Platz, ist immer "bereit"
- **SubAgents** erscheinen nur wenn sie arbeiten, verschwinden wenn fertig
- **Speech Bubbles** zeigen aktuelle Tätigkeit
- **WebSocket** pusht nur bei echten Zustandsänderungen: `agent_spawned`, `agent_working`, `agent_done`

### Was wegfällt:
- Idle-States (wander, talk, coffee, phone)
- Personality/Mood-System
- Relationship-Tracking
- Spieler-Character (WASD)
- BFS-Pathfinding

### Was bleibt:
- Tilemap + Büro-Grafik
- Agent-Sprites an Schreibtischen
- Klick auf Agent → Detail-Panel (Task, Dauer, Tools)

## Was bleibt / geht / neu

### Bleibt:
- FastAPI + WebSockets
- aiosqlite/SQLite (tasks, messages, tool_log)
- Tools: `shell_runner`, `code_executor`, `web_surfer`, `vision`, `obsidian_manager`
- Telegram-Bot (Polling-Loop, vereinfacht)
- Obsidian-Watcher (watchdog, direkt an MainAgent)
- Phaser.js + Tilemap (nur Rendering)
- pydantic-settings + `.env`
- `cli_bridge.py` (Gemini/Claude CLI)

### Wird entfernt:
- `sim_engine.py`
- `pm_logic.py`
- `team_lead.py`
- `personality_engine.py` / `relationship_engine.py`
- `agent_pool.py` (7 feste Agenten)
- `orchestrator.py`
- `notification_router.py`
- Frontend: Player-Character, Idle-FSM, BFS-Pathfinding

### Neu zu bauen:
- `main_agent.py` — Klassifizierung, Routing, direkte Antworten
- `sub_agent.py` — Leichtgewichtige SubAgent-Klasse
- `obsidian_writer.py` — Kanban-Updates, Ergebnis-Routing, Frontmatter
- Überarbeitete `main.py` — Schlanker Lifespan
- Überarbeitete `telegram_bot.py` — Alles durch MainAgent
- Überarbeitete Frontend-Dateien — Passive Agent-Anzeige

### LLM-Config (`.env`):
```
LLM_BACKEND=ollama        # ollama | gemini_cli | claude_cli
OLLAMA_MODEL=gemma3:27b
```
