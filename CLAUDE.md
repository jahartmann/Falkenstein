# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projektübersicht

"Falkenstein" ist ein gamifiziertes KI-Büro als 2D-Pixelart-Lebenssimulation mit 7 KI-Agenten (PM Star, Teamleiterin Nina, Coder Alex & Bob, Researcherin Amelia, Writerin Clara, Ops Max). Die Agenten bearbeiten echte Tasks (WORK-Mode) oder simulieren autonomes Büroleben (SIM/IDLE-Mode). LLM-Routing: Ollama für 95% der Arbeit, Premium-CLIs (Claude/Gemini) nur für finale komplexe Aufgaben.

## Entwicklung

### Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Server starten
```bash
python -m backend.main
```
Server läuft auf `http://localhost:8080`. Frontend wird automatisch von `frontend/` served.

### Tests
```bash
python -m pytest tests/ -v               # alle Tests (30 Tests)
python -m pytest tests/test_agent.py -v   # einzelner Test
python -m pytest tests/test_database.py::test_upsert_and_get_agent -v  # einzelne Testfunktion
```

### Voraussetzungen
- Python 3.11+
- Ollama lokal installiert und laufend (`http://localhost:11434`)
- Ein Modell geladen: `ollama pull llama3`

## Tech Stack

- **Frontend:** Phaser.js 3.80 mit Tiled-Tilemaps (48x48 Tiles), HTML/CSS UI-Overlays
- **Backend:** Python FastAPI mit WebSockets, aiosqlite
- **LLM:** Ollama via `asyncio.to_thread()` für parallele Requests
- **Datenbank:** SQLite (World State, Tasks, Beziehungen)
- **Konfiguration:** pydantic-settings aus `.env`

## Architektur

### Backend-Module (`backend/`)
- `main.py` — FastAPI Entry, WebSocket `/ws`, REST API, Sim-Loop (5s Ticks)
- `config.py` — Settings aus `.env` via pydantic-settings
- `database.py` — SQLite Schema (6 Tabellen), CRUD-Operationen
- `models.py` — Pydantic Models + Enums (AgentRole, AgentState, TaskStatus, etc.)
- `agent.py` — Agent-Klasse mit State Machine (IDLE↔WORK), Tool-Ausführung, Persönlichkeit
- `agent_pool.py` — Erstellt und verwaltet das 7er-Team mit festen Traits/Positionen
- `orchestrator.py` — Empfängt Tasks, routet via Keyword-Matching an passende Rolle
- `sim_engine.py` — IDLE-Verhalten: Ollama entscheidet wander/talk/coffee/phone/sit
- `llm_client.py` — Ollama-Wrapper mit `asyncio.to_thread()` für parallele Calls
- `ws_manager.py` — WebSocket-Verbindungsverwaltung, Broadcast, Dead-Connection-Cleanup
- `tools/base.py` — Tool-Interface (ToolResult, ToolRegistry) mit Ollama Function Calling Schema
- `tools/file_manager.py` — Dateien lesen/schreiben/löschen mit Path-Traversal-Schutz

### Frontend (`frontend/`)
- `index.html` — Phaser-Container + Task-Input-Panel
- `game.js` — Phaser Scene: Tiled-Map laden, Camera Pan/Zoom, WebSocket-Events
- `agents.js` — Agent-Sprites, Namens-Labels, Sprechblasen, Tween-Bewegung
- `websocket.js` — WS-Client mit Auto-Reconnect und Event-Emitter

### Datenfluss
1. Task rein (REST API / WebSocket / zukünftig Telegram)
2. Orchestrator routet an passenden idle Agent
3. Agent wechselt IDLE→WORK, führt Tool-Calls via Ollama aus
4. Jeder Schritt → WebSocket-Broadcast → Frontend-Animation
5. Task fertig → Agent zurück in IDLE → Sim-Verhalten

### SQLite-Tabellen
`agents`, `tasks`, `messages`, `relationships`, `tool_log`, `personality_log`

## Konventionen

- Agenten-IDs: `pm`, `team_lead`, `coder_1`, `coder_2`, `researcher`, `writer`, `ops`
- Agent States: `idle_wander`, `idle_talk`, `idle_coffee`, `idle_phone`, `idle_sit`, `work_sit`, `work_type`, `work_tool`, `work_review`
- Alle Pfade konfigurierbar via `.env` — keine hardcodierten Pfade
- Relationships in DB: alphabetisch sortierte composite PK (bidirektionaler Lookup)

## Sprache

Projektdokumentation und Kommunikation auf Deutsch. Code-Kommentare auf Englisch.

## Referenz-Assets

- `Büro/Neues_Office.tmj` — Original Tiled-Map (60x48, 48px Tiles)
- `Büro/Modern tiles_Free/Characters_free/` — 4 Character-Sprites (Adam, Alex, Amelia, Bob)
- `Büro/Modern_Office_Revamped_v1/` — Möbel/Tileset-Assets in 16/32/48px
- `Büro/Star-Office-UI/` — Älterer Phaser-Prototyp (Referenz, nicht in Produktion)
