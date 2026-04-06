# System-Monitor + Update-Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live-Systemmetriken (CPU, RAM, GPU, Temp, Watts) im Dashboard anzeigen und einen Update-Workflow (git pull + pip install + Neustart) in der Config-Sektion bereitstellen.

**Architecture:** `SystemMonitor` kapselt psutil-Basis-Metriken + optionale powermetrics-Erweiterung als Async-Hintergrund-Task. Ein neuer `/api/admin/system/metrics` Endpunkt gibt den letzten Snapshot zurück. Das Frontend ergänzt die Health-Sektion um eine Metriken-Leiste und fügt eine neue "System"-Sektion hinzu. Der Update-Workflow ist ein SSE-Endpunkt (`/api/admin/update`) mit Terminal-Modal im Dashboard.

**Tech Stack:** Python 3.11+, FastAPI, psutil, asyncio.create_subprocess_exec, SSE (text/event-stream), Vanilla JS

---

## Datei-Map

| Aktion | Datei | Verantwortung |
|--------|-------|---------------|
| Erstellen | `backend/system_monitor.py` | psutil + powermetrics Polling, gecacht |
| Erstellen | `tests/test_system_monitor.py` | Tests für SystemMonitor |
| Erstellen | `tests/test_update_endpoint.py` | Tests für /api/admin/update |
| Modifizieren | `requirements.txt` | psutil ergänzen |
| Modifizieren | `backend/admin_api.py` | /system/metrics + /update Endpunkte |
| Modifizieren | `backend/main.py` | SystemMonitor starten/stoppen, in set_dependencies |
| Modifizieren | `frontend/dashboard.html` | System-Sidebar-Button, System-Sektion, Metriken-div in Health, Update-Button |
| Modifizieren | `frontend/dashboard.js` | loadHealth() erweitern, loadSystem(), runUpdate() |

---

## Task 1: `backend/system_monitor.py` + psutil

**Files:**
- Create: `backend/system_monitor.py`
- Create: `tests/test_system_monitor.py`
- Modify: `requirements.txt`

- [ ] **Schritt 1.1: Failing Test schreiben**

```python
# tests/test_system_monitor.py
import pytest
from unittest.mock import patch, MagicMock
from backend.system_monitor import SystemMonitor


def test_get_metrics_returns_required_keys():
    monitor = SystemMonitor()
    metrics = monitor.get_metrics()
    assert "cpu_percent" in metrics
    assert "ram_used_gb" in metrics
    assert "ram_total_gb" in metrics
    assert "ram_percent" in metrics
    assert "disk_percent" in metrics
    assert "cpu_watts" in metrics       # None wenn powermetrics nicht verfügbar
    assert "gpu_percent" in metrics     # None wenn powermetrics nicht verfügbar
    assert "cpu_temp_c" in metrics      # None wenn powermetrics nicht verfügbar


def test_get_metrics_base_values_are_floats():
    monitor = SystemMonitor()
    metrics = monitor.get_metrics()
    assert isinstance(metrics["cpu_percent"], float)
    assert isinstance(metrics["ram_used_gb"], float)
    assert isinstance(metrics["ram_total_gb"], float)
    assert isinstance(metrics["ram_percent"], float)
    assert isinstance(metrics["disk_percent"], float)


def test_get_metrics_extended_values_none_without_powermetrics():
    """Without a cached powermetrics result, extended fields must be None."""
    monitor = SystemMonitor()
    monitor._pm_cache = None  # explicitly clear cache
    metrics = monitor.get_metrics()
    assert metrics["cpu_watts"] is None
    assert metrics["gpu_percent"] is None
    assert metrics["cpu_temp_c"] is None


def test_parse_powermetrics_extracts_watts():
    monitor = SystemMonitor()
    sample_json = {
        "processor": {
            "packages": [{"package_mW": 8400.0}]
        },
        "gpu": {},
        "smc": {"temperatures": []}
    }
    result = monitor._parse_powermetrics(sample_json)
    assert result["cpu_watts"] == pytest.approx(8.4, rel=0.01)


def test_parse_powermetrics_extracts_temp():
    monitor = SystemMonitor()
    sample_json = {
        "processor": {"packages": [{"package_mW": 5000.0}]},
        "gpu": {},
        "smc": {
            "temperatures": [
                {"key": "Tp01", "value": 52.3},
                {"key": "Tb0T", "value": 38.0},
            ]
        }
    }
    result = monitor._parse_powermetrics(sample_json)
    assert result["cpu_temp_c"] == pytest.approx(52.3, rel=0.01)


def test_parse_powermetrics_missing_fields_returns_none():
    monitor = SystemMonitor()
    result = monitor._parse_powermetrics({})
    assert result["cpu_watts"] is None
    assert result["cpu_temp_c"] is None
    assert result["gpu_percent"] is None
```

- [ ] **Schritt 1.2: Test ausführen und Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_system_monitor.py -v 2>&1 | head -15
```

Erwartet: `ModuleNotFoundError: No module named 'backend.system_monitor'`

- [ ] **Schritt 1.3: psutil zu `requirements.txt` ergänzen**

Am Ende von `/Users/janikhartmann/Falkenstein/requirements.txt` ergänzen:
```
psutil>=5.9.0
```

Installieren:
```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && pip install psutil>=5.9.0
```

- [ ] **Schritt 1.4: `backend/system_monitor.py` erstellen**

```python
# backend/system_monitor.py
"""System resource monitor — psutil (base) + powermetrics (extended, macOS only).

Base metrics (always available): CPU %, RAM, Disk
Extended metrics (macOS Apple Silicon): CPU watts, GPU %, CPU temp °C
Extended metrics are polled every 3 seconds in a background task and cached.
Falls back gracefully to None if powermetrics is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import psutil


# Temperature keys to try in order (Apple Silicon SMC keys for CPU die temp)
_TEMP_KEYS = ("Tp01", "Tp09", "Tp0P", "TC0P", "TC0D", "CPU die temperature")

_PM_COMMAND = [
    "/usr/bin/powermetrics",
    "--samplers", "cpu_power,smc,gpu_power",
    "-n", "1",
    "--format", "json",
]


class SystemMonitor:
    """Polls system metrics and caches the latest values."""

    def __init__(self) -> None:
        self._pm_cache: dict[str, float | None] | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    # ── Public API ────────────────────────────────────────────────────

    def get_metrics(self) -> dict[str, Any]:
        """Return a snapshot of current system metrics."""
        vm = psutil.virtual_memory()
        extended = self._pm_cache or {}
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_used_gb": round(vm.used / 1e9, 1),
            "ram_total_gb": round(vm.total / 1e9, 1),
            "ram_percent": round(vm.percent, 1),
            "disk_percent": round(psutil.disk_usage("/").percent, 1),
            "cpu_watts": extended.get("cpu_watts"),
            "gpu_percent": extended.get("gpu_percent"),
            "cpu_temp_c": extended.get("cpu_temp_c"),
        }

    async def start(self) -> None:
        """Start background powermetrics polling (macOS only, no-op elsewhere)."""
        if sys.platform != "darwin":
            return
        self._running = True
        # Warm up psutil cpu_percent (first call always returns 0.0)
        psutil.cpu_percent(interval=None)
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop background polling."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Internal ──────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                self._pm_cache = await self._run_powermetrics()
            except Exception:
                pass  # Keep last cached value on failure
            await asyncio.sleep(3)

    async def _run_powermetrics(self) -> dict[str, float | None]:
        """Run powermetrics once and return parsed extended metrics."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *_PM_COMMAND,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode != 0 or not stdout:
                return {}
            # powermetrics may emit multiple JSON objects; take the last complete one
            raw = stdout.decode("utf-8", errors="replace").strip()
            # Find the last '{' to locate the final JSON object
            last_brace = raw.rfind("\n{")
            if last_brace != -1:
                raw = raw[last_brace:].strip()
            data = json.loads(raw)
            return self._parse_powermetrics(data)
        except Exception:
            return {}

    def _parse_powermetrics(self, data: dict) -> dict[str, float | None]:
        """Parse powermetrics JSON into our metric dict."""
        result: dict[str, float | None] = {
            "cpu_watts": None,
            "gpu_percent": None,
            "cpu_temp_c": None,
        }

        # CPU watts from processor package power
        try:
            pkg_mw = data["processor"]["packages"][0]["package_mW"]
            result["cpu_watts"] = round(pkg_mw / 1000.0, 1)
        except (KeyError, IndexError, TypeError):
            pass

        # CPU temperature from SMC
        try:
            temps = data["smc"]["temperatures"]
            for entry in temps:
                if entry.get("key") in _TEMP_KEYS:
                    result["cpu_temp_c"] = round(float(entry["value"]), 1)
                    break
        except (KeyError, TypeError):
            pass

        # GPU % from gpu_energy_mj ratio (approximation when available)
        try:
            gpu_active = data["gpu"].get("gpu_active_pct")
            if gpu_active is not None:
                result["gpu_percent"] = round(float(gpu_active), 1)
        except (KeyError, TypeError, AttributeError):
            pass

        return result
```

- [ ] **Schritt 1.5: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_system_monitor.py -v
```

Erwartet: alle 6 Tests grün.

- [ ] **Schritt 1.6: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/system_monitor.py tests/test_system_monitor.py requirements.txt && git commit -m "feat: SystemMonitor — psutil + powermetrics Polling mit Fallback"
```

---

## Task 2: `/api/admin/system/metrics` Endpunkt + `main.py` Integration

**Files:**
- Modify: `backend/admin_api.py`
- Modify: `backend/main.py`
- Test: `tests/test_system_monitor.py` (ergänzen)

- [ ] **Schritt 2.1: Failing Test ergänzen**

An `tests/test_system_monitor.py` anhängen:

```python
@pytest.mark.asyncio
async def test_system_metrics_endpoint():
    """Test /api/admin/system/metrics returns all required keys."""
    from httpx import AsyncClient
    from fastapi import FastAPI
    from backend.admin_api import router
    import backend.admin_api as admin_module

    # Wire a real SystemMonitor
    monitor = SystemMonitor()
    admin_module._system_monitor = monitor

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/api/admin/system/metrics")

    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_percent" in data
    assert "ram_used_gb" in data
    assert "disk_percent" in data
```

- [ ] **Schritt 2.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_system_monitor.py::test_system_metrics_endpoint -v 2>&1 | head -15
```

Erwartet: `AttributeError` (Endpunkt noch nicht vorhanden)

- [ ] **Schritt 2.3: `admin_api.py` — globale Variable + Endpunkt ergänzen**

In `backend/admin_api.py`:

**Nach den bestehenden globalen Variablen** (ca. Zeile 25, nach `_soul_memory = None`) einfügen:
```python
_system_monitor = None
```

**`set_dependencies()`** erweitern — Signatur und Body:
```python
def set_dependencies(db=None, scheduler=None, config_service=None,
                     main_agent=None, budget_tracker=None, llm_router=None,
                     fact_memory=None, soul_memory=None, system_monitor=None):
    global _db, _scheduler, _config_service, _main_agent, _budget_tracker, _llm_router, _fact_memory, _soul_memory, _system_monitor
    _db = db; _scheduler = scheduler; _config_service = config_service
    _main_agent = main_agent; _budget_tracker = budget_tracker; _llm_router = llm_router
    _fact_memory = fact_memory; _soul_memory = soul_memory; _system_monitor = system_monitor
```

**Am Ende der Datei** (nach den Ollama-Endpunkten) einfügen:

```python
# ── System Monitor ────────────────────────────────────────────────────

@router.get("/system/metrics")
async def get_system_metrics():
    """Return current system resource metrics (CPU, RAM, GPU, Temp, Watts)."""
    if _system_monitor is None:
        return {"error": "SystemMonitor not initialized"}
    return _system_monitor.get_metrics()
```

- [ ] **Schritt 2.4: `main.py` — SystemMonitor starten**

In `backend/main.py`:

**Import ergänzen** (nach den bestehenden Imports):
```python
from backend.system_monitor import SystemMonitor
```

**In `lifespan()` — nach `llm_router = LLMRouter(...)` (ca. Zeile 126)**:
```python
# System Monitor
system_monitor = SystemMonitor()
await system_monitor.start()
```

**In `admin_api.set_dependencies(...)` — `system_monitor=system_monitor` ergänzen**:
```python
admin_api.set_dependencies(
    db=db, scheduler=scheduler, config_service=config_service,
    main_agent=main_agent, budget_tracker=budget_tracker,
    llm_router=llm_router, fact_memory=fact_memory,
    soul_memory=soul_memory, system_monitor=system_monitor,
)
```

**Im Shutdown-Block** (nach `await scheduler.stop()`):
```python
await system_monitor.stop()
```

- [ ] **Schritt 2.5: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_system_monitor.py -v 2>&1 | tail -15
```

Erwartet: alle 7 Tests grün.

- [ ] **Schritt 2.6: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/admin_api.py backend/main.py tests/test_system_monitor.py && git commit -m "feat: /api/admin/system/metrics Endpunkt + main.py Integration"
```

---

## Task 3: `/api/admin/update` SSE-Endpunkt

**Files:**
- Modify: `backend/admin_api.py`
- Create: `tests/test_update_endpoint.py`

- [ ] **Schritt 3.1: Failing Test schreiben**

```python
# tests/test_update_endpoint.py
import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from backend.admin_api import router

app = FastAPI()
app.include_router(router)


@pytest.mark.asyncio
async def test_update_endpoint_exists():
    """POST /api/admin/update should return 200 with SSE content-type."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Use stream to avoid waiting for full SSE response
        async with ac.stream("POST", "/api/admin/update") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_update_endpoint_streams_lines():
    """Update endpoint should stream at least one data: line."""
    lines = []
    async with AsyncClient(app=app, base_url="http://test") as ac:
        async with ac.stream("POST", "/api/admin/update") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    lines.append(line)
                if len(lines) >= 1:
                    break
    assert len(lines) >= 1
```

- [ ] **Schritt 3.2: Test ausführen — Fehler bestätigen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_update_endpoint.py -v 2>&1 | head -15
```

Erwartet: 404 (Endpunkt noch nicht vorhanden)

- [ ] **Schritt 3.3: `/api/admin/update` in `admin_api.py` ergänzen**

Nach dem `/system/metrics` Endpunkt einfügen:

```python
@router.post("/update")
async def update_server():
    """Run git pull + pip install and stream output via SSE. No restart is triggered."""
    import json as _json
    from pathlib import Path as _Path
    from fastapi.responses import StreamingResponse

    project_root = _Path(__file__).parent.parent

    async def stream_update():
        # Step 1: git pull
        yield f"data: {_json.dumps({'line': '$ git pull'})}\n\n"
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "pull",
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                yield f"data: {_json.dumps({'line': line})}\n\n"
            await proc.wait()
            if proc.returncode != 0:
                yield f"data: {_json.dumps({'status': 'error', 'line': f'git pull fehlgeschlagen (exit {proc.returncode})'})}\n\n"
                return
        except Exception as e:
            yield f"data: {_json.dumps({'status': 'error', 'line': str(e)})}\n\n"
            return

        # Step 2: pip install
        yield f"data: {_json.dumps({'line': '$ pip install -r requirements.txt'})}\n\n"
        try:
            import sys as _sys
            proc = await asyncio.create_subprocess_exec(
                _sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                yield f"data: {_json.dumps({'line': line})}\n\n"
            await proc.wait()
            if proc.returncode != 0:
                yield f"data: {_json.dumps({'status': 'error', 'line': f'pip install fehlgeschlagen (exit {proc.returncode})'})}\n\n"
                return
        except Exception as e:
            yield f"data: {_json.dumps({'status': 'error', 'line': str(e)})}\n\n"
            return

        yield f"data: {_json.dumps({'status': 'done'})}\n\n"

    return StreamingResponse(stream_update(), media_type="text/event-stream")
```

**Wichtig:** `asyncio` muss bereits importiert sein in `admin_api.py`. Prüfe ob `import asyncio` vorhanden ist — falls nicht, am Anfang der Datei ergänzen.

- [ ] **Schritt 3.4: Tests ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/test_update_endpoint.py -v 2>&1 | tail -15
```

Erwartet: beide Tests grün.

- [ ] **Schritt 3.5: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add backend/admin_api.py tests/test_update_endpoint.py && git commit -m "feat: /api/admin/update SSE-Endpunkt — git pull + pip install Stream"
```

---

## Task 4: Frontend — Health-Sektion Metriken-Leiste

**Files:**
- Modify: `frontend/dashboard.html` (Metriken-div in `#section-health`)
- Modify: `frontend/dashboard.js` (`loadHealth()` erweitern)

- [ ] **Schritt 4.1: `dashboard.html` — Metriken-div ergänzen**

In `frontend/dashboard.html` die `#section-health` Sektion (aktuell Zeile 312–333) so erweitern:

```html
<!-- Health Section -->
<section class="section" id="section-health">
  <div class="section-header"><h1>System Health</h1><button class="btn" onclick="loadHealth()">Aktualisieren</button></div>
  <div class="stats-row" id="health-stats"></div>

  <!-- NEU: Kompakte Systemmetriken-Leiste -->
  <div id="health-system-metrics" style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius)">
    <span class="text-muted" style="font-size:12px">Lade Systemmetriken...</span>
  </div>

  <div class="panels">
    <div class="panel">
      <h2>Ollama</h2>
      <div id="health-ollama"></div>
    </div>
    <div class="panel">
      <h2>Datenbank</h2>
      <div id="health-db"></div>
    </div>
  </div>
  <div class="panel" style="margin-top:16px">
    <h2>LLM Routing</h2>
    <div id="health-routing"></div>
  </div>
  <div class="panel" style="margin-top:16px">
    <h2>Token Budget</h2>
    <div id="health-budget"></div>
  </div>
</section>
```

Ersetze die bestehende `#section-health` vollständig mit dem obigen HTML.

- [ ] **Schritt 4.2: `dashboard.js` — `loadHealth()` um Metriken-Leiste erweitern**

In `frontend/dashboard.js` die Funktion `loadHealth()` (ca. Zeile 921). Nach der schließenden `} catch (e) { ... }` der bestehenden Funktion (Zeile 971) — also nach `loadHealth()` — eine neue Hilfsfunktion einfügen:

```javascript
function renderMetricBar(pct, color) {
  const c = color || (pct > 80 ? 'var(--red)' : pct > 60 ? '#f0a500' : 'var(--green)');
  return `<div style="width:80px;height:6px;background:var(--border);border-radius:3px;display:inline-block;vertical-align:middle;margin-left:4px">
    <div style="width:${Math.min(pct,100)}%;height:100%;background:${c};border-radius:3px"></div>
  </div>`;
}

async function loadHealthMetrics() {
  const el = document.getElementById('health-system-metrics');
  if (!el) return;
  try {
    const m = await api('/system/metrics');
    const fmt = (v, unit) => v != null ? `${v}${unit}` : '—';
    const tempColor = m.cpu_temp_c == null ? 'var(--text-muted)'
      : m.cpu_temp_c >= 85 ? 'var(--red)'
      : m.cpu_temp_c >= 70 ? '#f0a500'
      : 'var(--green)';
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">CPU</span>
        <strong>${fmt(m.cpu_percent, '%')}</strong>
        ${m.cpu_percent != null ? renderMetricBar(m.cpu_percent) : ''}
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">RAM</span>
        <strong>${m.ram_used_gb != null ? `${m.ram_used_gb}/${m.ram_total_gb} GB (${m.ram_percent}%)` : '—'}</strong>
        ${m.ram_percent != null ? renderMetricBar(m.ram_percent) : ''}
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">Temp</span>
        <strong style="color:${tempColor}">${fmt(m.cpu_temp_c, '°C')}</strong>
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">Watts</span>
        <strong>${fmt(m.cpu_watts, ' W')}</strong>
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:13px">
        <span class="text-muted">GPU</span>
        <strong>${fmt(m.gpu_percent, '%')}</strong>
        ${m.gpu_percent != null ? renderMetricBar(m.gpu_percent) : ''}
      </div>
    `;
  } catch {
    el.innerHTML = '<span class="text-muted" style="font-size:12px">Metriken nicht verfügbar</span>';
  }
}
```

Dann in `loadHealth()` am Ende (vor der schließenden `}`), vor dem `} catch (e)` Block, folgende Zeile ergänzen:

```javascript
    loadHealthMetrics();
```

Und nach `loadHealth()` Definition einen Auto-Refresh ergänzen — suche den Abschnitt in `dashboard.js` wo Sektionen per `switch` geladen werden (ca. Zeile 88–95 mit `else if (s === 'health') loadHealth()`). Dort prüfen ob ein `setInterval` bereits existiert oder nicht — wenn nicht, in `loadHealth()` ganz am Anfang einfügen:

```javascript
async function loadHealth() {
  // Auto-refresh Systemmetriken alle 5 Sekunden wenn Sektion aktiv
  if (!window._healthMetricsInterval) {
    window._healthMetricsInterval = setInterval(() => {
      if (document.getElementById('section-health')?.classList.contains('active')) {
        loadHealthMetrics();
      }
    }, 5000);
  }
  // ... rest of existing code
```

- [ ] **Schritt 4.3: Visuell prüfen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m backend.main &
sleep 2 && curl -s http://localhost:8800/api/admin/system/metrics | python3 -m json.tool
```

Erwartet: JSON mit `cpu_percent`, `ram_used_gb`, etc. Dann Server stoppen: `kill %1`

- [ ] **Schritt 4.4: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add frontend/dashboard.html frontend/dashboard.js && git commit -m "feat: Health-Sektion Systemmetriken-Leiste mit Auto-Refresh"
```

---

## Task 5: Frontend — neue "System"-Sektion

**Files:**
- Modify: `frontend/dashboard.html` (Sidebar-Button + System-Sektion)
- Modify: `frontend/dashboard.js` (`loadSystem()` + Auto-Refresh)

- [ ] **Schritt 5.1: `dashboard.html` — Sidebar-Button + System-Sektion**

**Sidebar-Button** (in `frontend/dashboard.html`, nach dem Health-Button bei Zeile 61–65):

```html
<button class="sidebar-btn" data-section="system" title="System">
  <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
    <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
  </svg>
</button>
```

Einfügen zwischen dem Health-Button und dem Files-Button.

**System-Sektion** (in `frontend/dashboard.html`, nach `#section-health` und vor `#section-files`):

```html
<!-- System Section -->
<section class="section" id="section-system">
  <div class="section-header">
    <h1>System</h1>
    <button class="btn" onclick="loadSystem()">Aktualisieren</button>
  </div>
  <div id="system-metrics-grid" style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:8px">
    <div class="panel" id="system-card-cpu"></div>
    <div class="panel" id="system-card-ram"></div>
    <div class="panel" id="system-card-gpu"></div>
    <div class="panel" id="system-card-temp"></div>
  </div>
</section>
```

- [ ] **Schritt 5.2: `dashboard.js` — `loadSystem()` ergänzen**

Am Ende von `dashboard.js` (vor dem Init-Block mit `loadDashboard()`) einfügen:

```javascript
// ── System Section ────────────────────────────────────────────────────

function renderSystemCard(id, title, mainValue, subValue, pct, color) {
  const el = document.getElementById(id);
  if (!el) return;
  const barColor = color || (pct > 80 ? 'var(--red)' : pct > 60 ? '#f0a500' : 'var(--green)');
  el.innerHTML = `
    <h2 style="margin:0 0 12px">${title}</h2>
    <div style="font-size:2em;font-weight:700;line-height:1">${mainValue}</div>
    ${subValue ? `<div style="font-size:0.85em;color:var(--text-muted);margin-top:4px">${subValue}</div>` : ''}
    ${pct != null ? `
      <div style="margin-top:12px;height:8px;background:var(--border);border-radius:4px">
        <div style="width:${Math.min(pct,100)}%;height:100%;background:${barColor};border-radius:4px;transition:width 0.5s"></div>
      </div>
    ` : ''}
  `;
}

async function loadSystem() {
  try {
    const m = await api('/system/metrics');
    const na = '—';

    // CPU
    renderSystemCard(
      'system-card-cpu', 'CPU',
      m.cpu_percent != null ? `${m.cpu_percent}%` : na,
      m.cpu_watts != null ? `${m.cpu_watts} W` : null,
      m.cpu_percent,
    );

    // RAM
    renderSystemCard(
      'system-card-ram', 'RAM',
      m.ram_percent != null ? `${m.ram_percent}%` : na,
      m.ram_used_gb != null ? `${m.ram_used_gb} / ${m.ram_total_gb} GB` : null,
      m.ram_percent,
    );

    // GPU
    renderSystemCard(
      'system-card-gpu', 'GPU',
      m.gpu_percent != null ? `${m.gpu_percent}%` : na,
      m.gpu_percent == null ? 'powermetrics nicht verfügbar' : null,
      m.gpu_percent,
    );

    // Temp
    const tempColor = m.cpu_temp_c == null ? null
      : m.cpu_temp_c >= 85 ? 'var(--red)'
      : m.cpu_temp_c >= 70 ? '#f0a500'
      : 'var(--green)';
    renderSystemCard(
      'system-card-temp', 'Temperatur',
      m.cpu_temp_c != null ? `${m.cpu_temp_c}°C` : na,
      m.disk_percent != null ? `Disk: ${m.disk_percent}%` : null,
      null,
      tempColor,
    );
    // Color the temp value
    const tempEl = document.querySelector('#system-card-temp div[style*="font-size:2em"]');
    if (tempEl && tempColor) tempEl.style.color = tempColor;

  } catch (e) {
    console.error('System metrics error:', e);
  }
}
```

**Sektion in `navTo`-Switch einbinden** — in der `switch` oder `if-else`-Kette wo Sektionen geladen werden (Zeile ~88–95), nach `else if (s === 'health') loadHealth();` ergänzen:

```javascript
else if (s === 'system') {
  loadSystem();
  if (!window._systemInterval) {
    window._systemInterval = setInterval(() => {
      if (document.getElementById('section-system')?.classList.contains('active')) {
        loadSystem();
      }
    }, 5000);
  }
}
```

**Command-Palette** — in der `COMMANDS`-Liste (ca. Zeile 1106) nach dem Health-Eintrag ergänzen:

```javascript
{ name: 'System Monitor', action: () => navTo('system'), section: 'system' },
```

- [ ] **Schritt 5.3: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add frontend/dashboard.html frontend/dashboard.js && git commit -m "feat: neue System-Sektion mit CPU/RAM/GPU/Temp Kacheln"
```

---

## Task 6: Frontend — Update-Button + Modal in Config

**Files:**
- Modify: `frontend/dashboard.html` (Update-Button in Config-Header)
- Modify: `frontend/dashboard.js` (`runUpdate()` + Modal)

- [ ] **Schritt 6.1: `dashboard.html` — Update-Button in Config-Header**

In `frontend/dashboard.html` die Config-Sektion (Zeile 191–200) — den Header anpassen:

```html
<section class="section" id="section-config">
  <div class="section-header">
    <h1>Konfiguration</h1>
    <div style="display:flex;gap:8px">
      <button class="btn" onclick="runUpdate()">⬆ Update & Neustart</button>
      <button class="btn" style="background:var(--red);color:#fff" onclick="restartServer()">Server neustarten</button>
    </div>
  </div>
  <div style="background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;margin-bottom:16px;font-size:12px;color:var(--text-muted)">
    Änderungen an Server-Einstellungen (Token, Port) werden in die <strong>.env</strong> geschrieben und erfordern einen <strong>Neustart</strong>.
  </div>
  <div id="config-container"></div>
</section>
```

- [ ] **Schritt 6.2: `dashboard.js` — `runUpdate()` + Modal**

Am Ende von `dashboard.js` (vor dem Init-Block) einfügen:

```javascript
// ── Update Workflow ───────────────────────────────────────────────────

async function runUpdate() {
  if (!confirm('Server wird gestoppt, Code aktualisiert und neu gestartet.\n\nFortfahren?')) return;

  // Inject modal
  document.body.insertAdjacentHTML('beforeend', `
    <div id="update-modal" style="position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center">
      <div style="background:#1a1a1a;color:#e0e0e0;border-radius:8px;padding:24px;width:600px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;gap:12px">
        <h3 style="margin:0;color:#fff">⬆ Update & Neustart</h3>
        <div id="update-output" style="flex:1;overflow-y:auto;font-family:monospace;font-size:12px;line-height:1.6;max-height:400px;background:#0d0d0d;padding:12px;border-radius:4px;white-space:pre-wrap"></div>
        <div id="update-status" style="font-size:13px;color:#aaa"></div>
        <button id="update-close-btn" style="display:none;align-self:flex-end" class="btn" onclick="document.getElementById('update-modal').remove()">Schließen</button>
      </div>
    </div>
  `);

  const output = document.getElementById('update-output');
  const status = document.getElementById('update-status');
  const closeBtn = document.getElementById('update-close-btn');

  function appendLine(text, color) {
    const line = document.createElement('div');
    line.textContent = text;
    if (color) line.style.color = color;
    output.appendChild(line);
    // Keep max 200 lines
    while (output.children.length > 200) output.removeChild(output.firstChild);
    output.scrollTop = output.scrollHeight;
  }

  const token = localStorage.getItem('falkenstein_token') || '';
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;

  try {
    const resp = await fetch('/api/admin/update', { method: 'POST', headers });
    if (!resp.body) throw new Error('Kein Response-Body');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      for (const line of text.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.line !== undefined) {
            appendLine(data.line);
          }
          if (data.status === 'done') {
            appendLine('');
            appendLine('✅ Update erfolgreich — Neustart in 3s...', '#4caf50');
            status.textContent = 'Neustart wird durchgeführt...';
            let countdown = 3;
            const timer = setInterval(async () => {
              countdown--;
              status.textContent = `Neustart in ${countdown}s...`;
              if (countdown <= 0) {
                clearInterval(timer);
                // Trigger restart via existing endpoint
                const rtoken = localStorage.getItem('falkenstein_token') || '';
                await fetch('/api/admin/restart', {
                  method: 'POST',
                  headers: rtoken ? { 'Authorization': 'Bearer ' + rtoken } : {},
                }).catch(() => {});
              }
            }, 1000);
            return; // Modal bleibt offen; Reconnect-Overlay übernimmt
          }
          if (data.status === 'error') {
            appendLine('');
            appendLine('❌ Fehler — kein Neustart durchgeführt.', 'var(--red)');
            if (data.line) appendLine(data.line, 'var(--red)');
            closeBtn.style.display = 'block';
            return;
          }
        } catch {}
      }
    }
  } catch (err) {
    appendLine('❌ Verbindungsfehler: ' + err.message, 'var(--red)');
    closeBtn.style.display = 'block';
  }
}
```

- [ ] **Schritt 6.3: Vollständige Test-Suite ausführen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m pytest tests/ -v --ignore=tests/test_llm_gemma4.py -k "not test_integration" 2>&1 | tail -20
```

Erwartet: alle Tests grün.

- [ ] **Schritt 6.4: Commit**

```bash
cd /Users/janikhartmann/Falkenstein && git add frontend/dashboard.html frontend/dashboard.js && git commit -m "feat: Update-Workflow — Button + Terminal-Modal mit SSE-Stream in Config-Sektion"
```

---

## Abschluss

- [ ] **Server starten und Endpunkte smoke-testen**

```bash
cd /Users/janikhartmann/Falkenstein && source venv/bin/activate && python -m backend.main &
sleep 2
curl -s http://localhost:8800/api/admin/system/metrics | python3 -m json.tool
kill %1
```

Erwartet: JSON mit allen 8 Feldern (cpu_percent, ram_used_gb, ram_total_gb, ram_percent, disk_percent, cpu_watts/null, gpu_percent/null, cpu_temp_c/null)

- [ ] **Push**

```bash
cd /Users/janikhartmann/Falkenstein && git push origin main
```
