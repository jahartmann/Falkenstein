from backend.agent import Agent
from backend.models import (
    AgentData, AgentRole, AgentState, AgentTraits, AgentMood, Position,
)
from backend.llm_client import LLMClient
from backend.database import Database
from backend.tools.base import ToolRegistry

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


class AgentPool:
    def __init__(self, llm: LLMClient, db: Database, tools: ToolRegistry):
        self.agents: list[Agent] = []
        for spec in TEAM:
            data = AgentData(
                id=spec["id"], name=spec["name"], role=spec["role"],
                state=AgentState.IDLE_SIT, position=spec["position"],
                traits=spec["traits"], mood=AgentMood(),
            )
            self.agents.append(Agent(data=data, llm=llm, db=db, tools=tools))

    def get_agent(self, agent_id: str) -> Agent | None:
        for a in self.agents:
            if a.data.id == agent_id:
                return a
        return None

    def get_idle_agents(self) -> list[Agent]:
        return [a for a in self.agents if a.is_idle]

    def get_agents_state(self) -> list[dict]:
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
            }
            for a in self.agents
        ]

    async def save_all(self):
        for agent in self.agents:
            await agent.db.upsert_agent(agent.data)
