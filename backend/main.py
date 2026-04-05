import asyncio
import time as _time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.config import DB_PATH, PORT, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ALLOWED_CHAT_IDS, API_TOKEN
from fastapi.middleware.cors import CORSMiddleware
from backend.security.auth import BearerAuthMiddleware
from backend.security.telegram_allowlist import TelegramAllowlist
from backend.config_service import ConfigService
from backend.admin_api import router as admin_router
from backend import admin_api
from backend.database import Database
from backend.llm_client import LLMClient
from backend.ws_manager import WSManager
from backend.telegram_bot import TelegramBot
from backend.main_agent import MainAgent
from backend.obsidian_writer import ObsidianWriter
from backend.smart_scheduler import SmartScheduler
from backend.memory.soul_memory import SoulMemory
from backend.review_gate import ReviewGate
from backend.intent_engine import IntentEngine
from backend.tools.base import ToolRegistry
from backend.tools.file_manager import FileManagerTool
from backend.tools.web_surfer import WebSurferTool
from backend.tools.shell_runner import ShellRunnerTool
from backend.tools.code_executor import CodeExecutorTool
from backend.tools.obsidian_manager import ObsidianManagerTool
from backend.tools.cli_bridge import CLIBridgeTool, CLIBudgetTracker
from backend.tools.vision import VisionTool
from backend.tools.system_shell import SystemShellTool
from backend.tools.ollama_manager import OllamaManagerTool
from backend.tools.self_config import SelfConfigTool
from backend.tools.ops_executor import OpsExecutor
from backend.memory.fact_memory import FactMemory
from backend.llm_router import LLMRouter

db: Database = None
fact_memory: FactMemory = None
soul_memory: SoulMemory = None
ws_mgr = WSManager()
telegram: TelegramBot = None
main_agent: MainAgent = None
budget_tracker: CLIBudgetTracker = None
llm_router: LLMRouter = None
telegram_task: asyncio.Task = None
scheduler: SmartScheduler = None

# External agents (Claude Code subagents etc.) — TTL-based, auto-expire after 60s
_external_agents: dict[str, dict] = {}


class ExternalAgentIn(BaseModel):
    id: str
    name: str = ""
    type: str = "external"  # coder, researcher, writer, ops, external
    task: str = ""


async def handle_telegram_message(msg: dict):
    """All Telegram messages go through MainAgent — including /commands, voice, images."""
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat_id", "")

    # Voice message → transcribe with Whisper, then process as text
    voice_path = msg.get("voice_path")
    if voice_path:
        from backend.stt import transcribe
        if telegram and telegram.enabled:
            await telegram.send_message("Transkribiere...", chat_id=chat_id or None)
        transcribed = await transcribe(voice_path)
        if transcribed:
            # Combine with any caption
            full_text = f"{text} {transcribed}".strip() if text else transcribed
            await main_agent.handle_message(full_text, chat_id=chat_id)
        else:
            if telegram and telegram.enabled:
                await telegram.send_message(
                    "Konnte die Sprachnachricht nicht verstehen.", chat_id=chat_id or None,
                )
        return

    # Image → analyze with vision
    image_path = msg.get("image_path")
    if image_path:
        await main_agent.handle_message(text, chat_id=chat_id, image_path=image_path)
        return

    # Regular text
    if text:
        await main_agent.handle_message(text, chat_id=chat_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, telegram, telegram_task, main_agent, budget_tracker, scheduler, fact_memory, soul_memory, llm_router

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

    # 4. LLM + Router (config from ConfigService)
    llm_config = config_service.get_category("llm")
    llm = LLMClient(config=llm_config)
    llm_router = LLMRouter(local_llm=llm, config_service=config_service)

    # 5. Tools (use config_service for paths)
    vault_path = config_service.get_path("obsidian_vault_path")
    workspace = config_service.get_path("workspace_path")
    workspace.mkdir(parents=True, exist_ok=True)

    tools = ToolRegistry()
    tools.register(FileManagerTool(workspace_path=workspace))
    tools.register(WebSurferTool(config_service=config_service))
    tools.register(ShellRunnerTool(workspace_path=workspace))
    tools.register(CodeExecutorTool(workspace_path=workspace))
    tools.register(ObsidianManagerTool(vault_path=vault_path))

    cli_budget = config_service.get_int("cli_daily_token_budget", 50000)
    cli_provider = config_service.get("cli_provider", "claude")
    budget_tracker = CLIBudgetTracker(daily_budget=cli_budget)
    tools.register(CLIBridgeTool(
        workspace_path=workspace,
        budget_tracker=budget_tracker,
        provider=cli_provider,
    ))
    tools.register(VisionTool(workspace_path=workspace, llm=llm))
    project_root = Path(__file__).parent.parent
    tools.register(SystemShellTool())
    tools.register(OpsExecutor(project_root=project_root))
    tools.register(OllamaManagerTool())
    tools.register(SelfConfigTool(project_path=project_root))

    # 6. Obsidian Writer
    obsidian_writer = ObsidianWriter(vault_path=vault_path)

    # 7. Telegram + Allowlist
    allowlist = TelegramAllowlist(
        owner_chat_id=TELEGRAM_CHAT_ID,
        allowed_ids_csv=TELEGRAM_ALLOWED_CHAT_IDS,
    )
    media_dir = workspace / "_media"
    media_dir.mkdir(parents=True, exist_ok=True)
    telegram = TelegramBot(
        token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID,
        allowlist=allowlist, download_dir=media_dir,
    )

    # 8. Scheduler (DB-backed, smart)
    scheduler = SmartScheduler(db)

    # 9. ReviewGate + IntentEngine
    review_gate = ReviewGate(llm=llm)
    intent_engine = IntentEngine(llm=llm)

    # 10. MainAgent (Falki)
    main_agent = MainAgent(
        llm=llm,
        tools=tools,
        db=db,
        obsidian_writer=obsidian_writer,
        telegram=telegram if telegram.enabled else None,
        ws_callback=ws_mgr.broadcast,
        soul_memory=soul_memory,
        review_gate=review_gate,
        intent_engine=intent_engine,
        scheduler=scheduler,
        llm_router=llm_router,
        config_service=config_service,
        allowlist=allowlist,
    )

    # 11. Wire admin API
    admin_api.set_dependencies(
        db=db, scheduler=scheduler, config_service=config_service,
        main_agent=main_agent, budget_tracker=budget_tracker,
        llm_router=llm_router, fact_memory=fact_memory,
        soul_memory=soul_memory,
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
        # Send via Telegram
        if telegram and telegram.enabled:
            await telegram.send_message(text, chat_id=reminder.get('chat_id'))
            if reminder.get('follow_up'):
                await telegram.send_message("Soll ich dazu was machen?", chat_id=reminder.get('chat_id'))

    async def handle_step(step):
        await main_agent.handle_message(
            step['agent_prompt'], chat_id=step.get('chat_id', ''),
        )

    await scheduler.start(
        on_task_due=main_agent.handle_scheduled,
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
    if telegram_task:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass
    if scheduler:
        await scheduler.stop()
    await db.close()


app = FastAPI(title="Falkenstein", lifespan=lifespan)
app.add_middleware(BearerAuthMiddleware, api_token=API_TOKEN)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(admin_router)

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
    # Prefer dashboard.html, fall back to index.html
    dashboard_path = frontend_dir / "dashboard.html"
    if dashboard_path.exists():
        return FileResponse(dashboard_path)
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"status": "Falkenstein running"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    status = main_agent.get_status() if main_agent else {"active_agents": []}
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
            await main_agent.handle_message(text)
    elif msg_type == "get_state":
        status = main_agent.get_status()
        await ws.send_json({"type": "state_update", **status})


@app.post("/api/task")
async def create_task(title: str, description: str = ""):
    await main_agent.handle_message(description or title)
    return {"status": "submitted"}


@app.get("/api/agents")
async def get_agents():
    if main_agent:
        return main_agent.get_status()
    return {"active_agents": []}


@app.get("/api/tasks")
async def get_tasks():
    open_tasks = await db.get_open_tasks()
    return [t.model_dump() for t in open_tasks]


@app.get("/api/status")
async def get_status():
    status = main_agent.get_status() if main_agent else {"active_agents": []}
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
    if ws_mgr and agent.id not in (main_agent.active_agents if main_agent else {}):
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
    uvicorn.run("backend.main:app", host="0.0.0.0", port=PORT, reload=True)
