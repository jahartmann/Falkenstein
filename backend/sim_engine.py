import random
from backend.agent import Agent
from backend.models import AgentState
from backend.llm_client import LLMClient

ACTION_TO_STATE = {
    "wander": AgentState.IDLE_WANDER,
    "talk": AgentState.IDLE_TALK,
    "coffee": AgentState.IDLE_COFFEE,
    "phone": AgentState.IDLE_PHONE,
    "sit": AgentState.IDLE_SIT,
}


class SimEngine:
    def __init__(self, agents: list[Agent], llm: LLMClient):
        self.agents = agents
        self.llm = llm

    def _nearby_agents(self, agent: Agent, radius: int = 5) -> list[Agent]:
        result = []
        for other in self.agents:
            if other.data.id == agent.data.id:
                continue
            dx = abs(other.data.position.x - agent.data.position.x)
            dy = abs(other.data.position.y - agent.data.position.y)
            if dx <= radius and dy <= radius:
                result.append(other)
        return result

    async def tick(self) -> list[dict]:
        events = []
        for agent in self.agents:
            if not agent.is_idle:
                continue
            event = await self._tick_agent(agent)
            if event:
                events.append(event)
        return events

    async def _tick_agent(self, agent: Agent) -> dict | None:
        nearby = self._nearby_agents(agent)
        nearby_names = [a.data.name for a in nearby]
        action_str = await self.llm.generate_sim_action(
            agent_name=agent.data.name,
            personality=agent.personality_description,
            nearby_agents=nearby_names,
        )
        action = action_str.strip().lower().rstrip(".")
        if action not in ACTION_TO_STATE:
            action = "sit"
        new_state = ACTION_TO_STATE[action]
        agent.data.state = new_state

        if action == "talk" and nearby:
            partner = random.choice(nearby)
            message = await self.llm.generate_chat_message(
                agent_name=agent.data.name,
                personality=agent.personality_description,
                partner_name=partner.data.name,
            )
            return {
                "type": "talk",
                "agent": agent.data.id,
                "partner": partner.data.id,
                "message": message,
                "x": agent.data.position.x,
                "y": agent.data.position.y,
            }

        if action == "wander":
            dx = random.randint(-3, 3)
            dy = random.randint(-3, 3)
            agent.data.position.x = max(0, min(59, agent.data.position.x + dx))
            agent.data.position.y = max(0, min(47, agent.data.position.y + dy))
            return {
                "type": "move",
                "agent": agent.data.id,
                "x": agent.data.position.x,
                "y": agent.data.position.y,
            }

        if action == "coffee":
            return {"type": "coffee", "agent": agent.data.id}

        return {"type": "idle", "agent": agent.data.id, "action": action}
