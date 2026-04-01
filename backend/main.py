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
from backend.tools.base import ToolRegistry
from backend.tools.file_manager import FileManagerTool

db: Database = None
pool: AgentPool = None
orchestrator: Orchestrator = None
sim: SimEngine = None
ws_mgr = WSManager()
sim_task: asyncio.Task = None


async def sim_loop():
    """Main simulation loop — ticks every 5 seconds."""
    while True:
        try:
            events = await sim.tick()
            for event in events:
                await ws_mgr.broadcast(event)
            await ws_mgr.broadcast({
                "type": "state_update",
                "agents": pool.get_agents_state(),
            })
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Sim loop error: {e}")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, pool, orchestrator, sim, sim_task

    db = Database(settings.db_path)
    await db.init()

    llm = LLMClient()

    tools = ToolRegistry()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    tools.register(FileManagerTool(workspace_path=settings.workspace_path))

    pool = AgentPool(llm=llm, db=db, tools=tools)
    await pool.save_all()

    orchestrator = Orchestrator(pool=pool, db=db, llm=llm)
    sim = SimEngine(agents=pool.agents, llm=llm)

    sim_task = asyncio.create_task(sim_loop())

    print(f"Falkenstein running on port {settings.frontend_port}")
    yield

    sim_task.cancel()
    try:
        await sim_task
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
