import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.config import settings
from backend.database import Database
from backend.llm_client import LLMClient
from backend.ws_manager import WSManager
from backend.telegram_bot import TelegramBot
from backend.main_agent import MainAgent
from backend.obsidian_writer import ObsidianWriter
from backend.obsidian_watcher import ObsidianWatcher
from backend.tools.base import ToolRegistry
from backend.tools.file_manager import FileManagerTool
from backend.tools.web_surfer import WebSurferTool
from backend.tools.shell_runner import ShellRunnerTool
from backend.tools.code_executor import CodeExecutorTool
from backend.tools.obsidian_manager import ObsidianManagerTool
from backend.tools.cli_bridge import CLIBridgeTool, CLIBudgetTracker
from backend.tools.vision import VisionTool

db: Database = None
ws_mgr = WSManager()
telegram: TelegramBot = None
main_agent: MainAgent = None
budget_tracker: CLIBudgetTracker = None
telegram_task: asyncio.Task = None
watcher_task: asyncio.Task = None


async def handle_telegram_message(msg: dict):
    """All Telegram messages go through MainAgent."""
    text = msg["text"].strip()
    chat_id = msg.get("chat_id", "")

    if text.startswith("/status"):
        status = main_agent.get_status()
        agents = status["active_agents"]
        if not agents:
            await telegram.send_message("💤 Keine aktiven Agents.", chat_id=chat_id)
        else:
            lines = ["🏢 *Aktive Agents:*"]
            for a in agents:
                lines.append(f"  🤖 {a['type']}: {a['task']}")
            await telegram.send_message("\n".join(lines), chat_id=chat_id)
    elif text.startswith("/stop"):
        await telegram.send_message("⏹ Stop noch nicht implementiert.", chat_id=chat_id)
    elif text.startswith("/start") or text.startswith("/help"):
        await telegram.send_message(
            "🏢 *Falkenstein Assistent*\n\n"
            "Schick mir einfach eine Nachricht oder Aufgabe.\n\n"
            "/status — Aktive Agents\n"
            "/stop — Task abbrechen",
            chat_id=chat_id,
        )
    else:
        await main_agent.handle_message(text, chat_id=chat_id)


async def handle_obsidian_todo(content: str, source_file: str):
    """New todo from Obsidian Inbox -> MainAgent."""
    await main_agent.handle_message(content)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, telegram, telegram_task, main_agent, budget_tracker, watcher_task

    # Database
    db = Database(settings.db_path)
    await db.init()

    # LLM
    llm = LLMClient()

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

    # Obsidian Writer
    obsidian_writer = ObsidianWriter(vault_path=settings.obsidian_vault_path)

    # Telegram
    telegram = TelegramBot()

    # MainAgent
    main_agent = MainAgent(
        llm=llm,
        tools=tools,
        db=db,
        obsidian_writer=obsidian_writer,
        telegram=telegram if telegram.enabled else None,
        ws_callback=ws_mgr.broadcast,
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

    print(f"Falkenstein running on port {settings.frontend_port}")
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
    await db.close()


app = FastAPI(title="Falkenstein", lifespan=lifespan)

frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
async def index():
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
    status["budget"] = {
        "used": budget_tracker.used,
        "budget": budget_tracker.daily_budget,
        "remaining": budget_tracker.remaining,
    }
    return status


@app.get("/api/budget")
async def get_budget():
    return {
        "used": budget_tracker.used,
        "budget": budget_tracker.daily_budget,
        "remaining": budget_tracker.remaining,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
