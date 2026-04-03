# Intelligentes Notification-Routing: Telegram ↔ Obsidian

## Zusammenfassung

Bidirektionales Todo-Management zwischen Telegram und Obsidian mit intelligentem Feedback-Routing. Todos fließen in beide Richtungen, Task-Ergebnisse und Events werden regelbasiert (mit LLM-Hybrid-Check) an das richtige Ziel geroutet.

## Architektur

### Neue Module

1. **`backend/notification_router.py`** — `NotificationRouter`: Zentraler Event-Router
2. **`backend/obsidian_watcher.py`** — `ObsidianWatcher`: File-Watcher für Vault-Änderungen

### Geänderte Module

- **`backend/main.py`** — Router + Watcher initialisieren, sim_loop nutzt Router statt direkter Telegram-Calls
- **`backend/telegram_bot.py`** — Router-Referenz, neue `notify_obsidian_todo()` Methode
- **`backend/tools/obsidian_manager.py`** — Neue Methoden `write_task_result()` und `log_escalation()`
- **`.env.example`** — Neue Config-Variablen

---

## NotificationRouter

### Klasse

```python
NotificationRouter(telegram, obsidian_tool, llm_client, db)
```

### Routing-Regeltabelle

| Event | Telegram | Obsidian |
|---|---|---|
| `task_assigned` | Kurz-Info ("Alex arbeitet an X") | — |
| `task_completed` | Kurz-Summary | Volles Ergebnis in Projekt-Tasks.md |
| `escalation_success` | Warnung | Detail-Log in Daily Report + Projekt-Notizen |
| `escalation_failed` | Warnung | Detail-Log |
| `budget_warning` | Sofort | — |
| `daily_report` | Zusammenfassung | Voller Report (wie bisher) |
| `todo_from_telegram` | Bestätigung | Eintrag in Inbox/Tasks |
| `todo_from_obsidian` | Benachrichtigung | — (bereits vorhanden) |
| `subtask_completed` | — | Update in Parent-Task |
| `project_created` | Kurz-Info | Ordnerstruktur (wie bisher) |

### LLM-Hybrid-Check

- Wird bei Events ausgelöst die an beide Ziele gehen sollen, wenn der Inhalt < 100 Zeichen ist
- Nutzt Light-Model (Gemma4 oder konfiguriertes light_model)
- Prompt: "Ist dieses Ergebnis detailliert genug für eine Dokumentation? Ja/Nein"
- Bei "Nein": nur Telegram, Obsidian wird übersprungen
- Konfigurierbar via `LLM_ROUTING_ENABLED` (default: true)

### Methoden

- `async route_event(event_type: str, payload: dict)` — Hauptmethode, dispatcht nach Regeltabelle
- `_format_telegram(event_type, payload) -> str` — Knappe Formatierung
- `_format_obsidian(event_type, payload) -> str` — Vollständige Markdown-Formatierung
- `_should_write_obsidian(event_type, payload) -> bool` — Regelcheck + optionaler LLM-Check

---

## ObsidianWatcher

### Klasse

```python
ObsidianWatcher(vault_path, notification_router, db)
```

### Funktionsweise

- Nutzt `watchdog` Library für Filesystem-Events
- Thread-basierter Observer mit asyncio Bridge (`loop.call_soon_threadsafe`)
- Überwacht gezielt:
  - `Management/Inbox.md` — neue Checkbox-Einträge (`- [ ]`)
  - `Falkenstein/Projekte/*/Tasks.md` — neue Todos pro Projekt

### Änderungserkennung

- Speichert pro Datei ein Set von Zeilen-Hashes (SHA256 der Zeile)
- Bei FileModified-Event: Datei neu lesen, Diff mit bekannten Hashes
- Nur neue `- [ ]` Einträge werden als Todos erkannt
- Ignoriert: Checkbox-Updates (`- [x]`), Nicht-Todo-Zeilen, Löschungen

### Debouncing

- 2 Sekunden Verzögerung nach letzter Änderung pro Datei
- Obsidian schreibt manchmal mehrfach bei einem Save
- Timer wird bei jeder neuen Änderung an derselben Datei zurückgesetzt

### Auto-Submit

- Konfigurierbar via `OBSIDIAN_AUTO_SUBMIT_TASKS` (default: false)
- Wenn aktiviert: neue Todos werden zusätzlich als Tasks an den Orchestrator submitted

### Lifecycle

- `async start()` — Observer starten, Initial-Scan der überwachten Dateien
- `async stop()` — Observer stoppen
- Läuft als asyncio-Task in main.py

---

## Integration in main.py

### Initialisierung (in lifespan)

```
1. ... (bestehende Initialisierung bis Telegram)
2. NotificationRouter(telegram, obsidian_tool, llm, db)
3. ObsidianWatcher(vault_path, router, db)
```

### Asyncio-Tasks

```
1. sim_loop() — bestehend, nutzt jetzt router.route_event() statt _notify_telegram()
2. telegram.poll_loop() — bestehend
3. watcher.start() — NEU
```

### sim_loop Änderung

Statt:
```python
if event_type == "task_completed":
    await telegram.notify_task_done(...)
```

Wird:
```python
await router.route_event(event_type, payload)
```

Der Router entscheidet dann über Telegram und/oder Obsidian.

---

## Telegram-Bot Änderungen

- Erhält `router` Referenz bei Initialisierung
- `/todo` Command: schreibt weiterhin direkt in Obsidian (schnelle Bestätigung), informiert Router
- Neue Methode `notify_obsidian_todo(text, project)` — wird vom Router aufgerufen bei Watcher-Events

---

## Obsidian-Manager Änderungen

### Neue Methoden

- `write_task_result(task_title, result, project)` — Ergebnis an Projekt-Tasks.md anhängen oder Checkbox aktualisieren
- `log_escalation(agent_name, task_title, details)` — Eskalationsdetails in Daily Report und/oder Projekt-Notizen

---

## Config (.env)

```
OBSIDIAN_WATCH_ENABLED=true        # Watcher an/aus
OBSIDIAN_AUTO_SUBMIT_TASKS=false   # Obsidian-Todos als Agent-Tasks einreichen
LLM_ROUTING_ENABLED=true           # Hybrid LLM-Check an/aus
```

---

## Datenfluss-Beispiele

### Todo von Telegram
```
User: "/todo Login fixen | website"
→ main.py parsed → obsidian.execute(todo, "Login fixen", "website")
→ router.route_event("todo_from_telegram", {text, project})
→ Telegram: "✓ Todo eingetragen"
→ Obsidian: Eintrag in Falkenstein/Projekte/website/Tasks.md
```

### Todo von Obsidian
```
User schreibt "- [ ] API Docs schreiben" in Inbox.md
→ Watcher erkennt neue Zeile (Debounce 2s)
→ router.route_event("todo_from_obsidian", {text, source_file})
→ Telegram: "Neuer Todo aus Obsidian: API Docs schreiben"
→ Optional: orchestrator.submit_task() wenn AUTO_SUBMIT=true
```

### Task completed
```
Agent Alex schließt Task ab
→ router.route_event("task_completed", {agent, task, result})
→ result > 100 Zeichen → beide Ziele
→ Telegram: "Alex hat 'Login fixen' abgeschlossen ✓"
→ Obsidian: Volles Ergebnis in Projekte/website/Tasks.md
→ Falls result < 100 Zeichen: LLM-Check → ggf. nur Telegram
```

### Eskalation
```
Agent Bob eskaliert
→ router.route_event("escalation_success", {...})
→ Telegram: "⚠ Eskalation bei Bob: CLI hat übernommen"
→ Obsidian: Detail-Log in Daily Report + Projekt-Notizen
```

---

## Testing

### test_notification_router.py
- Jeder Event-Typ wird gemäß Regeltabelle korrekt geroutet
- LLM-Hybrid-Check: wird bei kurzen Ergebnissen aufgerufen, bei langen übersprungen
- Formatierung: Telegram-Output knapp, Obsidian-Output mit Markdown
- LLM_ROUTING_ENABLED=false: kein LLM-Call, rein regelbasiert

### test_obsidian_watcher.py
- Neue `- [ ]` Einträge in Inbox.md werden erkannt
- Neue Einträge in Projekt-Tasks.md werden erkannt
- Duplikate (gleiche Zeile) werden nicht doppelt gemeldet
- Debouncing: mehrere schnelle Änderungen → ein Event
- `- [x]` Änderungen werden ignoriert
- Nicht-Todo-Zeilen werden ignoriert

### test_integration_routing.py
- End-to-End: Todo über Telegram → Obsidian-Eintrag vorhanden
- End-to-End: Todo in Obsidian → Telegram-Benachrichtigung gesendet
- End-to-End: Task-Completion → beide Ziele erhalten korrekte Formate

Mocks: Telegram-API (httpx), Dateisystem (tmp_path), LLM-Client (fester Response).

---

## Dependencies

- `watchdog` — Filesystem-Monitoring (neuer Eintrag in requirements.txt)
