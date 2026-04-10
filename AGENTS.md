# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

Falkenstein: Persönlicher KI-Assistent ("Falki"). Telegram = Steuerung, Obsidian = Wissensbasis, Büro-UI = passiver Monitor. Siehe `SOUL.md` für Charakter/Ton.

## Commands
```bash
./start.sh                                           # empfohlen: setup + run + auto-restart + git-watch
source venv312/bin/activate                          # manuell: venv aktivieren
python -m backend.main                               # server (Port via FRONTEND_PORT, default 8800)
python -m pytest tests/ -v                           # alle Tests
python -m pytest tests/test_flow.py::test_name -v    # einzelner Test
```
Requires: Python 3.11–3.13 (CrewAI <3.14), Ollama mit `gemma4:26b`, `.env` aus `.env.example`.

## Stack
FastAPI + WebSockets + aiosqlite | CrewAI 0.108+ (LLM-Orchestrierung) | Ollama native (`gemma4:e4b` light / `gemma4:26b` heavy) | MCP (stdio) für externe Tools | Phaser.js Dashboard (passiv) | Pfade via `pydantic-settings` aus `.env`.

## Architektur

**Message-Flow** (`backend/main.py` → `handle_telegram_message`):
Telegram/WS/HTTP → `FalkensteinFlow.handle_message()` → `InputGuard` → `PromptConsolidator` → `RuleEngine.route()`:
- `quick_reply` → direkt via `NativeOllamaClient` (kein Crew, kein Vault-Context)
- `direct_mcp` → MCP-Tool direkt (Reminder, Licht, Kalender, Musik, HomeKit)
- `crew` → CrewAI-Crew via Keyword-Match
- `classify` → LLM entscheidet Crew-Typ

**Crews** (`backend/crews/`, CrewAI-basiert, kurzlebig):
`coder`, `researcher`, `writer`, `ops`, `web_design`, `swift`, `ki_expert`, `analyst`, `premium`. Jeder hat eigenes Tool-Set, wird pro Task neu instanziert. `premium` nutzt CLI-Bridge (Codex/gemini).

**EventBus** (`event_bus.py`): Crews publishen Lifecycle-Events → broadcast an WSManager (Frontend) + Telegram. Quick-Replies und direct_mcp umgehen EventBus → Result wird in `main.py` direkt gesendet.

**MCP-Bridge** (`backend/mcp/`): stdio-basiert, verwaltet Lifetime von `apple-mcp`, `mcp-obsidian`, `desktop-commander`. Tools werden via `create_all_mcp_tools()` dynamisch in Crew-Tool-Sets eingehängt (generic → alle Crews, desktop → ops/coder, obsidian → researcher/writer).

**Memory**: `SoulMemory` (persönliche Fakten, SQLite) + `FactMemory` (legacy, wird migriert) + `VaultIndex` (Obsidian-Scan, als Kontext an Crews).

## Konventionen
- Ergebnis-Ordner in Obsidian: `Recherchen`, `Guides`, `Cheat-Sheets`, `Code`, `Reports`
- Pfade via `backend/config.py` + `ConfigService` (DB-backed, hot-reload für Felder in `HOT_RELOAD_FIELDS`)
- Sprache: Doku/Kommunikation Deutsch, Code-Kommentare Englisch
- DB-Tabellen: `agents`, `tasks`, `messages`, `tool_log` (siehe `backend/database.py`)
- Neue Crew hinzufügen: Klasse in `backend/crews/` + Eintrag in `CREW_CLASSES` (`falkenstein_flow.py`) + Keywords in `rule_engine.py` + Tool-Set in `main.py::lifespan`

## Gotchas
- **Python 3.12 bevorzugt**: `start.sh` legt `venv312` an; `venv` (alt) ist ggf. noch da, aber inaktiv
- **Ollama Model-Namen**: In `.env` müssen die tatsächlichen Ollama-Tags stehen — Tippfehler (`gemma4:26b` vs `gemma3:27b`) machen Telegram unresponsive
- **MCP-Start ist non-fatal**: Schlägt Bridge-Start fehl, läuft Falki ohne MCP-Tools weiter (Log-Warning)
- **`start.sh` killt Orphans**: Alte `backend.main`-Prozesse + MCP-Node-Kinder + Port-Locks vor dem Start
- **Quick-Replies haben keinen Vault-Context** — absichtlich, sonst wird "hi" zu 30s Wartezeit
- **EventBus vs direkter Send**: Für `quick_reply`/`direct_mcp` muss `main.py` das Result selbst per Telegram senden — Crews tun das selbst via EventBus

## Token-Effizienz
- Subagenten mit `model: "sonnet"` oder `model: "haiku"` wenn Opus aktiv
- Explore-Agents: `haiku` für gerichtete Lookups, `sonnet` für Architektur-/Synthese-Fragen
- Antworten kurz und direkt, kein Filler
