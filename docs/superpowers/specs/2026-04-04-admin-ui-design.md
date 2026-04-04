# Admin UI — Design Spec

**Datum:** 2026-04-04

## Zusammenfassung

Separate Admin-Seite unter `/admin` mit clean/modern Dashboard. Zeigt System-Status und ermöglicht Konfiguration aller Einstellungen. Hot-Reload für unkritische Werte, Neustart-Hinweis für Server-kritische.

## Bereiche

### 1. System Status (oberer Bereich)

Dashboard-Cards mit Live-Daten:
- Aktive Agents (Typ + Task)
- Offene Tasks (Anzahl)
- CLI-Budget (Balken: verbraucht/übrig)
- Server-Uptime
- Ollama-Verbindung (Online/Offline)
- Letzte 5 Tasks (Titel + Status + Agent)

### 2. Settings (Hauptbereich)

Gruppiert in Cards mit je einem "Speichern"-Button:

| Gruppe | Felder | Hot-Reload? |
|--------|--------|-------------|
| LLM | `ollama_model`, `ollama_model_light`, `ollama_model_heavy`, `ollama_host`, `ollama_num_ctx`, `ollama_num_ctx_extended` | Ja |
| Telegram | `telegram_bot_token`, `telegram_chat_id` | Ja |
| CLI | `cli_provider`, `cli_daily_token_budget` | Ja |
| Obsidian | `obsidian_vault_path`, `obsidian_watch_enabled`, `obsidian_auto_submit_tasks` | Ja |
| Server | `frontend_port`, `db_path`, `workspace_path` | Nein — Badge "Neustart nötig" |

Sensitive Felder (Token) als Password-Input mit Sichtbarkeits-Toggle.

## API-Routen

### GET /api/admin/dashboard

Liefert System-Status:
```json
{
  "active_agents": [{"agent_id": "...", "type": "coder", "task": "..."}],
  "open_tasks_count": 3,
  "recent_tasks": [{"id": 1, "title": "...", "status": "done", "agent": "researcher"}],
  "budget": {"used": 1200, "budget": 50000, "remaining": 48800},
  "uptime_seconds": 3600,
  "ollama_status": "online"
}
```

### GET /api/admin/settings

Liefert alle aktuellen Settings:
```json
{
  "groups": {
    "llm": {
      "ollama_model": {"value": "gemma4:26b", "hot_reload": true, "type": "text"},
      "ollama_host": {"value": "http://localhost:11434", "hot_reload": true, "type": "text"},
      ...
    },
    "telegram": {
      "telegram_bot_token": {"value": "***", "hot_reload": true, "type": "password"},
      ...
    },
    ...
  }
}
```

### PUT /api/admin/settings

Body: `{"group": "llm", "values": {"ollama_model": "gemma3:27b"}}`

Response:
```json
{
  "saved": true,
  "hot_reloaded": true,
  "restart_required": false
}
```

Schreibt Werte in `.env`. Bei hot-reload-fähigen Werten wird zusätzlich das `settings`-Objekt im laufenden Server aktualisiert.

## Frontend

- `frontend/admin.html` — Standalone HTML-Seite
- Vanilla JS + CSS (kein Framework)
- CSS: Clean/modern mit Cards, Sidebar optional, dunkler Header
- Responsive (funktioniert auf Tablet/Desktop)
- Fetch API für Backend-Kommunikation
- Auto-Refresh der Dashboard-Daten alle 10 Sekunden

## Technische Details

### Hot-Reload Mechanismus

Hot-Reload-fähige Felder:
- `ollama_model`, `ollama_model_light`, `ollama_model_heavy`, `ollama_host`
- `ollama_num_ctx`, `ollama_num_ctx_extended`
- `telegram_bot_token`, `telegram_chat_id`
- `cli_provider`, `cli_daily_token_budget`
- `obsidian_vault_path`, `obsidian_watch_enabled`, `obsidian_auto_submit_tasks`

Diese werden sowohl in `.env` geschrieben als auch im laufenden `settings`-Objekt und abhängigen Komponenten (LLMClient, CLIBudgetTracker) aktualisiert.

Nicht hot-reload-fähig (Neustart nötig):
- `frontend_port`, `db_path`, `workspace_path`

### .env Schreiben

Bestehende `.env` wird gelesen, geänderte Keys werden aktualisiert, fehlende Keys werden angehängt. Kommentare und Formatierung bleiben erhalten.

### Sicherheit

- Kein Auth (lokaler Server)
- Token-Werte werden bei GET maskiert (`***`), bei PUT im Klartext empfangen
- Keine Cookies → kein CSRF-Risiko

## File Structure

- Create: `frontend/admin.html` — Admin-Dashboard Seite
- Create: `backend/admin_api.py` — API-Routen für Admin
- Modify: `backend/main.py` — Admin-Routen registrieren, `/admin` Route
- Modify: `backend/config.py` — Hot-Reload Methode auf Settings
