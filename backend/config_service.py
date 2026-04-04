"""ConfigService — SQLite-backed config with in-memory cache for fast sync reads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.database import Database

CONFIG_DEFAULTS: list[dict] = [
    {"key": "soul_prompt", "value": "", "category": "personality", "description": "Falki system prompt / personality"},
    {"key": "obsidian_vault_path", "value": "~/Library/Mobile Documents/iCloud~md~obsidian/Documents", "category": "paths", "description": "Obsidian vault root (iCloud)"},
    {"key": "workspace_path", "value": "./workspace", "category": "paths", "description": "SubAgent workspace directory"},
    {"key": "ollama_host", "value": "http://localhost:11434", "category": "llm", "description": "Ollama API host"},
    {"key": "ollama_model", "value": "gemma4:26b", "category": "llm", "description": "Default Ollama model"},
    {"key": "ollama_model_light", "value": "", "category": "llm", "description": "Light model (fast, cheap)"},
    {"key": "ollama_model_heavy", "value": "", "category": "llm", "description": "Heavy model (tool-use)"},
    {"key": "ollama_num_ctx", "value": "16384", "category": "llm", "description": "Context window size"},
    {"key": "ollama_num_ctx_extended", "value": "32768", "category": "llm", "description": "Extended context window"},
    {"key": "llm_max_retries", "value": "2", "category": "llm", "description": "LLM call retries"},
    {"key": "llm_provider_classify", "value": "local", "category": "llm", "description": "LLM provider for classification"},
    {"key": "llm_provider_action", "value": "local", "category": "llm", "description": "LLM provider for actions"},
    {"key": "llm_provider_content", "value": "local", "category": "llm", "description": "LLM provider for content"},
    {"key": "llm_provider_scheduled", "value": "local", "category": "llm", "description": "LLM provider for scheduled tasks"},
    {"key": "cli_provider", "value": "claude", "category": "llm", "description": "CLI LLM provider (claude/gemini)"},
    {"key": "cli_daily_token_budget", "value": "100000", "category": "llm", "description": "Daily CLI token budget"},
    {"key": "brave_api_key", "value": "", "category": "api_keys", "description": "Brave Search API key"},
    {"key": "obsidian_enabled", "value": "true", "category": "general", "description": "Write results to Obsidian"},
    {"key": "obsidian_auto_knowledge", "value": "true", "category": "general", "description": "Auto-write content results to Obsidian"},
]


class ConfigService:
    """Read/write config from SQLite with an in-memory cache for fast sync reads."""

    def __init__(self, db: Database) -> None:
        self._db = db
        # In-memory cache: key -> {key, value, category, description}
        self._cache: dict[str, dict] = {}

    async def init(self) -> None:
        """Seed defaults (skip existing keys), then load all into cache."""
        # Find which keys already exist in DB
        existing = await self._db.get_all_config()
        existing_keys = {row["key"] for row in existing}

        # Seed only missing defaults
        for d in CONFIG_DEFAULTS:
            if d["key"] not in existing_keys:
                await self._db.set_config(
                    d["key"], d["value"], d["category"], d.get("description")
                )

        # Load everything into cache
        await self._reload_cache()

    async def _reload_cache(self) -> None:
        rows = await self._db.get_all_config()
        self._cache = {
            row["key"]: {
                "key": row["key"],
                "value": row["value"],
                "category": row["category"],
                "description": row.get("description"),
            }
            for row in rows
        }

    # ------------------------------------------------------------------ #
    # Sync reads from cache
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: str | None = None) -> str | None:
        entry = self._cache.get(key)
        return entry["value"] if entry else default

    def get_int(self, key: str, default: int = 0) -> int:
        val = self.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes")

    def get_path(self, key: str, default: str = ".") -> Path:
        val = self.get(key, default)
        return Path(val).expanduser()

    def get_category(self, category: str) -> dict[str, str]:
        return {
            k: v["value"]
            for k, v in self._cache.items()
            if v["category"] == category
        }

    def get_all(self) -> list[dict]:
        return list(self._cache.values())

    # ------------------------------------------------------------------ #
    # Async writes (DB + cache)
    # ------------------------------------------------------------------ #

    async def set(
        self,
        key: str,
        value: str,
        category: str | None = None,
        description: str | None = None,
    ) -> None:
        # Resolve category/description from cache if not provided
        existing = self._cache.get(key, {})
        cat = category or existing.get("category", "general")
        desc = description or existing.get("description")

        await self._db.set_config(key, value, cat, desc)
        self._cache[key] = {
            "key": key,
            "value": value,
            "category": cat,
            "description": desc,
        }

    async def set_many(self, updates: dict[str, str]) -> None:
        for k, v in updates.items():
            await self.set(k, v)
