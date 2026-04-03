import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.config import settings
from backend.database import Database
from backend.llm_client import LLMClient
from backend.agent_pool import AgentPool
from backend.orchestrator import Orchestrator
from backend.sim_engine import SimEngine
from backend.ws_manager import WSManager
from backend.telegram_bot import TelegramBot
from backend.tools.base import ToolRegistry
from backend.tools.file_manager import FileManagerTool
from backend.tools.web_surfer import WebSurferTool
from backend.tools.shell_runner import ShellRunnerTool
from backend.tools.code_executor import CodeExecutorTool
from backend.tools.obsidian_manager import ObsidianManagerTool
from backend.tools.cli_bridge import CLIBridgeTool, CLIBudgetTracker
from backend.tools.vision import VisionTool
from backend.personality import PersonalityEngine
from backend.relationships import RelationshipEngine
from backend.memory.session import SessionMemory
from backend.memory.rag_engine import RAGEngine
from backend.daily_report import DailyReportGenerator

db: Database = None
pool: AgentPool = None
orchestrator: Orchestrator = None
sim: SimEngine = None
ws_mgr = WSManager()
telegram: TelegramBot = None
budget_tracker: CLIBudgetTracker = None
session_memory: SessionMemory = None
rag_engine: RAGEngine = None
sim_task: asyncio.Task = None
telegram_task: asyncio.Task = None
rel_engine: RelationshipEngine = None
personality_engine: PersonalityEngine = None
daily_reporter: DailyReportGenerator = None


async def sim_loop():
    tick_count = 0
    while True:
        try:
            # Sim tick for idle agents
            events = await sim.tick()

            # Work tick for working agents
            work_events = await orchestrator.run_work_tick()
            events.extend(work_events)

            # Broadcast all events
            for event in events:
                await ws_mgr.broadcast(event)

                # Telegram notifications for key events
                if telegram and telegram.enabled:
                    await _notify_telegram(event)

            await ws_mgr.broadcast({
                "type": "state_update",
                "agents": pool.get_agents_state(),
            })

            # Try to assign pending tasks
            while True:
                assigned = await orchestrator.assign_next_task()
                if not assigned:
                    break
                await ws_mgr.broadcast(assigned)
                if telegram and telegram.enabled:
                    await telegram.notify_task_assigned(
                        assigned.get("agent", "?"), assigned.get("task_title", "")
                    )

            # Retire idle sub-agents
            retired = pool.retire_idle_sub_agents()
            for rid in retired:
                await ws_mgr.broadcast({"type": "sub_agent_retired", "agent": rid})

            tick_count += 1
            if tick_count % 60 == 0:
                for agent in pool.agents:
                    await db.log_personality_snapshot(
                        agent.data.id, agent.data.traits, agent.data.mood
                    )

            # Auto daily report (check every tick, generates once per day after 18:00)
            if daily_reporter and daily_reporter.should_generate():
                try:
                    report = await daily_reporter.generate()
                    # Save to Obsidian
                    obsidian = pool.agents[0].tools.get("obsidian_manager")
                    if obsidian:
                        await obsidian.execute({"action": "daily_report", "content": report})
                    # Send to Telegram
                    if telegram and telegram.enabled:
                        summary = await daily_reporter.generate_telegram_summary()
                        await telegram.send_message(summary)
                    await ws_mgr.broadcast({"type": "daily_report_generated"})
                except Exception as e:
                    print(f"Daily report error: {e}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Sim loop error: {e}")
        await asyncio.sleep(10)


async def _notify_telegram(event: dict):
    """Send Telegram notifications for important events."""
    etype = event.get("type", "")
    agent_id = event.get("agent", "")
    agent = pool.get_agent(agent_id) if agent_id else None
    name = agent.data.name if agent else agent_id

    if etype == "task_completed":
        await telegram.notify_task_done(name, str(event.get("task_id", "")), "Fertig")
    elif etype == "escalation_success":
        await telegram.notify_escalation(name, event.get("output_preview", ""))
    elif etype == "escalation_failed":
        await telegram.notify_task_failed(name, "Eskalation", event.get("reason", ""))
    elif etype == "budget_warning":
        await telegram.notify_budget_warning(event["used"], event["budget"])


llm_client: LLMClient = None

# Telegram chat history per chat_id (session memory)
_telegram_history: dict[str, list[dict]] = {}
MAX_TELEGRAM_HISTORY = 15


async def handle_telegram_message(msg: dict):
    """Handle Telegram messages. Commands are instant, chat goes via LLM."""
    text = msg["text"].strip()
    chat_id = msg.get("chat_id", "")

    # --- Commands (instant, no LLM) ---
    if text.startswith("/start"):
        await telegram.send_message(
            "🏢 *Falkenstein KI-Büro*\n\n"
            "Befehle:\n"
            "/status — Team-Status\n"
            "/budget — CLI-Token-Budget\n"
            "/task <text> — Task an Agenten\n"
            "/todo <text> — Todo in Obsidian\n"
            "/projekt <name> — Neues Projekt\n"
            "/clear — Chat-Verlauf löschen"
        )

    elif text.startswith("/status"):
        agents_state = pool.get_agents_state()
        working = [a for a in agents_state if a["state"].startswith("work")]
        idle = [a for a in agents_state if a["state"].startswith("idle")]
        lines = [f"🏢 *Falkenstein Status*", f"Arbeitend: {len(working)} | Idle: {len(idle)}"]
        for a in agents_state:
            if a.get("is_sub_agent"):
                continue
            icon = "💻" if a["state"].startswith("work") else "😴"
            lines.append(f"  {icon} {a['name']}")
        await telegram.send_message("\n".join(lines))

    elif text.startswith("/budget"):
        if budget_tracker:
            await telegram.send_message(
                f"💰 *Budget*: {budget_tracker.used:,}/{budget_tracker.daily_budget:,} "
                f"({budget_tracker.remaining:,} übrig)"
            )

    elif text.startswith("/task"):
        task_text = text[5:].strip()
        if not task_text:
            await telegram.send_message("Nutzung: `/task Beschreibung`")
            return
        task_id = await orchestrator.submit_task(title=task_text[:100], description=task_text)
        event = await orchestrator.assign_next_task()
        await telegram.send_message(f"📥 Task #{task_id}: {task_text[:100]}")
        if event:
            await ws_mgr.broadcast(event)

    elif text.startswith("/todo"):
        todo_text = text[5:].strip()
        if not todo_text:
            await telegram.send_message("Nutzung: `/todo Text` oder `/todo Text | Projektname`")
            return
        # Parse optional project: "/todo Fix bug | website"
        parts = todo_text.split("|", 1)
        content = parts[0].strip()
        project = parts[1].strip() if len(parts) > 1 else None
        obsidian = pool.agents[0].tools.get("obsidian_manager")
        if obsidian:
            result = await obsidian.execute({"action": "todo", "content": content, "project": project})
            await telegram.send_message(f"✅ {result.output}")
        else:
            await telegram.send_message("Obsidian nicht verfügbar.")

    elif text.startswith("/projekt"):
        name = text[8:].strip()
        if not name:
            await telegram.send_message("Nutzung: `/projekt Name`")
            return
        obsidian = pool.agents[0].tools.get("obsidian_manager")
        if obsidian:
            result = await obsidian.execute({"action": "project", "content": name})
            await telegram.send_message(f"📁 {result.output}")

    elif text.startswith("/clear"):
        _telegram_history.pop(chat_id, None)
        await telegram.send_message("🧹 Verlauf gelöscht.")

    # --- Chat (via LLM) ---
    else:
        await _chat_with_gemma(text, chat_id)


async def _chat_with_gemma(text: str, chat_id: str):
    """Chat via Gemma 4 with extended context (128K) for long conversations. Free, local."""
    # Maintain session history — extended context allows much more history
    if chat_id not in _telegram_history:
        _telegram_history[chat_id] = []
    history = _telegram_history[chat_id]
    history.append({"role": "user", "content": text})

    # With Gemma 4's 256K context, keep more history (up to 50 turns)
    max_turns = 50
    if len(history) > max_turns * 2:
        history[:] = history[-max_turns * 2:]

    system = (
        "Du bist der Falkenstein-Assistent. Antworte hilfreich, kurz und auf Deutsch. "
        "Bei Fragen zu aktuellen Ereignissen sage ehrlich, dass du keine Live-Daten hast, "
        "und schlage vor den Task per /task einzureichen damit der Research-Agent suchen kann."
    )

    try:
        # Primary: Gemma 4 via Ollama with extended context (free)
        response = await llm_client.chat_extended_context(
            system_prompt=system,
            messages=history,
            num_predict=500,
            think=True,
        )
        history.append({"role": "assistant", "content": response})
        await telegram.send_message(response[:4000])
    except Exception as e:
        # Fallback: try Gemini CLI if Ollama fails
        try:
            from backend.tools.cli_bridge import CLIBridgeTool
            cli = CLIBridgeTool(
                workspace_path=settings.workspace_path,
                budget_tracker=budget_tracker,
                provider="gemini",
            )
            result = await cli.execute({"prompt": text, "provider": "gemini"})
            if result.success:
                history.append({"role": "assistant", "content": result.output})
                await telegram.send_message(f"_(via Gemini)_\n{result.output[:3900]}")
            else:
                await telegram.send_message(f"Fehler: Ollama und Gemini nicht erreichbar.\n{e}")
        except Exception as e2:
            await telegram.send_message(f"Fehler: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, pool, orchestrator, sim, sim_task, telegram_task
    global rel_engine, personality_engine, telegram, budget_tracker, llm_client, daily_reporter

    db = Database(settings.db_path)
    await db.init()

    llm = LLMClient()
    llm_client = llm

    tools = ToolRegistry()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    tools.register(FileManagerTool(workspace_path=settings.workspace_path))
    tools.register(WebSurferTool())
    tools.register(ShellRunnerTool(workspace_path=settings.workspace_path))
    tools.register(CodeExecutorTool(workspace_path=settings.workspace_path))
    tools.register(ObsidianManagerTool(vault_path=settings.obsidian_vault_path))

    # CLI Bridge with budget tracking
    budget_tracker = CLIBudgetTracker(daily_budget=settings.cli_daily_token_budget)
    tools.register(CLIBridgeTool(
        workspace_path=settings.workspace_path,
        budget_tracker=budget_tracker,
        provider=settings.cli_provider,
    ))

    # Vision tool (Gemma 4 26B image analysis)
    tools.register(VisionTool(workspace_path=settings.workspace_path, llm=llm))

    personality_engine = PersonalityEngine()
    rel_engine = RelationshipEngine(db)

    # Memory systems
    session_memory = SessionMemory(max_messages=15, timeout_seconds=1800)
    rag_engine = RAGEngine(persist_path=settings.db_path.parent / "chroma")
    await rag_engine.init()

    pool = AgentPool(llm=llm, db=db, tools=tools, personality_engine=personality_engine,
                     session_memory=session_memory, rag_engine=rag_engine)
    await pool.save_all()

    orchestrator = Orchestrator(pool=pool, db=db, llm=llm,
                                relationship_engine=rel_engine, budget_tracker=budget_tracker)
    sim = SimEngine(agents=pool.agents, llm=llm,
                    relationship_engine=rel_engine, personality_engine=personality_engine)

    daily_reporter = DailyReportGenerator(db=db, pool=pool)

    sim_task = asyncio.create_task(sim_loop())

    # Start Telegram polling if configured
    telegram = TelegramBot()
    if telegram.enabled:
        telegram.on_message(handle_telegram_message)
        telegram_task = asyncio.create_task(telegram.poll_loop())
        print(f"Telegram bot active")

    print(f"Falkenstein running on port {settings.frontend_port}")
    yield

    sim_task.cancel()
    try:
        await sim_task
    except asyncio.CancelledError:
        pass
    if telegram_task:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass
    await pool.save_all()
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
    return {"status": "Falkenstein backend running", "agents": pool.get_agents_state()}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_mgr.connect(ws)
    await ws_mgr.send_full_state(ws, pool.get_agents_state())
    try:
        while True:
            data = await ws.receive_json()
            await handle_ws_message(data)
    except WebSocketDisconnect:
        ws_mgr.disconnect(ws)


async def handle_ws_message(data: dict):
    msg_type = data.get("type", "")
    if msg_type == "submit_task":
        task_id = await orchestrator.submit_task(
            title=data["title"],
            description=data.get("description", ""),
            project=data.get("project"),
        )
        event = await orchestrator.assign_next_task()
        await ws_mgr.broadcast({"type": "task_submitted", "task_id": task_id})
        if event:
            await ws_mgr.broadcast(event)
    elif msg_type == "get_state":
        await ws_mgr.broadcast({
            "type": "state_update",
            "agents": pool.get_agents_state(),
        })


@app.post("/api/task")
async def create_task(title: str, description: str = "", project: str | None = None):
    task_id = await orchestrator.submit_task(title, description, project)
    event = await orchestrator.assign_next_task()
    if event:
        await ws_mgr.broadcast(event)
    return {"task_id": task_id}


@app.get("/api/agents")
async def get_agents():
    return pool.get_agents_state()


@app.get("/api/duos")
async def get_duos():
    duos = await rel_engine.detect_duos()
    return {"duos": duos}


@app.get("/api/relationships/{agent_id}")
async def get_relationships(agent_id: str):
    rels = await db.get_relationships_for(agent_id)
    return [r.model_dump() for r in rels]


@app.get("/api/budget")
async def get_budget():
    return {
        "used": budget_tracker.used,
        "budget": budget_tracker.daily_budget,
        "remaining": budget_tracker.remaining,
        "warning": budget_tracker.warning_threshold,
    }


@app.get("/api/tasks")
async def get_tasks():
    open_tasks = await db.get_open_tasks()
    return [t.model_dump() for t in open_tasks]


@app.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: int):
    task = await db.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    subtasks = await db.get_subtasks(task_id)
    return {
        "task": task.model_dump(),
        "subtasks": [s.model_dump() for s in subtasks],
    }


@app.get("/api/project/{project}")
async def get_project(project: str):
    return await orchestrator.team_lead.get_project_progress(project)


@app.get("/api/agent/{agent_id}")
async def get_agent_detail(agent_id: str):
    agent = pool.get_agent(agent_id)
    if not agent:
        return {"error": "Agent not found"}
    rels = await db.get_relationships_for(agent_id)
    history = await db.get_personality_history(agent_id, limit=10)
    return {
        "agent": {
            "id": agent.data.id,
            "name": agent.data.name,
            "role": agent.data.role.value,
            "state": agent.data.state.value,
            "traits": agent.data.traits.model_dump(),
            "mood": agent.data.mood.model_dump(),
            "current_task_id": agent.data.current_task_id,
        },
        "relationships": [r.model_dump() for r in rels],
        "personality_history": history,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
