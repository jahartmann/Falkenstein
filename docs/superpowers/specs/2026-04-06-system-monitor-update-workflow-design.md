# System-Monitor + Update-Workflow — Design Spec
**Datum:** 2026-04-06
**Status:** Approved

---

## Übersicht

Zwei unabhängige, aber zusammengehörige Features:

1. **Ressourcen-Anzeige** — CPU, RAM, GPU, Temperatur, Watt im Dashboard (Health-Sektion erweitert + neue System-Sektion)
2. **Update-Workflow** — Button in Config-Sektion: git pull + pip install mit Live-Output, dann automatischer Neustart

---

## 1. Ressourcen-Monitor

### Ziel

Live-Systemmetriken im Dashboard anzeigen: CPU-Auslastung, RAM-Verbrauch, GPU-Auslastung, CPU-Temperatur, CPU-Leistungsaufnahme (Watt). Basis-Metriken (CPU/RAM) immer verfügbar, erweiterte Metriken (GPU/Temp/Watts) nur auf macOS via `powermetrics`, graceful Fallback auf `null`/`—` wenn nicht verfügbar.

### Backend

**Neue Datei `backend/system_monitor.py`:**

- `SystemMonitor`-Klasse mit zwei Ebenen:
  - **Basis:** `psutil.cpu_percent()`, `psutil.virtual_memory()`, `psutil.disk_usage('/')`
  - **Erweitert:** `powermetrics` als Async-Subprocess (`powermetrics --samplers cpu_power,smc,gpu_power -n 1 --format json`), gecacht alle 3 Sekunden
- `start()` / `stop()` — Hintergrund-Task (asyncio) der `powermetrics` periodisch pollt
- `get_metrics() -> dict` — gibt aktuellen Snapshot zurück:

```python
{
    "cpu_percent": float,       # psutil
    "ram_used_gb": float,       # psutil
    "ram_total_gb": float,      # psutil
    "ram_percent": float,       # psutil
    "disk_percent": float,      # psutil
    "cpu_watts": float | None,  # powermetrics
    "gpu_percent": float | None,# powermetrics
    "cpu_temp_c": float | None, # powermetrics
}
```

- Wenn `powermetrics` nicht verfügbar oder fehlschlägt: erweiterte Felder bleiben `None`, kein Crash
- `psutil` wird als neue Dependency in `requirements.txt` ergänzt (falls noch nicht vorhanden)

**Neuer Endpunkt in `backend/admin_api.py`:**

```
GET /api/admin/system/metrics
```

- Gibt `system_monitor.get_metrics()` zurück
- `system_monitor` wird in `set_dependencies()` übergeben (wie andere globale Services)

**Integration in `backend/main.py`:**

- `SystemMonitor` instanziieren im `lifespan()`-Kontext
- `await system_monitor.start()` beim App-Start
- `await system_monitor.stop()` beim Shutdown
- An `admin_api.set_dependencies()` übergeben

### Frontend

**Health-Sektion — kompakte Metriken-Leiste:**

Unterhalb der bestehenden Health-Karten (Ollama, DB, Budget) eine neue Zeile mit 5 kompakten Metriken-Chips:

```
CPU 42% [████░░]   RAM 11.2/16 GB (70%) [███████░]   Temp 51°C   Watts 8.4W   GPU 12%
```

- Auto-Refresh alle 5 Sekunden via `setInterval` + `GET /api/admin/system/metrics`
- Fehlende Werte (`null`) → `—` anzeigen

**Neue "System"-Sektion in der Navigation:**

Eigene Sektion (zwischen "Health" und "Timeline") mit vier Kacheln:

| Kachel | Inhalt |
|--------|--------|
| CPU | Prozentzahl groß, Fortschrittsbalken, Watt darunter |
| RAM | `used / total GB`, Prozent, Fortschrittsbalken |
| GPU | Prozentzahl, Fortschrittsbalken (oder `—`) |
| Temp | °C groß, Farbkodierung: grün < 70°C, gelb < 85°C, rot ≥ 85°C |

- Refresh-Intervall: 5 Sekunden
- Kacheln zeigen `—` wenn `powermetrics` nicht verfügbar

---

## 2. Update-Workflow

### Ziel

Ein-Klick-Update: `git pull` + `pip install -r requirements.txt` mit sichtbarem Live-Output, danach automatischer Server-Neustart.

### Backend

**Neuer Endpunkt in `backend/admin_api.py`:**

```
POST /api/admin/update
```

- Führt sequenziell aus:
  1. `git pull` (im Projekt-Root)
  2. `pip install -r requirements.txt` (nur wenn git pull erfolgreich)
- Streamt Output live via SSE (`text/event-stream`)
- SSE-Event-Format: `data: {"line": "Already up to date."}\n\n`
- Abschluss-Event: `data: {"status": "done"}\n\n`
- Fehler-Event: `data: {"status": "error", "line": "<stderr>"}\n\n` → kein Neustart
- Nutzt `asyncio.create_subprocess_exec` für non-blocking subprocess
- Projekt-Root via `Path(__file__).parent.parent` (wie `OpsExecutor`)

### Frontend

**Config-Sektion — neuer Button:**

- "⬆ Update & Neustart" neben dem bestehenden "Neustart"-Button
- Klick → Bestätigungsdialog: *"Server wird gestoppt, Code aktualisiert und neu gestartet. Fortfahren?"*

**Update-Modal (öffnet nach Bestätigung):**

- Schwarzes Terminal-Fenster mit weißem Text
- Live-Output via `fetch` + `ReadableStream` (SSE-Konsumierung wie beim Ollama-Pull)
- Zeilenweise Ausgabe wird angehängt (max. 200 Zeilen, danach scrollt)
- Bei `{"status": "done"}`: Zeile `✅ Update erfolgreich — Neustart in 3s...` + Countdown
- Nach Countdown: ruft `/api/admin/restart` auf → Reconnect-Overlay (bereits vorhanden)
- Bei `{"status": "error"}`: Zeile `❌ Fehler — kein Neustart` + Schließen-Button

---

## Nicht-Ziele

- Kein historisches Graphing (nur aktueller Snapshot)
- Keine Windows/Linux-spezifischen GPU-APIs (nur macOS `powermetrics`)
- Kein separater Monitoring-Daemon (alles im FastAPI-Prozess)
- Kein automatisches Update ohne Benutzeraktion

---

## Implementierungsreihenfolge

1. `backend/system_monitor.py` + Tests
2. `/api/admin/system/metrics` Endpunkt + `main.py` Integration
3. Frontend: Health-Sektion erweitern
4. Frontend: neue System-Sektion
5. `/api/admin/update` Endpunkt + SSE-Stream
6. Frontend: Update-Button + Modal in Config-Sektion
