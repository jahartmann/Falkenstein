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
        proc = None
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
            last_brace = raw.rfind("\n{")
            if last_brace != -1:
                raw = raw[last_brace:].strip()
            data = json.loads(raw)
            return self._parse_powermetrics(data)
        except Exception:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
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

        # GPU % from gpu_active_pct
        try:
            gpu_active = data["gpu"].get("gpu_active_pct")
            if gpu_active is not None:
                result["gpu_percent"] = round(float(gpu_active), 1)
        except (KeyError, TypeError, AttributeError):
            pass

        return result
