"""Tests for MCP config models."""
import pytest
from backend.mcp.config import MCPServerConfig, ServerStatus


def test_server_config_defaults():
    cfg = MCPServerConfig(id="apple-mcp", name="Apple Services", command="npx", args=["-y", "apple-mcp"])
    assert cfg.id == "apple-mcp"
    assert cfg.enabled is True
    assert cfg.auto_restart is True
    assert cfg.env == {}


def test_server_config_custom():
    cfg = MCPServerConfig(
        id="mcp-obsidian",
        name="Obsidian Vault",
        command="npx",
        args=["-y", "mcp-obsidian"],
        env={"OBSIDIAN_API_KEY": "secret"},
        enabled=False,
        auto_restart=False,
    )
    assert cfg.enabled is False
    assert cfg.env["OBSIDIAN_API_KEY"] == "secret"


def test_server_status_defaults():
    cfg = MCPServerConfig(id="test", name="Test", command="echo", args=[])
    status = ServerStatus(config=cfg)
    assert status.status == "stopped"
    assert status.pid is None
    assert status.tools_count == 0
    assert status.last_call is None


def test_server_status_running():
    cfg = MCPServerConfig(id="test", name="Test", command="echo", args=[])
    status = ServerStatus(config=cfg, status="running", pid=12345, tools_count=5)
    assert status.status == "running"
    assert status.pid == 12345
