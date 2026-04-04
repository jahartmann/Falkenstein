# Obsidian-Integration Redesign

## Problem

- Zu viele verschachtelte Ordner, unklar wo was hingehort
- Ergebnisse nach Typ verstreut statt beim Projekt
- Tasks in Inbox unstrukturiert (kein Typ, kein Projekt)
- Schedule-Frontmatter manuell tippen ist umstandlich
- Keine Kopiervorlage fur Schedules

## Neue Vault-Struktur

```
KI-Buro/
  Inbox.md
  Kanban.md
  Schedules/
    _vorlage.md              <- Kopiervorlage mit Kurzreferenz
    heartbeat.md
  Projekte/
    <name>/
      README.md
      Tasks.md               <- Watcher beobachtet
      Ergebnisse/            <- alle Ergebnisse dieses Projekts
  Ergebnisse/                <- projektlose Ergebnisse
```

Alte Typ-Ordner (`Recherchen/`, `Guides/`, etc.) werden nicht mehr beschrieben. Bestehende Dateien bleiben.

## Inbox-Format

```
- [ ] Beschreibung #agent-typ @projekt
```

- `#typ` optional: `#coder`, `#researcher`, `#writer`, `#ops`. Ohne = MainAgent wahlt.
- `@projekt` optional: Ordnername unter `Projekte/`. Ohne = Ergebnis in `Ergebnisse/`.
- Beides wird vom Watcher geparst und als strukturiertes Dict weitergegeben.

Regex: `^- \[ \] (.+?)(?:\s+#(\w+))?(?:\s+@([\w-]+))?\s*$`

## Ergebnis-Routing

`ObsidianWriter.write_result(title, typ, content, project=None)`:
- Mit Projekt: `Projekte/{projekt}/Ergebnisse/YYYY-MM-DD-{slug}.md`
- Ohne Projekt: `Ergebnisse/YYYY-MM-DD-{slug}.md`

Frontmatter enthalt Typ:
```yaml
---
typ: recherche
erstellt: 2026-04-04
agent: researcher
---
```

## Schedule-Vorlage

`Schedules/_vorlage.md`:
```markdown
---
name: Name des Jobs
schedule: taglich 09:00
agent: researcher
active: true
active_hours: 08:00-22:00
light_context: false
---

<!-- Schedule-Formate:
  taglich HH:MM | stundlich | alle N Minuten | alle N Stunden
  Mo-Fr HH:MM | montags HH:MM ... sonntags HH:MM
  wochentlich TAG HH:MM | cron: EXPR
-->

Dein Prompt hier. Was soll der Agent tun?
```

## Code-Anderungen

### 1. obsidian_watcher.py

- Regex erweitern: `#typ` und `@projekt` parsen
- `detect_changes()` gibt `list[dict]` zuruck mit keys: `text`, `agent_type`, `project`, `source_file`
- Callback-Signatur: `on_new_todo(todo: dict)` statt `on_new_todo(content: str, source_file: str)`

### 2. obsidian_writer.py

- `RESULT_TYPE_MAP` entfernen (keine Typ-Ordner mehr)
- `write_result()` bekommt `project: str | None = None` Parameter
- Pfad-Logik: mit Projekt -> `Projekte/{project}/Ergebnisse/`, ohne -> `Ergebnisse/`
- Frontmatter bekommt `typ`-Feld
- `Ergebnisse/`-Unterordner anlegen wenn noetig

### 3. obsidian_manager.py

- Ordner-Konstanten aktualisieren (keine Typ-Unterordner)
- `write_task_result()` Projekt-Ergebnis-Pfad anpassen

### 4. main.py

- `handle_obsidian_todo()` nimmt `dict` statt `str` + `str`
- Gibt `agent_type` und `project` an MainAgent weiter

### 5. main_agent.py

- `handle_message()` oder neuer Entry akzeptiert optionalen `agent_type` und `project`
- Nutzt `agent_type` wenn gesetzt statt selbst zu klassifizieren
- Reicht `project` an `write_result()` durch

### 6. scheduler.py

- `VAULT_PREFIX` Pfad anpassen: `Schedules/` direkt unter `KI-Buro/` (nicht mehr unter `Management/`)
- `_create_default_heartbeat()` aktualisieren

### 7. Vorlagen erstellen

- `Schedules/_vorlage.md` im Vault anlegen
- `Inbox.md` Header/Kommentar mit Format-Referenz

## Nicht geandert

- Kanban-Logik bleibt gleich
- Watcher beobachtet weiterhin `Inbox.md` und `Tasks.md`
- Scheduler-Logik (Tick, Frontmatter-Parsing) bleibt gleich
- Alte Ergebnis-Ordner bleiben bestehen, werden nicht migriert
