"""Speech-to-Text service using faster-whisper (local, no API needed)."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_model = None
_model_lock = asyncio.Lock()


async def _get_model():
    """Lazy-load Whisper model on first use."""
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is not None:
            return _model
        log.info("Loading Whisper model (base)...")
        from faster_whisper import WhisperModel
        # "base" is a good balance: ~150MB, fast, accurate enough for German
        _model = await asyncio.to_thread(
            WhisperModel, "base", device="cpu", compute_type="int8"
        )
        log.info("Whisper model loaded")
        return _model


async def transcribe(audio_path: str | Path, language: str = "de") -> str:
    """Transcribe an audio file to text. Returns the transcription."""
    path = Path(audio_path)
    if not path.exists():
        return ""

    model = await _get_model()

    def _do_transcribe():
        segments, info = model.transcribe(
            str(path), language=language,
            beam_size=5, vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments if seg.text.strip()]
        return " ".join(parts)

    try:
        text = await asyncio.to_thread(_do_transcribe)
        log.info(f"Transcribed {path.name}: {text[:100]}...")
        return text
    except Exception as e:
        log.error(f"Transcription failed for {path}: {e}")
        return ""
