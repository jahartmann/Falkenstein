# Falkenstein Jarvis Phase 1 — Design Spec

**Datum:** 2026-04-08
**Scope:** MCP-Integration + Admin UI Command Center + Pixel-Büro Upgrade
**Phase 2 (separat):** Voice bidirektional, Proaktives Lernen

---

## 1. Überblick

Falkenstein wird von einem Chat-basierten Agent-System zu einem vollwertigen Personal Assistant transformiert — vergleichbar mit Jarvis oder OpenClaw. Phase 1 schafft die Grundlage: echte Gerätekonnektivität via MCP, ein professionelles Command Center als Admin UI, und ein atmosphärisches Pixel-Büro als Chill-Modus.

### Kernprinzip

Alles ist organisch integriert — keine aufgesetzten Komponenten, sondern ein zusammenhängendes System. MCP-Tools fühlen sich an wie native Fähigkeiten, die Admin UI ist das zentrale Gateway, das Pixel-Büro eine alternative Visualisierung derselben Daten.

### Zielplattform

Dedizierter Mac Studio mit Apple ID. Läuft nur Ollama + Falkenstein. Volle Systemkontrolle erlaubt.

---

## 2. MCP-Bridge Architektur

### Neue Dateien

```
backend/mcp/
├── __init__.py
├── bridge.py          # MCPBridge Singleton — Lifecycle, Health, Tool-Routing
├── registry.py        # Server-Registry — Config, Status, Discovery
├── tool_adapter.py    # MCP-Tools → CrewAI BaseTool Wrapper
└── config.py          # Server-Definitionen, Pydantic Models
```

### MCPBridge (bridge.py)

Singleton, initialisiert beim FastAPI-Start nach EventBus.

**Verantwortlichkeiten:**
- Startet MCP Server als Subprozesse (stdio-Transport, JSON-RPC 2.0)
- Überwacht Health (Heartbeat/Ping), restartet bei Crash
- Cached Tool-Schemas nach `tools/list` Discovery
- Proxied `tools/call` — CrewAI-Agent oder Flow ruft auf, Bridge routet zum richtigen Server
- Hot-Reload: Server können über Admin UI an/ausgeschaltet werden ohne Backend-Neustart

**Interface:**
```python
class MCPBridge:
    async def start() -> None                    # Alle enabled Server starten
    async def stop() -> None                     # Graceful shutdown
    async def restart_server(server_id: str)     # Einzelnen Server neustarten
    async def toggle_server(server_id: str, enabled: bool)
    async def list_servers() -> list[ServerStatus]
    async def list_tools(server_id: str) -> list[ToolSchema]
    async def call_tool(server_id: str, tool_name: str, args: dict) -> ToolResult
    async def discover_tools() -> list[MCPTool]  # Alle Tools aller Server
```

### Server-Registry (registry.py)

Konfiguration welche MCP Server verfügbar sind, aus `.env` + DB:

```python
class MCPServerConfig(BaseModel):
    id: str                    # z.B. "apple-mcp"
    name: str                  # z.B. "Apple Services"
    command: str               # z.B. "npx"
    args: list[str]            # z.B. ["-y", "apple-mcp"]
    env: dict[str, str]        # Server-spezifische Env Vars
    enabled: bool              # An/Aus Toggle
    auto_restart: bool         # Bei Crash neustarten

class ServerStatus(BaseModel):
    config: MCPServerConfig
    status: str                # "running" | "stopped" | "error"
    pid: int | None
    tools_count: int
    last_call: datetime | None
    uptime_seconds: float
```

### Tool-Adapter (tool_adapter.py)

Automatische Konvertierung MCP-Tool → CrewAI BaseTool:

```python
class MCPCrewTool(BaseTool):
    name: str              # z.B. "apple_create_reminder"
    description: str       # Aus MCP Schema
    mcp_server: str        # z.B. "apple-mcp"
    mcp_tool_name: str     # z.B. "create_reminder"
    args_schema: Type      # Dynamisch aus JSON-Schema generiert

    def _run(self, **kwargs) -> str:
        # Sync wrapper um bridge.call_tool()
        return asyncio.run(bridge.call_tool(self.mcp_server, self.mcp_tool_name, kwargs))
```

### MCP Server — Phase 1

| Server | Package | Transport | Tools |
|--------|---------|-----------|-------|
| **apple-mcp** | `apple-mcp` (npm) | stdio | create_reminder, list_reminders, create_event, list_events, create_note, search_notes, play_music, search_music, list_homekit_devices, control_homekit, send_message, read_mail |
| **desktop-commander** | `desktop-commander` (npm) | stdio | execute_command, list_processes, kill_process, read_file, write_file, search_files |
| **mcp-obsidian** | `mcp-obsidian` (npm) | stdio | read_note, write_note, search_vault, list_notes |

### Integration in Flow

Zwei Pfade — direkt oder via Crew:

**Direkt (einfache Befehle):**
```
"Mach Licht aus" → RuleEngine → route: "direct_mcp"
→ NativeOllamaClient.classify() → {server: "apple-mcp", tool: "control_homekit", args: {...}}
→ MCPBridge.call_tool() → Ergebnis → Telegram/UI Antwort
```
Kein CrewAI Overhead. Schnelle Antwortzeit.

**Via Crew (komplexe Aufgaben):**
```
"Recherchiere MCP Server und schreib einen Report" → RuleEngine → route: "crew:researcher"
→ CrewAI Crew mit MCP-Tools als verfügbare Tools
→ Agent entscheidet selbst welche Tools (inkl. MCP) er nutzt
```

**Crew-Tool-Zuordnung (erweitert):**

| Crew | Bestehende Tools | + MCP-Tools |
|------|-----------------|-------------|
| ops | ollama_manager, self_config, system_shell | desktop-commander (alle) |
| researcher | obsidian | mcp-obsidian, apple (notes, mail) |
| writer | obsidian | mcp-obsidian, apple (notes) |
| coder | code_executor, shell_runner | desktop-commander |
| **alle Crews** | — | apple (reminders, calendar, music, homekit) |

### .env Erweiterungen

```env
# MCP Configuration
MCP_SERVERS=apple-mcp,desktop-commander,mcp-obsidian
MCP_APPLE_ENABLED=true
MCP_DESKTOP_COMMANDER_ENABLED=true
MCP_OBSIDIAN_ENABLED=true
MCP_OBSIDIAN_VAULT_PATH=/path/to/obsidian/vault
MCP_NODE_PATH=npx
MCP_AUTO_RESTART=true
MCP_HEALTH_INTERVAL=30
```

### DB-Tabelle

```sql
CREATE TABLE mcp_calls (
    id INTEGER PRIMARY KEY,
    server_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args TEXT,           -- JSON
    result TEXT,         -- JSON
    success BOOLEAN,
    duration_ms INTEGER,
    triggered_by TEXT,   -- "crew:researcher" | "direct" | "proactive"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Admin UI — Command Center

### Tech-Stack

- **Vanilla HTML/CSS/JS** (wie bestehend, kein Framework)
- **CSS Custom Properties** für Light/Dark Theming
- **WebSocket** für Live-Updates (bestehender WS-Manager)
- **Kein Build-Step** — direkt serviert via FastAPI Static Files

### Design-Sprache

- **Light Mode (Default):** `--bg: #f8f9fa`, `--card-bg: #ffffff`, `--accent: #0ea5e9` (Teal-Blue), feine Schatten
- **Dark Mode:** `--bg: #0f172a`, `--card-bg: #1e293b`, gleiche Akzentfarbe, dezente Borders statt Schatten
- **Cards:** `border-radius: 12px`, `padding: 20px`, Header mit Icon + Titel, dezenter `box-shadow`
- **Font:** System Stack (`-apple-system, BlinkMacSystemFont, 'SF Pro', sans-serif`)
- **Toggle:** Sun/Moon Icon in der Top Bar, Preference in localStorage

### Layout

Sidebar (links, 220px, collapsible) + Top Bar (56px) + Main Content + Quick-Chat (unten, 60px, persistent).

### Sektionen

**Dashboard (Startseite):**
- Card-Grid (responsive, 3 Spalten):
  - **Active Agents:** Pulsierender Dot pro Agent, Name, Crew-Typ, Laufzeit
  - **MCP Servers:** Status-Dots (grün/rot), Anzahl Tools, letzter Call
  - **System Health:** CPU/RAM/GPU als Mini-Gauges
  - **Letzte Aktivitäten:** Chronologischer Feed (Icon + Text + Timestamp)
  - **Nächste Termine/Tasks:** Aus Apple Calendar + Falkenstein Tasks

**Agents:**
- Card pro Agent (aktiv = farbiger Border + Pulse, fertig = grau, Fehler = rot)
- Card-Inhalt: Name, Typ-Badge, Status, aktueller Task, Laufzeit, Tool-Log (collapsible)
- Progress-Bar wenn verfügbar

**Chat:**
- Vollbild-Chat, Message-Bubbles (User rechts blau, Falki links grau)
- Markdown-Rendering, Code-Blöcke mit Syntax-Highlighting
- Agent-Aktivität inline anzeigen (z.B. "🤖 Researcher gestartet...")
- Quick-Actions: Buttons für häufige Befehle

**Tasks:**
- Kanban mit 3 Spalten: Pending → Running → Done
- Drag & Drop (optional, nice-to-have)
- Task-Cards: Titel, Agent, Erstellt, Status-Badge

**MCP:**
- Card pro Server: Name, Status-Badge, Tool-Count, Uptime
- Expand: Alle Tools gelistet mit Beschreibung
- Actions: Restart, Enable/Disable
- Call-Log: Letzte 10 Calls mit Ergebnis

**Schedules:**
- Card pro Schedule: Name, Cron-Expression (human-readable), nächste Ausführung
- Actions: Run Now, Edit, Delete, Enable/Disable

**Memory:**
- 3-Tab Layout: User | Self | Relationship
- JSON/Text Editor pro Eintrag
- Timeline der Erinnerungen

**Obsidian:**
- Ordner-Browser links, Note-Vorschau rechts
- Quick-Create Button
- Letzte Notizen als Cards

**System:**
- CPU/RAM/GPU/Disk als kreisförmige Gauges
- Ollama Models als Cards (Name, Size, Modified)
- DB-Statistiken: Tabellen, Rows, Size

**Settings:**
- Kategorisiert in Tabs: Ollama | API Keys | Telegram | MCP | Personality | Server
- Form-Felder mit Labels, Save-Button pro Kategorie
- MCP Server Config: Pfade, Enable/Disable, Custom Args

### Quick-Chat Input

- Immer sichtbar am unteren Rand (alle Sektionen)
- Input + Send-Button + Voice-Button (Phase 2)
- Antworten als Toast-Notification (kurz) oder Chat-Sektion (lang)
- Keyboard-Shortcut: `/` fokussiert den Input

### API-Erweiterungen

```
GET  /api/admin/mcp/servers              # Alle Server + Status
POST /api/admin/mcp/servers/{id}/restart  # Server neustarten
POST /api/admin/mcp/servers/{id}/toggle   # An/Aus
GET  /api/admin/mcp/servers/{id}/tools    # Tool-Liste
GET  /api/admin/mcp/servers/{id}/logs     # Call-History
GET  /api/admin/agents/active             # Aktive Agents (ersetzt kaputtes get_status)
GET  /api/admin/dashboard                 # Erweitert: + MCP Status + nächste Termine
POST /api/admin/proactive/watchers        # Neuen Watcher anlegen
GET  /api/admin/proactive/watchers        # Alle Watcher listen
```

### Bestehende Bugs fixen

- `get_status()` → muss aktive Crews aus EventBus lesen, nicht aus altem MainAgent
- Externe Agents (Claude Code SubAgents) im Dashboard anzeigen
- WebSocket Reconnect-Logic verbessern

---

## 4. Pixel-Büro — Chill-Modus

### Konzept

Separate Fullscreen-View, erreichbar über Sidebar-Button. Atmosphärische Echtzeit-Visualisierung des Agent-Systems. Läuft nebenbei wie ein Lo-fi Girl Stream.

### Technisch

- Bestehende **Phaser.js 3.80** Basis erweitern
- **Tiled-Maps** (48px Tiles) — neue Map: gemütliches Büro mit Schreibtischen, Pflanzen, Kaffee
- **WebSocket-Events** vom EventBus treiben Animationen
- Eigene HTML-Seite (`pixel-buero.html`), gelinkt aus Admin UI

### Pixel-Charaktere

| Crew-Typ | Look | Desk-Position |
|----------|------|--------------|
| researcher | Brille, Buch | Schreibtisch 1 (Bibliothek-Ecke) |
| coder | Hoodie, Dual-Monitor | Schreibtisch 2 (Tech-Ecke) |
| writer | Stift, Notizbuch | Schreibtisch 3 (ruhige Ecke) |
| ops | Helm, Terminal | Schreibtisch 4 (Server-Rack) |
| analyst | Diagramme | Schreibtisch 5 |
| swift | Apple-Logo T-Shirt | Schreibtisch 2 (shared mit coder) |

### Animationen

| Event | Animation |
|-------|-----------|
| Agent spawnt | Charakter läuft von Tür zum Schreibtisch, setzt sich |
| `obsidian` Tool | Liest/schreibt in Buch |
| `shell_runner` / `code_executor` | Tippt am Terminal |
| `web_search` | Schaut auf Bildschirm mit Lupe |
| `apple_create_reminder` | Hält Notizblock hoch |
| MCP-Call (generisch) | Sprechblase mit Tool-Icon |
| Agent idle | Lehnt sich zurück, trinkt Kaffee |
| Agent fertig | Steht auf, stretcht, Partikel-Animation, verschwindet |
| Agent error | Rote Wolke über Kopf, kratzt sich |

### Musik-Player

- **Position:** Unten links im Pixel-Büro
- **HTML5 Audio API**, Playlist aus Config
- **Genres:** Lofi (Default), Jazz, Ambient, Classical — wählbar
- **Controls:** Play/Pause, Skip, Volume-Slider
- **Persistenz:** Musik läuft weiter bei kurzem Wechsel zur Admin UI (Audio-Context bleibt)
- **Playlist-Config** in Settings oder lokale MP3s in `frontend/music/`

### Stimmungselemente

- **Tageszeit-Beleuchtung:** Morgens hell/warm → Mittags klar → Abends warm/gedimmt → Nachts Lampenlicht + Sterne durchs Fenster
- **Ambiente-Sounds (optional):** Leises Tastatur-Klackern bei tippenden Agents, Papier-Rascheln beim Lesen
- **Dekoration:** Pflanzen, Kaffeetassen, Bücherregale, Poster — gibt dem Büro Persönlichkeit

### Activity Feed (Mini)

- Unten rechts: Kleines halbtransparentes Panel
- Zeigt letzte 5 Agent-Aktivitäten als einzeilige Einträge
- Nicht-intrusiv, verschwindet nach 10s Inaktivität

---

## 5. Proactive Engine (Grundlage)

Erweiterung des bestehenden `SmartScheduler`:

```
backend/proactive/
├── __init__.py
├── engine.py          # ProactiveEngine — erweitert SmartScheduler
├── watchers.py        # Konfigurierbare Überwachungen
└── patterns.py        # Pattern-Learning aus SoulMemory (Phase 2 ausbau)
```

### Watcher-Typen (Phase 1)

| Typ | Beispiel | Prüf-Intervall |
|-----|----------|----------------|
| **github_release** | "Prüfe ob ollama/ollama ein neues Release hat" | 6h |
| **health_check** | "Prüfe ob Ollama läuft" | 5min |
| **schedule_reminder** | "Erinnere mich jeden Montag 9:00 an Weekly" | cron |

### Notification-Kanäle

- **Telegram:** Proaktive Nachrichten an den Chat
- **Admin UI:** Toast-Notifications via WebSocket
- **Pixel-Büro:** Agent spawnt kurz und zeigt Notification-Animation

### DB-Tabelle

```sql
CREATE TABLE watchers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,         -- "github_release" | "health_check" | "custom"
    config TEXT NOT NULL,       -- JSON
    interval_seconds INTEGER,
    cron_expression TEXT,
    last_check TIMESTAMP,
    last_result TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. Datei-Struktur (Änderungen)

### Neue Dateien

```
backend/mcp/__init__.py
backend/mcp/bridge.py
backend/mcp/registry.py
backend/mcp/tool_adapter.py
backend/mcp/config.py
backend/proactive/__init__.py
backend/proactive/engine.py
backend/proactive/watchers.py
backend/proactive/patterns.py
backend/api/mcp_router.py          # MCP API Endpoints
frontend/command-center.html        # Neue Admin UI
frontend/command-center.js
frontend/command-center.css
frontend/pixel-buero.html           # Upgraded Pixel-Büro
frontend/pixel-buero.js
frontend/pixel-buero.css
frontend/music/                     # Lofi/Ambient Tracks
```

### Modifizierte Dateien

```
backend/main.py                     # MCPBridge init, neue Router, Flow-Erweiterung
backend/flow.py                     # direct_mcp Route, MCP-Tools an Crews
backend/event_bus.py                # MCP-Events, Agent-Status fix
backend/api/admin_router.py         # MCP + Proactive Endpoints
backend/config/settings.py          # MCP Config Felder
.env                                # MCP Server Config
```

### Entfernte / Ersetzte Dateien

```
frontend/dashboard.html  → ersetzt durch command-center.html
frontend/dashboard.js    → ersetzt durch command-center.js
frontend/dashboard.css   → ersetzt durch command-center.css
```

---

## 7. Abhängigkeiten

### Python

```
mcp>=1.0.0              # Anthropic MCP SDK (Client)
```

### Node.js (für MCP Server)

```
npx apple-mcp
npx desktop-commander
npx mcp-obsidian
```

Node.js muss auf dem Mac Studio installiert sein. `npx` installiert Server on-the-fly.

### Obsidian

Das **Local REST API** Plugin muss im Vault aktiv sein (für mcp-obsidian).

---

## 8. Nicht in Phase 1

Folgende Features werden bewusst auf Phase 2 verschoben:

- **Voice bidirektional** (TTS mit Piper, STT im Dashboard)
- **Pattern Learning** (SoulMemory lernt aus Gewohnheiten)
- **Spotify MCP Server** (nur Apple Music in Phase 1)
- **Browser-Steuerung** (Playwright MCP)
- **Mail senden** (nur lesen in Phase 1)
- **Drag & Drop** im Task-Kanban
- **Wetter-Widget** im Pixel-Büro
