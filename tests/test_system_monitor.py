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
