from __future__ import annotations

import itertools
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class TelegramJob:
    id: str
    chat_id: str
    prompt: str
    route_action: str
    created_at: float = field(default_factory=time.time)
    status: str = "queued"
    crew_type: str | None = None
    crew_id: str | None = None
    progress_steps: int = 0
    last_progress: str = ""
    last_progress_at: float = 0.0
    result_preview: str = ""


class TelegramJobManager:
    """Tracks Telegram background jobs and throttles progress spam."""

    def __init__(self, max_jobs: int = 200, progress_interval_seconds: float = 1.5):
        self.max_jobs = max_jobs
        self.progress_interval_seconds = progress_interval_seconds
        self._counter = itertools.count(1)
        self._jobs: OrderedDict[str, TelegramJob] = OrderedDict()
        self._lock = threading.Lock()

    def create_job(self, chat_id: str, prompt: str, route_action: str) -> TelegramJob:
        with self._lock:
            job_id = f"TG-{next(self._counter):04d}"
            job = TelegramJob(
                id=job_id,
                chat_id=str(chat_id),
                prompt=prompt,
                route_action=route_action,
            )
            self._jobs[job_id] = job
            self._jobs.move_to_end(job_id)
            while len(self._jobs) > self.max_jobs:
                self._jobs.popitem(last=False)
            return job

    def get(self, job_id: str | None) -> TelegramJob | None:
        if not job_id:
            return None
        with self._lock:
            return self._jobs.get(job_id)

    def mark_started(
        self, job_id: str | None, *, crew_type: str | None = None, crew_id: str | None = None,
    ) -> TelegramJob | None:
        if not job_id:
            return None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status = "running"
            if crew_type:
                job.crew_type = crew_type
            if crew_id:
                job.crew_id = crew_id
            self._jobs.move_to_end(job_id)
            return job

    def bind_crew(self, job_id: str | None, crew_id: str) -> TelegramJob | None:
        return self.mark_started(job_id, crew_id=crew_id)

    def note_progress(self, job_id: str | None, label: str) -> dict | None:
        if not job_id:
            return None
        now = time.time()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if (
                label == job.last_progress
                and now - job.last_progress_at < self.progress_interval_seconds
            ):
                return None
            if (
                label != job.last_progress
                and job.last_progress_at
                and now - job.last_progress_at < 0.25
            ):
                return None
            job.progress_steps += 1
            job.last_progress = label
            job.last_progress_at = now
            self._jobs.move_to_end(job_id)
            return {
                "job_id": job.id,
                "step": job.progress_steps,
                "label": label,
                "crew_id": job.crew_id,
                "crew_type": job.crew_type,
            }

    def complete(self, job_id: str | None, *, status: str, result_preview: str = "") -> TelegramJob | None:
        if not job_id:
            return None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status = status
            job.result_preview = result_preview[:300]
            self._jobs.move_to_end(job_id)
            return job


class TelegramResponseCache:
    """Small exact-match cache for fast Telegram quick replies."""

    def __init__(self, ttl_seconds: float = 180.0, max_entries: int = 128):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(text: str) -> str:
        return " ".join(text.split()).strip().lower()

    def get(self, text: str) -> str | None:
        key = self._key(text)
        now = time.time()
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            stored_at, value = item
            if now - stored_at > self.ttl_seconds:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return value

    def set(self, text: str, value: str) -> None:
        key = self._key(text)
        with self._lock:
            self._entries[key] = (time.time(), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
