import datetime
import pytest

from backend.scheduler import parse_schedule, next_run


def test_parse_taeglich():
    s = parse_schedule("täglich 07:00")
    assert s["type"] == "daily"
    assert s["hour"] == 7
    assert s["minute"] == 0


def test_parse_stuendlich():
    s = parse_schedule("stündlich")
    assert s["type"] == "hourly"


def test_parse_alle_minuten():
    s = parse_schedule("alle 30 Minuten")
    assert s["type"] == "interval_minutes"
    assert s["minutes"] == 30


def test_parse_alle_stunden():
    s = parse_schedule("alle 6 Stunden")
    assert s["type"] == "interval_hours"
    assert s["hours"] == 6


def test_parse_wochentags():
    s = parse_schedule("Mo-Fr 09:00")
    assert s["type"] == "weekdays"
    assert s["hour"] == 9


def test_parse_wochentag():
    s = parse_schedule("montags 08:00")
    assert s["type"] == "weekly"
    assert s["weekday"] == 0  # Monday
    assert s["hour"] == 8


def test_parse_cron():
    s = parse_schedule("cron: 0 7 * * 1-5")
    assert s["type"] == "cron"
    assert s["expr"] == "0 7 * * 1-5"


def test_next_run_daily():
    # If it's 06:00 and task is "täglich 07:00" -> next run today at 07:00
    after = datetime.datetime(2026, 4, 4, 6, 0)
    schedule = parse_schedule("täglich 07:00")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 7, 0)


def test_next_run_daily_past():
    # If it's 08:00 and task is "täglich 07:00" -> next run tomorrow at 07:00
    after = datetime.datetime(2026, 4, 4, 8, 0)
    schedule = parse_schedule("täglich 07:00")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 5, 7, 0)


def test_next_run_hourly():
    after = datetime.datetime(2026, 4, 4, 8, 15)
    schedule = parse_schedule("stündlich")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 9, 0)


def test_next_run_interval_minutes():
    after = datetime.datetime(2026, 4, 4, 8, 0)
    schedule = parse_schedule("alle 30 Minuten")
    nxt = next_run(schedule, after)
    assert nxt == datetime.datetime(2026, 4, 4, 8, 30)


def test_next_run_weekdays_on_weekday():
    # Friday 2026-04-03 at 10:00, task is Mo-Fr 09:00 -> already past today, next is Monday
    after = datetime.datetime(2026, 4, 4, 10, 0)  # Saturday
    schedule = parse_schedule("Mo-Fr 09:00")
    nxt = next_run(schedule, after)
    assert nxt.weekday() == 0  # Monday
    assert nxt.hour == 9


def test_next_run_weekly():
    after = datetime.datetime(2026, 4, 4, 10, 0)  # Friday
    schedule = parse_schedule("montags 08:00")
    nxt = next_run(schedule, after)
    assert nxt.weekday() == 0
    assert nxt.hour == 8
