"""Tests for MCP-related EventBus extensions."""
from backend.event_bus import STREAM_TO_TELEGRAM, TOOL_TO_ANIMATION

def test_mcp_tools_stream_check():
    from backend.event_bus import should_stream_to_telegram
    assert should_stream_to_telegram("mcp_apple_create_reminder") is True
    assert should_stream_to_telegram("shell_runner") is True
    assert should_stream_to_telegram("unknown_tool") is False

def test_mcp_tool_animation():
    from backend.event_bus import get_tool_animation
    assert get_tool_animation("mcp_apple_create_reminder") == "thinking"
    assert get_tool_animation("shell_runner") == "typing"
    assert get_tool_animation("obsidian") == "reading"
