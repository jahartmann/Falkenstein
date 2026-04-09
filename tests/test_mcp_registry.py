"""Tests for MCP server registry."""
import pytest
from backend.mcp.registry import MCPRegistry
from backend.mcp.config import MCPServerConfig


# ── Legacy tests (updated or kept where semantics still apply) ────────────────

def test_registry_list_servers_catalog_seeded():
    # New registry seeds from catalog on load_from_db — bare __init__ has no servers
    reg = MCPRegistry()
    # Without load_from_db, _servers is empty
    assert reg.list_servers() == []


def test_registry_get_missing():
    reg = MCPRegistry()
    assert reg.get("nonexistent") is None


def test_registry_from_settings_shim():
    # from_settings is now a deprecated shim that returns an empty registry
    reg = MCPRegistry.from_settings(
        server_ids="apple-mcp,desktop-commander",
        enabled_flags={"apple-mcp": True, "desktop-commander": False},
        node_path="npx",
    )
    # Shim returns empty registry (no servers without load_from_db)
    assert isinstance(reg, MCPRegistry)
    assert reg.list_servers() == []


# ── New DB-backed registry tests (Task 8) ────────────────────────────────────

@pytest.mark.asyncio
async def test_load_from_db_empty(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    # Catalog entries exist but nothing is installed/enabled
    srv = reg.get("apple-mcp")
    assert srv is not None
    assert srv.config.enabled is False
    assert reg.is_installed("apple-mcp") is False
    await db.close()


@pytest.mark.asyncio
async def test_persist_install_state(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    await reg.load_from_db(db)
    await reg.set_installed(db, "apple-mcp", True, config={"k": "v"})
    await reg.set_enabled(db, "apple-mcp", True)

    reg2 = MCPRegistry()
    await reg2.load_from_db(db)
    assert reg2.is_installed("apple-mcp") is True
    assert reg2.get("apple-mcp").config.enabled is True
    assert reg2.get_user_config("apple-mcp") == {"k": "v"}
    await db.close()


@pytest.mark.asyncio
async def test_env_migration_one_shot(tmp_path):
    from backend.database import Database
    db = Database(tmp_path / "t.db")
    await db.init()
    reg = MCPRegistry()
    legacy = {"mcp_apple_enabled": True,
              "mcp_desktop_commander_enabled": False,
              "mcp_obsidian_enabled": True}
    await reg.migrate_from_env(db, legacy_flags=legacy)
    await reg.load_from_db(db)
    assert reg.get("apple-mcp").config.enabled is True
    assert reg.get("mcp-obsidian").config.enabled is True
    # Running migration again should be idempotent (no crash)
    await reg.migrate_from_env(db, legacy_flags=legacy)
    await db.close()
