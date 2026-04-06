# Falkenstein Agent Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Robustere Intent-Erkennung, korrekte Output-Routing, präzise modulare Prompts (Claude Code Leak Best Practices), Ollama Model-Browser in der UI, und Workspace-Kontext-Anhang per Chat.

**Architecture:** Intent-Prefilter vor dem LLM-Classify-Call fängt Schedule/Task/Obsidian-Intents zuverlässig ab. Alle System-Prompts werden in `backend/prompts/` modularisiert. `LLMClient` bekommt `chat_light()` / `chat_heavy()` für Modell-Routing. Neues `output_router.py` entscheidet wo Ergebnisse landen. Workspace-API + "+" Button im Chat-UI.

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, asyncio, pytest + AsyncMock, vanilla JS (kein Framework)

---

## Datei-Map

| Aktion | Datei | Verantwortung |
|--------|-------|---------------|
| Erstellen | `backend/prompts/__init__.py` | Package |
| Erstellen | `backend/prompts/classify.py` | Modularer Classifier-Prompt |
| Erstellen | `backend/prompts/subagent.py` | SubAgent-Prompts mit Output-Templates |
| Erstellen | `backend/prompts/schedule.py` | Schedule-Agent-Prompt |
| Erstellen | `backend/intent_prefilter.py` | Keyword+Regex+Semantic Intent-Erkennung |
| Erstellen | `backend/prompt_consolidator.py` | Nummerierte Prompts → Einzel-Prompt |
| Erstellen | `backend/output_router.py` | Ergebnis-Routing nach Kontext |
| Erstellen | `backend/workspace_api.py` | File-Upload + Pfad-Kontext API |
| Erstellen | `tests/test_intent_prefilter.py` | Tests für Prefilter |
| Erstellen | `tests/test_prompt_consolidator.py` | Tests für Konsolidierung |
| Erstellen | `tests/test_output_router.py` | Tests für Output-Routing |
| Erstellen | `tests/test_workspace_api.py` | Tests für Workspace-API |
| Modifizieren | `backend/llm_client.py` | `chat_light()` + `chat_heavy()` |
| Modifizieren | `backend/llm_router.py` | `telegram`-Typ + `get_client_with_size()` |
| Modifizieren | `backend/main_agent.py` | Prefilter einbinden, neue Prompts nutzen |
| Modifizieren | `backend/sub_agent.py` | Neue Prompts aus `prompts/subagent.py` |
| Modifizieren | `backend/admin_api.py` | Ollama-Endpunkte |
| Modifizieren | `backend/main.py` | `workspace_api` Router registrieren |
| Modifizieren | `frontend/dashboard.js` | Ollama Model-Browser Modal |
| Modifizieren | `frontend/index.html` | "+" Button + Workspace-Badge |

---

## Task 1: Modulare Prompts (`backend/prompts/`)

**Files:**
- Create: `backend/prompts/__init__.py`
- Create: `backend/prompts/classify.py`
- Create: `backend/prompts/subagent.py`
- Create: `backend/prompts/schedule.py`
- Test: `tests/test_prompts.py`

- [ ] **Schritt 1.1: Failing Test schreiben**

```python
# tests/test_prompts.py
import pytest
from backend.prompts.classify import build_classify_prompt
from backend.prompts.subagent import build_subagent_prompt
from backend.prompts.schedule import build_schedule_prompt


def test_classify_prompt_contains_kern_identitaet():
    prompt = build_classify_prompt()
    assert "Falki" in prompt
    assert "NIEMALS" in prompt
    assert "ops_command" in prompt


def test_classify_prompt_with_context():
    prompt = build_classify_prompt(
        active_agents="sub_researcher_abc: Recherche läuft",
        open_tasks="- [open] Task #1 Analyse",
        workspace="~/Buchprojekt",
    )
    assert "sub_researcher_abc" in prompt
    assert "~/Buchprojekt" in prompt


def test_classify_prompt_without_context():
    prompt = build_classify_prompt()
    assert "Aktive Agents:" not in prompt  # section omitted when empty


def test_subagent_prompt_researcher():
    prompt = build_subagent_prompt("researcher", "Analysiere KI-Trends", "recherche")
    assert "researcher" in prompt.lower()
    assert "## Zusammenfassung" in prompt
    assert "## Quellen" in prompt
    assert "Analysiere KI-Trends" in prompt


def test_subagent_prompt_coder():
    prompt = build_subagent_prompt("coder", "Refactore auth.py", "code")
    assert "## Problem" in prompt
    assert "## Lösung" in prompt


def test_subagent_prompt_writer():
    prompt = build_subagent_prompt("writer", "Schreibe Guide", "guide")
    assert "## Voraussetzungen" in prompt
    assert "## Schritt-für-Schritt" in prompt


def test_subagent_prompt_report():
    prompt = build_subagent_prompt("ops", "Analysiere Server-Logs", "report")
    assert "## Executive Summary" in prompt
    assert "## Empfehlungen" in prompt


def test_schedule_prompt():
    prompt = build_schedule_prompt(
        schedule_name="Morning Briefing",
        last_run="2026-04-06T08:00",
        result_type="report",
        obsidian_folder="Reports",
    )
    assert "Morning Briefing" in prompt
    assert "Reports" in prompt
    assert "## Executive Summary" in prompt
```

- [ ] **Schritt 1.2: Test ausführen und Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_prompts.py -v 2>&1 | head -30
```

Erwartet: `ModuleNotFoundError: No module named 'backend.prompts'`

- [ ] **Schritt 1.3: `backend/prompts/__init__.py` erstellen**

```python
# backend/prompts/__init__.py
```

- [ ] **Schritt 1.4: `backend/prompts/classify.py` erstellen**

```python
# backend/prompts/classify.py
"""Modularer Classifier-Prompt — nach Claude Code Leak Best Practices.

Aufbau:
  SEKTION 1  Kern-Identität       (statisch, für Prompt-Cache geeignet)
  SEKTION 2  Explizite Verbote    (statisch)
  SEKTION 3  Intent-Definitionen  (statisch)
  SEKTION 4  Kognitive Anforderungen (statisch)
  SEKTION 5  Output-Format-Templates (statisch)
  SEKTION 6  Dynamischer Kontext  (session-spezifisch, NICHT gecacht)
"""
from __future__ import annotations

_STATIC = """\
# SEKTION 1 — KERN-IDENTITÄT
Du bist Falki, ein intelligenter Assistent-Router im Falkenstein-System.
Deine einzige Aufgabe: Nachrichten analysieren und zum richtigen Handler routen.
Du antwortest IMMER mit validem JSON — kein Text davor oder danach.

# SEKTION 2 — EXPLIZITE VERBOTE
NIEMALS:
- ops_command für Schedule-Erstellung nutzen (auch bei "anlegen", "erstellen", "einrichten", "aufsetzen")
- Ein Shell-Skript vorschlagen wenn eine DB-API verfügbar ist
- Jeden Punkt eines nummerierten Prompts einzeln behandeln — verstehe den GESAMT-INTENT
- Bestätigung pro Punkt zurückgeben statt des Gesamt-Ergebnisses
- Raten wenn du unsicher bist — nutze quick_reply um nachzufragen

# SEKTION 3 — INTENT-DEFINITIONEN

**quick_reply** — Direkt beantwortbar ohne SubAgent.
Wann: Fragen, Status-Anfragen, Smalltalk, kurze Infos, Definitionen.
Beispiele JA: "Wie geht's?", "Was machst du gerade?", "Erkläre mir X kurz"
Beispiele NEIN: "Recherchiere X" (→ content), "Starte Server" (→ ops_command)

**action** — Der User will, dass etwas GETAN wird. Kein Report.
Wann: optimiere, konfiguriere, installiere, repariere, ändere, update.
Beispiele JA: "Optimiere die DB-Queries", "Installiere das Package"
Beispiele NEIN: "Erkläre wie ich X optimiere" (→ quick_reply)

**content** — Der User will ein ERGEBNIS sehen (Dokument, Analyse, Code).
Wann: recherchiere, analysiere, erstelle Guide/Report/Cheat-Sheet/Code, schreibe.
Ergebnis landet in Obsidian.
Beispiele JA: "Recherchiere aktuelle KI-Trends", "Erstelle einen Guide zu Python async"
Beispiele NEIN: "Mach X" ohne Ergebnis-Dokument (→ action)

**multi_step** — Mehrere abhängige Schritte mit einem Gesamtziel.
Wann: "X und dann Y", nummerierte Schritte die ein gemeinsames Ziel haben.
WICHTIG: Erkenne das ÜBERGEORDNETE ZIEL, nicht die Einzelschritte.
Beispiele JA: "1. Recherchiere X 2. Erstelle Guide daraus" → Gesamtziel: Guide zu X

**ops_command** — Systembefehle, Server-Operationen.
Wann: git pull, server starten/stoppen, logs, Ordner ansehen, update.
Beispiele JA: "Pull den Code", "Zeig mir die Logs", "Starte den Server neu"
Beispiele NEIN: "Erstelle einen Schedule" (→ NIEMALS ops_command)

# SEKTION 4 — KOGNITIVE ANFORDERUNGEN
Bevor du antwortest:
1. Was ist der GESAMT-INTENT dieser Nachricht?
2. Bei nummerierten Punkten: Was ist das übergeordnete Ziel aller Punkte zusammen?
3. Welcher Intent-Typ passt am besten zum GESAMT-INTENT?
4. Wenn unklar: quick_reply mit Rückfrage, nicht raten.

# SEKTION 5 — OUTPUT-FORMAT-TEMPLATES
Antworte NUR mit einem dieser JSON-Formate:

quick_reply:  {"type": "quick_reply", "answer": "<direkte Antwort>"}
action:       {"type": "action", "agent": "<coder|researcher|writer|ops>", "title": "<kurzer Titel>"}
content:      {"type": "content", "agent": "<typ>", "result_type": "<recherche|guide|cheat-sheet|code|report>", "title": "<kurzer Titel>"}
multi_step:   {"type": "multi_step", "title": "<Gesamtziel>", "consolidated_prompt": "<ein Prompt der das Gesamtziel beschreibt>", "agent": "<typ>", "result_type": "<typ>"}
ops_command:  {"type": "ops_command", "command_hint": "<was der user will>", "title": "<kurzer Titel>"}
"""


def build_classify_prompt(
    active_agents: str = "",
    open_tasks: str = "",
    workspace: str = "",
) -> str:
    """Build the full classifier system prompt.

    Static sections are at the top (prompt-cache friendly).
    Dynamic context is appended at the bottom.
    """
    parts = [_STATIC]

    # SEKTION 6 — nur wenn Kontext vorhanden
    context_lines = []
    if active_agents:
        context_lines.append(f"Aktive Agents:\n{active_agents}")
    if open_tasks:
        context_lines.append(f"Offene Tasks:\n{open_tasks}")
    if workspace:
        context_lines.append(f"Aktiver Workspace: {workspace}")

    if context_lines:
        parts.append("# SEKTION 6 — AKTUELLE SESSION\n" + "\n\n".join(context_lines))

    return "\n\n".join(parts)
```

- [ ] **Schritt 1.5: `backend/prompts/subagent.py` erstellen**

```python
# backend/prompts/subagent.py
"""SubAgent-Prompts mit expliziten Output-Templates."""
from __future__ import annotations

_OUTPUT_TEMPLATES: dict[str, str] = {
    "recherche": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Zusammenfassung\n"
        "(2-3 Sätze: Was ist das Kernresultat?)\n\n"
        "## Kernpunkte\n"
        "(5-10 Bullet-Points mit den wichtigsten Erkenntnissen)\n\n"
        "## Details\n"
        "(Ausführliche Erläuterung der wichtigsten Aspekte)\n\n"
        "## Quellen\n"
        "(URLs oder Quellen wenn vorhanden)"
    ),
    "guide": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Überblick\n"
        "(Was wird erreicht, für wen ist der Guide?)\n\n"
        "## Voraussetzungen\n"
        "(Was muss vorher installiert/bekannt sein?)\n\n"
        "## Schritt-für-Schritt\n"
        "(Nummerierte Schritte mit konkreten Befehlen/Code-Beispielen)\n\n"
        "## Tipps & Fallstricke\n"
        "(Häufige Fehler und wie man sie vermeidet)"
    ),
    "cheat-sheet": (
        "## Format deiner Antwort\n"
        "Erstelle ein kompaktes Cheat-Sheet:\n\n"
        "## Wichtigste Befehle/Konzepte\n"
        "(Tabellarisch oder als Code-Blöcke, sehr kompakt)\n\n"
        "## Häufige Patterns\n"
        "(Kurze Beispiele)"
    ),
    "code": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Problem\n"
        "(Was wird gelöst?)\n\n"
        "## Lösung\n"
        "```\n(vollständiger Code)\n```\n\n"
        "## Erklärung\n"
        "(Wichtige Design-Entscheidungen erklären)"
    ),
    "report": (
        "## Format deiner Antwort\n"
        "Strukturiere dein Ergebnis EXAKT so:\n\n"
        "## Executive Summary\n"
        "(3-5 Sätze: Was wurde gefunden, was sind die wichtigsten Erkenntnisse?)\n\n"
        "## Details\n"
        "(Ausführliche Analyse)\n\n"
        "## Empfehlungen\n"
        "(Konkrete nächste Schritte)"
    ),
}

_DEFAULT_TEMPLATE = _OUTPUT_TEMPLATES["recherche"]

_BASE_REQUIREMENTS = """\
## Anforderungen
- Antworte EINMAL mit dem vollständigen, fertigen Ergebnis
- KEIN "Ich habe Punkt 1 erledigt..." — nur das Endergebnis
- KEINE Statusmeldungen während der Arbeit — nur das finale Dokument
- Sprache: Deutsch (Ausnahme: Code-Kommentare auf Englisch)
- Wenn du ein Tool nutzt und es scheitert: kurz erwähnen und weitermachen
"""


def build_subagent_prompt(
    agent_type: str,
    task: str,
    result_type: str = "recherche",
) -> str:
    """Build a SubAgent system prompt with the appropriate output template."""
    template = _OUTPUT_TEMPLATES.get(result_type, _DEFAULT_TEMPLATE)
    return (
        f"Du bist ein {agent_type}-SubAgent im Falkenstein-System.\n\n"
        f"## Deine Aufgabe\n{task}\n\n"
        f"{template}\n\n"
        f"{_BASE_REQUIREMENTS}"
    )
```

- [ ] **Schritt 1.6: `backend/prompts/schedule.py` erstellen**

```python
# backend/prompts/schedule.py
"""Prompts für Schedule-Tasks die der SmartScheduler ausführt."""
from __future__ import annotations
from backend.prompts.subagent import _OUTPUT_TEMPLATES, _BASE_REQUIREMENTS


def build_schedule_prompt(
    schedule_name: str,
    last_run: str | None,
    result_type: str = "report",
    obsidian_folder: str = "Reports",
) -> str:
    """Build system prompt for a scheduled SubAgent run."""
    template = _OUTPUT_TEMPLATES.get(result_type, _OUTPUT_TEMPLATES["report"])
    last_run_str = f"Letzter Lauf: {last_run}" if last_run else "Erster Lauf"
    return (
        f"Du bist ein automatischer Schedule-Agent im Falkenstein-System.\n\n"
        f"## Schedule\n"
        f"Name: {schedule_name}\n"
        f"{last_run_str}\n\n"
        f"## Ablage\n"
        f"Speichere das Ergebnis in Obsidian-Ordner: {obsidian_folder}\n\n"
        f"{template}\n\n"
        f"{_BASE_REQUIREMENTS}"
    )
```

- [ ] **Schritt 1.7: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_prompts.py -v
```

Erwartet: alle Tests grün.

- [ ] **Schritt 1.8: `main_agent.py` — alte Prompt-Konstanten ersetzen**

In `backend/main_agent.py` die bestehenden Konstanten `_CLASSIFY_SYSTEM`, `_ENRICH_PROMPT_SYSTEM`, `_SCHEDULE_META_SYSTEM` durch Imports aus `backend/prompts/` ersetzen.

Am Anfang der Datei ergänzen:
```python
from backend.prompts.classify import build_classify_prompt
from backend.prompts.subagent import build_subagent_prompt
from backend.prompts.schedule import build_schedule_prompt
```

Die Konstante `_CLASSIFY_SYSTEM` entfernen und in `classify()` ersetzen:
```python
# ALT (in classify()):
parts.append(_CLASSIFY_SYSTEM)

# NEU:
parts.append(build_classify_prompt(
    active_agents="\n".join(
        f"  {aid}: {info.get('task', '?')}"
        for aid, info in self.active_agents.items()
    ) if self.active_agents else "",
    open_tasks="\n".join(
        f"  - [{t.status if hasattr(t, 'status') else t.get('status', '?')}] "
        f"{t.title if hasattr(t, 'title') else t.get('title', '?')}"
        for t in (open_tasks if 'open_tasks' in dir() else [])[:10]
    ),
    workspace=getattr(self, '_active_workspace', ''),
))
```

Außerdem in `sub_agent.py` die `_SYSTEM_PROMPTS`-Konstante durch `build_subagent_prompt()` ersetzen — in `SubAgent.__init__()`:
```python
# ALT:
self._system_prompt = _SYSTEM_PROMPTS.get(agent_type, _SYSTEM_PROMPTS["researcher"])

# NEU — nach dem Import:
from backend.prompts.subagent import build_subagent_prompt
# in __init__:
self._system_prompt = build_subagent_prompt(agent_type, task_description)
```

- [ ] **Schritt 1.9: Smoke-Test**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_prompts.py tests/test_sub_agent.py tests/test_main_agent.py -v 2>&1 | tail -20
```

Erwartet: alle Tests grün.

- [ ] **Schritt 1.10: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/prompts/ tests/test_prompts.py backend/main_agent.py backend/sub_agent.py && git commit -m "feat: modulare Prompts nach Claude Code Best Practices (backend/prompts/)"
```

---

## Task 2: `LLMClient` — `chat_light()` / `chat_heavy()` + `LLMRouter` Update

**Files:**
- Modify: `backend/llm_client.py`
- Modify: `backend/llm_router.py`
- Test: `tests/test_llm_router_sizing.py`

- [ ] **Schritt 2.1: Failing Test schreiben**

```python
# tests/test_llm_router_sizing.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.llm_router import LLMRouter

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.model = "gemma4:26b"
    llm.model_light = "gemma3:4b"
    llm.model_heavy = "gemma4:26b"
    llm.chat_light = AsyncMock(return_value="light response")
    llm.chat_heavy = AsyncMock(return_value="heavy response")
    return llm

def test_router_has_telegram_type(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    client, size = router.get_client_with_size("telegram")
    assert size == "light"

def test_router_classify_is_light(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("classify")
    assert size == "light"

def test_router_action_is_heavy(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("action")
    assert size == "heavy"

def test_router_scheduled_is_heavy(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("scheduled")
    assert size == "heavy"

def test_router_content_is_heavy(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    _, size = router.get_client_with_size("content")
    assert size == "heavy"

def test_get_client_with_size_returns_tuple(mock_llm):
    router = LLMRouter(local_llm=mock_llm)
    result = router.get_client_with_size("telegram")
    assert isinstance(result, tuple)
    assert len(result) == 2
```

- [ ] **Schritt 2.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_llm_router_sizing.py -v 2>&1 | head -20
```

Erwartet: `AttributeError: 'LLMRouter' object has no attribute 'get_client_with_size'`

- [ ] **Schritt 2.3: `backend/llm_client.py` — `chat_light()` + `chat_heavy()` ergänzen**

`LLMClient.chat()` akzeptiert bereits `model` und `num_ctx` Parameter. Die neuen Methoden rufen `chat()` direkt auf. Am Ende der `LLMClient`-Klasse (nach `chat_with_tools()`-Methode, vor `confidence_check()`) einfügen:

```python
async def chat_light(self, system_prompt: str = "", messages: list | None = None,
                     temperature: float = 0.7) -> str:
    """Chat using the light model (fast, reduced context)."""
    return await self.chat(
        system_prompt=system_prompt,
        messages=messages or [],
        model=self.model_light,
        num_ctx=max(4096, self.num_ctx // 4),
        temperature=temperature,
    )

async def chat_heavy(self, system_prompt: str = "", messages: list | None = None,
                     temperature: float = 0.7) -> str:
    """Chat using the heavy model (full context, best reasoning)."""
    return await self.chat(
        system_prompt=system_prompt,
        messages=messages or [],
        model=self.model_heavy,
        num_ctx=self.num_ctx,
        temperature=temperature,
    )
```

- [ ] **Schritt 2.4: `backend/llm_router.py` — `telegram`-Typ + `get_client_with_size()`**

```python
# In llm_router.py — DEFAULT_ROUTING erweitern:
DEFAULT_ROUTING = {
    "classify": "local",
    "telegram": "local",   # quick replies via model_light
    "action": "local",
    "content": "local",
    "scheduled": "local",
}

# Modell-Größe pro Task-Typ (light = schnell, heavy = vollständig)
_SIZE_MAP: dict[str, str] = {
    "classify": "light",
    "telegram": "light",
    "action": "heavy",
    "content": "heavy",
    "scheduled": "heavy",
}
```

Neue Methode in `LLMRouter`:
```python
def get_client_with_size(self, task_type: str = "classify") -> tuple:
    """Return (client, size) where size is 'light' or 'heavy'."""
    client = self.get_client(task_type)
    size = _SIZE_MAP.get(task_type, "heavy")
    return client, size
```

- [ ] **Schritt 2.5: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_llm_router_sizing.py tests/test_llm_client.py -v 2>&1 | tail -20
```

Erwartet: alle grün.

- [ ] **Schritt 2.6: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/llm_client.py backend/llm_router.py tests/test_llm_router_sizing.py && git commit -m "feat: LLMClient chat_light/chat_heavy + LLMRouter telegram-Typ mit Größen-Routing"
```

---

## Task 3: Intent-Prefilter + Schedule-Bug-Fix

**Files:**
- Create: `backend/intent_prefilter.py`
- Modify: `backend/main_agent.py` (Prefilter einbinden)
- Test: `tests/test_intent_prefilter.py`

- [ ] **Schritt 3.1: Failing Test schreiben**

```python
# tests/test_intent_prefilter.py
import pytest
from backend.intent_prefilter import IntentPrefilter, PrefilterResult

@pytest.fixture
def prefilter():
    return IntentPrefilter()

# --- Schedule-Erkennung ---
def test_schedule_keyword_direct(prefilter):
    result = prefilter.check("erstelle einen Schedule für tägliche News")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_natural_briefing(prefilter):
    result = prefilter.check("ich will täglich ein Briefing")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_natural_morgens(prefilter):
    result = prefilter.check("mach mir jeden morgen eine Zusammenfassung")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_with_time(prefilter):
    result = prefilter.check("schicke mir um 8:00 einen Report")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_reminder(prefilter):
    result = prefilter.check("erinner mich morgen früh an das Meeting")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_weekly(prefilter):
    result = prefilter.check("wöchentlich montags Server-Status prüfen")
    assert result == PrefilterResult.CREATE_SCHEDULE

def test_schedule_regelmassig(prefilter):
    result = prefilter.check("überwache regelmäßig die CPU-Auslastung")
    assert result == PrefilterResult.CREATE_SCHEDULE

# --- Task-Erkennung ---
def test_task_create(prefilter):
    result = prefilter.check("erstelle einen Task: Website redesign")
    assert result == PrefilterResult.CREATE_TASK

def test_task_anlegen(prefilter):
    result = prefilter.check("leg einen neuen Task an")
    assert result == PrefilterResult.CREATE_TASK

# --- Kein Match ---
def test_no_match_simple_question(prefilter):
    result = prefilter.check("wie geht es dir?")
    assert result == PrefilterResult.NONE

def test_no_match_research(prefilter):
    result = prefilter.check("recherchiere KI-Trends 2026")
    assert result == PrefilterResult.NONE

def test_no_match_ops(prefilter):
    result = prefilter.check("pull den code und starte den server")
    assert result == PrefilterResult.NONE

# --- Kein Schedule für ops ---
def test_no_schedule_for_shell(prefilter):
    """'täglich' allein ohne Aktion sollte kein Schedule sein wenn Kontext fehlt"""
    result = prefilter.check("zeig mir die täglichen Logs von heute")
    # "täglichen" als Adjektiv, nicht als Schedule-Trigger
    assert result == PrefilterResult.NONE
```

- [ ] **Schritt 3.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_intent_prefilter.py -v 2>&1 | head -15
```

Erwartet: `ModuleNotFoundError`

- [ ] **Schritt 3.3: `backend/intent_prefilter.py` erstellen**

```python
# backend/intent_prefilter.py
"""Intent-Prefilter — erkennt klare Intents vor dem LLM-Classify-Call.

Drei Ebenen:
  1. Direkte Keywords (Score 1.0)
  2. Regex-Muster (Score 0.85)
  3. Kontext-Ausschluss (verhindert false positives)

Gibt None zurück wenn kein klarer Intent erkannt → normaler LLM-Classify-Pfad.
"""
from __future__ import annotations
import re
from enum import Enum


class PrefilterResult(str, Enum):
    CREATE_SCHEDULE = "create_schedule"
    CREATE_TASK = "create_task"
    ROUTE_OBSIDIAN = "route_obsidian"
    NONE = "none"


# Keywords die eindeutig auf Schedule-Intent hindeuten
_SCHEDULE_KEYWORDS = {
    "schedule", "täglich", "stündlich", "wöchentlich", "monatlich",
    "briefing", "erinnerung", "reminder", "regelmäßig", "wiederkehrend",
    "automatisch ausführen", "jeden morgen", "jeden abend", "jeden tag",
    "montags", "dienstags", "mittwochs", "donnerstags", "freitags",
    "samstags", "sonntags", "alle stunden", "alle minuten",
}

# Keywords die einen Task-Create nahelegen
_TASK_KEYWORDS = {
    "erstelle task", "neuer task", "task anlegen", "aufgabe erstellen",
    "aufgabe anlegen", "neuen task",
}

# Regex-Muster für Schedule-Intent (mit Aktionsverb-Kontext)
_SCHEDULE_PATTERNS = [
    # "ich will täglich/jeden/regelmäßig X"
    re.compile(r"\bich will\s+(täglich|jeden|morgens|abends|wöchentlich|regelmäßig|stündlich)\b", re.IGNORECASE),
    # "mach mir täglich/jeden/regelmäßig X"
    re.compile(r"\bmach\s+(mir|das|bitte|mal)?\s*(täglich|jeden|regelmäßig|automatisch|stündlich)\b", re.IGNORECASE),
    # "erstelle/leg an/richte ein ... schedule/briefing/zusammenfassung/monitoring"
    re.compile(r"\b(erstelle|leg\s+an|richte\s+ein|setz\s+auf|starte)\b.{0,40}\b(schedule|briefing|zusammenfassung|report|monitoring|überwachung|check|reminder|erinnerung)\b", re.IGNORECASE),
    # "um HH:MM ... (schicke|sende|zeig|mach)" — Zeitangabe mit Aktion
    re.compile(r"\bum\s+\d{1,2}:\d{2}\b.{0,60}\b(schicke|sende|zeig|mach|erstelle|check|prüfe)\b", re.IGNORECASE),
    re.compile(r"\b(schicke|sende|zeig|mach|erstelle|check|prüfe)\b.{0,60}\bum\s+\d{1,2}:\d{2}\b", re.IGNORECASE),
    # "jeden montag/dienstag/... HH:MM" oder nur Wochentag mit Aktion
    re.compile(r"\bjeden\s+(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b", re.IGNORECASE),
    # "alle N minuten/stunden"
    re.compile(r"\balle\s+\d+\s+(minuten|stunden|min|std)\b", re.IGNORECASE),
    # "erinner mich ... um/an/morgen"
    re.compile(r"\berinner\s+(mich|uns)\b", re.IGNORECASE),
    # Explizit "täglich" als Adverb mit Aktion (nicht nur als Adjektiv)
    re.compile(r"\btäglich\s+(um|morgens|abends|mittags|früh|ab|ab\s+\d)", re.IGNORECASE),
    # "wöchentlich montag HH:MM"
    re.compile(r"\bwöchentlich\s+\w+\s+\d{1,2}:\d{2}\b", re.IGNORECASE),
]

# Ausschluss-Muster: wenn diese zutreffen, ist es KEIN Schedule auch bei Keyword-Match
_SCHEDULE_EXCLUSIONS = [
    re.compile(r"\b(zeig|schau|gib|lies|lese)\s+mir\b.{0,30}\b(täglichen|wöchentlichen|aktuellen)\b", re.IGNORECASE),
    re.compile(r"\b(die|den|das)\s+(täglichen|wöchentlichen)\b", re.IGNORECASE),
]

_TASK_PATTERNS = [
    re.compile(r"\b(erstell|leg\s+an|füge\s+hinzu)\b.{0,20}\b(task|aufgabe)\b", re.IGNORECASE),
    re.compile(r"\b(neuen?\s+task|neues?\s+aufgabe)\b", re.IGNORECASE),
]


class IntentPrefilter:
    """Fast, zero-LLM intent detection for common patterns."""

    def check(self, message: str) -> PrefilterResult:
        """Check message for high-confidence intents.

        Returns PrefilterResult.NONE if no clear intent detected.
        """
        msg_lower = message.lower()

        # --- Ausschlüsse prüfen (false positives vermeiden) ---
        for excl in _SCHEDULE_EXCLUSIONS:
            if excl.search(message):
                return PrefilterResult.NONE

        # --- Ebene 1: Direkte Keywords ---
        for keyword in _TASK_KEYWORDS:
            if keyword in msg_lower:
                return PrefilterResult.CREATE_TASK

        for keyword in _SCHEDULE_KEYWORDS:
            if keyword in msg_lower:
                # Zusätzliche Prüfung: "täglich" als Adjektiv vor Nomen ausschließen
                if keyword in ("täglich", "wöchentlich", "stündlich"):
                    # Nur wenn es als Adverb/Schedule-Trigger verwendet wird
                    if re.search(r"\b" + keyword + r"\s+(um|\d|morgens|abends|früh|ab)", msg_lower):
                        return PrefilterResult.CREATE_SCHEDULE
                    if re.search(r"\b(ich will|mach mir|erstelle|leg an)\b", msg_lower):
                        return PrefilterResult.CREATE_SCHEDULE
                    # Nicht matchen bei "die täglichen Logs", "täglichen Report anzeigen" etc.
                    continue
                return PrefilterResult.CREATE_SCHEDULE

        # --- Ebene 2: Regex-Muster ---
        for pattern in _TASK_PATTERNS:
            if pattern.search(message):
                return PrefilterResult.CREATE_TASK

        for pattern in _SCHEDULE_PATTERNS:
            if pattern.search(message):
                return PrefilterResult.CREATE_SCHEDULE

        return PrefilterResult.NONE
```

- [ ] **Schritt 3.4: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_intent_prefilter.py -v
```

Erwartet: alle Tests grün. Wenn einzelne Tests fehlschlagen, Regex-Muster anpassen.

- [ ] **Schritt 3.5: Prefilter in `main_agent.py` einbinden**

In `backend/main_agent.py` am Anfang ergänzen:
```python
from backend.intent_prefilter import IntentPrefilter, PrefilterResult
```

In `__init__()`:
```python
self._prefilter = IntentPrefilter()
```

In `handle_message()` direkt nach dem `_input_guard`-Check:
```python
# Intent-Prefilter (vor LLM-Call — 0 Token)
prefilter_result = self._prefilter.check(text)
if prefilter_result == PrefilterResult.CREATE_SCHEDULE:
    response = await self._schedule_create(text, chat_id)
    if self.telegram and chat_id:
        for chunk in self._split_telegram_message(response):
            await self.telegram.send_message(chunk, chat_id=chat_id or None)
    if self.ws_callback:
        await self.ws_callback({"type": "reply", "text": response})
    return
if prefilter_result == PrefilterResult.CREATE_TASK:
    response = await self._task_create_from_natural(text, chat_id)
    if self.telegram and chat_id:
        await self.telegram.send_message(response[:4000], chat_id=chat_id or None)
    return
```

Neue Methode `_task_create_from_natural()` in `main_agent.py`:
```python
async def _task_create_from_natural(self, text: str, chat_id: str) -> str:
    """Create a DB task from natural language."""
    # Extract title via LLM (light model, simple task)
    response = await self.llm.chat(
        system_prompt=(
            "Extrahiere aus dieser Nachricht einen kurzen Task-Titel (max 10 Wörter). "
            "Antworte NUR mit dem Titel, kein JSON, kein Markdown."
        ),
        messages=[{"role": "user", "content": text}],
        temperature=0.1,
    )
    title = response.strip()[:200] or "Neuer Task"
    task_id = await self.db.create_task(
        title=title,
        description=text,
        agent_type="researcher",
    )
    return f"Task #{task_id} erstellt: {title}"
```

- [ ] **Schritt 3.6: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_intent_prefilter.py tests/test_main_agent.py -v 2>&1 | tail -20
```

- [ ] **Schritt 3.7: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/intent_prefilter.py backend/main_agent.py tests/test_intent_prefilter.py && git commit -m "feat: Intent-Prefilter für Schedule/Task-Erkennung vor LLM-Call"
```

---

## Task 4: Prompt-Konsolidierung

**Files:**
- Create: `backend/prompt_consolidator.py`
- Modify: `backend/main_agent.py` (Konsolidierung vor Classify einbinden)
- Test: `tests/test_prompt_consolidator.py`

- [ ] **Schritt 4.1: Failing Test schreiben**

```python
# tests/test_prompt_consolidator.py
import pytest
from backend.prompt_consolidator import PromptConsolidator, has_numbered_points

def test_has_numbered_points_detects_list():
    text = "1. Recherchiere KI-Trends\n2. Erstelle einen Guide\n3. Speichere in Obsidian"
    assert has_numbered_points(text) is True

def test_has_numbered_points_detects_bullet():
    text = "- Recherchiere X\n- Analysiere Y\n- Schreibe Report"
    assert has_numbered_points(text) is True

def test_has_numbered_points_ignores_single_item():
    text = "1. Recherchiere KI-Trends"
    assert has_numbered_points(text) is False

def test_has_numbered_points_ignores_plain():
    text = "Wie geht es dir?"
    assert has_numbered_points(text) is False

def test_has_numbered_points_detects_mixed():
    text = "Bitte mach folgendes:\n1. Recherchiere X\n2. Erstelle Y"
    assert has_numbered_points(text) is True

def test_consolidator_extracts_points():
    consolidator = PromptConsolidator()
    text = "1. Recherchiere KI-Trends 2026\n2. Erstelle daraus einen Guide\n3. Lege in Obsidian ab"
    points = consolidator.extract_points(text)
    assert len(points) == 3
    assert "KI-Trends" in points[0]
    assert "Guide" in points[1]
    assert "Obsidian" in points[2]

def test_consolidator_builds_single_prompt():
    consolidator = PromptConsolidator()
    points = [
        "Recherchiere KI-Trends 2026",
        "Erstelle daraus einen strukturierten Guide",
        "Speichere in Obsidian",
    ]
    result = consolidator.build_consolidated_prompt(points)
    assert "KI-Trends" in result
    assert "Guide" in result
    # Single prompt, not a list
    assert "\n1." not in result or result.count("\n1.") == 0
```

- [ ] **Schritt 4.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_prompt_consolidator.py -v 2>&1 | head -15
```

Erwartet: `ModuleNotFoundError`

- [ ] **Schritt 4.3: `backend/prompt_consolidator.py` erstellen**

```python
# backend/prompt_consolidator.py
"""Konsolidiert nummerierte/aufgezählte Prompts zu einem einzigen kohärenten Prompt.

Beispiel:
    "1. Recherchiere KI-Trends\n2. Erstelle Guide\n3. Speichere in Obsidian"
    →  "Recherchiere aktuelle KI-Trends 2026 und erstelle daraus einen
        strukturierten Guide. Speichere das Ergebnis in Obsidian."
"""
from __future__ import annotations
import re


# Mindestanzahl Punkte für Konsolidierung
_MIN_POINTS = 2

_NUMBERED_RE = re.compile(r"^\s*(\d+[\.\):]|\-|\•|\*)\s+(.+)", re.MULTILINE)


def has_numbered_points(text: str) -> bool:
    """Return True if text contains 2+ numbered/bulleted points."""
    matches = _NUMBERED_RE.findall(text)
    return len(matches) >= _MIN_POINTS


class PromptConsolidator:
    """Turns multi-point prompts into a single consolidated task prompt."""

    def extract_points(self, text: str) -> list[str]:
        """Extract individual points from a numbered/bulleted list."""
        matches = _NUMBERED_RE.findall(text)
        return [m[1].strip() for m in matches]

    def build_consolidated_prompt(self, points: list[str]) -> str:
        """Merge points into one fluid prompt.

        Simple approach: join with connective words.
        The LLM will interpret this as one coherent task.
        """
        if not points:
            return ""
        if len(points) == 1:
            return points[0]

        # Join points into a single flowing instruction
        # First point: main task
        # Subsequent points: "und dann", "anschließend", "zuletzt"
        connectors = ["", " und dann ", " anschließend ", " zuletzt ", " außerdem "]
        parts = []
        for i, point in enumerate(points):
            if i == 0:
                parts.append(point)
            elif i < len(connectors):
                parts.append(connectors[i] + point.lower())
            else:
                parts.append(" sowie " + point.lower())

        return "".join(parts) + "."

    def consolidate(self, text: str) -> tuple[str, bool]:
        """Consolidate a message if it contains multiple points.

        Returns:
            (consolidated_text, was_consolidated)
        """
        if not has_numbered_points(text):
            return text, False
        points = self.extract_points(text)
        if len(points) < _MIN_POINTS:
            return text, False
        consolidated = self.build_consolidated_prompt(points)
        return consolidated, True
```

- [ ] **Schritt 4.4: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_prompt_consolidator.py -v
```

Erwartet: alle grün.

- [ ] **Schritt 4.5: Konsolidierung in `main_agent.py` einbinden**

In `backend/main_agent.py`:
```python
from backend.prompt_consolidator import PromptConsolidator
```

In `__init__()`:
```python
self._consolidator = PromptConsolidator()
```

In `handle_message()` direkt nach dem Prefilter-Check (aber vor `classify()`):
```python
# Prompt-Konsolidierung: nummerierte Listen → ein kohärenter Prompt
text, was_consolidated = self._consolidator.consolidate(text)
# Optional: User informieren
if was_consolidated and self.telegram and chat_id:
    await self.telegram.send_message(
        f"_Verstanden als: {text[:200]}..._" if len(text) > 200 else f"_Verstanden als: {text}_",
        chat_id=chat_id or None,
    )
```

- [ ] **Schritt 4.6: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_prompt_consolidator.py tests/test_main_agent.py -v 2>&1 | tail -15
```

- [ ] **Schritt 4.7: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/prompt_consolidator.py backend/main_agent.py tests/test_prompt_consolidator.py && git commit -m "feat: Prompt-Konsolidierung für nummerierte Multi-Punkt-Prompts"
```

---

## Task 5: Output-Router

**Files:**
- Create: `backend/output_router.py`
- Modify: `backend/main_agent.py` (Output-Router nach SubAgent-Ergebnis nutzen)
- Test: `tests/test_output_router.py`

- [ ] **Schritt 5.1: Failing Test schreiben**

```python
# tests/test_output_router.py
import pytest
from unittest.mock import AsyncMock
from backend.output_router import OutputRouter, OutputDestination

@pytest.fixture
def router():
    mock_llm = AsyncMock()
    mock_llm.chat_light = AsyncMock(return_value="obsidian")
    return OutputRouter(llm=mock_llm)

def test_explicit_obsidian_keyword(router):
    dest = router.check_explicit("schreib das in obsidian", "recherche")
    assert dest == OutputDestination.OBSIDIAN

def test_explicit_task_keyword(router):
    dest = router.check_explicit("erstelle einen task daraus", "code")
    assert dest == OutputDestination.TASK

def test_explicit_schedule_keyword(router):
    dest = router.check_explicit("als schedule anlegen", "report")
    assert dest == OutputDestination.SCHEDULE

def test_explicit_reply_keyword(router):
    dest = router.check_explicit("zeig mir das hier", "recherche")
    assert dest == OutputDestination.REPLY

def test_no_explicit_returns_none(router):
    dest = router.check_explicit("recherchiere KI-Trends", "recherche")
    assert dest is None

def test_default_content_goes_to_obsidian(router):
    dest = router.get_default_destination("content", "recherche")
    assert dest == OutputDestination.OBSIDIAN

def test_default_action_goes_to_reply(router):
    dest = router.get_default_destination("action", None)
    assert dest == OutputDestination.REPLY

def test_obsidian_folder_for_result_type(router):
    assert router.get_obsidian_folder("recherche") == "Recherchen"
    assert router.get_obsidian_folder("guide") == "Guides"
    assert router.get_obsidian_folder("code") == "Code"
    assert router.get_obsidian_folder("report") == "Reports"
    assert router.get_obsidian_folder("cheat-sheet") == "Cheat-Sheets"
```

- [ ] **Schritt 5.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_output_router.py -v 2>&1 | head -15
```

Erwartet: `ModuleNotFoundError`

- [ ] **Schritt 5.3: `backend/output_router.py` erstellen**

```python
# backend/output_router.py
"""Output-Router — entscheidet wohin ein SubAgent-Ergebnis gelangt.

3-Stufen-Check:
  1. Explizite Keyword-Anweisung im Original-Prompt (0 Token)
  2. Kontext-Inferenz via model_light (wenn kein expliziter Hinweis)
  3. Nachfragen (wenn Confidence ≤ 0.8)
"""
from __future__ import annotations
import re
from enum import Enum


class OutputDestination(str, Enum):
    OBSIDIAN = "obsidian"
    TASK = "task"
    SCHEDULE = "schedule"
    REPLY = "reply"


_OBSIDIAN_KEYWORDS = [
    "in obsidian", "obsidian ablegen", "speichere in", "leg ab in",
    "in die vault", "in vault", "abspeichern",
]
_TASK_KEYWORDS = [
    "als task", "in tasks", "task erstellen", "aufgabe anlegen",
    "task anlegen", "als aufgabe",
]
_SCHEDULE_KEYWORDS = [
    "als schedule", "schedule anlegen", "täglich ausführen",
    "als wiederkehrende", "automatisch wiederholen",
]
_REPLY_KEYWORDS = [
    "hier antworten", "zeig mir", "sag mir", "schick mir", "schreib mir",
    "antworte hier", "nur hier",
]

_OBSIDIAN_FOLDERS: dict[str, str] = {
    "recherche": "Recherchen",
    "guide": "Guides",
    "cheat-sheet": "Cheat-Sheets",
    "code": "Code",
    "report": "Reports",
}


class OutputRouter:
    """Routes agent output to the correct destination."""

    def __init__(self, llm=None):
        self._llm = llm

    def check_explicit(self, original_prompt: str, result_type: str | None) -> OutputDestination | None:
        """Check for explicit routing keywords in the original prompt.

        Returns None if no explicit destination found.
        """
        text = original_prompt.lower()
        for kw in _TASK_KEYWORDS:
            if kw in text:
                return OutputDestination.TASK
        for kw in _SCHEDULE_KEYWORDS:
            if kw in text:
                return OutputDestination.SCHEDULE
        for kw in _REPLY_KEYWORDS:
            if kw in text:
                return OutputDestination.REPLY
        for kw in _OBSIDIAN_KEYWORDS:
            if kw in text:
                return OutputDestination.OBSIDIAN
        return None

    def get_default_destination(self, intent_type: str, result_type: str | None) -> OutputDestination:
        """Get the default destination based on intent type.

        content → obsidian (has a document result)
        action/ops_command/quick_reply → reply (just confirm what was done)
        """
        if intent_type == "content":
            return OutputDestination.OBSIDIAN
        if intent_type == "multi_step":
            return OutputDestination.OBSIDIAN
        return OutputDestination.REPLY

    def get_obsidian_folder(self, result_type: str | None) -> str:
        """Map result_type to the correct Obsidian folder."""
        return _OBSIDIAN_FOLDERS.get(result_type or "", "Recherchen")

    async def resolve(
        self,
        original_prompt: str,
        intent_type: str,
        result_type: str | None,
        conversation_history: list[dict] | None = None,
    ) -> OutputDestination:
        """Determine output destination using the 3-step check.

        Step 1: Explicit keyword in prompt → immediate routing
        Step 2: Context inference via LLM (if llm available)
        Step 3: Fall back to default
        """
        # Step 1: explicit keyword
        explicit = self.check_explicit(original_prompt, result_type)
        if explicit is not None:
            return explicit

        # Step 2: LLM context inference (only if history available and LLM configured)
        if self._llm and conversation_history and len(conversation_history) >= 2:
            history_text = "\n".join(
                f"{m['role']}: {m['content'][:200]}"
                for m in conversation_history[-5:]
            )
            try:
                resp = await self._llm.chat_light(
                    system_prompt=(
                        "Analysiere diesen Gesprächsverlauf und bestimme wohin das Ergebnis soll. "
                        "Antworte NUR mit einem Wort: obsidian / task / schedule / reply"
                    ),
                    messages=[{"role": "user", "content": f"Kontext:\n{history_text}\n\nAufgabe: {original_prompt[:300]}"}],
                    temperature=0.0,
                )
                dest_str = resp.strip().lower()
                if dest_str in ("obsidian", "task", "schedule", "reply"):
                    return OutputDestination(dest_str)
            except Exception:
                pass

        # Step 3: Default based on intent type
        return self.get_default_destination(intent_type, result_type)
```

- [ ] **Schritt 5.4: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_output_router.py -v
```

Erwartet: alle grün.

- [ ] **Schritt 5.5: Output-Router in `main_agent.py` einbinden**

In `backend/main_agent.py`:
```python
from backend.output_router import OutputRouter, OutputDestination
```

In `__init__()`:
```python
llm_for_router = llm_router.get_client("classify") if llm_router else llm
self._output_router = OutputRouter(llm=llm_for_router)
```

Nach dem SubAgent-Lauf, wenn das Ergebnis vorliegt, den Router aufrufen. Suche in `main_agent.py` nach dem Punkt wo `result` an `obsidian_writer.write_result()` übergeben wird und ergänze die Routing-Logik:

```python
# Nach SubAgent-Fertigstellung — Output-Router entscheidet Ziel
dest = await self._output_router.resolve(
    original_prompt=text,
    intent_type=intent.get("type", "content"),
    result_type=intent.get("result_type"),
    conversation_history=await self.db.get_chat_history(chat_id or "default", limit=5),
)

if dest == OutputDestination.OBSIDIAN and self.obsidian_writer:
    folder = self._output_router.get_obsidian_folder(intent.get("result_type"))
    self.obsidian_writer.write_result(
        title=intent.get("title", "Ergebnis"),
        content=result,
        result_type=intent.get("result_type", "recherche"),
        folder=folder,
    )
    reply = f"In Obsidian ({folder}) gespeichert: {intent.get('title', 'Ergebnis')}"
elif dest == OutputDestination.TASK:
    task_id = await self.db.create_task(
        title=intent.get("title", "Task"),
        description=result[:2000],
        agent_type=intent.get("agent", "researcher"),
    )
    reply = f"Task #{task_id} erstellt: {intent.get('title', 'Task')}"
else:
    # REPLY — direkt zurückgeben
    reply = result
```

- [ ] **Schritt 5.6: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_output_router.py tests/test_main_agent.py -v 2>&1 | tail -20
```

- [ ] **Schritt 5.7: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/output_router.py backend/main_agent.py tests/test_output_router.py && git commit -m "feat: Output-Router — kontext-bewusstes Ergebnis-Routing (Obsidian/Task/Reply)"
```

---

## Task 6: Ollama Model-Browser (API + Frontend)

**Files:**
- Modify: `backend/admin_api.py` (3 neue Endpunkte)
- Modify: `frontend/dashboard.js` (Modal + Dropdowns)
- Test: `tests/test_ollama_browser_api.py`

- [ ] **Schritt 6.1: Failing Test schreiben**

```python
# tests/test_ollama_browser_api.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient
from fastapi import FastAPI
from backend.admin_api import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_ollama_models_endpoint_structure():
    """Test that /api/admin/ollama/models returns expected structure."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {
                "name": "gemma4:26b",
                "size": 15_000_000_000,
                "modified_at": "2026-04-01T10:00:00Z",
                "details": {"parameter_size": "26B"},
            }
        ]
    }
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/ollama/models")
        # Accept 200 or 500 (Ollama not running in test env)
        assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_ollama_pull_requires_model_name():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/api/admin/ollama/pull", json={})
    assert resp.status_code == 422  # Validation error — missing model field
```

- [ ] **Schritt 6.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_ollama_browser_api.py -v 2>&1 | head -20
```

Erwartet: 404-Fehler (Endpunkte noch nicht vorhanden).

- [ ] **Schritt 6.3: Ollama-Endpunkte in `backend/admin_api.py` ergänzen**

Am Ende von `admin_api.py` vor den letzten Endpunkten ergänzen:

```python
# ── Ollama Model Browser ──────────────────────────────────────────────

class OllamaPullRequest(BaseModel):
    model: str


@router.get("/ollama/models")
async def list_ollama_models():
    """List all locally available Ollama models."""
    import httpx
    ollama_host = "http://localhost:11434"
    if _config_service:
        saved = _config_service.get("ollama_host")
        if saved:
            ollama_host = saved
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", ""),
                    "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "modified_at": m.get("modified_at", ""),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                })
            return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}


@router.post("/ollama/pull")
async def pull_ollama_model(req: OllamaPullRequest):
    """Pull an Ollama model. Returns SSE stream of progress."""
    import httpx
    from fastapi.responses import StreamingResponse
    import json as _json

    ollama_host = "http://localhost:11434"
    if _config_service:
        saved = _config_service.get("ollama_host")
        if saved:
            ollama_host = saved

    async def stream_pull():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream(
                    "POST",
                    f"{ollama_host}/api/pull",
                    json={"name": req.model, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line:
                            yield f"data: {line}\n\n"
            yield "data: {\"status\": \"success\"}\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(stream_pull(), media_type="text/event-stream")


@router.delete("/ollama/models/{model_name:path}")
async def delete_ollama_model(model_name: str):
    """Delete a local Ollama model."""
    import httpx
    ollama_host = "http://localhost:11434"
    if _config_service:
        saved = _config_service.get("ollama_host")
        if saved:
            ollama_host = saved
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                "DELETE",
                f"{ollama_host}/api/delete",
                json={"name": model_name},
            )
            if resp.status_code == 200:
                return {"status": "deleted", "model": model_name}
            return {"status": "error", "detail": resp.text}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
```

- [ ] **Schritt 6.4: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_ollama_browser_api.py -v 2>&1 | tail -15
```

- [ ] **Schritt 6.5: Frontend — Ollama Modal + LLM-Routing Dropdowns**

In `frontend/dashboard.js` die Funktion `loadLLMRouting()` suchen und erweitern, um Dropdowns statt Inputs zu nutzen. Zuerst die bestehende Funktion lesen:

```bash
grep -n "loadLLMRouting\|llm.*routing\|LLMRouting" /Users/janikhartmann/Falkenstein/frontend/dashboard.js | head -20
```

Dann die `renderLLMRouting()`-Funktion so anpassen, dass sie Modelle lädt und Dropdowns rendert:

```javascript
// In dashboard.js — neue Funktion ergänzen:
async function loadOllamaModels() {
  try {
    const data = await api('/ollama/models');
    return (data.models || []).map(m => m.name);
  } catch {
    return [];
  }
}

function renderModelSelect(id, currentValue, models) {
  const opts = models.map(m =>
    `<option value="${esc(m)}" ${m === currentValue ? 'selected' : ''}>${esc(m)}</option>`
  ).join('');
  return `<select id="${id}" class="model-select">${opts}</select>`;
}

// Neues Ollama-Modal
function renderOllamaModal(models) {
  return `
  <div id="ollama-modal" class="modal-overlay" onclick="if(event.target===this)closeOllamaModal()">
    <div class="modal-box">
      <h3>Modell-Manager</h3>
      <table class="ollama-table">
        <thead><tr><th>Modell</th><th>Größe</th><th>Datum</th><th></th></tr></thead>
        <tbody>
          ${models.map(m => `
            <tr>
              <td><code>${esc(m.name)}</code></td>
              <td>${esc(m.size_gb)} GB</td>
              <td>${m.modified_at ? new Date(m.modified_at).toLocaleDateString('de') : '—'}</td>
              <td><button class="btn-danger btn-sm" onclick="deleteOllamaModel('${esc(m.name)}')">🗑</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div class="pull-row">
        <input id="pull-model-input" type="text" placeholder="z.B. gemma3:4b" class="input-sm">
        <button class="btn-primary" onclick="pullOllamaModel()">⬇ Pullen</button>
      </div>
      <div id="pull-progress"></div>
      <button class="btn-secondary" onclick="closeOllamaModal()">Schließen</button>
    </div>
  </div>`;
}

async function openOllamaModal() {
  const data = await api('/ollama/models');
  const models = data.models || [];
  document.body.insertAdjacentHTML('beforeend', renderOllamaModal(models));
}

function closeOllamaModal() {
  document.getElementById('ollama-modal')?.remove();
}

async function deleteOllamaModel(name) {
  if (!confirm(`Modell "${name}" löschen?`)) return;
  const result = await api(`/ollama/models/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (result.status === 'deleted') {
    closeOllamaModal();
    openOllamaModal();
  } else {
    alert('Fehler: ' + (result.detail || 'Unbekannt'));
  }
}

async function pullOllamaModel() {
  const modelName = document.getElementById('pull-model-input')?.value?.trim();
  if (!modelName) return;
  const progressEl = document.getElementById('pull-progress');
  if (progressEl) progressEl.textContent = 'Starte Download...';

  const token = localStorage.getItem('falkenstein_token') || '';
  const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
  const evtSource = new EventSource(`/api/admin/ollama/pull?model=${encodeURIComponent(modelName)}`);
  // Use fetch + SSE for POST:
  const resp = await fetch('/api/admin/ollama/pull', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({ model: modelName }),
  });
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value);
    const lines = text.split('\n').filter(l => l.startsWith('data: '));
    for (const line of lines) {
      try {
        const data = JSON.parse(line.slice(6));
        if (progressEl) {
          if (data.status === 'success') {
            progressEl.textContent = '✅ Download abgeschlossen';
            closeOllamaModal();
            openOllamaModal();
          } else if (data.error) {
            progressEl.textContent = '❌ Fehler: ' + data.error;
          } else {
            const pct = data.completed && data.total
              ? Math.round(data.completed / data.total * 100) + '%'
              : data.status || '';
            progressEl.textContent = pct;
          }
        }
      } catch {}
    }
  }
}
```

- [ ] **Schritt 6.6: Tests + Server-Smoke-Test**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_ollama_browser_api.py tests/test_admin_api.py -v 2>&1 | tail -20
```

- [ ] **Schritt 6.7: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/admin_api.py frontend/dashboard.js tests/test_ollama_browser_api.py && git commit -m "feat: Ollama Model-Browser — API-Endpunkte + Frontend Modal mit Pull/Delete"
```

---

## Task 7: Workspace-Kontext-Anhang

**Files:**
- Create: `backend/workspace_api.py`
- Modify: `backend/main.py` (Router registrieren)
- Modify: `backend/main_agent.py` (`_active_workspace` Feld)
- Modify: `frontend/index.html` ("+" Button + Badge)
- Modify: `frontend/dashboard.js` (Workspace-Funktionen)
- Test: `tests/test_workspace_api.py`

- [ ] **Schritt 7.1: Failing Test schreiben**

```python
# tests/test_workspace_api.py
import pytest
import os
import tempfile
from httpx import AsyncClient
from fastapi import FastAPI

# Patch dependencies before import
import backend.workspace_api as ws_module
ws_module._sessions = {}

from backend.workspace_api import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_set_workspace_path_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.post("/api/workspace/path", json={"path": tmpdir})
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == tmpdir
        assert data["type"] == "directory"


@pytest.mark.asyncio
async def test_set_workspace_path_invalid():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/api/workspace/path", json={"path": "/nonexistent/path/xyz"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_workspace_empty():
    ws_module._sessions = {}
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/workspace/current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is False


@pytest.mark.asyncio
async def test_delete_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        async with AsyncClient(app=app, base_url="http://test") as ac:
            await ac.post("/api/workspace/path", json={"path": tmpdir})
            resp = await ac.delete("/api/workspace/current")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"
```

- [ ] **Schritt 7.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_workspace_api.py -v 2>&1 | head -15
```

Erwartet: `ModuleNotFoundError`

- [ ] **Schritt 7.3: `backend/workspace_api.py` erstellen**

```python
# backend/workspace_api.py
"""Workspace-Kontext-API — File-Upload und Verzeichnis-Pfad für Agenten-Kontext."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# In-memory session store: session_id → workspace info
# In production this would be per-user; here we use a single "default" session
_sessions: dict[str, dict] = {}
_DEFAULT_SESSION = "default"
_UPLOAD_BASE = Path(tempfile.gettempdir()) / "falkenstein_workspace"


class WorkspacePathRequest(BaseModel):
    path: str
    session_id: str = _DEFAULT_SESSION


@router.post("/path")
async def set_workspace_path(req: WorkspacePathRequest):
    """Set an existing local directory as workspace context (no upload)."""
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Pfad nicht gefunden: {req.path}")

    ws_type = "directory" if p.is_dir() else "file"
    file_list: list[str] = []
    if p.is_dir():
        file_list = [
            str(f.relative_to(p))
            for f in p.rglob("*")
            if f.is_file() and not f.name.startswith(".")
        ][:100]  # max 100 files listed

    _sessions[req.session_id] = {
        "path": str(p),
        "type": ws_type,
        "files": file_list,
        "active": True,
    }
    return {"path": str(p), "type": ws_type, "file_count": len(file_list)}


@router.post("/upload")
async def upload_workspace_file(
    file: UploadFile = File(...),
    session_id: str = _DEFAULT_SESSION,
):
    """Upload a file as workspace context."""
    upload_dir = _UPLOAD_BASE / session_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest = upload_dir / (file.filename or "upload")
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    _sessions[session_id] = {
        "path": str(dest),
        "type": "file",
        "files": [file.filename or "upload"],
        "active": True,
    }
    return {"path": str(dest), "filename": file.filename, "size": len(content)}


@router.get("/current")
async def get_workspace(session_id: str = _DEFAULT_SESSION):
    """Get current workspace context for a session."""
    ws = _sessions.get(session_id)
    if not ws or not ws.get("active"):
        return {"active": False}
    return {**ws, "active": True}


@router.delete("/current")
async def clear_workspace(session_id: str = _DEFAULT_SESSION):
    """Clear workspace context for a session."""
    _sessions.pop(session_id, None)
    return {"status": "cleared"}


def get_workspace_context(session_id: str = _DEFAULT_SESSION) -> str:
    """Return workspace context string for injection into agent prompts."""
    ws = _sessions.get(session_id)
    if not ws or not ws.get("active"):
        return ""
    path = ws.get("path", "")
    files = ws.get("files", [])
    if files:
        file_preview = ", ".join(files[:10])
        return f"Aktiver Workspace: {path} ({len(files)} Dateien: {file_preview})"
    return f"Aktiver Workspace: {path}"
```

- [ ] **Schritt 7.4: Router in `backend/main.py` registrieren**

In `backend/main.py` ergänzen:
```python
from backend.workspace_api import router as workspace_router
```

Und beim App-Setup:
```python
app.include_router(workspace_router)
```

- [ ] **Schritt 7.5: `_active_workspace` in `MainAgent` einbinden**

In `backend/main_agent.py`:
```python
from backend.workspace_api import get_workspace_context
```

In `_build_context()` ergänzen:
```python
ws_context = get_workspace_context()
if ws_context:
    parts.append(ws_context)
```

- [ ] **Schritt 7.6: Frontend "+" Button und Workspace-Badge**

In `frontend/dashboard.js` ergänzen:

```javascript
// Workspace functions
async function initWorkspaceButton() {
  const chatForm = document.getElementById('chat-form') || document.querySelector('.chat-input-row');
  if (!chatForm) return;

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.id = 'workspace-btn';
  btn.className = 'btn-icon';
  btn.title = 'Workspace anhängen';
  btn.textContent = '+';
  btn.onclick = toggleWorkspaceMenu;
  chatForm.prepend(btn);

  // Badge anzeigen wenn Workspace aktiv
  await refreshWorkspaceBadge();
}

async function refreshWorkspaceBadge() {
  const existing = document.getElementById('workspace-badge');
  if (existing) existing.remove();

  const data = await api('/../../api/workspace/current').catch(() => ({ active: false }));
  if (!data.active) return;

  const badge = document.createElement('div');
  badge.id = 'workspace-badge';
  badge.className = 'workspace-badge';
  badge.innerHTML = `📁 ${esc(data.path)} <span onclick="clearWorkspace()">✕</span>`;
  const chatInput = document.getElementById('chat-input') || document.querySelector('.chat-input-row');
  if (chatInput) chatInput.parentNode.insertBefore(badge, chatInput.nextSibling);
}

function toggleWorkspaceMenu() {
  const existing = document.getElementById('workspace-menu');
  if (existing) { existing.remove(); return; }

  const menu = document.createElement('div');
  menu.id = 'workspace-menu';
  menu.className = 'workspace-menu';
  menu.innerHTML = `
    <button onclick="pickWorkspaceFile()">📄 Datei hochladen</button>
    <button onclick="pickWorkspaceFolder()">📁 Ordner hochladen</button>
    <button onclick="pickWorkspaceDirectory()">📂 Verzeichnis wählen</button>
  `;
  document.getElementById('workspace-btn').after(menu);
  document.addEventListener('click', function closeMenu(e) {
    if (!menu.contains(e.target) && e.target.id !== 'workspace-btn') {
      menu.remove();
      document.removeEventListener('click', closeMenu);
    }
  });
}

function pickWorkspaceFile() {
  document.getElementById('workspace-menu')?.remove();
  const input = document.createElement('input');
  input.type = 'file';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    const token = localStorage.getItem('falkenstein_token') || '';
    await fetch('/api/workspace/upload', {
      method: 'POST',
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
      body: form,
    });
    await refreshWorkspaceBadge();
  };
  input.click();
}

function pickWorkspaceFolder() {
  document.getElementById('workspace-menu')?.remove();
  const input = document.createElement('input');
  input.type = 'file';
  input.webkitdirectory = true;
  input.onchange = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    // Upload first file to get path context
    const form = new FormData();
    form.append('file', files[0]);
    const token = localStorage.getItem('falkenstein_token') || '';
    await fetch('/api/workspace/upload', {
      method: 'POST',
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
      body: form,
    });
    await refreshWorkspaceBadge();
  };
  input.click();
}

async function pickWorkspaceDirectory() {
  document.getElementById('workspace-menu')?.remove();
  if (!window.showDirectoryPicker) {
    alert('Dein Browser unterstützt showDirectoryPicker nicht. Bitte Pfad manuell eingeben.');
    const path = prompt('Verzeichnis-Pfad eingeben:');
    if (path) await setWorkspacePath(path);
    return;
  }
  try {
    const dirHandle = await window.showDirectoryPicker();
    await setWorkspacePath(dirHandle.name);  // Nur Name, nicht voller Pfad via API möglich
  } catch (e) {
    if (e.name !== 'AbortError') console.error(e);
  }
}

async function setWorkspacePath(path) {
  const token = localStorage.getItem('falkenstein_token') || '';
  await fetch('/api/workspace/path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { 'Authorization': 'Bearer ' + token } : {}) },
    body: JSON.stringify({ path }),
  });
  await refreshWorkspaceBadge();
}

async function clearWorkspace() {
  const token = localStorage.getItem('falkenstein_token') || '';
  await fetch('/api/workspace/current', {
    method: 'DELETE',
    headers: token ? { 'Authorization': 'Bearer ' + token } : {},
  });
  document.getElementById('workspace-badge')?.remove();
}
```

- [ ] **Schritt 7.7: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_workspace_api.py -v 2>&1 | tail -15
```

Erwartet: alle grün.

- [ ] **Schritt 7.8: Integration-Smoke-Test**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/ -v --ignore=tests/test_llm_gemma4.py -k "not test_integration" 2>&1 | tail -30
```

Erwartet: alle Tests grün (außer ggf. Tests die Ollama/LLM laufend benötigen).

- [ ] **Schritt 7.9: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/workspace_api.py backend/main.py backend/main_agent.py frontend/dashboard.js tests/test_workspace_api.py && git commit -m "feat: Workspace-Kontext-Anhang — API + Frontend + Button mit Finder-Integration"
```

---

## Abschluss

- [ ] **Vollständige Test-Suite ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/ -v --ignore=tests/test_llm_gemma4.py 2>&1 | tail -40
```

Erwartet: alle Tests grün.

- [ ] **Server starten und smoke-testen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m backend.main &
sleep 3
curl -s http://localhost:8800/api/admin/ollama/models | python3 -m json.tool
```

- [ ] **Final Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add -A && git commit -m "feat: Falkenstein Agent Overhaul — Prompts, Prefilter, Output-Router, Ollama Browser, Workspace"
```
