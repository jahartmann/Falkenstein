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
from backend.personality import PersonalityEngine
from backend.relationships import RelationshipEngine

db: Database = None
pool: AgentPool = None
orchestrator: Orchestrator = None
sim: SimEngine = None
ws_mgr = WSManager()
sim_task: asyncio.Task = None
rel_engine: RelationshipEngine = None
personality_engine: PersonalityEngine = None


async def sim_loop():
    tick_count = 0
    while True:
        try:
            events = await sim.tick()
            for event in events:
                await ws_mgr.broadcast(event)
            await ws_mgr.broadcast({
                "type": "state_update",
                "agents": pool.get_agents_state(),
            })
            tick_count += 1
            if tick_count % 60 == 0:
                for agent in pool.agents:
                    await db.log_personality_snapshot(
                        agent.data.id, agent.data.traits, agent.data.mood
                    )
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Sim loop error: {e}")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, pool, orchestrator, sim, sim_task, rel_engine, personality_engine

    db = Database(settings.db_path)
    await db.init()

    llm = LLMClient()

    tools = ToolRegistry()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)
    tools.register(FileManagerTool(workspace_path=settings.workspace_path))

    personality_engine = PersonalityEngine()
    rel_engine = RelationshipEngine(db)

    pool = AgentPool(llm=llm, db=db, tools=tools, personality_engine=personality_engine)
    await pool.save_all()

    orchestrator = Orchestrator(pool=pool, db=db, llm=llm, relationship_engine=rel_engine)
    sim = SimEngine(agents=pool.agents, llm=llm,
                    relationship_engine=rel_engine, personality_engine=personality_engine)

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


@app.get("/api/duos")
async def get_duos():
    duos = await rel_engine.detect_duos()
    return {"duos": duos}


@app.get("/api/relationships/{agent_id}")
async def get_relationships(agent_id: str):
    rels = await db.get_relationships_for(agent_id)
    return [r.model_dump() for r in rels]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.frontend_port, reload=True)
