# Scheduled Tasks & Heartbeat — Design Spec

**Datum:** 2026-04-04

## Zusammenfassung

Scheduled Tasks System mit Obsidian als Source of Truth. Tasks werden als Markdown-Files mit YAML-Frontmatter in `KI-Büro/Management/Schedules/` gespeichert. Ein Scheduler-Loop prüft jede Minute ob Tasks fällig sind und führt sie über MainAgent aus. HEARTBEAT_OK-Signal unterdrückt Benachrichtigungen wenn nichts zu berichten ist.

## Obsidian-Struktur

Ein File pro Scheduled Task in `KI-Büro/Management/Schedules/`:

```
KI-Büro/Management/Schedules/
├── morgen-briefing.md
├── heartbeat.md
├── wochen-report.md
├── .last_run.json        ← Persistente Ausführungszeiten
└── ...
```

### Task-File Format

```markdown
---
name: Morgen-Briefing
schedule: täglich 07:00
agent: researcher
active: true
active_hours: 06:00-22:00
light_context: true
---

# Morgen-Briefing

Dein Prompt hier...
```

**Frontmatter-Felder:**

| Feld | Pflicht | Default | Beschreibung |
|------|---------|---------|-------------|
| `name` | Ja | — | Anzeigename |
| `schedule` | Ja | — | Zeitplan (siehe Schedule-Formate) |
| `agent` | Nein | `researcher` | SubAgent-Typ: coder/researcher/writer/ops |
| `active` | Nein | `true` | Aktiviert/deaktiviert |
| `active_hours` | Nein | — | Zeitfenster z.B. `06:00-22:00`, außerhalb wird nicht getriggert |
| `light_context` | Nein | `false` | Wenn true: kein System-Status-Kontext, nur der Prompt |

**Body:** Der komplette Prompt als Markdown. Wird 1:1 an den SubAgent übergeben.

### Schedule-Formate

Menschenlesbar, wird intern zu nächstem Ausführungszeitpunkt berechnet:

| Format | Beispiel | Bedeutung |
|--------|----------|-----------|
| `täglich HH:MM` | `täglich 07:00` | Jeden Tag um 7:00 |
| `stündlich` | `stündlich` | Jede volle Stunde |
| `alle N Minuten` | `alle 30 Minuten` | Alle 30 Min |
| `alle N Stunden` | `alle 6 Stunden` | Alle 6h |
| `Mo-Fr HH:MM` | `Mo-Fr 09:00` | Werktags um 9:00 |
| `montags HH:MM` | `montags 08:00` | Jeden Montag um 8:00 |
| `wöchentlich TAG HH:MM` | `wöchentlich Freitag 18:00` | Jeden Freitag 18:00 |
| `cron: EXPR` | `cron: 0 7 * * 1-5` | Cron-Fallback |

## Scheduler Engine (`backend/scheduler.py`)

### Tick-Loop

Async Loop der parallel zum Telegram-Polling läuft:

1. **Startup:** Alle `.md` Files aus `Schedules/` lesen und parsen
2. **Last-Run laden:** `.last_run.json` lesen — enthält `{"filename": "2026-04-04T07:00:00"}` pro Task
3. **Verpasste nachholen:** Beim Start prüfen ob ein Task seit dem letzten Run fällig gewesen wäre. Wenn ja UND noch im `active_hours` Fenster → sofort ausführen.
4. **Tick (jede 60 Sekunden):**
   - Für jeden aktiven Task: Ist er jetzt fällig? (nächste Ausführungszeit ≤ jetzt)
   - Prüfe `active_hours` — wenn außerhalb, überspringen
   - Wenn fällig → `MainAgent.handle_scheduled(task)` aufrufen
   - `last_run` aktualisieren und `.last_run.json` schreiben
5. **File-Reload:** Wenn ObsidianWatcher eine Änderung in `Schedules/` meldet → Tasks neu laden

### Schedule-Parser

Parst die menschenlesbaren Schedule-Strings und berechnet den nächsten Ausführungszeitpunkt:

```python
def next_run(schedule: str, after: datetime) -> datetime:
    """Berechnet nächsten Ausführungszeitpunkt nach 'after'."""
```

Unterstützt alle Formate aus der Tabelle oben. Cron-Fallback nutzt `croniter` (pip-Dependency) oder einfache Eigenimplementierung für die gängigen Patterns.

### Zuverlässigkeit

- **Persistente Last-Run:** `.last_run.json` wird nach jeder Ausführung geschrieben, nicht nur im RAM
- **Verpasste Tasks nachholen:** Beim Serverstart werden alle Tasks geprüft. Wenn ein Task seit dem letzten Run fällig war und noch im active_hours-Fenster liegt, wird er sofort ausgeführt
- **Kein Drift:** Timer rechnet mit absoluten Zeitpunkten (`next_run`), nicht mit relativen Sleeps
- **Timeout:** Wenn ein SubAgent nach 5 Minuten nicht fertig ist, wird er abgebrochen und als Fehler geloggt
- **Keine Doppelausführung:** `last_run` wird VOR der Ausführung auf "jetzt" gesetzt, nicht danach

## HEARTBEAT_OK-Flow

```
Scheduler tick → Task fällig?
  → Ja → MainAgent.handle_scheduled(task)
    → SubAgent.run(prompt)
      → Ergebnis beginnt mit "HEARTBEAT_OK"?
        → Ja: Stille. Nur last_run aktualisieren. Kein Telegram, kein Obsidian-Ergebnis.
        → Nein: Normaler Flow — Telegram-Nachricht + Obsidian-Ergebnis + Kanban
```

## Default Heartbeat

Beim ersten Start wird `heartbeat.md` automatisch erstellt wenn `Schedules/` leer ist:

```markdown
---
name: Heartbeat
schedule: alle 30 Minuten
agent: ops
active: true
active_hours: 08:00-22:00
light_context: true
---

# System Heartbeat

Prüfe den Systemstatus:
- Ist Ollama erreichbar?
- Gibt es neue Einträge in der Obsidian Inbox?
- Gibt es fehlgeschlagene Tasks?
- Wie ist der CLI-Budget-Stand?

Wenn alles in Ordnung ist, antworte NUR mit: HEARTBEAT_OK
Wenn es Probleme oder wichtige Updates gibt, erstelle einen kurzen Statusbericht.
```

## Admin UI

Neue Sektion "Scheduled Tasks" im Admin-Dashboard (`/admin`):

- Tabelle: Name, Schedule, nächste Ausführung, letzte Ausführung, Status (aktiv/inaktiv)
- Toggle aktiv/inaktiv pro Task (schreibt `active: true/false` ins Frontmatter)
- "Jetzt ausführen" Button pro Task
- Letzte Ausführung: Ergebnis-Preview (erste 200 Zeichen) oder "HEARTBEAT_OK"
- Link zur Obsidian-File (falls gewünscht)

### API-Endpoints

- `GET /api/admin/schedules` — Alle Scheduled Tasks mit Status
- `POST /api/admin/schedules/{name}/run` — Task sofort ausführen
- `PUT /api/admin/schedules/{name}/toggle` — Aktiv/inaktiv umschalten

## File Structure

### Neue Dateien:
- `backend/scheduler.py` — Schedule-Parser, Tick-Loop, Task-Loader, .last_run.json Management
- `tests/test_scheduler.py` — Tests für Schedule-Parser und Tick-Logik

### Geänderte Dateien:
- `backend/main_agent.py` — Neue `handle_scheduled()` Methode mit HEARTBEAT_OK-Logik
- `backend/main.py` — Scheduler im Lifespan starten
- `backend/obsidian_watcher.py` — `Schedules/` Ordner mitbeobachten
- `backend/admin_api.py` — Schedule-Endpoints hinzufügen
- `frontend/admin.html` — Scheduled Tasks Sektion
- `backend/tools/obsidian_manager.py` — `Schedules/` in Vault-Struktur aufnehmen
