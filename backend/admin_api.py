from __future__ import annotations

import asyncio
import glob as globmod
import os
import time

from fastapi import APIRouter
from pydantic import BaseModel

from backend.models import TaskStatus

router = APIRouter(prefix="/api/admin", tags=["admin"])

_start_time: float = 0.0

# ── dependency injection ─────────────────────────────────────────────
_db = None
_scheduler = None
_config_service = None
_main_agent = None  # Now FalkensteinFlow
_flow = None
_budget_tracker = None
_llm_router = None
_fact_memory = None
_soul_memory = None
_system_monitor = None
_mcp_bridge = None


def set_dependencies(db=None, scheduler=None, config_service=None,
                     main_agent=None, flow=None, budget_tracker=None, llm_router=None,
                     fact_memory=None, soul_memory=None, system_monitor=None,
                     mcp_bridge=None):
    global _db, _scheduler, _config_service, _main_agent, _flow, _budget_tracker, _llm_router, _fact_memory, _soul_memory, _system_monitor, _mcp_bridge
    _db = db; _scheduler = scheduler; _config_service = config_service
    _flow = flow; _main_agent = main_agent or flow  # Flow replaces MainAgent
    _budget_tracker = budget_tracker; _llm_router = llm_router
    _fact_memory = fact_memory; _soul_memory = soul_memory
    _system_monitor = system_monitor
    _mcp_bridge = mcp_bridge


def init(start_time: float):
    global _start_time
    _start_time = start_time


# ── Pydantic models ─────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    name: str
    schedule: str
    agent_type: str = "researcher"
    prompt: str
    active: bool = True
    active_hours: str | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    agent_type: str | None = None
    prompt: str | None = None
    active: bool | None = None
    active_hours: str | None = None


class ScheduleAICreate(BaseModel):
    description: str


class TaskSubmit(BaseModel):
    text: str
    chat_id: str | None = None


class TaskCreate(BaseModel):
    title: str
    description: str
    agent_type: str = "researcher"
    project: str | None = None
    depends_on: list[int] = []


class TaskPatch(BaseModel):
    status: str


class ConfigBatchUpdate(BaseModel):
    updates: dict[str, str]


class LLMRoutingUpdate(BaseModel):
    routing: dict[str, str]  # e.g. {"classify": "local", "action": "claude", ...}


# ── Dashboard ────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_dashboard():
    import httpx

    active = []
    # FalkensteinFlow has no get_status(); active agents are tracked via EventBus

    open_count = 0
    recent = []
    if _db and _db._conn:
        open_tasks = await _db.get_open_tasks()
        open_count = len(open_tasks)
        cursor = await _db._conn.execute(
            "SELECT id, title, status, assigned_to FROM tasks ORDER BY id DESC LIMIT 5"
        )
        rows = await cursor.fetchall()
        recent = [
            {"id": r["id"], "title": r["title"], "status": r["status"], "agent": r["assigned_to"] or ""}
            for r in rows
        ]

    budget = {}
    if _budget_tracker:
        budget = {
            "used": _budget_tracker.used,
            "budget": _budget_tracker.daily_budget,
            "remaining": _budget_tracker.remaining,
        }

    ollama_status = "offline"
    ollama_host = _config_service.get("ollama_host", "http://localhost:11434") if _config_service else "http://localhost:11434"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
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


# ── Schedule endpoints (DB-backed, integer IDs) ─────────────────────

@router.get("/schedules")
async def get_schedules():
    if not _scheduler:
        return {"tasks": []}
    return {"tasks": _scheduler.get_all_tasks_info()}


@router.get("/schedules/{schedule_id}")
async def get_schedule_detail(schedule_id: int):
    if not _db:
        return {"error": "DB not initialized"}
    row = await _db.get_schedule(schedule_id)
    if not row:
        return {"error": f"Schedule {schedule_id} not found"}

    # Add next runs preview
    from backend.scheduler import parse_schedule, get_next_runs
    parsed = parse_schedule(row.get("schedule", ""))
    preview = []
    if parsed.get("type") != "cron":
        runs = get_next_runs(parsed, count=3, active_hours_str=row.get("active_hours"))
        preview = [r.isoformat() for r in runs]

    return {**dict(row), "next_runs_preview": preview}


@router.post("/schedules")
async def create_schedule(data: ScheduleCreate):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    new_id = await _db.create_schedule(
        name=data.name,
        schedule=data.schedule,
        agent_type=data.agent_type,
        prompt=data.prompt,
        active=int(data.active),
        active_hours=data.active_hours,
    )
    await _scheduler.reload_tasks()
    return {"created": True, "id": new_id, "name": data.name}


@router.post("/schedules/ai-create")
async def ai_create_schedule(data: ScheduleAICreate):
    if not _db or not _scheduler or not _flow:
        return {"error": "Not initialized"}

    # Simple schedule creation from description (no LLM meta-extraction)
    name = data.description[:60] or "Neuer Task"
    schedule = "täglich 09:00"
    agent_type = "researcher"

    new_id = await _db.create_schedule(
        name=name,
        schedule=schedule,
        agent_type=agent_type,
        prompt=data.description,
        active=1,
        active_hours=None,
    )
    await _scheduler.reload_tasks()

    return {
        "created": True,
        "id": new_id,
        "name": name,
        "schedule": schedule,
        "agent_type": agent_type,
        "prompt": data.description,
    }


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: int, update: ScheduleUpdate):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    # Build kwargs from non-None fields
    kwargs = {}
    if update.name is not None:
        kwargs["name"] = update.name
    if update.schedule is not None:
        kwargs["schedule"] = update.schedule
    if update.agent_type is not None:
        kwargs["agent_type"] = update.agent_type
    if update.prompt is not None:
        kwargs["prompt"] = update.prompt
    if update.active is not None:
        kwargs["active"] = int(update.active)
    if update.active_hours is not None:
        kwargs["active_hours"] = update.active_hours

    await _db.update_schedule(schedule_id, **kwargs)
    await _scheduler.reload_tasks()
    return {"saved": True, "id": schedule_id}


@router.post("/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    new_state = await _db.toggle_schedule(schedule_id)
    await _scheduler.reload_tasks()
    return {"active": new_state, "id": schedule_id}


@router.post("/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: int):
    if not _scheduler or not _flow:
        return {"error": "Not initialized"}
    # Find task in scheduler's in-memory list
    task = None
    for t in _scheduler.tasks:
        if t["id"] == schedule_id:
            task = t
            break
    if not task:
        return {"error": f"Schedule {schedule_id} not found in scheduler"}
    await _scheduler.mark_run(task)
    asyncio.create_task(_flow.handle_scheduled(task))
    return {"triggered": True, "name": task["name"]}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    if not _db or not _scheduler:
        return {"error": "Not initialized"}
    row = await _db.get_schedule(schedule_id)
    if not row:
        return {"error": f"Schedule {schedule_id} not found"}
    await _db.delete_schedule(schedule_id)
    await _scheduler.reload_tasks()
    return {"deleted": True, "name": row.get("name", "")}


# ── Config endpoints (ConfigService) ────────────────────────────────

@router.get("/config")
async def get_config():
    if not _config_service:
        return {"config": []}
    config_list = _config_service.get_all()
    # Merge Settings (.env) fields — always use .env values as source of truth
    from backend.config import settings as _settings
    existing_map = {c["key"]: i for i, c in enumerate(config_list)}
    settings_fields = {
        "mcp_servers": ("MCP Server (kommagetrennt)", "mcp"),
        "mcp_apple_enabled": ("Apple MCP aktiv", "mcp"),
        "mcp_desktop_commander_enabled": ("Desktop Commander aktiv", "mcp"),
        "mcp_obsidian_enabled": ("Obsidian MCP aktiv", "mcp"),
        "mcp_node_path": ("Node/NPX Pfad", "mcp"),
        "mcp_auto_restart": ("Auto-Restart bei Crash", "mcp"),
        "mcp_health_interval": ("Health-Check Intervall (s)", "mcp"),
        "ollama_num_ctx": ("Kontext-Fenster", "ollama"),
        "ollama_keep_alive": ("Keep Alive", "ollama"),
        "serper_api_key": ("Serper API Key (CrewAI Web Search)", "api_keys"),
        "brave_api_key": ("Brave Search API Key", "api_keys"),
        "cli_provider": ("Premium LLM Provider", "premium"),
        "cli_daily_token_budget": ("Tägliches Token-Budget", "premium"),
    }
    for key, (desc, cat) in settings_fields.items():
        if not hasattr(_settings, key):
            continue
        val = str(getattr(_settings, key))
        entry = {"key": key, "value": val, "category": cat, "description": desc}
        if key in existing_map:
            # Override DB value with .env value if DB value is empty
            idx = existing_map[key]
            if not config_list[idx].get("value"):
                config_list[idx] = entry
        else:
            config_list.append(entry)
    return {"config": config_list}


@router.get("/config/{category}")
async def get_config_category(category: str):
    if not _config_service:
        return {"config": {}}
    return {"config": _config_service.get_category(category)}


@router.put("/config")
async def put_config(data: ConfigBatchUpdate):
    if not _config_service:
        return {"error": "ConfigService not initialized"}
    await _config_service.set_many(data.updates)
    return {"saved": True, "count": len(data.updates)}


@router.post("/restart")
async def restart_server():
    """Restart the server process — exits with code 42 so start.sh restarts."""
    async def _do_restart():
        await asyncio.sleep(0.5)
        os._exit(42)
    asyncio.create_task(_do_restart())
    return {"restarting": True}


# ── Tasks ────────────────────────────────────────────────────────────

@router.get("/tasks")
async def get_tasks(status: str | None = None, agent: str | None = None,
                    search: str | None = None, limit: int = 50, offset: int = 0):
    """Get tasks with optional filters and pagination."""
    tasks = await _db.get_all_tasks(limit=limit, offset=offset, status=status, agent=agent, search=search)
    total = await _db.get_task_count(status=status, agent=agent, search=search)
    return {
        "tasks": [
            {
                "id": t.id, "title": t.title, "description": t.description,
                "status": t.status.value, "agent": t.assigned_to or "",
                "result": t.result or "", "project": t.project or "",
                "created_at": str(t.created_at) if t.created_at else "",
                "updated_at": str(t.updated_at) if t.updated_at else "",
            }
            for t in tasks
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tasks/{task_id}")
async def get_single_task(task_id: int):
    """Get a single task with full result."""
    task = await _db.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    return {
        "id": task.id, "title": task.title, "description": task.description,
        "status": task.status.value, "agent": task.assigned_to or "",
        "result": task.result or "", "project": task.project or "",
        "created_at": str(task.created_at) if task.created_at else "",
        "updated_at": str(task.updated_at) if task.updated_at else "",
    }


@router.patch("/tasks/{task_id}")
async def patch_task(task_id: int, patch: TaskPatch):
    """Manually update task status from dashboard."""
    status = TaskStatus(patch.status)
    updated = await _db.update_task_status_manual(task_id, status)
    return {"updated": updated}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    """Delete a task."""
    deleted = await _db.delete_task(task_id)
    return {"deleted": deleted}


@router.post("/tasks/submit")
async def submit_task(data: TaskSubmit):
    """Submit a new task via admin UI or Siri Shortcut (goes through MainAgent).

    If chat_id is provided (e.g. Telegram chat_id), response goes there.
    Otherwise defaults to "dashboard" for WS push.
    """
    if not _flow:
        return {"error": "Not initialized"}
    chat_id = data.chat_id or "dashboard"
    asyncio.create_task(_flow.handle_message(data.text, chat_id=chat_id))
    return {"submitted": True}


@router.post("/tasks/create")
async def create_task_with_deps(data: TaskCreate):
    """Create a task with optional dependencies. Stays OPEN until deps are met."""
    from backend.models import TaskData, TaskStatus
    task = TaskData(
        title=data.title,
        description=data.description,
        status=TaskStatus.OPEN,
        assigned_to=data.agent_type,
        project=data.project,
        depends_on=data.depends_on,
    )
    task_id = await _db.create_task(task)
    # If no dependencies, dispatch immediately
    if not data.depends_on and _flow:
        asyncio.create_task(_flow.handle_message(data.description))
    return {"task_id": task_id, "depends_on": data.depends_on}


@router.get("/agents/{agent_id}/log")
async def get_agent_log(agent_id: str, limit: int = 50):
    """Get tool execution log for a specific agent."""
    async with _db._conn.execute(
        "SELECT tool_name, input, output, success, created_at FROM tool_log "
        "WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
        (agent_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return {
        "logs": [
            {
                "tool": r["tool_name"],
                "input": (r["input"] or "")[:200],
                "output": (r["output"] or "")[:500],
                "success": bool(r["success"]),
                "time": r["created_at"],
            }
            for r in reversed(list(rows))
        ]
    }


# ── Siri / iOS Shortcuts ─────────────────────────────────────────────

_bot_username_cache: str | None = None


@router.get("/siri-info")
async def get_siri_info():
    global _bot_username_cache
    from backend.config import API_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, PORT
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "localhost"

    # Fetch bot username (cached after first call)
    bot_username = _bot_username_cache or ""
    if not bot_username and TELEGRAM_TOKEN:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe")
                if resp.status_code == 200:
                    bot_username = resp.json().get("result", {}).get("username", "")
                    _bot_username_cache = bot_username
        except Exception:
            pass

    return {
        "api_token": API_TOKEN,
        "server_url": f"http://{local_ip}:{PORT}",
        "telegram_bot_token": TELEGRAM_TOKEN,
        "telegram_chat_id": TELEGRAM_CHAT_ID,
        "telegram_api_url": f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        "bot_username": bot_username,
        "port": PORT,
    }


# ── Memory ───────────────────────────────────────────────────────────

@router.get("/memory")
async def get_memory(layer: str = ""):
    """Get all stored memories (SoulMemory 3-layer system), optionally filtered by layer."""
    if _soul_memory:
        if layer and layer in ("user", "self", "relationship"):
            memories = await _soul_memory.get_by_layer(layer)
        else:
            memories = await _soul_memory.get_all()
        return {
            "memories": [
                {"id": m["id"], "layer": m["layer"], "category": m["category"],
                 "key": m["key"], "value": m["value"], "source": m.get("source", "")}
                for m in memories
            ]
        }
    if _fact_memory:
        facts = await _fact_memory.get_all_active()
        return {
            "memories": [
                {"id": f.id, "layer": "user", "category": f.category,
                 "key": "", "value": f.content, "source": f.source}
                for f in facts
            ]
        }
    return {"memories": []}


class MemoryCreate(BaseModel):
    layer: str = "user"
    category: str = "general"
    key: str = ""
    value: str


@router.post("/memory")
async def create_memory(mem: MemoryCreate):
    """Add a memory entry, deduplicating via upsert."""
    if not _soul_memory:
        return {"error": "Memory not initialized"}
    result = await _soul_memory.upsert(
        layer=mem.layer, category=mem.category,
        key=mem.key, value=mem.value,
    )
    return {"id": result["id"], "action": result["action"], "saved": True}


class MemoryUpdate(BaseModel):
    value: str = None
    category: str = None
    key: str = None


@router.put("/memory/{memory_id}")
async def update_memory(memory_id: int, body: MemoryUpdate):
    """Update an existing memory entry."""
    if not _soul_memory:
        return {"error": "Memory not initialized"}
    await _soul_memory.update(
        memory_id=memory_id,
        new_value=body.value,
        category=body.category,
        key=body.key,
    )
    return {"updated": True, "id": memory_id}


# ── Reminders ────────────────────────────────────────────────────────

class ReminderCreate(BaseModel):
    text: str
    due_at: str
    chat_id: str = "dashboard"
    follow_up: bool = False


@router.get("/reminders")
async def get_reminders():
    """Get all reminders."""
    if not _db or not _db._conn:
        return {"reminders": []}
    cursor = await _db._conn.execute(
        "SELECT id, chat_id, text, due_at, delivered, follow_up, created_at "
        "FROM reminders ORDER BY due_at ASC"
    )
    rows = await cursor.fetchall()
    return {"reminders": [dict(r) for r in rows]}


@router.post("/reminders")
async def create_reminder(rem: ReminderCreate):
    """Create a reminder directly (bypassing chat intent)."""
    if not _scheduler:
        return {"error": "Scheduler not initialized"}
    rid = await _scheduler.add_reminder(
        chat_id=rem.chat_id, text=rem.text,
        due_at=rem.due_at, follow_up=rem.follow_up,
    )
    return {"id": rid, "saved": True}


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int):
    """Delete a reminder."""
    if not _db or not _db._conn:
        return {"error": "DB not initialized"}
    await _db._conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    await _db._conn.commit()
    return {"deleted": True}


# ── LLM Routing ─────────────────────────────────────────────────────

@router.get("/llm-routing")
async def get_llm_routing():
    """LLM routing removed — CrewAI flow handles model selection."""
    return {"routing": {}, "providers": []}


@router.put("/llm-routing")
async def put_llm_routing(update: LLMRoutingUpdate):
    """LLM routing removed — CrewAI flow handles model selection."""
    return {"error": "LLM routing is no longer configurable via this endpoint."}


# ── Tool Log (global) ────────────────────────────────────────────────

@router.get("/tool-log")
async def get_tool_log(agent_id: str | None = None, tool: str | None = None,
                       success: int | None = None, limit: int = 100, offset: int = 0):
    """Global tool execution log with filters."""
    if not _db or not _db._conn:
        return {"logs": [], "total": 0}
    where = []
    params = []
    if agent_id:
        where.append("agent_id = ?")
        params.append(agent_id)
    if tool:
        where.append("tool_name LIKE ?")
        params.append(f"%{tool}%")
    if success is not None:
        where.append("success = ?")
        params.append(success)
    where_str = ("WHERE " + " AND ".join(where)) if where else ""

    count_sql = f"SELECT COUNT(*) FROM tool_log {where_str}"
    cursor = await _db._conn.execute(count_sql, params)
    row = await cursor.fetchone()
    total = row[0] if row else 0

    sql = f"SELECT id, agent_id, tool_name, input, output, success, created_at FROM tool_log {where_str} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    cursor = await _db._conn.execute(sql, params + [limit, offset])
    rows = await cursor.fetchall()
    return {
        "logs": [
            {"id": r["id"], "agent_id": r["agent_id"], "tool": r["tool_name"],
             "input": (r["input"] or "")[:300], "output": (r["output"] or "")[:500],
             "success": bool(r["success"]), "time": r["created_at"]}
            for r in rows
        ],
        "total": total,
    }


# ── System Health ────────────────────────────────────────────────────

@router.get("/health")
async def get_health():
    """System health: Ollama status, uptime, DB stats, WS connections."""
    import httpx

    ollama_host = _config_service.get("ollama_host", "http://localhost:11434") if _config_service else "http://localhost:11434"
    ollama_info = {"status": "offline", "models": []}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                ollama_info["status"] = "online"
                ollama_info["models"] = [
                    {"name": m["name"], "size": m.get("size", 0),
                     "modified": m.get("modified_at", "")}
                    for m in data.get("models", [])
                ]
    except Exception:
        pass

    db_stats = {}
    if _db and _db._conn:
        for table in ["tasks", "tool_log", "messages", "memories", "schedules"]:
            try:
                cursor = await _db._conn.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cursor.fetchone()
                db_stats[table] = row[0] if row else 0
            except Exception:
                db_stats[table] = -1

    budget = {}
    if _budget_tracker:
        budget = {"used": _budget_tracker.used, "budget": _budget_tracker.daily_budget, "remaining": _budget_tracker.remaining}

    return {
        "uptime_seconds": int(time.time() - _start_time) if _start_time else 0,
        "ollama": ollama_info,
        "db_stats": db_stats,
        "budget": budget,
    }


# ── Obsidian Preview ─────────────────────────────────────────────────

@router.get("/obsidian/recent")
async def get_obsidian_recent(limit: int = 20):
    """Get recently modified Obsidian notes."""
    vault = _config_service.get_path("obsidian_vault_path") if _config_service else None
    if not vault or not vault.exists():
        return {"notes": [], "vault_path": str(vault or "")}

    md_files = []
    for f in vault.rglob("*.md"):
        if ".obsidian" in str(f) or ".trash" in str(f):
            continue
        try:
            stat = f.stat()
            rel = str(f.relative_to(vault))
            md_files.append({"path": rel, "modified": stat.st_mtime, "size": stat.st_size})
        except Exception:
            continue

    md_files.sort(key=lambda x: x["modified"], reverse=True)
    return {"notes": md_files[:limit], "vault_path": str(vault)}


@router.get("/obsidian/note")
async def get_obsidian_note(path: str):
    """Read a single Obsidian note content."""
    vault = _config_service.get_path("obsidian_vault_path") if _config_service else None
    if not vault:
        return {"error": "Vault not configured"}

    full_path = (vault / path).resolve()
    # Security: ensure path is within vault
    if not str(full_path).startswith(str(vault.resolve())):
        return {"error": "Access denied"}
    if not full_path.exists() or not full_path.is_file():
        return {"error": "Note not found"}

    try:
        content = full_path.read_text(encoding="utf-8")
        return {"path": path, "content": content}
    except Exception as e:
        return {"error": str(e)}


# ── Memory (delete) ──────────────────────────────────────────────────

@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: int):
    """Delete a memory fact."""
    if not _db or not _db._conn:
        return {"error": "DB not initialized"}
    await _db._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    await _db._conn.commit()
    return {"deleted": True}


# ── File Browser ─────────────────────────────────────────────────────

@router.get("/files")
async def list_files(path: str = ""):
    """List files and directories in workspace."""
    workspace = _config_service.get_path("workspace_path") if _config_service else None
    if not workspace:
        return {"error": "Workspace not configured", "items": []}

    workspace = workspace.resolve()
    target = (workspace / path).resolve()

    if not str(target).startswith(str(workspace)):
        return {"error": "Access denied"}
    if not target.exists():
        return {"error": "Path not found", "items": []}

    items = []
    if target.is_dir():
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith("."):
                continue
            try:
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry.relative_to(workspace)),
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if entry.is_file() else 0,
                    "modified": stat.st_mtime,
                })
            except Exception:
                continue

    return {"items": items, "current": path, "workspace": str(workspace)}


@router.get("/files/read")
async def read_file(path: str):
    """Read file content from workspace."""
    workspace = _config_service.get_path("workspace_path") if _config_service else None
    if not workspace:
        return {"error": "Workspace not configured"}

    workspace = workspace.resolve()
    full = (workspace / path).resolve()

    if not str(full).startswith(str(workspace)):
        return {"error": "Access denied"}
    if not full.exists() or not full.is_file():
        return {"error": "File not found"}

    try:
        content = full.read_text(encoding="utf-8", errors="replace")
        return {"path": path, "content": content, "size": full.stat().st_size}
    except Exception as e:
        return {"error": str(e)}


# ── Ollama Model Browser ──────────────────────────────────────────────

class OllamaPullRequest(BaseModel):
    model: str


@router.get("/ollama/models")
async def list_ollama_models():
    """List all locally available Ollama models."""
    import httpx
    ollama_host = "http://localhost:11434"
    if _config_service:
        saved = _config_service.get("ollama_host")
        if saved:
            ollama_host = saved
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", ""),
                    "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "modified_at": m.get("modified_at", ""),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                })
            return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}


@router.post("/ollama/pull")
async def pull_ollama_model(req: OllamaPullRequest):
    """Pull an Ollama model. Returns SSE stream of progress."""
    import httpx
    from fastapi.responses import StreamingResponse

    ollama_host = "http://localhost:11434"
    if _config_service:
        saved = _config_service.get("ollama_host")
        if saved:
            ollama_host = saved

    async def stream_pull():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream(
                    "POST",
                    f"{ollama_host}/api/pull",
                    json={"name": req.model, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line:
                            yield f"data: {line}\n\n"
            yield 'data: {"status": "success"}\n\n'
        except Exception as e:
            import json as _json
            yield f"data: {_json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream_pull(), media_type="text/event-stream")


@router.delete("/ollama/models/{model_name:path}")
async def delete_ollama_model(model_name: str):
    """Delete a local Ollama model."""
    import httpx
    ollama_host = "http://localhost:11434"
    if _config_service:
        saved = _config_service.get("ollama_host")
        if saved:
            ollama_host = saved
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                "DELETE",
                f"{ollama_host}/api/delete",
                json={"name": model_name},
            )
            if resp.status_code == 200:
                return {"status": "deleted", "model": model_name}
            return {"status": "error", "detail": resp.text}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── Chat History ─────────────────────────────────────────────────────

@router.get("/chat-history")
async def get_chat_history(limit: int = 50):
    """Get recent chat messages."""
    if not _db or not _db._conn:
        return {"messages": []}
    cursor = await _db._conn.execute(
        "SELECT id, role, content, created_at FROM chat_history ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    rows = await cursor.fetchall()
    return {
        "messages": [
            {"id": r["id"], "role": r["role"], "content": r["content"], "time": r["created_at"]}
            for r in reversed(list(rows))
        ]
    }


# ── System Monitor ────────────────────────────────────────────────────

@router.get("/system/metrics")
async def get_system_metrics():
    """Return current system resource metrics (CPU, RAM, GPU, Temp, Watts)."""
    if _system_monitor is None:
        return {"error": "SystemMonitor not initialized"}
    return _system_monitor.get_metrics()


# ── Update ────────────────────────────────────────────────────────────

@router.post("/update")
async def update_server():
    """Run git pull + pip install and stream output via SSE. No restart is triggered."""
    import json as _json
    from pathlib import Path as _Path
    from fastapi.responses import StreamingResponse

    project_root = _Path(__file__).parent.parent

    async def _run_cmd(cmd: list, cwd: str):
        """Run a command and yield output lines. Cleans up subprocess on any exit path."""
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for raw_line in proc.stdout:
                yield raw_line.decode("utf-8", errors="replace").rstrip()
            await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"exit {proc.returncode}")
        except Exception:
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            raise

    async def stream_update():
        import sys as _sys

        # Find the right pip: prefer venv312, fallback to current executable
        venv312_pip = project_root / "venv312" / "bin" / "pip"
        if venv312_pip.exists():
            pip_cmd = [str(venv312_pip), "install", "-r", "requirements.txt"]
        else:
            pip_cmd = [_sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]

        try:
            # Step 1: git pull
            yield f"data: {_json.dumps({'line': '$ git pull'})}\n\n"
            try:
                async for line in _run_cmd(["git", "pull"], str(project_root)):
                    yield f"data: {_json.dumps({'line': line})}\n\n"
            except RuntimeError as e:
                yield f"data: {_json.dumps({'status': 'error', 'line': f'git pull fehlgeschlagen ({e})'})}\n\n"
                return
            except Exception as e:
                yield f"data: {_json.dumps({'status': 'error', 'line': str(e)})}\n\n"
                return

            # Step 2: pip install (uses venv312 if available)
            yield f"data: {_json.dumps({'line': '$ ' + ' '.join(pip_cmd)})}\n\n"
            try:
                async for line in _run_cmd(pip_cmd, str(project_root)):
                    yield f"data: {_json.dumps({'line': line})}\n\n"
            except RuntimeError as e:
                yield f"data: {_json.dumps({'status': 'error', 'line': f'pip install fehlgeschlagen ({e})'})}\n\n"
                return
            except Exception as e:
                yield f"data: {_json.dumps({'status': 'error', 'line': str(e)})}\n\n"
                return

            yield f"data: {_json.dumps({'status': 'done'})}\n\n"
        except GeneratorExit:
            pass  # Client disconnected — subprocess already cleaned up by _run_cmd

    return StreamingResponse(stream_update(), media_type="text/event-stream")


# ── MCP Server Management ──────────────────────────────────────────────────

@router.get("/mcp/servers")
async def list_mcp_servers():
    if _mcp_bridge is None:
        return {"servers": [], "bridge_initialized": False}
    try:
        servers = []
        for s in _mcp_bridge.servers:
            try:
                servers.append({
                    "id": s.config.id,
                    "name": s.config.name,
                    "command": s.config.command,
                    "enabled": s.config.enabled,
                    "status": s.status,
                    "pid": s.pid,
                    "tools_count": s.tools_count,
                    "last_call": str(s.last_call) if s.last_call else None,
                    "uptime_seconds": s.uptime_seconds,
                    "last_error": s.last_error,
                })
            except Exception as e:
                servers.append({
                    "id": getattr(s.config, "id", "unknown"),
                    "name": getattr(s.config, "name", "unknown"),
                    "command": getattr(s.config, "command", ""),
                    "enabled": False,
                    "status": "error",
                    "pid": None,
                    "tools_count": 0,
                    "last_call": None,
                    "uptime_seconds": 0,
                    "last_error": f"Serialization error: {e}",
                })
        return {"bridge_initialized": True, "servers": servers}
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("list_mcp_servers error: %s", e, exc_info=True)
        return {"bridge_initialized": True, "servers": [], "error": str(e)}

@router.get("/mcp/servers/{server_id}/tools")
async def get_mcp_server_tools(server_id: str):
    if _mcp_bridge is None:
        return []
    tools = await _mcp_bridge.list_tools(server_id)
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]

@router.post("/mcp/servers/{server_id}/restart")
async def restart_mcp_server(server_id: str):
    if _mcp_bridge is None:
        return {"error": "MCP not initialized"}
    await _mcp_bridge.restart_server(server_id)
    return {"status": "restarted", "server_id": server_id}

@router.post("/mcp/servers/{server_id}/toggle")
async def toggle_mcp_server(server_id: str, body: dict):
    if _mcp_bridge is None:
        return {"error": "MCP not initialized"}
    enabled = body.get("enabled", True)
    await _mcp_bridge.toggle_server(server_id, enabled)
    return {"status": "toggled", "server_id": server_id, "enabled": enabled}

@router.get("/mcp/servers/{server_id}/logs")
async def get_mcp_server_logs(server_id: str, limit: int = 50):
    if _db is None:
        return []
    return await _db.get_mcp_calls(limit=limit, server_id=server_id)
