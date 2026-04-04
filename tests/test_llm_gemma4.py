"""Tests for Gemma 4 specific LLM features: thinking, structured output, context management."""
import pytest
from backend.llm_client import strip_thinking, LLMClient


def test_strip_thinking_removes_block():
    text = "Hallo <think>\nIch denke nach...\n</think> Das ist die Antwort."
    result = strip_thinking(text)
    assert "denke nach" not in result
    assert "Antwort" in result


def test_strip_thinking_no_block():
    text = "Normale Antwort ohne Thinking."
    assert strip_thinking(text) == text


def test_strip_thinking_multiple_blocks():
    text = "<think>\nA</think> Mitte <think>\nB</think> Ende"
    result = strip_thinking(text)
    assert "Mitte" in result
    assert "Ende" in result
    assert "A" not in result
    assert "B" not in result


def test_strip_thinking_empty():
    assert strip_thinking("") == ""


def test_clean_history():
    llm = LLMClient.__new__(LLMClient)
    msgs = [
        {"role": "user", "content": "Frage"},
        {"role": "assistant", "content": "<think>\nReasoning</think> Antwort"},
        {"role": "user", "content": "Nächste Frage"},
    ]
    cleaned = llm._clean_history(msgs)
    assert "Reasoning" not in cleaned[1]["content"]
    assert "Antwort" in cleaned[1]["content"]
    assert cleaned[0]["content"] == "Frage"
    assert cleaned[2]["content"] == "Nächste Frage"


def test_clean_history_preserves_tool_messages():
    llm = LLMClient.__new__(LLMClient)
    msgs = [
        {"role": "tool", "content": "Tool result data"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "test"}}]},
    ]
    cleaned = llm._clean_history(msgs)
    assert cleaned[0]["content"] == "Tool result data"
    assert cleaned[1]["tool_calls"] is not None


def test_build_options_with_temperature():
    llm = LLMClient.__new__(LLMClient)
    opts = llm._build_options(temperature=0.5)
    assert opts["temperature"] == 0.5


def test_build_options_empty_returns_none():
    llm = LLMClient.__new__(LLMClient)
    opts = llm._build_options()
    assert opts is None
