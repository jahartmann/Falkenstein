import time
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
from backend.config import settings, HOT_RELOAD_FIELDS

router = APIRouter(prefix="/api/admin", tags=["admin"])

_start_time: float = 0.0

_SETTINGS_SCHEMA: dict[str, dict[str, dict]] = {
    "llm": {
        "ollama_host": {"type": "text", "hot_reload": True},
        "ollama_model": {"type": "text", "hot_reload": True},
        "ollama_model_light": {"type": "text", "hot_reload": True},
        "ollama_model_heavy": {"type": "text", "hot_reload": True},
        "ollama_num_ctx": {"type": "number", "hot_reload": True},
        "ollama_num_ctx_extended": {"type": "number", "hot_reload": True},
        "llm_max_retries": {"type": "number", "hot_reload": True},
    },
    "telegram": {
        "telegram_bot_token": {"type": "password", "hot_reload": True},
        "telegram_chat_id": {"type": "text", "hot_reload": True},
    },
    "cli": {
        "cli_provider": {"type": "select", "options": ["claude", "gemini"], "hot_reload": True},
        "cli_daily_token_budget": {"type": "number", "hot_reload": True},
    },
    "obsidian": {
        "obsidian_vault_path": {"type": "text", "hot_reload": True},
        "obsidian_watch_enabled": {"type": "boolean", "hot_reload": True},
        "obsidian_auto_submit_tasks": {"type": "boolean", "hot_reload": True},
    },
    "server": {
        "frontend_port": {"type": "number", "hot_reload": False},
        "db_path": {"type": "text", "hot_reload": False},
        "workspace_path": {"type": "text", "hot_reload": False},
    },
}

_SENSITIVE_FIELDS = {"telegram_bot_token"}


def init(start_time: float):
    global _start_time
    _start_time = start_time


def write_env_file(env_path: Path, updates: dict[str, str]):
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class SettingsUpdate(BaseModel):
    group: str
    values: dict[str, str]


@router.get("/dashboard")
async def get_dashboard():
    from backend.main import main_agent, budget_tracker, db
    import httpx

    active = []
    if main_agent:
        active = main_agent.get_status().get("active_agents", [])

    open_count = 0
    recent = []
    if db and db._conn:
        open_tasks = await db.get_open_tasks()
        open_count = len(open_tasks)
        cursor = await db._conn.execute(
            "SELECT id, title, status, assigned_to FROM tasks ORDER BY id DESC LIMIT 5"
        )
        rows = await cursor.fetchall()
        recent = [
            {"id": r["id"], "title": r["title"], "status": r["status"], "agent": r["assigned_to"] or ""}
            for r in rows
        ]

    budget = {}
    if budget_tracker:
        budget = {
            "used": budget_tracker.used,
            "budget": budget_tracker.daily_budget,
            "remaining": budget_tracker.remaining,
        }

    ollama_status = "offline"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            if resp.status_code == 200:
                ollama_status = "online"
    except Exception:
        pass

    return {
        "active_agents": active,
        "open_tasks_count": open_count,
        "recent_tasks": recent,
        "budget": budget,
        "uptime_seconds": int(time.time() - _start_time) if _start_time else 0,
        "ollama_status": ollama_status,
    }


@router.get("/settings")
async def get_settings():
    groups = {}
    for group_name, fields in _SETTINGS_SCHEMA.items():
        group_data = {}
        for field_name, field_meta in fields.items():
            raw_value = getattr(settings, field_name, "")
            value = str(raw_value) if raw_value is not None else ""
            if field_name in _SENSITIVE_FIELDS and value:
                value = "***"
            group_data[field_name] = {
                "value": value,
                "hot_reload": field_meta["hot_reload"],
                "type": field_meta["type"],
            }
            if "options" in field_meta:
                group_data[field_name]["options"] = field_meta["options"]
        groups[group_name] = group_data
    return {"groups": groups}


@router.put("/settings")
async def put_settings(update: SettingsUpdate):
    group_fields = _SETTINGS_SCHEMA.get(update.group, {})
    if not group_fields:
        return {"saved": False, "error": f"Unknown group: {update.group}"}

    env_updates = {}
    hot_reloaded = True
    restart_required = False

    for field_name, new_value in update.values.items():
        if field_name not in group_fields:
            continue
        field_meta = group_fields[field_name]
        env_key = field_name.upper()
        env_updates[env_key] = new_value

        if field_meta["hot_reload"] and field_name in HOT_RELOAD_FIELDS:
            current_type = type(getattr(settings, field_name, ""))
            if current_type == int:
                setattr(settings, field_name, int(new_value))
            elif current_type == bool:
                setattr(settings, field_name, new_value.lower() in ("true", "1", "yes"))
            elif current_type == Path:
                setattr(settings, field_name, Path(new_value))
            else:
                setattr(settings, field_name, new_value)
        else:
            hot_reloaded = False
            restart_required = True

    env_path = Path(".env")
    write_env_file(env_path, env_updates)

    return {
        "saved": True,
        "hot_reloaded": hot_reloaded,
        "restart_required": restart_required,
    }
