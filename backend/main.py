import asyncio
import logging
import time as _time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.config import DB_PATH, PORT, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ALLOWED_CHAT_IDS, API_TOKEN, settings
from backend.native_ollama import NativeOllamaClient
from backend.event_bus import FalkensteinEventBus
from backend.vault_index import VaultIndex
from backend.flow.falkenstein_flow import FalkensteinFlow
from backend.tools.crewai_wrappers import (
    CodeExecutorTool as CrewCodeExecutorTool, ShellRunnerTool as CrewShellRunnerTool,
    SystemShellTool as CrewSystemShellTool,
    ObsidianTool, OllamaManagerTool as CrewOllamaManagerTool,
    SelfConfigTool as CrewSelfConfigTool, OpsExecutorTool,
)
from fastapi.middleware.cors import CORSMiddleware
from backend.security.auth import BearerAuthMiddleware
from backend.security.telegram_allowlist import TelegramAllowlist
from backend.config_service import ConfigService
from backend.admin_api import router as admin_router, mcp_router
from backend.workspace_api import router as workspace_router
from backend import admin_api
from backend.database import Database
from backend.ws_manager import WSManager
from backend.telegram_bot import TelegramBot
from backend.obsidian_writer import ObsidianWriter
from backend.smart_scheduler import SmartScheduler
from backend.memory.soul_memory import SoulMemory
from backend.tools.base import ToolRegistry
from backend.tools.shell_runner import ShellRunnerTool
from backend.tools.code_executor import CodeExecutorTool
from backend.tools.obsidian_manager import ObsidianManagerTool
from backend.tools.system_shell import SystemShellTool
from backend.tools.ollama_manager import OllamaManagerTool
from backend.tools.self_config import SelfConfigTool
from backend.tools.ops_executor import OpsExecutor
from backend.memory.fact_memory import FactMemory
from backend.system_monitor import SystemMonitor
from backend.mcp import MCPBridge, MCPRegistry, create_all_mcp_tools
from backend.mcp.permissions import PermissionResolver
from backend.mcp.approvals import ApprovalStore
from backend.telegram_runtime import TelegramJobManager, TelegramResponseCache

log = logging.getLogger(__name__)

db: Database = None
fact_memory: FactMemory = None
soul_memory: SoulMemory = None
ws_mgr = WSManager()
telegram: TelegramBot = None
flow: FalkensteinFlow = None
budget_tracker = None
telegram_task: asyncio.Task = None
scheduler: SmartScheduler = None
telegram_jobs: TelegramJobManager = None
telegram_cache: TelegramResponseCache = None

# External agents (Claude Code subagents etc.) — TTL-based, auto-expire after 60s
_external_agents: dict[str, dict] = {}


class ExternalAgentIn(BaseModel):
    id: str
    name: str = ""
    type: str = "external"  # coder, researcher, writer, ops, external
    task: str = ""


async def handle_telegram_message(msg: dict):
    """All Telegram messages go through FalkensteinFlow.
    For quick_reply: result is returned directly, we send it here.
    For crews: EventBus sends Telegram messages during lifecycle."""
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat_id", "")

    async def _send_result(result: str):
        """Send flow result to Telegram if EventBus didn't already."""
        if result and telegram and telegram.enabled and chat_id:
            await telegram.send_message(result, chat_id=chat_id)

    async def _send_job_ack(job_id: str):
        if telegram and telegram.enabled and chat_id:
            await telegram.send_message(
                f"🧾 Job {job_id} angenommen.\nIch melde Fortschritt und Ergebnis hier.",
                chat_id=chat_id,
            )

    async def _run_background(
        message_text: str, *, image_path: str | None = None, job_id: str | None = None,
    ):
        try:
            await flow.handle_message(
                message_text, chat_id=chat_id, image_path=image_path, job_id=job_id,
            )
        except Exception as e:
            logging.getLogger(__name__).error("Background flow error: %s", e, exc_info=True)
            if telegram_jobs and job_id:
                telegram_jobs.complete(job_id, status="error", result_preview=str(e))
            if telegram and telegram.enabled and chat_id:
                if job_id:
                    await telegram.send_message(f"❌ Job {job_id} Fehler: {e}", chat_id=chat_id)
                else:
                    await telegram.send_message(f"Fehler: {e}", chat_id=chat_id)

    async def _handle_user_text(message_text: str, *, image_path: str | None = None):
        route = flow.rule_engine.route(message_text)
        if image_path is not None or route.action not in ("quick_reply", "direct_mcp"):
            job = telegram_jobs.create_job(chat_id, message_text or "[media]", route.action) if telegram_jobs else None
            if job:
                await _send_job_ack(job.id)
            asyncio.create_task(_run_background(message_text, image_path=image_path, job_id=job.id if job else None))
            return

        if route.action == "quick_reply" and telegram_cache:
            cached = telegram_cache.get(message_text)
            if cached is not None:
                await _send_result(cached)
                return

        result = await flow.handle_message(message_text, chat_id=chat_id)
        if route.action == "quick_reply" and telegram_cache and result:
            telegram_cache.set(message_text, result)
        await _send_result(result)

    try:
        # Voice message → transcribe with Whisper, then process as text
        voice_path = msg.get("voice_path")
        if voice_path:
            from backend.stt import transcribe
            if telegram and telegram.enabled:
                await telegram.send_message("Transkribiere...", chat_id=chat_id or None)
            transcribed = await transcribe(voice_path)
            if transcribed:
                full_text = f"{text} {transcribed}".strip() if text else transcribed
                await _handle_user_text(full_text)
            else:
                if telegram and telegram.enabled:
                    await telegram.send_message(
                        "Konnte die Sprachnachricht nicht verstehen.", chat_id=chat_id or None,
                    )
            return

        # Image → analyze with vision
        image_path = msg.get("image_path")
        if image_path:
            await _handle_user_text(text, image_path=image_path)
            return

        # Regular text
        if text:
            await _handle_user_text(text)

    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Telegram handler error: %s", e, exc_info=True)
        if telegram and telegram.enabled and chat_id:
            await telegram.send_message(f"Fehler: {e}", chat_id=chat_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, telegram, telegram_task, flow, budget_tracker, scheduler, fact_memory, soul_memory, telegram_jobs, telegram_cache

    # 1. Database
    db = Database(DB_PATH)
    await db.init()

    # 2. ConfigService (DB-backed config)
    config_service = ConfigService(db)
    await config_service.init()

    # 3. Soul Memory (+ legacy fact migration)
    soul_memory = SoulMemory(db)
    await soul_memory.init()

    try:
        fact_memory = FactMemory(db)
        await fact_memory.init()
        if await fact_memory.count() > 0:
            migrated = await soul_memory.migrate_from_facts(fact_memory)
            if migrated:
                print(f"Migrated {migrated} facts to SoulMemory")
    except Exception:
        fact_memory = None

    # System Monitor
    system_monitor = SystemMonitor()
    await system_monitor.start()

    # 5. Paths from config
    def _cfg(key: str, fallback: str = "") -> str:
        value = config_service.get(key, fallback)
        return value if value not in (None, "") else fallback

    vault_path = config_service.get_path("obsidian_vault_path", str(settings.obsidian_vault_path))
    workspace = config_service.get_path("workspace_path", str(settings.workspace_path))
    workspace.mkdir(parents=True, exist_ok=True)

    telegram_token = _cfg("telegram_bot_token", TELEGRAM_TOKEN)
    telegram_chat_id = _cfg("telegram_chat_id", TELEGRAM_CHAT_ID)
    telegram_allowed_chat_ids = _cfg("telegram_allowed_chat_ids", TELEGRAM_ALLOWED_CHAT_IDS)

    ollama_host = _cfg("ollama_host", settings.ollama_host)
    ollama_model = _cfg("ollama_model", settings.ollama_model)
    ollama_model_light = _cfg("ollama_model_light", settings.ollama_model_light) or ollama_model
    ollama_model_heavy = _cfg("ollama_model_heavy", settings.ollama_model_heavy) or ollama_model
    ollama_keep_alive = _cfg("ollama_keep_alive", settings.ollama_keep_alive)

    # 6. Telegram + Allowlist
    allowlist = TelegramAllowlist(
        owner_chat_id=telegram_chat_id,
        allowed_ids_csv=telegram_allowed_chat_ids,
    )
    media_dir = workspace / "_media"
    media_dir.mkdir(parents=True, exist_ok=True)
    telegram = TelegramBot(
        token=telegram_token, chat_id=telegram_chat_id,
        allowlist=allowlist, download_dir=media_dir,
    )

    # 7. Scheduler (DB-backed, smart)
    scheduler = SmartScheduler(db)

    # ── NEW: FalkensteinFlow replaces MainAgent ──

    # Native Ollama Client
    native_ollama = NativeOllamaClient(
        host=ollama_host,
        model_light=ollama_model_light,
        model_heavy=ollama_model_heavy,
        keep_alive=ollama_keep_alive,
    )

    # VaultIndex
    vault_index = None
    if vault_path:
        try:
            vault_path.mkdir(parents=True, exist_ok=True)
            vault_index = VaultIndex(vault_path)
            vault_index.scan()
        except Exception as e:
            log.warning("Vault index init failed for %s: %s", vault_path, e)

    # EventBus
    telegram_jobs = TelegramJobManager()
    telegram_cache = TelegramResponseCache()
    event_bus = FalkensteinEventBus(
        ws_manager=ws_mgr,
        telegram_bot=telegram,
        db=db,
        telegram_jobs=telegram_jobs,
    )

    # ── MCP Bridge ────────────────────────────────────────────────────
    mcp_registry = MCPRegistry()
    # One-shot migration of legacy .env MCP flags (idempotent)
    await mcp_registry.migrate_from_env(db, legacy_flags={
        "mcp_apple_enabled": settings.mcp_apple_enabled,
        "mcp_desktop_commander_enabled": settings.mcp_desktop_commander_enabled,
        "mcp_obsidian_enabled": settings.mcp_obsidian_enabled,
    })
    await mcp_registry.load_from_db(db)

    mcp_bridge = MCPBridge(mcp_registry)
    permission_resolver = PermissionResolver(db)
    approval_timeout = config_service.get_int("mcp_approval_timeout_seconds", 600)
    approval_store = ApprovalStore(
        telegram_bot=telegram, ws_manager=ws_mgr, db=db,
        timeout_seconds=approval_timeout,
    )
    telegram.approval_store = approval_store
    mcp_bridge.attach_policy(resolver=permission_resolver, approval_store=approval_store)

    try:
        await mcp_bridge.start()
        installed_count = sum(
            1 for s in mcp_registry.list_servers()
            if mcp_registry.is_installed(s.config.id)
        )
        log.info("MCP Bridge started (%d installed servers)", installed_count)
    except Exception as e:
        log.warning("MCP Bridge start failed (non-fatal): %s", e)

    # CrewAI Tool instances (wrappers around existing tool executors)
    code_exec_tool = CrewCodeExecutorTool()
    shell_tool = CrewShellRunnerTool()
    sys_shell_tool = CrewSystemShellTool()
    obsidian_tool = ObsidianTool()
    ollama_mgr_tool = CrewOllamaManagerTool()
    self_config_tool = CrewSelfConfigTool()
    ops_exec_tool = OpsExecutorTool()

    project_root = Path(__file__).parent.parent
    code_exec_tool.set_executor(CodeExecutorTool(workspace))
    shell_tool.set_executor(ShellRunnerTool(workspace))
    sys_shell_tool.set_executor(SystemShellTool())
    obsidian_tool.set_executor(ObsidianManagerTool(vault_path))
    ollama_mgr_tool.set_executor(OllamaManagerTool())
    self_config_tool.set_executor(SelfConfigTool(project_root))
    ops_exec_tool.set_executor(OpsExecutor(project_root))

    # Tool sets per crew type
    crew_tools = {
        "coder": [code_exec_tool, shell_tool],
        "researcher": [obsidian_tool],
        "writer": [obsidian_tool],
        "ops": [ollama_mgr_tool, self_config_tool, sys_shell_tool],
        "web_design": [shell_tool],
        "swift": [shell_tool, code_exec_tool],
        "ki_expert": [shell_tool, code_exec_tool, ollama_mgr_tool],
        "analyst": [code_exec_tool],
        "premium": [],
    }

    # ── MCP Tools for CrewAI ──────────────────────────────────────────
    try:
        mcp_tool_schemas = await mcp_bridge.discover_tools()
        mcp_crewai_tools = create_all_mcp_tools(mcp_tool_schemas, mcp_bridge)

        mcp_general_tools = [t for t in mcp_crewai_tools
                             if any(k in t.name for k in ("reminder", "calendar", "event", "music", "homekit", "note"))]
        mcp_desktop_tools = [t for t in mcp_crewai_tools if "desktop" in t.name]
        mcp_obsidian_tools = [t for t in mcp_crewai_tools if "obsidian" in t.name]

        for crew_type in crew_tools:
            crew_tools[crew_type] = crew_tools[crew_type] + mcp_general_tools
        crew_tools["ops"] = crew_tools["ops"] + mcp_desktop_tools
        crew_tools["coder"] = crew_tools["coder"] + mcp_desktop_tools
        crew_tools["researcher"] = crew_tools["researcher"] + mcp_obsidian_tools
        crew_tools["writer"] = crew_tools["writer"] + mcp_obsidian_tools
        log.info("Added %d MCP tools to crews", len(mcp_crewai_tools))
    except Exception as e:
        log.warning("MCP tool discovery failed (non-fatal): %s", e)

    # FalkensteinFlow
    flow = FalkensteinFlow(
        event_bus=event_bus,
        native_ollama=native_ollama,
        vault_index=vault_index,
        settings=settings,
        tools=crew_tools,
        mcp_bridge=mcp_bridge,
    )

    app.state.flow = flow
    app.state.event_bus = event_bus

    # 11. Wire admin API
    admin_api.set_dependencies(
        db=db, scheduler=scheduler, config_service=config_service,
        flow=flow,
        fact_memory=fact_memory,
        soul_memory=soul_memory, system_monitor=system_monitor,
        mcp_bridge=mcp_bridge,
        permission_resolver=permission_resolver,
        approval_store=approval_store,
    )
    admin_api.init(start_time=_time.time())

    # 12. Start Scheduler with reminder/step handlers
    async def handle_reminder(reminder):
        text = f"Erinnerung: {reminder['text']}"
        # Broadcast to dashboard
        await ws_mgr.broadcast({
            "type": "chat_reply", "role": "assistant",
            "content": text, "chat_id": reminder.get("chat_id", "dashboard"),
        })
        await db.append_chat(reminder.get("chat_id") or "default", "assistant", text)
        # Send via Telegram (use stored chat_id only if it's a numeric Telegram ID)
        if telegram and telegram.enabled:
            tg_chat_id = reminder.get('chat_id')
            if tg_chat_id and not tg_chat_id.lstrip('-').isdigit():
                tg_chat_id = None  # fall back to default Telegram chat_id
            await telegram.send_message(text, chat_id=tg_chat_id)
            if reminder.get('follow_up'):
                await telegram.send_message("Soll ich dazu was machen?", chat_id=tg_chat_id)

    async def handle_step(step):
        await flow.handle_message(
            step['agent_prompt'], chat_id=step.get('chat_id', ''),
        )

    await scheduler.start(
        on_task_due=flow.handle_scheduled,
        on_reminder_due=handle_reminder,
        on_step_due=handle_step,
    )
    print("Scheduler active")

    # 12. Start Telegram polling (if enabled)
    if telegram.enabled:
        telegram.on_message(handle_telegram_message)
        telegram_task = asyncio.create_task(telegram.poll_loop())
        print("Telegram bot active")

    print(f"Falki running on port {PORT}")
    yield

    # Shutdown
    await mcp_bridge.stop()
    if telegram_task:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass
    if scheduler:
        await scheduler.stop()
    await system_monitor.stop()
    await db.close()


app = FastAPI(title="Falkenstein", lifespan=lifespan)
app.add_middleware(BearerAuthMiddleware, api_token=API_TOKEN)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(admin_router)
app.include_router(mcp_router)
app.include_router(workspace_router)

frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/office")
async def office():
    office_path = frontend_dir / "office.html"
    if office_path.exists():
        return FileResponse(office_path)
    return {"error": "office.html not found"}


@app.get("/")
async def index():
    # Prefer command-center.html, fall back to dashboard.html
    cc_path = frontend_dir / "command-center.html"
    if cc_path.exists():
        return FileResponse(cc_path)
    dashboard_path = frontend_dir / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path)
    return {"status": "Falkenstein running"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    status = {"active_agents": []}  # Flow uses EventBus for live updates
    await ws.send_json({"type": "full_state", **status})
    try:
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data, ws)
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)


async def handle_ws_message(data: dict, ws: WebSocket):
    msg_type = data.get("type", "")
    if msg_type == "submit_task":
        text = data.get("description", data.get("title", ""))
        if text:
            await flow.handle_message(text)
    elif msg_type == "get_state":
        status = {"active_agents": []}  # Flow uses EventBus for live updates
        await ws.send_json({"type": "state_update", **status})


@app.post("/api/task")
async def create_task(title: str, description: str = ""):
    await flow.handle_message(description or title)
    return {"status": "submitted"}


@app.get("/api/agents")
async def get_agents():
    return {"active_agents": []}


@app.get("/api/tasks")
async def get_tasks():
    open_tasks = await db.get_open_tasks()
    return [t.model_dump() for t in open_tasks]


@app.get("/api/status")
async def get_status():
    status = {"active_agents": []}  # Flow uses EventBus for live updates
    if budget_tracker:
        status["budget"] = {
            "used": budget_tracker.used,
            "budget": budget_tracker.daily_budget,
            "remaining": budget_tracker.remaining,
        }
    return status


@app.get("/api/budget")
async def get_budget():
    if not budget_tracker:
        return {"error": "not initialized"}
    return {
        "used": budget_tracker.used,
        "budget": budget_tracker.daily_budget,
        "remaining": budget_tracker.remaining,
    }


@app.post("/api/agents/external")
async def register_external_agent(agent: ExternalAgentIn):
    """Register or heartbeat an external agent (Claude Code, etc.). TTL=60s."""
    _external_agents[agent.id] = {
        "id": agent.id,
        "name": agent.name,
        "type": agent.type,
        "task": agent.task,
        "ts": _time.time(),
    }
    # Broadcast to WS clients
    if ws_mgr:
        await ws_mgr.broadcast({
            "type": "agent_spawned",
            "agent_id": agent.id,
            "agent_type": agent.type,
            "task": agent.task or agent.name,
        })
    return {"status": "ok"}


@app.delete("/api/agents/external/{agent_id}")
async def unregister_external_agent(agent_id: str):
    """Remove an external agent."""
    _external_agents.pop(agent_id, None)
    if ws_mgr:
        await ws_mgr.broadcast({"type": "agent_done", "agent_id": agent_id})
    return {"status": "ok"}


@app.get("/api/agents/external")
async def get_external_agents():
    """Get active external agents, pruning expired ones (TTL 60s)."""
    now = _time.time()
    expired = [k for k, v in _external_agents.items() if now - v["ts"] > 60]
    for k in expired:
        _external_agents.pop(k, None)
    return {"agents": list(_external_agents.values())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=PORT)
