"""Tests for new Settings fields added for CrewAI migration."""

from backend.config import Settings


def test_ollama_keep_alive_default():
    s = Settings()
    assert s.ollama_keep_alive == "30m"


def test_ollama_stream_tools_default():
    s = Settings()
    assert s.ollama_stream_tools is False


def test_ollama_stream_text_default():
    s = Settings()
    assert s.ollama_stream_text is True


def test_serper_api_key_default():
    s = Settings()
    assert isinstance(s.serper_api_key, str)
    assert s.serper_api_key == ""


def test_serper_api_key_override(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key-123")
    s = Settings()
    assert s.serper_api_key == "test-key-123"


def test_ollama_keep_alive_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "5m")
    s = Settings()
    assert s.ollama_keep_alive == "5m"


def test_ollama_stream_tools_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_STREAM_TOOLS", "true")
    s = Settings()
    assert s.ollama_stream_tools is True


def test_ollama_stream_text_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_STREAM_TEXT", "false")
    s = Settings()
    assert s.ollama_stream_text is False
