"""Tests for MCP server registry."""
import pytest
from backend.mcp.registry import MCPRegistry
from backend.mcp.config import MCPServerConfig

def _apple_config():
    return MCPServerConfig(id="apple-mcp", name="Apple Services", command="npx", args=["-y", "apple-mcp"])

def _desktop_config():
    return MCPServerConfig(id="desktop-commander", name="Desktop Commander", command="npx", args=["-y", "@anthropic/desktop-commander"], enabled=False)

def test_registry_empty():
    reg = MCPRegistry()
    assert reg.list_servers() == []

def test_registry_register():
    reg = MCPRegistry()
    reg.register(_apple_config())
    servers = reg.list_servers()
    assert len(servers) == 1
    assert servers[0].config.id == "apple-mcp"

def test_registry_get():
    reg = MCPRegistry()
    reg.register(_apple_config())
    status = reg.get("apple-mcp")
    assert status is not None
    assert status.config.name == "Apple Services"

def test_registry_get_missing():
    reg = MCPRegistry()
    assert reg.get("nonexistent") is None

def test_registry_enabled_only():
    reg = MCPRegistry()
    reg.register(_apple_config())
    reg.register(_desktop_config())
    enabled = reg.list_enabled()
    assert len(enabled) == 1
    assert enabled[0].config.id == "apple-mcp"

def test_registry_toggle():
    reg = MCPRegistry()
    reg.register(_apple_config())
    reg.toggle("apple-mcp", False)
    assert reg.get("apple-mcp").config.enabled is False
    enabled = reg.list_enabled()
    assert len(enabled) == 0

def test_registry_update_status():
    reg = MCPRegistry()
    reg.register(_apple_config())
    reg.update_status("apple-mcp", status="running", pid=1234, tools_count=12)
    s = reg.get("apple-mcp")
    assert s.status == "running"
    assert s.pid == 1234
    assert s.tools_count == 12

def test_registry_from_settings_string():
    reg = MCPRegistry.from_settings(
        server_ids="apple-mcp,desktop-commander",
        enabled_flags={"apple-mcp": True, "desktop-commander": False},
        node_path="npx",
    )
    assert len(reg.list_servers()) == 2
    assert len(reg.list_enabled()) == 1
