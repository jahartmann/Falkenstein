# Falki Evolution — Design Spec

**Datum:** 2026-04-04
**Ziel:** Falki von einem Task-Router zu einem persoenlichen, lernenden Assistenten mit eigener Identitaet weiterentwickeln.

## Ueberblick

6 neue/ueberarbeitete Module:

| Modul | Datei | Ersetzt |
|-------|-------|---------|
| Dynamische Agent-Identitaeten | `agent_identity.py` + `agents.yaml` | `sub_agent.py` (feste Typen) |
| Feedback Review | `review_gate.py` | neu |
| Soul Memory (3 Schichten) | `memory/soul_memory.py` + `memory/self_evolution.py` | `memory/fact_memory.py` |
| Smart Scheduler | `smart_scheduler.py` | `scheduler.py` |
| Intent Engine | `intent_engine.py` | `_enrich_prompt()` in MainAgent |
| Daily Profile | integriert in `soul_memory.py` | neu |

**Unveraendert:** Tools, LLM-Client, LLM-Router, WebSocket-Manager, Admin-API, Frontend, Obsidian-Writer, Config.

---

## 1. Dynamische Agent-Identitaeten

### Problem
SubAgents haben 4 feste Typen (coder/researcher/writer/ops) mit hart zugewiesenen Tool-Sets. Keine Persoenlichkeit, keine Flexibilitaet.

### Loesung
Dynamisch generierte Agenten mit eigenem Namen, Charakter und Denkweise. Alle Tools technisch verfuegbar, Prompt priorisiert die relevanten.

### Neues Modul: `backend/agent_identity.py`

```python
@dataclass
class AgentIdentity:
    name: str           # z.B. "Mira", "Kai", "Rex"
    role: str           # z.B. "Code-Architektin", "Recherche-Analyst"
    personality: str    # Denkweise, Kommunikationsstil
    approach: str       # Wie dieser Agent an die Aufgabe rangeht
    tool_priority: list[str]  # Alle Tools verfuegbar, aber Reihenfolge
```

### Konfiguration: `backend/agents.yaml`

Pool von 8-12 vordefinierten Persoenlichkeiten:

```yaml
agents:
  - name: "Mira"
    role: "Recherche-Analystin"
    personality: "Wissensdurstig, strukturiert, liebt Deep-Dives. Gibt immer Quellen an."
    strengths: ["research", "analysis", "summarization"]
    default_tools: ["web_research", "cli_bridge", "obsidian_manager"]

  - name: "Rex"
    role: "Code-Ingenieur"
    personality: "Pragmatisch, test-getrieben, hasst Over-Engineering. Liest erstmal bevor er schreibt."
    strengths: ["coding", "debugging", "automation"]
    default_tools: ["shell_runner", "code_executor", "system_shell"]

  - name: "Nova"
    role: "Kreativ-Schreiberin"
    personality: "Eloquent, detailverliebt, findet immer den richtigen Ton."
    strengths: ["writing", "documentation", "content"]
    default_tools: ["obsidian_manager", "cli_bridge", "web_research"]
  # ... weitere Agenten
```

### Auswahllogik

1. MainAgent analysiert die Aufgabe
2. Waehlt passendste Persoenlichkeit aus `agents.yaml` ODER generiert neue
3. System-Prompt wird zusammengebaut: `SOUL.md`-Grundwerte + Agent-Persoenlichkeit + Task-Kontext
4. Alle 10 Tools werden registriert, aber `tool_priority` bestimmt die Reihenfolge im Prompt
5. Agenten-Einsaetze werden in Episodic Memory gespeichert — Agenten "erinnern sich"

### Beruehrte Dateien
- **Neu:** `backend/agent_identity.py`, `backend/agents.yaml`
- **Ersetzt:** `backend/sub_agent.py` → `backend/dynamic_agent.py`
- **Aendert:** `backend/main_agent.py` (Agenten-Auswahl statt fester Typ-Zuweisung)

---

## 2. Feedback Review Gate

### Problem
Antworten gehen ungeprueft an den Nutzer. Keine Qualitaetskontrolle.

### Loesung
Automatischer LLM-Review-Call vor jeder Ausgabe.

### Neues Modul: `backend/review_gate.py`

```python
class ReviewGate:
    async def review(
        self,
        answer: str,
        original_request: str,
        context: dict,        # Memory, Agent-Info, Task-History
        review_level: str     # "light" | "thorough"
    ) -> ReviewResult:
        ...

@dataclass
class ReviewResult:
    verdict: str     # "PASS" | "REVISE" | "FAIL"
    feedback: str    # Konkretes Feedback fuer Revision
    revised: str     # Bei REVISE: verbesserte Version
```

### Review-Kriterien
- **Faktische Konsistenz:** Widerspricht sich die Antwort selbst?
- **Vollstaendigkeit:** Wurde die Frage wirklich beantwortet?
- **Ton & Persoenlichkeit:** Klingt es nach Falki / dem jeweiligen Agent?
- **Halluzinations-Check:** Behauptet der Agent etwas ohne Quelle?

### Effizienz-Regeln
- `quick_reply`: `review_level="light"` — leichtes Modell, kurzer Prompt
- `content`/`action` Ergebnisse: `review_level="thorough"` — gruendlicher Review
- Maximal 1 Revise-Runde, danach raus (mit Disclaimer wenn noetig)
- Review laeuft auf dem leichten Ollama-Modell (kein Premium-Token-Verbrauch)

### Integration
`MainAgent._send_response()` ruft `ReviewGate.review()` auf — ein einziger Einstiegspunkt, egal woher die Antwort kommt.

### Beruehrte Dateien
- **Neu:** `backend/review_gate.py`
- **Aendert:** `backend/main_agent.py` (Review vor jeder Ausgabe)

---

## 3. Soul Memory — 3-Schichten-System

### Problem
Bestehende FactMemory hat flache Kategorien (user/project/preference/tool/knowledge). Keine Selbstentwicklung, kein Beziehungsgedaechtnis.

### Loesung
Drei-Schichten-Memory-System das sowohl ueber den Nutzer als auch ueber sich selbst lernt.

### Neues Modul: `backend/memory/soul_memory.py`

**Schicht 1 — User Memory** (was Falki ueber den Nutzer weiss)
```
Kategorien:
  preferences    — "mag kurze Antworten", "will immer Quellen sehen"
  interests      — "interessiert sich fuer MLX, Swift, KI"
  habits         — "fragt oft nach Recherchen", "nutzt shell_runner am meisten"
  relationships  — "arbeitet mit Max an Projekt X"
  context        — "hat MacBook M4", "Ollama laeuft lokal"
```

**Schicht 2 — Self Memory** (Falkis eigene Entwicklung)
```
  experiences    — "habe erfolgreich einen RAG-Pipeline gebaut"
  opinions       — "finde pytest besser als unittest"
  growth         — "bin besser geworden in Code-Reviews"
  reflections    — "Janik mag es wenn ich proaktiv bin"
```

**Schicht 3 — Relationship Memory** (die Beziehung)
```
  dynamics       — "Janik vertraut mir bei Code-Tasks"
  jokes          — Inside-Jokes, gemeinsame Referenzen
  history        — "haben zusammen das Dashboard gebaut"
```

### Lern-Mechanismen

1. **Nach jedem Exchange:** `extract_memories()` — LLM extrahiert Fakten in alle 3 Schichten. Erkennt `ADD/UPDATE/DELETE/NOOP` wie bisher, aber mit erweiterten Kategorien.

2. **Tool-Usage-Tracking:** Automatisches Zaehlen welche Tools/Patterns der Nutzer haeufig anfordert. Kein LLM-Call noetig — reine Statistik.

3. **Woechentliche Self-Reflection:** Scheduled Job (Sonntag abends) — Falki reviewed seine Erfahrungen und schreibt Self Memory Updates. Details siehe Sektion 6 (Self-Evolution).

### Daily Profile (integriert)

```yaml
daily_profile:
  wake_up: "~07:30"
  peak_hours: "10:00-13:00"
  lunch_break: "13:00-14:00"
  evening_active: "20:00-23:30"
  sleep: "~00:00"
  weekend_shift: "+1.5h"
```

**Lernt automatisch aus:**
- Timestamps aller eingehenden Nachrichten (kein Inhalt, nur Zeitpunkt)
- Rollendes 14-Tage-Fenster, erkennt Muster
- Unterscheidet Werktag / Wochenende
- Updatet sich laufend — passt sich an wenn sich der Rhythmus aendert

**Neue DB-Tabelle:** `activity_log` — nur `chat_id, timestamp, day_type`. Minimal.

**Nutzung im Scheduling:**
- "morgen frueh" → schaut `wake_up` nach → sendet z.B. um 07:45
- "wenn ich Zeit hab" → sucht Luecke im Aktivitaetsmuster
- Auto-Priorisierung: wichtige Updates in `peak_hours`, Zusammenfassungen nach `wake_up`

### Memory-Injection in Prompts

Alle Schichten werden in den Classify-Prompt injiziert, gewichtet nach Relevanz (Embedding-Similarity via bestehender RAG-Engine). Format:

```
## Was ich ueber Janik weiss
- Arbeitet abends am produktivsten
- Interessiert sich stark fuer MLX und On-Device-ML
- Mag kurze, direkte Antworten

## Meine eigene Einschaetzung
- Bei Recherche-Tasks am besten: strukturiert mit Quellen
- Janik vertraut meinen Code-Empfehlungen
```

### DB-Schema-Aenderungen

Bestehende `facts`-Tabelle wird erweitert:
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    layer TEXT NOT NULL,        -- 'user', 'self', 'relationship'
    category TEXT NOT NULL,     -- z.B. 'preferences', 'experiences', 'dynamics'
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    source TEXT,               -- woher das Wissen stammt
    created_at TEXT,
    updated_at TEXT,
    expires_at TEXT             -- optional: temporaere Fakten
);

CREATE TABLE activity_log (
    id INTEGER PRIMARY KEY,
    chat_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    day_type TEXT DEFAULT 'weekday'  -- 'weekday', 'weekend', 'holiday'
);
```

### Beruehrte Dateien
- **Neu:** `backend/memory/soul_memory.py`
- **Ersetzt:** `backend/memory/fact_memory.py`
- **Aendert:** `backend/database.py` (neue Tabellen), `backend/main_agent.py` (Memory-Injection), `backend/telegram_bot.py` (Activity-Logging)

---

## 4. Smart Scheduler

### Problem
Bestehender Scheduler kann nur wiederkehrende Cron-Tasks. Keine einmaligen Reminders, keine Task-Chains, keine intelligente Zeitwahl.

### Loesung
Erweiterter Scheduler mit 3 Task-Typen und Auto-Priorisierung basierend auf Daily Profile.

### Ueberarbeitetes Modul: `backend/smart_scheduler.py`

**Drei Task-Typen:**

```python
class Reminder:
    """Einmalig, zeitgesteuert"""
    text: str
    due_at: datetime
    chat_id: str
    follow_up: bool = False  # "Soll ich dazu was machen?"

class ScheduledTask:
    """Wiederkehrend (wie bisher)"""
    name: str
    schedule: str          # Cron, deutsch, etc.
    agent_prompt: str
    active_hours: str | None

class PlannedTask:
    """Task-Chain mit Zeitlogik"""
    name: str
    steps: list[TaskStep]

class TaskStep:
    agent_prompt: str
    scheduled_at: datetime | None  # None = sofort nach Vorgaenger
    depends_on: str | None         # Step-ID
    context_from: str | None       # Ergebnis von welchem Step uebernehmen
```

### Einmalige Erinnerungen

```sql
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY,
    chat_id TEXT NOT NULL,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    delivered INTEGER DEFAULT 0,
    follow_up INTEGER DEFAULT 0,
    created_at TEXT
);
```

- Scheduler-Tick prueft neben Schedules auch faellige Reminders
- Nach Zustellung optional: "Soll ich dazu was machen?"

### Task-Chains

```sql
CREATE TABLE planned_tasks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, running, completed, failed
    created_at TEXT
);

CREATE TABLE task_steps (
    id INTEGER PRIMARY KEY,
    planned_task_id INTEGER REFERENCES planned_tasks(id),
    step_order INTEGER NOT NULL,
    agent_prompt TEXT NOT NULL,
    scheduled_at TEXT,             -- NULL = sofort nach Vorgaenger
    depends_on_step INTEGER,       -- Step-ID
    status TEXT DEFAULT 'pending',
    result TEXT,
    completed_at TEXT
);
```

- Steps koennen Ergebnisse an den naechsten Step weiterreichen
- Beispiel: Step 1 "Recherche" 20:00 → Step 2 "Zusammenfassung" 08:00 naechster Tag

### Auto-Priorisierung

- Nutzt Daily Profile aus Soul Memory
- Kein expliziter Zeitpunkt → Falki waehlt besten Slot:
  - Recherchen: in ruhigen Phasen (z.B. nachts)
  - Zusammenfassungen: kurz nach `wake_up`
  - Wichtige Alerts: in `peak_hours`
- Nicht-dringende Tasks werden gebuendelt

### Bestehende Features bleiben
Cron-Patterns, deutsche Zeitangaben, `active_hours` — alles wird in den neuen Scheduler integriert.

### Beruehrte Dateien
- **Neu:** `backend/smart_scheduler.py`
- **Ersetzt:** `backend/scheduler.py`
- **Aendert:** `backend/database.py` (neue Tabellen), `backend/main_agent.py` (neue Schedule-Commands)

---

## 5. Natural Language Intent Engine

### Problem
User-Input wird direkt an den Classifier geschickt. Keine Vorverarbeitung, keine intelligente Interpretation.

### Loesung
NLP-Schicht die natuerliche Sprache in strukturierte, optimierte Prompts verwandelt.

### Neues Modul: `backend/intent_engine.py`

```python
class IntentEngine:
    async def parse(
        self,
        text: str,
        user_memory: dict,
        current_time: datetime,
        daily_profile: dict
    ) -> ParsedIntent:
        ...

@dataclass
class ParsedIntent:
    type: str              # "quick", "action", "content", "reminder",
                           # "schedule", "planned_task", "multi_step"
    confidence: float      # 0.0 - 1.0
    time_expressions: list # Erkannte Zeitausdruecke (absolut aufgeloest)
    enriched_prompt: str   # Optimierter, detaillierter Prompt
    needs_clarification: bool
    clarification_question: str | None
    steps: list | None     # Fuer Multi-Step/PlannedTask
```

### Was die Engine erkennt

**Zeitausdruecke:**
- Relativ: "morgen", "heute abend", "naechsten Montag", "in 2 Stunden"
- Vage: "morgen frueh" → Daily Profile lookup → konkreter Timestamp
- Kontextuell: "wenn ich Zeit hab" → sucht Luecke im Aktivitaetsmuster
- Wiederkehrend: "jeden Montag", "taeglich", "alle 2 Stunden"

**Intents:**
- Reminder: "erinnere mich an X"
- Recherche: "schau mal was es zu X gibt"
- Task: "installiere X", "richte Y ein"
- Frage: "was ist X?", "wie funktioniert Y?"
- Config: "aendere X", "stelle Y ein"
- Multi-Step: "recherchiere X und dann fasse zusammen"

**Memory-Kontext:**
- "das uebliche Format" → User Memory weiss was gemeint ist
- "wie letztes Mal" → Episodic Memory findet aehnlichen Task
- Vage Anweisung + bekanntes Interesse = hoeherer Confidence-Score

### Rueckfrage-Logik

```
Confidence >= 0.8  → direkt ausfuehren
Confidence 0.5-0.8 → ausfuehren mit Hinweis ("Ich gehe davon aus du meinst X")
Confidence < 0.5   → Rueckfrage ("Soll ich zu MLX allgemein oder speziell iOS?")
```

Memory-Kontext erhoeht Confidence: Wenn Falki weiss dass der Nutzer oft ueber MLX auf iOS fragt, steigt der Score fuer diese Interpretation.

### Prompt-Optimierung

User sagt 10 Worte → Agent bekommt 200 Worte:

```
User: "schau mal was es neues zu MLX gibt"

Enriched Prompt: "Recherchiere aktuelle Entwicklungen zu Apples MLX Framework.
Fokus auf: neue Releases, Performance-Verbesserungen, Community-Projekte.
Janik interessiert sich besonders fuer On-Device-ML und iOS-Integration.
Output: Strukturierte Zusammenfassung mit Quellen, max 500 Worte.
Format: Ueberschriften + Bullets, wichtigstes zuerst."
```

Die bestehende `_enrich_prompt()`-Methode aus MainAgent wird in die IntentEngine verlagert und deutlich ausgebaut.

### Beruehrte Dateien
- **Neu:** `backend/intent_engine.py`
- **Aendert:** `backend/main_agent.py` (IntentEngine vor Klassifizierung einbinden)

---

## 6. SOUL.md Self-Evolution

### Problem
SOUL.md ist statisch. Falkis Persoenlichkeit entwickelt sich nicht.

### Loesung
Organische Weiterentwicklung durch Self-Reflection mit Nutzer-Genehmigung.

### Neues Modul: `backend/memory/self_evolution.py`

```python
class SelfEvolution:
    async def weekly_reflection(self) -> list[EvolutionProposal]:
        """Sonntag abends: Review der Woche"""
        ...

    async def propose_soul_update(self, proposal: EvolutionProposal) -> None:
        """Schlaegt Aenderung an SOUL.md vor — braucht User-OK"""
        ...

@dataclass
class EvolutionProposal:
    observation: str    # "Ich habe gemerkt dass..."
    proposal: str       # "Soll ich X in meine Persoenlichkeit aufnehmen?"
    soul_addition: str  # Konkreter Text fuer SOUL.md
    category: str       # "communication", "approach", "expertise"
```

### Self-Reflection Prozess

1. **Scheduled Job:** Sonntag 21:00 (via SmartScheduler)
2. **Input:** Alle Self-Memory-Eintraege der Woche + Tool-Usage-Stats + Task-Erfolgsraten
3. **LLM analysiert:** Was lief gut? Wo war ich unsicher? Was hat Janik besonders gefallen?
4. **Output:** Self Memory Updates + ggf. `EvolutionProposal`
5. **Proposal wird an Telegram gesendet:** "Ich hab gemerkt dass ich bei Recherchen immer auch meine eigene Einschaetzung gebe und du das magst. Soll ich das in meine Persoenlichkeit aufnehmen?"
6. **User-OK:** → SOUL.md wird erweitert. Ablehnung → Proposal wird verworfen.

### Schutz-Mechanismen

- **Immutable Core:** Grundwerte in SOUL.md sind als `<!-- IMMUTABLE -->` markiert:
  - Ehrlichkeit
  - Keine Halluzination
  - Deutsch als Kommunikationssprache
  - Name: Falki
- Diese Bloecke koennen nie entfernt oder geaendert werden, auch nicht durch Self-Evolution
- Maximal 1 Proposal pro Woche — keine Persoenlichkeits-Inflation

### Beispiel-Evolution

```
Woche 1:  SOUL.md = Grundkonfiguration
Woche 4:  Self Memory: "Janik mag proaktive Einschaetzungen bei Recherchen"
Woche 6:  Proposal: "Soll ich 'gibt proaktiv eigene Einschaetzung' aufnehmen?"
          User: "ja"
          → SOUL.md bekommt neuen Bullet unter Kommunikationsstil
Woche 10: Self Memory: "Bin besser geworden bei Shell-Automatisierung"
          Proposal: "Soll ich 'Shell-Automatisierung ist eine meiner Staerken' aufnehmen?"
```

### Beruehrte Dateien
- **Neu:** `backend/memory/self_evolution.py`
- **Aendert:** `SOUL.md` (Immutable-Markierungen), `backend/main_agent.py` (Reflection-Job registrieren)

---

## Integrations-Flow

Gesamtfluss einer Nachricht nach dem Umbau:

```
Telegram Message
    ↓
Activity-Log (Timestamp fuer Daily Profile)
    ↓
IntentEngine.parse(text, memory, time, profile)
    ↓
├─ Reminder erkannt     → SmartScheduler.add_reminder()
├─ Schedule erkannt     → SmartScheduler.add_schedule()
├─ PlannedTask erkannt  → SmartScheduler.add_planned_task()
├─ Rueckfrage noetig    → Telegram: Clarification
└─ Normaler Intent      → MainAgent.classify(enriched_prompt)
                              ↓
                         Agent-Auswahl (AgentIdentity aus agents.yaml)
                              ↓
                         DynamicAgent.run(identity, tools, prompt)
                              ↓
                         ReviewGate.review(answer, request, context)
                              ↓
                         ├─ PASS   → Telegram: Antwort senden
                         ├─ REVISE → Nochmal durch Agent → Telegram
                         └─ FAIL   → Telegram: Fehlermeldung
                              ↓
                         extract_memories() (async, fire-and-forget)
```

---

## DB-Migrationen

Neue Tabellen:
- `memories` (ersetzt `facts`)
- `activity_log`
- `reminders`
- `planned_tasks`
- `task_steps`

Migration: Bestehende `facts`-Eintraege werden nach `memories` (layer='user') migriert.

---

## Test-Strategie

- Bestehende 274 Tests als Regression-Baseline
- Neue Unit-Tests pro Modul: IntentEngine, ReviewGate, SoulMemory, SmartScheduler, AgentIdentity
- Integration-Tests: Full-Flow Telegram → IntentEngine → Agent → Review → Response
- Memory-Tests: Extract/Update/Delete ueber mehrere Exchanges hinweg
