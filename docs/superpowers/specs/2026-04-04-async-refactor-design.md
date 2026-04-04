# Falkenstein Async Refactor — Design Spec

**Datum:** 2026-04-04
**Ziel:** Falkenstein von synchron/blockierend auf vollständig async umbauen. SQLite als Single Source of Truth. Telegram + Admin Dashboard als Steuerung. Obsidian als Managed Knowledge Base.

---

## 1. Kernprinzipien

- **SQLite = Single Source of Truth** für Tasks, Schedules, Config, Facts, Agent-State
- **Telegram = Remote-Steuerung** (funktioniert von überall)
- **Admin Dashboard = Lokale Schaltzentrale** (localhost:8800, Full Control + Config)
- **Obsidian = Managed Knowledge Base** (Falkenstein liest & schreibt, kein Watcher/Input-Kanal)
- **Alles async** — sofortige Antworten, SubAgents als Background-Tasks
- **Standalone-fähig** — neue Installation komplett über Dashboard konfigurierbar

---

## 2. Datenarchitektur

### 2.1 SQLite-Tabellen

Bestehend (unverändert):
- `agents` — Agent Identity, State, Grid Position
- `tasks` — Task Lifecycle (open/in_progress/done), Result
- `messages` — Inter-Agent Messages
- `tool_log` — Tool Call History
- `facts` — LLM-extracted User/Project Knowledge

Neu:

**`schedules`**
```sql
CREATE TABLE schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    schedule TEXT NOT NULL,
    agent_type TEXT DEFAULT 'researcher',
    prompt TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    active_hours TEXT,
    light_context INTEGER DEFAULT 0,
    last_run TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

**`config`**
```sql
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
```

Config-Categories: `llm`, `paths`, `personality`, `api_keys`, `general`

### 2.2 Bootstrap `.env` (minimal)

```env
PORT=8800
DB_PATH=./data/falkenstein.db
TELEGRAM_TOKEN=xxx
```

Alles andere (LLM-Routing, Obsidian-Pfad, Brave API Key, SOUL-Prompt, Model-Settings) lebt in der `config`-Tabelle und wird beim ersten Start mit Defaults befüllt.

### 2.3 Config-Defaults (Seed bei Erststart)

| key | value | category |
|---|---|---|
| `soul_prompt` | Inhalt von SOUL.md | personality |
| `obsidian_vault_path` | `~/Obsidian` | paths |
| `workspace_path` | `./workspace` | paths |
| `ollama_model` | `gemma4:26b` | llm |
| `ollama_light_model` | `gemma3:4b` | llm |
| `llm_provider_classify` | `ollama` | llm |
| `llm_provider_action` | `ollama` | llm |
| `llm_provider_content` | `ollama` | llm |
| `llm_provider_scheduled` | `ollama` | llm |
| `brave_api_key` | (leer) | api_keys |
| `obsidian_enabled` | `true` | general |
| `obsidian_auto_knowledge` | `true` | general |

---

## 3. Async-Architektur

### 3.1 Background-Task Dispatch

Jeder Input kehrt sofort zurück. SubAgents laufen als `asyncio.Task`:

```python
# main_agent.py — nach classify()
if decision in ("action", "content"):
    task_obj = asyncio.create_task(self._run_agent(sub, chat_id, ...))
    self.active_agents[agent_id] = task_obj
    return "Agent gestartet"  # sofort zurück
```

Bei Fertigstellung (Callback/done-Handler):
1. Telegram: Ergebnis-Nachricht senden
2. SQLite: `tasks.status = 'done'`, `tasks.result = ...`
3. Obsidian: Ergebnis-Note + Kanban-Update (wenn `content` und smart-classify sagt "wissenswert")
4. WebSocket: `agent_done` Event an Dashboard
5. `active_agents` Dict: Entry entfernen

### 3.2 Telegram-Loop (nicht-blockierend)

```python
# telegram_bot.py
for msg in messages:
    asyncio.create_task(handler(msg))  # statt await handler(msg)
```

### 3.3 Scheduler (parallel)

```python
# scheduler.py
for task in due:
    self.mark_run(task)  # DB update statt JSON file
    asyncio.create_task(self._on_task_due(task))  # statt await wait_for()
```

Scheduler liest aus `schedules`-Tabelle statt Obsidian .md Files.

### 3.4 Agent-Tracking

```python
class MainAgent:
    active_agents: dict[str, asyncio.Task] = {}

    async def cancel_agent(self, agent_id: str):
        if task := self.active_agents.get(agent_id):
            task.cancel()
            del self.active_agents[agent_id]
```

### 3.5 Sync File-I/O eliminieren

Alle `Path.read_text()` / `Path.write_text()` in async Context werden zu:
- `await asyncio.to_thread(path.read_text, ...)` für Obsidian-Operationen
- Oder direkt `aiosqlite` für DB-Reads (wo Obsidian-Reads durch DB-Reads ersetzt werden)

---

## 4. Admin Dashboard

### 4.1 Überblick

- URL: `http://localhost:8800/` (ersetzt Phaser.js Büro)
- Tech: Vanilla HTML/JS/CSS (kein Framework, wie bestehendes `/admin`)
- Live-Updates via WebSocket
- Responsive (Desktop-first, aber nutzbar auf Tablet)

### 4.2 Tabs

**Dashboard (Startseite)**
- Aktive Agents mit Status, Laufzeit, Task-Beschreibung (live via WS)
- Letzte 10 abgeschlossene Tasks mit Ergebnis-Preview
- System-Status: Ollama-Verbindung, Telegram-Status, Obsidian-Pfad
- Nächste fällige Schedules

**Tasks**
- Tabelle: alle Tasks, filterbar nach Status (open/in_progress/done)
- Task-Detail: Beschreibung, Ergebnis (vollständig), Tool-Log
- "Neuer Task" Button → Agent-Typ wählen, Prompt eingeben, absenden
- "Abbrechen" Button für laufende Tasks

**Schedules**
- Tabelle: alle Schedules mit Status (aktiv/inaktiv), nächste Ausführung, letzte Ausführung
- Erstellen: Name, Schedule-Ausdruck, Agent-Typ, Prompt
- Editieren: Inline oder Modal
- Toggle aktiv/inaktiv
- "Jetzt ausführen" Button
- Löschen mit Bestätigung

**Config**
- Gruppiert nach Category (LLM, Paths, Personality, API Keys, General)
- SOUL-Prompt: Textarea mit Syntax-Highlighting (optional)
- LLM-Routing: Dropdowns pro Task-Typ (ollama/claude/gemini)
- API-Keys: Password-Fields
- Pfade: Text-Inputs mit Validierung
- "Speichern" pro Sektion, Änderungen sofort wirksam (kein Restart)

### 4.3 API-Endpoints

```
GET    /api/status              — Aktive Agents, System-Info
GET    /api/tasks               — Task-Liste (query: ?status=open)
POST   /api/tasks               — Neuen Task starten
POST   /api/tasks/:id/cancel    — Agent abbrechen
GET    /api/tasks/:id           — Task-Detail mit Tool-Log

GET    /api/schedules           — Alle Schedules
POST   /api/schedules           — Schedule erstellen
PUT    /api/schedules/:id       — Schedule editieren
DELETE /api/schedules/:id       — Schedule löschen
POST   /api/schedules/:id/run   — Sofort ausführen
POST   /api/schedules/:id/toggle — Aktiv/Inaktiv toggle

GET    /api/config              — Alle Config-Werte (query: ?category=llm)
PUT    /api/config              — Config-Werte setzen (batch)
GET    /api/config/:key         — Einzelner Config-Wert
PUT    /api/config/:key         — Einzelner Config-Wert setzen

WebSocket /ws                   — Live-Events (erweitert)
```

### 4.4 WebSocket Events (erweitert)

```json
{"type": "agent_spawned", "agent_id": "...", "task": "...", "agent_type": "..."}
{"type": "agent_progress", "agent_id": "...", "iteration": 3, "tool": "web_search"}
{"type": "agent_done", "agent_id": "...", "result_preview": "...", "status": "done"}
{"type": "agent_error", "agent_id": "...", "error": "..."}
{"type": "schedule_triggered", "schedule_id": 1, "name": "..."}
{"type": "config_changed", "key": "...", "value": "..."}
```

---

## 5. Obsidian — Managed Knowledge Base

### 5.1 Rolle

Obsidian ist eine aktive Wissensbasis die Falkenstein verwaltet. Kein Input-Kanal (kein Watcher).

**Falkenstein darf:**
- Notes lesen (als Kontext für Tasks, RAG)
- Notes schreiben und aktualisieren
- Ordner erstellen und strukturieren
- Kanban-Board pflegen
- Ergebnis-Notes ablegen

**Wann wird in Obsidian geschrieben:**
Smart-Klassifikation durch MainAgent. Bei `content`-Tasks entscheidet die Klassifikation ob das Ergebnis wissenswert ist. `action`-Tasks schreiben nur auf expliziten User-Wunsch.

### 5.2 Bestehender obsidian_manager.py

Bleibt als Tool für SubAgents. Kann bereits:
- `read_note(path)` — Note lesen
- `write_note(path, content)` — Note schreiben/erstellen
- `list_folder(path)` — Ordnerinhalt
- `create_folder(path)` — Ordner anlegen

### 5.3 Obsidian optional

Config-Key `obsidian_enabled`. Wenn `false`, werden keine Obsidian-Writes ausgeführt. Ergebnisse bleiben nur in SQLite. Ermöglicht Installationen ohne Obsidian.

---

## 6. Was wegfällt

| Komponente | Grund |
|---|---|
| `obsidian_watcher.py` | Kein Input-Kanal mehr, Tasks kommen über Telegram/Dashboard |
| Schedule `.md` Files | Source of Truth ist SQLite |
| `.last_run.json` | `last_run` Spalte in `schedules`-Tabelle |
| Phaser.js Büro (`game.js`, Tiled Maps, Sprites) | Ersetzt durch Admin Dashboard |
| Meiste `.env`-Variablen | Wandern in `config`-Tabelle |
| `_build_context()` Obsidian-Reads | Kontext kommt aus SQLite (offene Tasks, aktive Agents) |

---

## 7. Migration

### 7.1 Bestehende Schedules

Beim ersten Start mit neuem Code:
1. Prüfe ob `KI-Büro/Schedules/*.md` existieren
2. Parse YAML-Frontmatter + Body
3. INSERT INTO `schedules`
4. Log: "N Schedules aus Obsidian migriert"

### 7.2 Bestehende `.env`-Config

Beim ersten Start:
1. Lese bestehende `.env`-Werte
2. Seed `config`-Tabelle mit diesen Werten (überschreibe Defaults)
3. Log: "Config aus .env migriert"

---

## 8. Nicht im Scope

- Auth/Login für Dashboard (kommt später wenn remote-fähig)
- Obsidian-Watcher als optionaler Input-Kanal (kann später wieder aktiviert werden)
- Phaser.js Büro-Visualisierung (kann später als Widget zurückkommen)
- Multi-User Support
- Encryption für API-Keys in DB
