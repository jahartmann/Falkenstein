# Falkenstein — Gamified AI Office Design Spec

## Vision

Falkenstein ist ein persistenter Python-Prozess mit 7 KI-Agenten, die echte Arbeit erledigen (Dateien schreiben, Web recherchieren, Code ausführen, Shell-Befehle) und in einem lebendigen 2D-Pixel-Büro (Phaser.js) visualisiert werden. Das System läuft headless (Telegram, Obsidian) oder mit visuellem Frontend.

## Architektur

### Prozessmodell

Async Monolith: ein FastAPI-Prozess. Ollama-Calls laufen parallel via `asyncio.to_thread()` / `ThreadPoolExecutor`. Ollama läuft als externer Prozess und bedient mehrere Requests gleichzeitig — GIL ist kein Problem da die Threads auf I/O warten.

### Komponenten-Übersicht

```
┌─────────────────────────────────────────────────┐
│  Phaser.js Frontend (Browser, optional)         │
│  ← WebSocket →                                  │
├─────────────────────────────────────────────────┤
│  FastAPI Backend (ein Prozess, immer aktiv)      │
│  ┌───────────┐  ┌────────────┐  ┌────────────┐ │
│  │ Orchestr. │  │ Telegram   │  │ WebSocket  │ │
│  │ (PM)      │  │ Bot        │  │ Server     │ │
│  └─────┬─────┘  └────────────┘  └────────────┘ │
│        │                                         │
│  ┌─────▼──────────────────────────────────────┐ │
│  │ Agent Pool (7 Kern-Agenten, async Tasks)   │ │
│  │ Jeder Agent: Persönlichkeit + Rolle +      │ │
│  │ State Machine (IDLE↔WORK) + Memory         │ │
│  └─────┬──────────────────────────────────────┘ │
│        │ asyncio.to_thread()                     │
│  ┌─────▼─────┐  ┌──────────┐  ┌──────────────┐ │
│  │ Ollama    │  │ CLI      │  │ Tool         │ │
│  │ (parallel)│  │ Bridge   │  │ Registry     │ │
│  └───────────┘  └──────────┘  └──────────────┘ │
│        │                                         │
│  ┌─────▼──────────────────────────────────────┐ │
│  │ SQLite + ChromaDB                          │ │
│  └────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### Datenfluss eines Tasks

1. Task kommt rein (Telegram, Web-UI, oder Obsidian-Inbox)
2. PM-Agent zerlegt ihn in Teilaufgaben → SQLite
3. Teamleiter weist Agenten zu, berücksichtigt Duos und Synergien
4. Agenten wechseln in WORK-Mode, picken ihre Teilaufgaben
5. Jeder Schritt → WebSocket-Event ans Frontend (Sprite bewegt sich, tippt, Tool-Icons)
6. Tool-Calls (Websuche, Dateien, Shell) werden real ausgeführt
7. Triage: einfach → Ollama fertig. Komplex → CLI-Bridge ruft Claude/Gemini
8. Confidence-Check: Review-Stufe bewertet Ollama-Ergebnis. Unzureichend → automatische Eskalation an CLI
9. Teamleiter koordiniert Review wenn Teilaufgaben fertig
10. Agenten zurück in IDLE-Mode → wandern, reden, Kaffee holen

## Team (7 Kern-Agenten)

| # | Rolle | Hauptaufgabe | LLM |
|---|-------|-------------|-----|
| 1 | **PM (Star)** | Tasks annehmen, zerlegen, priorisieren | Ollama |
| 2 | **Teamleiter** | Arbeit zuweisen, Reviews koordinieren, Duos erkennen, Qualität sichern | Ollama |
| 3 | **Coder 1** | Code schreiben, Bugs fixen | Ollama → CLI bei Bedarf |
| 4 | **Coder 2** | Code schreiben, Tests | Ollama → CLI bei Bedarf |
| 5 | **Researcher** | Webrecherche, Kontext sammeln, Obsidian pflegen | Ollama |
| 6 | **Writer** | Dokumentation, Reports, Texte | Ollama → CLI bei Bedarf |
| 7 | **Ops** | Shell-Kommandos, Deployment, Systemaufgaben | Ollama |

Plus temporäre Sub-Agenten die bei hoher Last gespawnt werden.

## LLM-Routing (Hybrid)

### Regelbasiertes Default-Routing

- Recherche, Planung, Zusammenfassungen, Sim-Verhalten → immer Ollama
- Finaler Code, komplexe Texte → CLI-Kandidaten

### Confidence-Check & Eskalation

1. Ollama produziert Ergebnis
2. Review-Stufe (Ollama) bewertet Qualität gegen Anforderungen
3. Bewertung "unzureichend" → automatische Eskalation an CLI
4. CLI bekommt komprimierten Prompt mit Kontext + bisherigem Entwurf
5. CLI-Ergebnis wird nochmals reviewed

### Kosten-Kontrolle

- Tägliches Token-Budget für CLI-Calls (konfigurierbar via `CLI_DAILY_TOKEN_BUDGET`)
- Logging aller CLI-Aufrufe mit Token-Count
- Warnung über Telegram wenn Budget 80% erreicht

## Dynamische Persönlichkeiten

### Traits (ändern sich langsam über Wochen)

```python
"traits": {
    "social": 0.7,        # Gesprächsfreudigkeit
    "focus": 0.8,         # Konzentrationsfähigkeit
    "confidence": 0.6,    # Selbstvertrauen, steigt mit Erfolg
    "patience": 0.5,      # sinkt bei Fehlschlägen
    "curiosity": 0.7,     # Interesse an neuen Themen
    "leadership": 0.3     # Verantwortungsübernahme
}
```

### Mood (ändert sich schnell, Minuten/Stunden)

```python
"mood": {
    "energy": 0.9,
    "stress": 0.2,
    "motivation": 0.8,
    "frustration": 0.0
}
```

### Trait-Entwicklung

| Event | Effekt |
|-------|--------|
| 5 Tasks hintereinander erfolgreich | `confidence` +0.05, `stress` -0.1 |
| CLI-Eskalation nötig | `confidence` -0.02 |
| Gemeinsames Projekt erfolgreich | `synergy` +0.1, `trust` +0.05 |
| 3x Review "mangelhaft" | `frustration` +0.2, `patience` -0.03 |
| Langer IDLE-Chat | `friendship` +0.05 |
| Schweren Bug allein gelöst | `confidence` +0.1, `respect` von allen +0.05 |
| Teamleiter lobt | `motivation` +0.2, `leadership` +0.02 |

### Langzeit-Effekte

- Schüchterner Agent mit vielen Erfolgen → wird selbstbewusster
- Gestresster Agent → mehr Pausen, öfter Kaffee
- Hoher `leadership`-Wert → Agent macht eigenständig Vorschläge

## Duo-System

### Entstehung

Wenn zwei Agenten oft erfolgreich zusammenarbeiten, steigt ihr `synergy`-Wert. Ab Schwellwert 0.85 → **Duo**.

### Effekte

- Teamleiter weist Duos bevorzugt gemeinsame Tasks zu
- Duo-Bonus im Prompt-Kontext: "Du arbeitest mit Alex zusammen, ihr ergänzt euch gut"
- Im Büro sichtbar: sitzen öfter nebeneinander, gemeinsame Kaffee-Pausen, eigene Gesprächsthemen

### Beziehungs-Datenmodell

```python
"relationships": {
    "coder_2": {
        "trust": 0.8,
        "synergy": 0.9,
        "friendship": 0.7,
        "respect": 0.8,
        "history": [
            {"type": "collab", "project": "api-v2", "outcome": "success"},
            {"type": "review", "result": "clean"},
            {"type": "chat", "topic": "neues Framework", "mood": "excited"}
        ]
    }
}
```

## Inter-Agenten-Kommunikation

### Message-Queue (SQLite)

```python
{
    "from": "researcher",
    "to": "coder_1",        # oder "team" für Broadcast
    "project": "website-v2",
    "type": "handoff",       # handoff | question | review | chat
    "content": "Recherche fertig. Hier die 3 APIs...",
    "timestamp": "2026-04-01T14:30:00"
}
```

### Kollaboration

1. PM erstellt Projekt mit Teilaufgaben
2. Teamleiter weist Agenten zu, definiert Abhängigkeiten
3. Researcher recherchiert → `handoff` an Coder
4. Coder 1 baut Frontend, Coder 2 baut Backend (parallel)
5. Teamleiter triggered Review wenn beide fertig
6. Writer erstellt Doku basierend auf fertigem Code

## Sim-Logik

### State Machine pro Agent

```
WORK MODE: sit → type → tool_use → review → done
IDLE MODE: wander | talk | coffee | phone | sit
```

### IDLE-Verhalten

Ollama entscheidet alle paar Sekunden was der Agent tut, gewichtet durch Persönlichkeit und Beziehungen:

- **Wandern** — zufällig durchs Büro (Pathfinding via Easystar.js)
- **Gespräch** — zu Kollegen gehen, Sprechblase mit generiertem Smalltalk
- **Kaffee** — zur Kaffeemaschine, Pause-Animation
- **Handy** — am Platz sitzen, Phone-Sprite
- **Sitzen** — idle-Animation am Schreibtisch

### Frontend-Visualisierung

- Sprite-Animationen: walk, sit, type, phone, talk
- Sprechblasen mit kurzen Sätzen (Ollama, 1-2 Sätze)
- Stimmungs-Emoji über dem Kopf
- Duo-Interaktionen: nebeneinander stehen, abwechselnd Sprechblasen
- Tool-Icons: Lupe (Suche), Diskette (Schreiben), Terminal (Code), Blitz (CLI), Notizbuch (Obsidian), Chat-Blase (Telegram)

## Tool-System

### Interface

```python
class Tool:
    name: str
    description: str  # für Ollama Function Calling Prompt

    async def execute(self, params: dict) -> ToolResult
    def schema(self) -> dict  # JSON Schema
```

### Tag-1 Tools

| Tool | Funktion |
|------|----------|
| `file_manager` | Dateien lesen/schreiben/löschen im Projektverzeichnis |
| `obsidian_manager` | Notizen, Kanban, Daily Reports im Vault |
| `web_surfer` | DuckDuckGo + BeautifulSoup Scraping |
| `telegram_bot` | Nachrichten senden/empfangen |
| `shell_runner` | Beliebige Shell-Befehle (Blacklist für destruktive Ops) |

### Zweite Welle

| Tool | Funktion |
|------|----------|
| `code_executor` | Python/Shell in `/workspace` Sandbox mit Timeout |
| `cli_bridge` | Claude/Gemini CLI Subprocess mit komprimiertem Prompt |

### Shell-Zugriff

Volle Shell-Freiheit wie Claude Code. Blacklist nur für destruktive Befehle: `rm -rf /`, `mkfs`, `dd`, `shutdown`, `reboot`, Fork-Bombs. Befehle außerhalb `WORKSPACE_PATH`/`HOME` → Bestätigung via Telegram/UI. Timeout default 5 Minuten. Alles geloggt.

## Memory (3-Tier)

### Tier 1 — Session Memory (RAM)

- Letzte 15 Nachrichten pro Agent im Kontext
- Aktuelle Telegram-Konversation
- Verfällt nach 30 Min Inaktivität

### Tier 2 — Episodic Memory (ChromaDB)

- Abgeschlossene Tasks → vektorisierte Zusammenfassung
- Wichtige Interaktionen → Episoden
- Persönlichkeits-Snapshots → täglich
- RAG-Abfrage vor jeder Planung

### Tier 3 — World State (SQLite)

```
agents          → Traits, Mood, Position, State
relationships   → Trust, Synergy, Friendship, History
tasks           → Status, Zuweisung, Projekt, Ergebnis
projects        → Teilaufgaben, Fortschritt, Beteiligte
messages        → Inter-Agenten-Kommunikation
tool_log        → Jede Tool-Ausführung mit I/O
personality_log → Trait-Änderungen über Zeit
```

## Frontend (Phaser.js)

- Phaser.js mit Tiled-Tilemap (`Neues_Office.tmj`)
- Easystar.js für Pathfinding
- Canvas 1280x720, `pixelArt: true`
- Assets: `Modern tiles_Free` (Tilesets), `Modern_Office_Revamped_v1` (Möbel)
- Character-Sprites aus Assets (walk, sit, type, phone, talk)
- WebSocket-Verbindung zum Backend für Echtzeit-Updates
- UI-Overlays: Task-Board, Agent-Details (Klick auf Sprite), Projekt-Fortschritt

## Externe Interfaces

### Telegram Bot

- Tasks empfangen als Nachrichten
- Status-Updates und Daily Reports senden
- Bestätigung für Shell-Befehle außerhalb sicherer Pfade
- Budget-Warnungen

### Obsidian Vault

- Strukturierte Ordner: `/Projekte/[Name]/`
- Kanban-Boards: `/Management/Inbox.md`
- Daily Reports: `Daily_Report_YYYY-MM-DD.md`
- Agent kann Vault als Wissensquelle lesen (RAG)

## Konfiguration

Alles via `.env` — kein hardcodierter Pfad:

```
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3
WORKSPACE_PATH=~/workspace
OBSIDIAN_VAULT_PATH=~/Obsidian
TELEGRAM_BOT_TOKEN=...
CLI_DAILY_TOKEN_BUDGET=50000
DB_PATH=./data/falkenstein.db
CHROMA_PATH=./data/chroma
FRONTEND_PORT=8080
WEBSOCKET_PORT=8081
BLACKLISTED_COMMANDS=rm -rf /,mkfs,dd,shutdown,reboot
```

## Deployment

- Entwicklung auf MacBook (lokal)
- Später Deployment auf stationären Mac (dauerhaft)
- Ein Prozess: `python -m backend.main`
- Frontend: statische Dateien, served by FastAPI oder separater Webserver

## Projektstruktur

```
/falkenstein
├── /backend
│   ├── main.py              # FastAPI Entry, WebSocket, Startup
│   ├── orchestrator.py      # PM-Logik, Task-Zerlegung
│   ├── team_lead.py         # Teamleiter-Logik, Zuweisung, Duos
│   ├── agent.py             # Agent-Basisklasse, State Machine
│   ├── agent_pool.py        # 7 Agenten verwalten, async Tasks
│   ├── llm_router.py        # Triage, Confidence-Check, Eskalation
│   ├── personality.py       # Trait-System, Mood, Entwicklung
│   ├── relationships.py     # Beziehungen, Duo-Erkennung, Synergy
│   ├── sim_engine.py        # IDLE-Verhalten, Gespräche, Bewegung
│   ├── /memory
│   │   ├── session.py       # RAM Session Buffer
│   │   ├── rag_engine.py    # ChromaDB Embedding & Retrieval
│   │   └── chroma_db/       # ChromaDB Speicherort
│   ├── /tools
│   │   ├── base.py          # Tool Interface
│   │   ├── file_manager.py
│   │   ├── obsidian_manager.py
│   │   ├── web_surfer.py
│   │   ├── shell_runner.py
│   │   ├── code_executor.py
│   │   └── cli_bridge.py
│   ├── /interfaces
│   │   ├── telegram_bot.py
│   │   └── websocket_server.py
│   └── database.py          # SQLite Schema & CRUD
├── /frontend
│   ├── index.html
│   ├── game.js              # Phaser Logic, Tilemap, Pathfinding
│   ├── ui.js                # HTML DOM Overlays
│   ├── websocket.js         # WS Client
│   └── /assets              # Tiled JSON, Tilesets, Sprites
├── /data                    # SQLite DB, ChromaDB (gitignored)
├── /workspace               # Isolierter Ordner für Agent-Arbeit
├── .env                     # Konfiguration
├── requirements.txt
└── CLAUDE.md
```
