from backend.agent import Agent
from backend.models import (
    AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position,
)
from backend.llm_client import LLMClient
from backend.database import Database
from backend.tools.base import ToolRegistry
from backend.personality import PersonalityEngine
from backend.memory.session import SessionMemory
from backend.memory.rag_engine import RAGEngine

TEAM = [
    {"id": "pm", "name": "Star", "role": AgentRole.PM,
     "traits": AgentTraits(social=0.8, focus=0.6, confidence=0.7, patience=0.7, curiosity=0.6, leadership=0.9),
     "position": Position(x=30, y=10)},
    {"id": "team_lead", "name": "Nina", "role": AgentRole.TEAM_LEAD,
     "traits": AgentTraits(social=0.7, focus=0.7, confidence=0.8, patience=0.6, curiosity=0.5, leadership=0.8),
     "position": Position(x=28, y=15)},
    {"id": "coder_1", "name": "Alex", "role": AgentRole.CODER_1,
     "traits": AgentTraits(social=0.5, focus=0.9, confidence=0.6, patience=0.5, curiosity=0.7, leadership=0.3),
     "position": Position(x=10, y=20)},
    {"id": "coder_2", "name": "Bob", "role": AgentRole.CODER_2,
     "traits": AgentTraits(social=0.6, focus=0.8, confidence=0.5, patience=0.6, curiosity=0.8, leadership=0.2),
     "position": Position(x=15, y=20)},
    {"id": "researcher", "name": "Amelia", "role": AgentRole.RESEARCHER,
     "traits": AgentTraits(social=0.6, focus=0.7, confidence=0.6, patience=0.8, curiosity=0.9, leadership=0.2),
     "position": Position(x=20, y=25)},
    {"id": "writer", "name": "Clara", "role": AgentRole.WRITER,
     "traits": AgentTraits(social=0.7, focus=0.6, confidence=0.7, patience=0.7, curiosity=0.6, leadership=0.3),
     "position": Position(x=25, y=25)},
    {"id": "ops", "name": "Max", "role": AgentRole.OPS,
     "traits": AgentTraits(social=0.4, focus=0.8, confidence=0.7, patience=0.5, curiosity=0.5, leadership=0.4),
     "position": Position(x=40, y=15)},
]

# Sub-agent naming
_SUB_AGENT_COUNTER = 0
_SUB_AGENT_NAMES = ["Finn", "Lena", "Tom", "Sara", "Jan", "Marie", "Paul", "Anna"]

# Role to spawn when all agents of that type are busy
ROLE_SPAWN_MAP = {
    AgentRole.CODER_1: AgentRole.CODER_2,
    AgentRole.CODER_2: AgentRole.CODER_1,
    AgentRole.RESEARCHER: AgentRole.RESEARCHER,
    AgentRole.WRITER: AgentRole.WRITER,
    AgentRole.OPS: AgentRole.OPS,
}


class AgentPool:
    def __init__(self, llm: LLMClient, db: Database, tools: ToolRegistry,
                 personality_engine: PersonalityEngine | None = None,
                 session_memory: SessionMemory | None = None,
                 rag_engine: RAGEngine | None = None,
                 max_sub_agents: int = 3):
        self._llm = llm
        self._db = db
        self._tools = tools
        self._pe = personality_engine or PersonalityEngine()
        self._sm = session_memory or SessionMemory()
        self._rag = rag_engine
        self.max_sub_agents = max_sub_agents
        self.agents: list[Agent] = []
        self._sub_agents: list[Agent] = []

        for spec in TEAM:
            data = AgentData(
                id=spec["id"], name=spec["name"], role=spec["role"],
                state=AgentState.IDLE_SIT, position=spec["position"],
                traits=spec["traits"], mood=AgentMood(),
            )
            self.agents.append(Agent(
                data=data, llm=llm, db=db, tools=tools,
                personality_engine=self._pe, session_memory=self._sm, rag_engine=self._rag,
            ))

    def get_agent(self, agent_id: str) -> Agent | None:
        for a in self.agents:
            if a.data.id == agent_id:
                return a
        for a in self._sub_agents:
            if a.data.id == agent_id:
                return a
        return None

    def get_idle_agents(self) -> list[Agent]:
        idle = [a for a in self.agents if a.is_idle]
        idle.extend(a for a in self._sub_agents if a.is_idle)
        return idle

    @property
    def all_busy(self) -> bool:
        return len(self.get_idle_agents()) == 0

    def spawn_sub_agent(self, role: AgentRole) -> Agent | None:
        """Spawn a temporary sub-agent when all core agents are busy."""
        if len(self._sub_agents) >= self.max_sub_agents:
            return None

        global _SUB_AGENT_COUNTER
        idx = _SUB_AGENT_COUNTER % len(_SUB_AGENT_NAMES)
        name = _SUB_AGENT_NAMES[idx]
        agent_id = f"sub_{_SUB_AGENT_COUNTER}"
        _SUB_AGENT_COUNTER += 1

        data = AgentData(
            id=agent_id, name=f"{name} (Temp)",
            role=role, state=AgentState.IDLE_SIT,
            position=Position(x=35 + idx * 2, y=30),
            traits=AgentTraits(),  # default traits
            mood=AgentMood(),
        )
        agent = Agent(
            data=data, llm=self._llm, db=self._db, tools=self._tools,
            personality_engine=self._pe, session_memory=self._sm, rag_engine=self._rag,
        )
        self._sub_agents.append(agent)
        return agent

    def retire_idle_sub_agents(self) -> list[str]:
        """Remove idle sub-agents that are no longer needed. Returns removed IDs."""
        retired = []
        still_active = []
        for a in self._sub_agents:
            if a.is_idle and a.data.current_task_id is None:
                retired.append(a.data.id)
            else:
                still_active.append(a)
        self._sub_agents = still_active
        return retired

    def get_agents_state(self) -> list[dict]:
        all_agents = self.agents + self._sub_agents
        return [
            {
                "id": a.data.id,
                "name": a.data.name,
                "role": a.data.role.value,
                "state": a.data.state.value,
                "x": a.data.position.x,
                "y": a.data.position.y,
                "mood": a.data.mood.model_dump(),
                "current_task_id": a.data.current_task_id,
                "is_sub_agent": a in self._sub_agents,
            }
            for a in all_agents
        ]

    async def save_all(self):
        for agent in self.agents:
            await agent.db.upsert_agent(agent.data)
