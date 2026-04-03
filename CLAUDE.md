# CLAUDE.md

Gamifiziertes KI-Büro: 2D-Pixelart-Simulation, 7 Agenten (WORK/IDLE-Mode). Ollama für 95%, Premium-CLIs für Komplexes.

## Commands
```bash
source venv/bin/activate && pip install -r requirements.txt  # setup
python -m backend.main                                        # server :8080
python -m pytest tests/ -v                                    # tests
```
Requires: Python 3.11+, Ollama running, `ollama pull llama3`

## Stack
Frontend: Phaser.js 3.80 + Tiled (48px) | Backend: FastAPI + WebSockets + aiosqlite | LLM: Ollama | DB: SQLite | Config: pydantic-settings `.env`

## Konventionen
- IDs: `pm`, `team_lead`, `coder_1`, `coder_2`, `researcher`, `writer`, `ops`
- States: `idle_wander/talk/coffee/phone/sit`, `work_sit/type/tool/review`
- Pfade via `.env`, keine hardcodierten Pfade
- Relationships: alphabetisch sortierte composite PK
- Sprache: Doku/Kommunikation Deutsch, Code-Kommentare Englisch
- DB-Tabellen: `agents`, `tasks`, `messages`, `relationships`, `tool_log`, `personality_log`

## Token-Effizienz
- Subagenten mit `model: "sonnet"` oder `model: "haiku"` starten wenn Opus aktiv
- Explore-Agents immer mit `model: "sonnet"`
- Antworten kurz und direkt, kein Filler
- Architektur-Details nicht in CLAUDE.md — Code lesen statt hier dokumentieren
