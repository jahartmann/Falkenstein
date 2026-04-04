"""
Migration script: Obsidian schedules + .env config -> SQLite.

Usage:
    python -m backend.migrate
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from backend.database import Database

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env -> Config mapping
# ---------------------------------------------------------------------------

ENV_TO_CONFIG: dict[str, tuple[str, str]] = {
    "OLLAMA_HOST": ("ollama_host", "llm"),
    "OLLAMA_MODEL": ("ollama_model", "llm"),
    "OLLAMA_MODEL_LIGHT": ("ollama_model_light", "llm"),
    "OLLAMA_MODEL_HEAVY": ("ollama_model_heavy", "llm"),
    "OLLAMA_NUM_CTX": ("ollama_num_ctx", "llm"),
    "OLLAMA_NUM_CTX_EXTENDED": ("ollama_num_ctx_extended", "llm"),
    "LLM_MAX_RETRIES": ("llm_max_retries", "llm"),
    "CLI_PROVIDER": ("cli_provider", "llm"),
    "CLI_DAILY_TOKEN_BUDGET": ("cli_daily_token_budget", "llm"),
    "OBSIDIAN_VAULT_PATH": ("obsidian_vault_path", "paths"),
    "WORKSPACE_PATH": ("workspace_path", "paths"),
    "BRAVE_API_KEY": ("brave_api_key", "api_keys"),
}


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter from markdown text."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    meta: dict = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if v.lower() in ("true", "false"):
                v = v.lower() == "true"
            meta[k.strip()] = v
    body = text[end + 3:].strip()
    return meta, body


# ---------------------------------------------------------------------------
# Migrate schedules from Obsidian vault
# ---------------------------------------------------------------------------

async def migrate_schedules(db: Database, vault_path: str) -> int:
    """Read .md files from <vault>/KI-Büro/Schedules/, insert into schedules table.

    Returns number of schedules migrated.
    """
    schedules_dir = Path(vault_path) / "KI-Büro" / "Schedules"
    if not schedules_dir.is_dir():
        log.warning("Schedules directory not found: %s", schedules_dir)
        return 0

    count = 0
    for md_file in sorted(schedules_dir.glob("*.md")):
        # Skip template files
        if md_file.name.startswith("_"):
            continue

        text = md_file.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)

        name = meta.get("name", md_file.stem)
        schedule = meta.get("schedule")
        if not schedule:
            log.warning("No schedule in %s, skipping", md_file.name)
            continue

        agent_type = meta.get("agent", "researcher")
        active = 1 if meta.get("active", True) else 0
        active_hours = meta.get("active_hours") or None
        light_context = 1 if meta.get("light_context", False) else 0
        prompt = body or meta.get("prompt", "")

        if not prompt:
            log.warning("No prompt in %s, skipping", md_file.name)
            continue

        try:
            await db.create_schedule(
                name=str(name),
                schedule=str(schedule),
                agent_type=str(agent_type),
                prompt=prompt,
                active=active,
                active_hours=str(active_hours) if active_hours else None,
                light_context=light_context,
            )
            count += 1
            log.info("Migrated schedule: %s", name)
        except Exception as e:
            # UNIQUE constraint — schedule already exists
            log.info("Schedule '%s' already exists, skipping: %s", name, e)

    return count


# ---------------------------------------------------------------------------
# Migrate .env config
# ---------------------------------------------------------------------------

async def migrate_env_config(db: Database, env_path: str) -> int:
    """Read .env file and write known keys to config table (don't overwrite).

    Returns number of config entries written.
    """
    env_file = Path(env_path)
    if not env_file.is_file():
        log.warning(".env file not found: %s", env_file)
        return 0

    count = 0
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")

        if key not in ENV_TO_CONFIG:
            continue

        config_key, category = ENV_TO_CONFIG[key]

        # Only write if not already in DB
        existing = await db.get_config(config_key)
        if existing is not None:
            log.info("Config '%s' already set, skipping", config_key)
            continue

        await db.set_config(key=config_key, value=value, category=category)
        count += 1
        log.info("Migrated config: %s -> %s", key, config_key)

    return count


# ---------------------------------------------------------------------------
# Migrate SOUL.md
# ---------------------------------------------------------------------------

async def migrate_soul(db: Database, soul_path: str) -> bool:
    """Read SOUL.md content, store as config key 'soul_prompt' if not set.

    Returns True if written, False if skipped.
    """
    soul_file = Path(soul_path)
    if not soul_file.is_file():
        log.warning("SOUL.md not found: %s", soul_file)
        return False

    existing = await db.get_config("soul_prompt")
    if existing is not None:
        log.info("soul_prompt already set, skipping")
        return False

    content = soul_file.read_text(encoding="utf-8").strip()
    if not content:
        log.warning("SOUL.md is empty, skipping")
        return False

    await db.set_config(
        key="soul_prompt",
        value=content,
        category="personality",
        description="System personality prompt from SOUL.md",
    )
    log.info("Migrated SOUL.md (%d chars)", len(content))
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_migration() -> None:
    """Run all migrations. Reads DB_PATH and OBSIDIAN_VAULT_PATH from env."""
    db_path = os.getenv("DB_PATH", "data/assistant.db")
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    env_path = os.getenv("ENV_PATH", ".env")
    soul_path = os.getenv("SOUL_PATH", "SOUL.md")

    db = Database(db_path)
    await db.initialize()

    log.info("=== Migration Start ===")

    # 1. Schedules
    if vault_path:
        n = await migrate_schedules(db, vault_path)
        log.info("Schedules migrated: %d", n)
    else:
        log.warning("OBSIDIAN_VAULT_PATH not set, skipping schedule migration")

    # 2. .env config
    n = await migrate_env_config(db, env_path)
    log.info("Config entries migrated: %d", n)

    # 3. SOUL.md
    written = await migrate_soul(db, soul_path)
    log.info("SOUL.md migrated: %s", written)

    log.info("=== Migration Complete ===")
    await db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(run_migration())


if __name__ == "__main__":
    main()
