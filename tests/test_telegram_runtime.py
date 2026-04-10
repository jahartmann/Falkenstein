from __future__ import annotations

from backend.telegram_runtime import TelegramJobManager, TelegramResponseCache


def test_response_cache_is_case_and_whitespace_insensitive():
    cache = TelegramResponseCache(ttl_seconds=60, max_entries=8)
    cache.set("  Hallo   Falki  ", "Hi!")
    assert cache.get("hallo falki") == "Hi!"


def test_response_cache_expires_entries():
    cache = TelegramResponseCache(ttl_seconds=0.0, max_entries=8)
    cache.set("status", "ok")
    assert cache.get("status") is None


def test_job_manager_generates_incrementing_ids_and_tracks_progress():
    jobs = TelegramJobManager(max_jobs=8, progress_interval_seconds=0.0)
    job = jobs.create_job("42", "Bitte recherchiere", "crew")
    assert job.id.startswith("TG-")

    jobs.mark_started(job.id, crew_type="researcher", crew_id="crew-1")
    progress = jobs.note_progress(job.id, "web_search")
    assert progress is not None
    assert progress["step"] == 1
    assert progress["crew_id"] == "crew-1"

    completed = jobs.complete(job.id, status="done", result_preview="Fertig")
    assert completed is not None
    assert completed.status == "done"
    assert completed.result_preview == "Fertig"
