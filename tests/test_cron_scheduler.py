"""Tests for cron expression support in scheduler."""
import datetime
import pytest
from backend.scheduler import parse_schedule, next_run, get_next_runs


def test_parse_cron_valid():
    result = parse_schedule("cron: */15 * * * *")
    assert result == {"type": "cron", "expr": "*/15 * * * *"}


def test_parse_cron_weekdays():
    result = parse_schedule("cron: 0 9 * * 1-5")
    assert result == {"type": "cron", "expr": "0 9 * * 1-5"}


def test_parse_cron_invalid_falls_back():
    result = parse_schedule("cron: INVALID GARBAGE")
    assert result["type"] == "interval_minutes"


def test_next_run_cron_every_15_min():
    sched = {"type": "cron", "expr": "*/15 * * * *"}
    after = datetime.datetime(2026, 4, 4, 10, 3)
    nxt = next_run(sched, after)
    assert nxt == datetime.datetime(2026, 4, 4, 10, 15)


def test_next_run_cron_daily_at_9():
    sched = {"type": "cron", "expr": "0 9 * * *"}
    after = datetime.datetime(2026, 4, 4, 10, 0)
    nxt = next_run(sched, after)
    assert nxt == datetime.datetime(2026, 4, 5, 9, 0)


def test_next_run_cron_weekdays_only():
    sched = {"type": "cron", "expr": "0 9 * * 1-5"}
    # Friday 10:00 → next is Monday 09:00
    after = datetime.datetime(2026, 4, 3, 10, 0)  # Friday
    nxt = next_run(sched, after)
    assert nxt.weekday() < 5
    assert nxt.hour == 9


def test_next_run_cron_first_of_month():
    sched = {"type": "cron", "expr": "0 8 1 * *"}
    after = datetime.datetime(2026, 4, 2, 0, 0)
    nxt = next_run(sched, after)
    assert nxt == datetime.datetime(2026, 5, 1, 8, 0)


def test_get_next_runs_cron():
    sched = parse_schedule("cron: 0 */2 * * *")
    after = datetime.datetime(2026, 4, 4, 9, 0)
    runs = get_next_runs(sched, count=3, after=after)
    assert len(runs) == 3
    assert runs[0] == datetime.datetime(2026, 4, 4, 10, 0)
    assert runs[1] == datetime.datetime(2026, 4, 4, 12, 0)
    assert runs[2] == datetime.datetime(2026, 4, 4, 14, 0)
