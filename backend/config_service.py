"""ConfigService — SQLite-backed config with in-memory cache for fast sync reads.

Config changes are persisted to both SQLite (primary) and .env (for bootstrap values).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.database import Database

# Map of config keys to their .env variable names (for write-back)
_ENV_KEY_MAP = {
    "api_token": "API_TOKEN",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "telegram_allowed_chat_ids": "TELEGRAM_ALLOWED_CHAT_IDS",
    "port": "FRONTEND_PORT",
    "ollama_host": "OLLAMA_HOST",
    "ollama_model": "OLLAMA_MODEL",
    "ollama_model_light": "OLLAMA_MODEL_LIGHT",
    "ollama_model_heavy": "OLLAMA_MODEL_HEAVY",
    "ollama_num_ctx": "OLLAMA_NUM_CTX",
    "ollama_num_ctx_extended": "OLLAMA_NUM_CTX_EXTENDED",
    "llm_max_retries": "LLM_MAX_RETRIES",
    "workspace_path": "WORKSPACE_PATH",
    "obsidian_vault_path": "OBSIDIAN_VAULT_PATH",
    "cli_daily_token_budget": "CLI_DAILY_TOKEN_BUDGET",
    "cli_provider": "CLI_PROVIDER",
    "brave_api_key": "BRAVE_API_KEY",
}


def _get_env(key: str, default: str = "") -> str:
    """Get value from environment (loaded via dotenv at startup)."""
    return os.getenv(_ENV_KEY_MAP.get(key, key.upper()), default)


CONFIG_DEFAULTS: list[dict] = [
    # Server
    {"key": "api_token", "value": _get_env("api_token"), "category": "server", "description": "API Token for authentication"},
    {"key": "telegram_bot_token", "value": _get_env("telegram_bot_token"), "category": "server", "description": "Telegram Bot Token"},
    {"key": "telegram_chat_id", "value": _get_env("telegram_chat_id"), "category": "server", "description": "Telegram Chat ID"},
    {"key": "telegram_allowed_chat_ids", "value": _get_env("telegram_allowed_chat_ids"), "category": "server", "description": "Erlaubte Telegram Chat IDs (kommasepariert)"},
    {"key": "port", "value": _get_env("port", "8800"), "category": "server", "description": "Server Port (Neustart nötig)"},
    # Paths
    {"key": "obsidian_vault_path", "value": _get_env("obsidian_vault_path", "~/Library/Mobile Documents/iCloud~md~obsidian/Documents"), "category": "paths", "description": "Obsidian vault root (iCloud)"},
    {"key": "workspace_path", "value": _get_env("workspace_path", "./workspace"), "category": "paths", "description": "SubAgent workspace directory"},
    # LLM
    {"key": "ollama_host", "value": _get_env("ollama_host", "http://localhost:11434"), "category": "llm", "description": "Ollama API host"},
    {"key": "ollama_model", "value": _get_env("ollama_model", "gemma4:26b"), "category": "llm", "description": "Default Ollama model"},
    {"key": "ollama_model_light", "value": _get_env("ollama_model_light"), "category": "llm", "description": "Light model (fast, cheap)"},
    {"key": "ollama_model_heavy", "value": _get_env("ollama_model_heavy"), "category": "llm", "description": "Heavy model (tool-use)"},
    {"key": "ollama_num_ctx", "value": _get_env("ollama_num_ctx", "16384"), "category": "llm", "description": "Context window size"},
    {"key": "ollama_num_ctx_extended", "value": _get_env("ollama_num_ctx_extended", "32768"), "category": "llm", "description": "Extended context window"},
    {"key": "llm_max_retries", "value": _get_env("llm_max_retries", "2"), "category": "llm", "description": "LLM call retries"},
    {"key": "llm_provider_classify", "value": "local", "category": "llm", "description": "LLM provider for classification"},
    {"key": "llm_provider_action", "value": "local", "category": "llm", "description": "LLM provider for actions"},
    {"key": "llm_provider_content", "value": "local", "category": "llm", "description": "LLM provider for content"},
    {"key": "llm_provider_scheduled", "value": "local", "category": "llm", "description": "LLM provider for scheduled tasks"},
    {"key": "cli_provider", "value": _get_env("cli_provider", "claude"), "category": "llm", "description": "CLI LLM provider (claude/gemini)"},
    {"key": "cli_daily_token_budget", "value": _get_env("cli_daily_token_budget", "100000"), "category": "llm", "description": "Daily CLI token budget"},
    # API Keys
    {"key": "brave_api_key", "value": _get_env("brave_api_key"), "category": "api_keys", "description": "Brave Search API key"},
    # General
    {"key": "soul_prompt", "value": "", "category": "personality", "description": "Falki system prompt / personality"},
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

        # Write back to .env if this key maps to an env var
        if key in _ENV_KEY_MAP:
            self._write_env(key, value)

    async def set_many(self, updates: dict[str, str]) -> None:
        for k, v in updates.items():
            await self.set(k, v)

    # ------------------------------------------------------------------ #
    # .env write-back
    # ------------------------------------------------------------------ #

    @staticmethod
    def _write_env(key: str, value: str) -> None:
        """Update a single key in the .env file."""
        env_var = _ENV_KEY_MAP.get(key)
        if not env_var:
            return
        env_path = Path(__file__).parent.parent / ".env"
        if not env_path.exists():
            env_path.write_text(f"{env_var}={value}\n")
            return

        lines = env_path.read_text(encoding="utf-8").splitlines()
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{env_var}=") or stripped.startswith(f"{env_var} ="):
                lines[i] = f"{env_var}={value}"
                found = True
                break
        if not found:
            lines.append(f"{env_var}={value}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
