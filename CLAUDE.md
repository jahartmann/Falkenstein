# CLAUDE.md

Smart Assistant: 1 MainAgent + SubAgents on demand. Telegram = Steuerung, Obsidian = Wissensbasis, Büro-UI = passiver Monitor.

## Commands
```bash
source venv/bin/activate && pip install -r requirements.txt  # setup
python -m backend.main                                        # server :8080
python -m pytest tests/ -v                                    # tests
```
Requires: Python 3.11+, Ollama running, `ollama pull gemma4:26b`

## Stack
Frontend: Phaser.js 3.80 + Tiled (48px) passive dashboard | Backend: FastAPI + WebSockets + aiosqlite | LLM: Ollama (Gemma 4) | Premium: Gemini/Claude CLI | DB: SQLite | Config: pydantic-settings `.env`

## Architecture
- MainAgent (`main_agent.py`): Klassifiziert Input, antwortet direkt oder spawnt SubAgent
- SubAgents (`sub_agent.py`): Kurzlebig, fokussiertes Tool-Set (coder/researcher/writer/ops)
- ObsidianWriter (`obsidian_writer.py`): Kanban, Task-Notes, Ergebnis-Routing
- Telegram: Thin transport, alles durch MainAgent
- Frontend: Zeigt nur aktive Agents, kein Sim-Loop

## Konventionen
- SubAgent-Typen: `coder`, `researcher`, `writer`, `ops`
- Ergebnis-Ordner: `Recherchen`, `Guides`, `Cheat-Sheets`, `Code`, `Reports`
- Pfade via `.env`, keine hardcodierten Pfade
- Sprache: Doku/Kommunikation Deutsch, Code-Kommentare Englisch
- DB-Tabellen: `agents`, `tasks`, `messages`, `tool_log`

## Token-Effizienz
- Subagenten mit `model: "sonnet"` oder `model: "haiku"` starten wenn Opus aktiv
- Explore-Agents immer mit `model: "sonnet"`
- Antworten kurz und direkt, kein Filler
