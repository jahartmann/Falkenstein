# Falkenstein Agent Overhaul — Design Spec
**Datum:** 2026-04-06
**Status:** Approved

---

## Übersicht

Fünf unabhängige, aber zusammengehörige Verbesserungen am Falkenstein-Agent-System:

1. Model-Routing + Ollama Model-Browser
2. Schedule-Bug-Fix + Intent-Prefilter
3. Prompt-Engineering-Overhaul (Claude Code Leak inspiriert)
4. Output-Routing (kontext-bewusst)
5. Workspace-Kontext-Anhang (UI)

---

## 1. Model-Routing + Ollama Model-Browser

### Ziel
Telegram-Schnellantworten laufen auf `model_light` (4B), Hintergrund-/Scheduled-Tasks auf `model_heavy` (26B). Modelle können in der UI per Dropdown ausgewählt und über die Ollama-API gepullt werden — kein manuelles Eintippen.

### Backend

**Neue API-Endpunkte in `admin_api.py`:**
- `GET /api/admin/ollama/models` — ruft `GET http://localhost:11434/api/tags` ab, gibt Liste mit Name, Größe, Datum zurück
- `POST /api/admin/ollama/pull` — Body: `{"model": "gemma3:4b"}` — startet `ollama pull` als Subprocess, streamt Fortschritt als SSE (`text/event-stream`)
- `DELETE /api/admin/ollama/models/{name}` — löscht ein lokales Modell via Ollama API

**`llm_router.py` — neuer Task-Typ `telegram`:**
```python
DEFAULT_ROUTING = {
    "classify": "local",
    "telegram": "local",   # NEU — mappt auf model_light
    "action": "local",
    "content": "local",
    "scheduled": "local",
}
```
- `telegram`-Calls nutzen `llm.model_light` statt `llm.model`
- `scheduled` und `action` nutzen `llm.model_heavy`
- `classify` bleibt auf `model_light` (schnell, reicht für Klassifizierung)

**`llm_client.py`:**
- `chat_light()` — nutzt `self.model_light`, reduzierter `num_ctx` (8192)
- `chat_heavy()` — nutzt `self.model_heavy`, voller `num_ctx`

**`llm_router.py` — `get_client_with_size(task_type)` statt nur `get_client()`:**
- Gibt Tupel `(client, size)` zurück: `size` ist `"light"` oder `"heavy"`
- `MainAgent` ruft dann `client.chat_light()` oder `client.chat_heavy()` je nach `size`
- `telegram` + `classify` → `"light"`, `action` + `content` + `scheduled` → `"heavy"`

### Frontend

**LLM-Routing-Sektion (bestehend, erweitert):**
- Dropdowns statt Freitext für classify/telegram/action/content/scheduled
- Dropdowns werden beim Laden mit `/api/admin/ollama/models` befüllt
- Speichern-Button persistiert via bestehendem Config-Endpunkt

**Neues Modal "Modell-Manager":**
- Trigger: "Modelle verwalten"-Button in der LLM-Routing-Sektion
- Inhalt: Tabelle mit lokalem Modell-Name, Größe (GB), Datum
- "+ Modell pullen"-Button: öffnet Input-Feld für Modell-Name (z.B. `gemma3:4b`)
- Pull-Fortschritt: Fortschrittsbalken via SSE-Stream
- Löschen-Button pro Modell (mit Bestätigung)

---

## 2. Schedule-Bug-Fix + Intent-Prefilter

### Ziel
"Leg einen Schedule an", "ich will täglich ein Briefing", "erinner mich um 9 Uhr" → landet immer in der DB und ist sofort in der UI sichtbar. Niemals als Shell-Skript.

### Neue Datei: `backend/intent_prefilter.py`

Drei Erkennungsebenen, läuft **vor** dem LLM-Classify-Call:

**Ebene 1 — Direkte Keywords** (sofortige Erkennung, 0 Token):
```
schedule-Keywords:  schedule, täglich, stündlich, wöchentlich, alle X minuten/stunden,
                    jeden morgen/abend/montag/.., um HH:MM, briefing, erinnerung, reminder,
                    regelmäßig, wiederkehrend, automatisch
task-Keywords:      erstelle task, neuer task, task anlegen, aufgabe erstellen
obsidian-Keywords:  in obsidian, obsidian ablegen, speichere in, leg ab in
```

**Ebene 2 — Muster-Kombinationen** (Regex):
```python
SCHEDULE_PATTERNS = [
    r"ich will (täglich|jeden|morgens|abends|wöchentlich|regelmäßig)",
    r"mach (mir|das|bitte)?.*(täglich|jeden|regelmäßig|automatisch)",
    r"(erstelle|leg an|richte ein|setz auf).*(schedule|aufgabe|briefing|zusammenfassung|report|monitoring)",
    r"um \d{1,2}:\d{2}",           # Zeitangabe mit Aktion im Kontext
    r"(täglich|wöchentlich|monatlich|stündlich)",
    r"jeden (tag|morgen|abend|montag|dienstag|mittwoch|donnerstag|freitag)",
]
```

**Ebene 3 — Semantic Fallback** (bei Score 0.5–0.8):
- Mini-LLM-Call mit `model_light` (4B): *"Ist das eine Anfrage für einen wiederkehrenden automatischen Task? Antworte nur: ja / nein / unklar"*
- `ja` → `create_schedule`, `nein` → normaler Classify-Pfad, `unklar` → normaler Classify-Pfad

**Confidence-Score:**
- Ebene 1 Match → Score 1.0 → direkt `create_schedule`
- Ebene 2 Match → Score 0.85 → direkt `create_schedule`
- Ebene 3 `ja` → Score 0.75 → `create_schedule`
- Sonst → `None` → normaler LLM-Classify-Pfad

### `main_agent.py` — Prefilter-Integration

```python
async def handle(self, message, chat_id):
    # 1. Intent-Prefilter (vor LLM-Call)
    prefilter_result = intent_prefilter.check(message)
    if prefilter_result == "create_schedule":
        return await self._schedule_create_from_natural(message, chat_id)
    if prefilter_result == "create_task":
        return await self._task_create_from_natural(message, chat_id)
    # 2. Normaler Classify-Pfad
    intent = await self.classify(message, chat_id)
    ...
```

**WICHTIG:** `ops_command` darf NIEMALS für Schedule-Erstellung genutzt werden. Explizit im Classifier-Prompt verboten.

### Scheduler-Reload nach DB-Insert

Nach `db.create_schedule(...)` sofort:
```python
await self.scheduler.reload_tasks()
```
→ Schedule erscheint ohne Server-Neustart in der UI.

---

## 3. Prompt-Engineering-Overhaul

### Ziel
Alle System-Prompts nach Claude Code Leak Best Practices umschreiben: modular, explizite Verbote, kognitive Anforderungen, Output-Templates, Cache-Boundary.

### Neue Datei-Struktur: `backend/prompts/`

```
backend/prompts/
├── __init__.py
├── classify.py      — Modularer Classifier-Prompt
├── subagent.py      — SubAgent-Prompts mit Output-Templates
└── schedule.py      — Schedule-Agent-Prompt
```

### `backend/prompts/classify.py`

**Aufbau (modular, dynamisch assembled):**

```
[SEKTION 1 — KERN-IDENTITÄT] (statisch, gecacht)
Du bist Falki. Deine Aufgabe: Nachrichten klassifizieren und zum richtigen Handler routen.

[SEKTION 2 — EXPLIZITE VERBOTE] (statisch, gecacht)
NIEMALS:
- ops_command für Schedule-Erstellung (auch wenn der User "anlegen", "erstellen", "einrichten" sagt)
- Shell-Skript wenn eine DB-API verfügbar ist
- Jeden Punkt eines nummerierten Prompts einzeln beantworten
- Bestätigung pro Punkt statt Gesamt-Ergebnis

[SEKTION 3 — INTENT-DEFINITIONEN] (statisch, gecacht)
Jeder Intent mit Beschreibung + 3 positiven Beispielen + 2 negativen Beispielen

[SEKTION 4 — KOGNITIVE ANFORDERUNGEN] (statisch, gecacht)
Verstehe den GESAMT-INTENT bevor du antwortest.
Bei nummerierten Punkten: Was ist das übergeordnete Ziel? Route zum passenden Handler mit konsolidiertem Prompt.

[SEKTION 5 — OUTPUT-FORMAT-TEMPLATES] (statisch, gecacht)
Für jeden Intent-Typ: exaktes JSON-Format + erlaubte Felder

[SEKTION 6 — DYNAMISCHER KONTEXT] (session-spezifisch, NICHT gecacht)
## Aktuelle Session
Aktive Agents: ...
Offene Tasks: ...
Aktiver Workspace: ...
```

### `backend/prompts/subagent.py`

**Aufbau:**
```
[KERN-ANWEISUNG]
Du bist ein {agent_type}-SubAgent. Deine Aufgabe: {consolidated_task}

[OUTPUT-TEMPLATE je nach result_type]
- recherche: Markdown mit ## Zusammenfassung, ## Quellen, ## Kernpunkte
- guide: Markdown mit ## Voraussetzungen, ## Schritt-für-Schritt, ## Tipps
- code: Markdown mit ## Problem, ## Lösung (Code-Block), ## Erklärung
- report: Markdown mit ## Executive Summary, ## Details, ## Empfehlungen

[EXPLIZITE ANFORDERUNGEN]
- Antworte einmal mit dem vollständigen Ergebnis
- Kein "Ich habe Punkt 1 erledigt..." — nur das Endergebnis
- Sprache: Deutsch (außer Code-Kommentare: Englisch)
```

### `backend/prompts/schedule.py`

Für den SmartScheduler wenn er einen SubAgent für einen Schedule-Task startet:
- Kontext: welcher Schedule, letzter Run, Ergebnis-Typ
- Explizites Output-Template
- Ablage-Anweisung (Obsidian-Ordner)

### Prompt-Konsolidierung (`backend/prompt_consolidator.py`)

Erkennt nummerierte/aufgezählte Prompts und baut einen einzigen kohärenten Prompt:

```python
def consolidate(message: str) -> str:
    """Erkennt nummerierte Punkte und konsolidiert zu einem Prompt."""
    # Erkennung: 3+ nummerierte Punkte oder Bullet-Points
    # Analyse: Was ist das Gesamtziel?
    # Output: Ein flüssiger, vollständiger Prompt
    # Beispiel: "1. Recherchiere X 2. Erstelle Guide"
    #        → "Recherchiere X und erstelle daraus einen strukturierten Guide."
```

---

## 4. Output-Routing (Kontext-bewusst)

### Ziel
Ergebnisse landen immer am richtigen Ort. Explizite Anweisungen werden respektiert. Bei Unklarheit wird gefragt statt geraten.

### Neue Datei: `backend/output_router.py`

**3-Stufen-Check (nach SubAgent-Fertigstellung):**

**Stufe 1 — Explizite Anweisung** (0 Token, Keyword-Check):
```python
OBSIDIAN_KEYWORDS = ["in obsidian", "obsidian ablegen", "speichere in", "leg ab in"]
TASK_KEYWORDS = ["als task", "in tasks", "task erstellen", "aufgabe anlegen"]
SCHEDULE_KEYWORDS = ["als schedule", "schedule anlegen", "täglich ausführen"]
REPLY_KEYWORDS = ["hier antworten", "zeig mir", "sag mir"]
```

**Stufe 2 — Kontext-Inferenz** (bei keiner expliziten Anweisung):
- Letzten 5 Nachrichten der Session analysieren
- `model_light`-Call: *"Wohin soll dieses Ergebnis basierend auf dem Kontext? Antworte nur: obsidian / task / schedule / reply"*
- Confidence > 0.8 → direkt routen

**Stufe 3 — Nachfragen** (bei Confidence ≤ 0.8):
- Kurze Frage via Telegram/WS: *"Wo soll ich das ablegen? [Obsidian] [Task] [Hier anzeigen]"*
- Inline-Buttons in Telegram für schnelle Auswahl

**Routing-Ziele:**

| Ziel | Aktion |
|------|--------|
| `obsidian` | `ObsidianWriter` mit Ordner aus `result_type` (Recherchen/Guides/Code/Reports) |
| `task` | `db.create_task()` → erscheint in UI Tasks-Sektion |
| `schedule` | `db.create_schedule()` + `scheduler.reload_tasks()` → erscheint in UI Schedules-Sektion |
| `reply` | Direkt an Telegram/WebSocket |

---

## 5. Workspace-Kontext-Anhang

### Ziel
User kann per "+" Button Dateien hochladen oder ein Verzeichnis auswählen. Der Kontext wird für die Session aktiv und im Chat sichtbar.

### Backend

**Neue Datei `backend/workspace_api.py`** (eigener FastAPI-Router, eingebunden in `main.py`):

- `POST /api/workspace/upload` — Multipart-Upload (Datei oder Ordner als ZIP), entpackt in `./workspace/<session_id>/`, gibt Pfad + Dateiliste zurück
- `POST /api/workspace/path` — Body: `{"path": "/Users/janik/Buchprojekt"}` — validiert Existenz, speichert als aktiven Workspace für Session
- `GET /api/workspace/current` — gibt aktiven Workspace zurück (Pfad + Typ + Dateiliste)
- `DELETE /api/workspace/current` — löscht aktiven Workspace für Session

**Kontext-Injektion in `MainAgent`:**
- Aktiver Workspace-Pfad wird in `_build_context()` ergänzt
- Bei File-Upload: bis zu 50k Token Dateiinhalt werden in SubAgent-Prompt injiziert (relevante Dateien nach Typ gefiltert: `.md`, `.txt`, `.py`, `.js` etc.)

### Frontend

**Chat-UI — "+" Button:**
- Position: links neben dem Chat-Input-Feld
- Dropdown bei Klick:
  - **📄 Datei hochladen** → `<input type="file">` (einzelne Datei)
  - **📁 Ordner hochladen** → `<input type="file" webkitdirectory>` (Ordner als Upload)
  - **📂 Verzeichnis wählen** → `window.showDirectoryPicker()` → nur Pfad wird an `/api/workspace/path` gesendet

**Aktiver Workspace Anzeige:**
- Badge/Chip unter dem Chat-Input: `📁 ~/Buchprojekt  ✕`
- "✕" entfernt den Workspace-Kontext für die Session
- Beim Reload bleibt der Workspace aktiv (in `sessionStorage` gespeichert)

---

## Nicht-Ziele (explizit ausgeschlossen)

- Kein TTS/Voice-Loop (separates Feature)
- Keine Authentifizierung für Workspace-Upload (läuft lokal)
- Kein Cloud-Storage (alles lokal)
- Keine Änderungen an der Phaser.js-Pixel-UI

---

## Implementierungsreihenfolge

1. `backend/prompts/` — Prompt-Overhaul (Basis für alles andere)
2. `backend/intent_prefilter.py` + Schedule-Bug-Fix
3. `backend/prompt_consolidator.py`
4. `backend/output_router.py`
5. Ollama Model-Browser API + Frontend
6. Workspace-API + Frontend "+" Button
