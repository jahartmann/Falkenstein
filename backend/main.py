import asyncio
import time as _time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.config import settings
from backend.admin_api import router as admin_router
from backend.database import Database
from backend.llm_client import LLMClient
from backend.ws_manager import WSManager
from backend.telegram_bot import TelegramBot
from backend.main_agent import MainAgent
from backend.obsidian_writer import ObsidianWriter
from backend.obsidian_watcher import ObsidianWatcher
from backend.scheduler import Scheduler
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
from backend.memory.fact_memory import FactMemory
from backend.llm_router import LLMRouter

db: Database = None
fact_memory: FactMemory = None
ws_mgr = WSManager()
telegram: TelegramBot = None
main_agent: MainAgent = None
budget_tracker: CLIBudgetTracker = None
llm_router: LLMRouter = None
telegram_task: asyncio.Task = None
watcher_task: asyncio.Task = None
scheduler: Scheduler = None
scheduler_task: asyncio.Task = None

# External agents (Claude Code subagents etc.) — TTL-based, auto-expire after 60s
_external_agents: dict[str, dict] = {}


class ExternalAgentIn(BaseModel):
    id: str
    name: str = ""
    type: str = "external"  # coder, researcher, writer, ops, external
    task: str = ""


async def handle_telegram_message(msg: dict):
    """All Telegram messages go through MainAgent — including /commands."""
    text = msg["text"].strip()
    chat_id = msg.get("chat_id", "")
    await main_agent.handle_message(text, chat_id=chat_id)


async def handle_obsidian_todo(todo: dict):
    """New todo from Obsidian Inbox -> MainAgent."""
    await main_agent.handle_message(
        todo["content"],
        agent_type_hint=todo.get("agent_type"),
        project_hint=todo.get("project"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, telegram, telegram_task, main_agent, budget_tracker, watcher_task, scheduler, scheduler_task, fact_memory, llm_router

    # Database
    db = Database(settings.db_path)
    await db.init()

    # Fact Memory
    fact_memory = FactMemory(db)
    await fact_memory.init()

    # LLM + Router
    llm = LLMClient()
    llm_router = LLMRouter(local_llm=llm)

    # Tools
    tools = ToolRegistry()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    tools.register(FileManagerTool(workspace_path=settings.workspace_path))
    tools.register(WebSurferTool())
    tools.register(ShellRunnerTool(workspace_path=settings.workspace_path))
    tools.register(CodeExecutorTool(workspace_path=settings.workspace_path))
    tools.register(ObsidianManagerTool(vault_path=settings.obsidian_vault_path))
    budget_tracker = CLIBudgetTracker(daily_budget=settings.cli_daily_token_budget)
    tools.register(CLIBridgeTool(
        workspace_path=settings.workspace_path,
        budget_tracker=budget_tracker,
        provider=settings.cli_provider,
    ))
    tools.register(VisionTool(workspace_path=settings.workspace_path, llm=llm))
    project_root = Path(__file__).parent.parent
    tools.register(SystemShellTool())
    tools.register(OllamaManagerTool())
    tools.register(SelfConfigTool(project_path=project_root))

    # Obsidian Writer
    obsidian_writer = ObsidianWriter(vault_path=settings.obsidian_vault_path)

    # Telegram
    telegram = TelegramBot()

    # Scheduler (create early so MainAgent can reference it)
    scheduler = None
    if settings.obsidian_vault_path.exists():
        scheduler = Scheduler(vault_path=settings.obsidian_vault_path)

    # MainAgent (Falki)
    main_agent = MainAgent(
        llm=llm,
        tools=tools,
        db=db,
        obsidian_writer=obsidian_writer,
        telegram=telegram if telegram.enabled else None,
        ws_callback=ws_mgr.broadcast,
        fact_memory=fact_memory,
        scheduler=scheduler,
        llm_router=llm_router,
    )

    # Start Telegram polling
    if telegram.enabled:
        telegram.on_message(handle_telegram_message)
        telegram_task = asyncio.create_task(telegram.poll_loop())
        print("Telegram bot active")

    # Start Obsidian Watcher
    if settings.obsidian_watch_enabled and settings.obsidian_vault_path.exists():
        watcher = ObsidianWatcher(
            vault_path=settings.obsidian_vault_path,
            on_new_todo=handle_obsidian_todo,
        )
        watcher_task = asyncio.create_task(watcher.start())
        print("Obsidian watcher active")

    # Start Scheduler
    if scheduler:
        scheduler_task = asyncio.create_task(
            scheduler.start(on_task_due=main_agent.handle_scheduled)
        )
        print("Scheduler active")

    from backend import admin_api
    admin_api.init(start_time=_time.time())

    print(f"Falki running on port {settings.frontend_port}")
    yield

    # Shutdown
    if telegram_task:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass
    if watcher_task:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
    await db.close()


app = FastAPI(title="Falkenstein", lifespan=lifespan)
app.include_router(admin_router)

frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def index():
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"status": "Falkenstein running"}


@app.get("/admin")
async def admin_page():
    admin_path = frontend_dir / "admin.html"
    if admin_path.exists():
        return FileResponse(admin_path)
    return {"error": "admin.html not found"}


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
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
