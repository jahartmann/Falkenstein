"""Tests for ConfigService — SQLite-backed config with in-memory cache."""

import pytest
import pytest_asyncio

from backend.database import Database
from backend.config_service import ConfigService, CONFIG_DEFAULTS


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.init()
    yield d
    await d.close()


@pytest_asyncio.fixture
async def cfg(db):
    svc = ConfigService(db)
    await svc.init()
    return svc


# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_seed_defaults(cfg: ConfigService):
    """init() seeds all CONFIG_DEFAULTS into DB."""
    all_entries = cfg.get_all()
    keys = {e["key"] for e in all_entries}
    for d in CONFIG_DEFAULTS:
        assert d["key"] in keys


@pytest.mark.asyncio
async def test_get_returns_default(cfg: ConfigService):
    """get() returns seeded default value."""
    assert cfg.get("ollama_host") == "http://localhost:11434"
    assert cfg.get("nonexistent") is None
    assert cfg.get("nonexistent", "fallback") == "fallback"


@pytest.mark.asyncio
async def test_set_and_get(cfg: ConfigService):
    """set() writes value, get() returns it."""
    await cfg.set("ollama_host", "http://remote:11434")
    assert cfg.get("ollama_host") == "http://remote:11434"


@pytest.mark.asyncio
async def test_get_category(cfg: ConfigService):
    """get_category() returns only keys of that category."""
    llm = cfg.get_category("llm")
    assert "ollama_host" in llm
    assert "obsidian_vault_path" not in llm


@pytest.mark.asyncio
async def test_get_all(cfg: ConfigService):
    """get_all() returns list of dicts with key/value/category."""
    entries = cfg.get_all()
    assert len(entries) >= len(CONFIG_DEFAULTS)
    assert all("key" in e and "value" in e and "category" in e for e in entries)


@pytest.mark.asyncio
async def test_set_updates_cache(cfg: ConfigService, db: Database):
    """set() updates both DB and in-memory cache."""
    await cfg.set("ollama_model", "llama3")
    # cache
    assert cfg.get("ollama_model") == "llama3"
    # DB
    assert await db.get_config("ollama_model") == "llama3"


@pytest.mark.asyncio
async def test_seed_does_not_overwrite_existing(db: Database):
    """Re-init preserves values already in DB."""
    # Pre-set a value before ConfigService init
    await db.set_config("ollama_host", "http://custom:9999", category="llm")

    svc = ConfigService(db)
    await svc.init()

    assert svc.get("ollama_host") == "http://custom:9999"


@pytest.mark.asyncio
async def test_get_int(cfg: ConfigService):
    assert cfg.get_int("ollama_num_ctx") == 16384
    assert cfg.get_int("nonexistent", 42) == 42


@pytest.mark.asyncio
async def test_get_bool(cfg: ConfigService):
    assert cfg.get_bool("obsidian_enabled") is True
    assert cfg.get_bool("nonexistent") is False


@pytest.mark.asyncio
async def test_get_path(cfg: ConfigService):
    from pathlib import Path
    p = cfg.get_path("obsidian_vault_path")
    assert isinstance(p, Path)
    assert str(p).endswith("Documents")


@pytest.mark.asyncio
async def test_set_many(cfg: ConfigService):
    await cfg.set_many({"ollama_host": "http://a:1", "ollama_model": "tiny"})
    assert cfg.get("ollama_host") == "http://a:1"
    assert cfg.get("ollama_model") == "tiny"
