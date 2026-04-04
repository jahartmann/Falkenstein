import asyncio
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
_main_agent = None
_budget_tracker = None
_llm_router = None
_fact_memory = None


def set_dependencies(db=None, scheduler=None, config_service=None,
                     main_agent=None, budget_tracker=None, llm_router=None,
                     fact_memory=None):
    global _db, _scheduler, _config_service, _main_agent, _budget_tracker, _llm_router, _fact_memory
    _db = db; _scheduler = scheduler; _config_service = config_service
    _main_agent = main_agent; _budget_tracker = budget_tracker; _llm_router = llm_router
    _fact_memory = fact_memory


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
    if _main_agent:
        active = _main_agent.get_status().get("active_agents", [])

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
    if not _db or not _scheduler or not _main_agent:
        return {"error": "Not initialized"}

    # LLM enrichment in parallel
    meta, enriched = await asyncio.gather(
        _main_agent._extract_schedule_meta(data.description),
        _main_agent._enrich_prompt(data.description),
    )

    name = meta.get("name", "Neuer Task")
    schedule = meta.get("schedule", "täglich 09:00")
    agent_type = meta.get("agent", "researcher")
    active_hours = meta.get("active_hours", None) or None

    new_id = await _db.create_schedule(
        name=name,
        schedule=schedule,
        agent_type=agent_type,
        prompt=enriched,
        active=1,
        active_hours=active_hours,
    )
    await _scheduler.reload_tasks()

    return {
        "created": True,
        "id": new_id,
        "name": name,
        "schedule": schedule,
        "agent_type": agent_type,
        "prompt": enriched,
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
    if not _scheduler or not _main_agent:
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
    asyncio.create_task(_main_agent.handle_scheduled(task))
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
    return {"config": _config_service.get_all()}


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
    """Submit a new task via the admin UI (goes through MainAgent)."""
    if not _main_agent:
        return {"error": "Not initialized"}
    asyncio.create_task(_main_agent.handle_message(data.text))
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
    if not data.depends_on and _main_agent:
        asyncio.create_task(_main_agent.handle_message(data.description))
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


# ── Memory ───────────────────────────────────────────────────────────

@router.get("/memory")
async def get_memory():
    """Get all stored facts from Falki's memory."""
    if not _fact_memory:
        return {"facts": []}
    facts = await _fact_memory.get_all_active()
    return {
        "facts": [
            {"id": f.id, "category": f.category, "content": f.content, "source": f.source}
            for f in facts
        ]
    }


# ── LLM Routing ─────────────────────────────────────────────────────

@router.get("/llm-routing")
async def get_llm_routing():
    """Get current LLM routing configuration."""
    if not _llm_router:
        return {"routing": {}, "providers": []}
    from backend.llm_router import PROVIDERS
    return {"routing": _llm_router.get_routing(), "providers": list(PROVIDERS)}


@router.put("/llm-routing")
async def put_llm_routing(update: LLMRoutingUpdate):
    """Update LLM routing configuration."""
    if not _llm_router:
        return {"error": "Router not initialized"}
    from backend.llm_router import PROVIDERS
    for task_type, provider in update.routing.items():
        if provider not in PROVIDERS:
            return {"error": f"Unbekannter Provider: {provider}. Erlaubt: {PROVIDERS}"}
        _llm_router.set_routing(task_type, provider)
    return {"saved": True, "routing": _llm_router.get_routing()}
