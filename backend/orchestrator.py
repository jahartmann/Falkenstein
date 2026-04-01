from backend.agent_pool import AgentPool
from backend.database import Database
from backend.llm_client import LLMClient
from backend.models import TaskData, TaskStatus, AgentRole
from backend.relationships import RelationshipEngine

ROLE_KEYWORDS = {
    AgentRole.CODER_1: ["code", "implementier", "bug", "fix", "programm", "api", "endpoint"],
    AgentRole.CODER_2: ["test", "code", "implementier", "backend", "frontend"],
    AgentRole.RESEARCHER: ["recherch", "such", "find", "analys", "vergleich"],
    AgentRole.WRITER: ["schreib", "doku", "text", "report", "artikel", "zusammenfass"],
    AgentRole.OPS: ["deploy", "server", "docker", "pipeline", "install", "config", "shell"],
}


class Orchestrator:
    def __init__(self, pool: AgentPool, db: Database, llm: LLMClient,
                 relationship_engine: RelationshipEngine | None = None):
        self.pool = pool
        self.db = db
        self.llm = llm
        self.rel_engine = relationship_engine
        self._pending_task_ids: list[int] = []

    async def submit_task(self, title: str, description: str, project: str | None = None) -> int:
        task = TaskData(title=title, description=description, project=project)
        task_id = await self.db.create_task(task)
        self._pending_task_ids.append(task_id)
        return task_id

    def _best_role_for_task(self, title: str, description: str) -> AgentRole:
        text = (title + " " + description).lower()
        scores: dict[AgentRole, int] = {}
        for role, keywords in ROLE_KEYWORDS.items():
            scores[role] = sum(1 for kw in keywords if kw in text)
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return AgentRole.CODER_1
        return best

    async def _find_duo_partner_idle(self, busy_agent_id: str) -> str | None:
        if not self.rel_engine:
            return None
        duos = await self.rel_engine.detect_duos()
        for a, b in duos:
            partner_id = None
            if a == busy_agent_id:
                partner_id = b
            elif b == busy_agent_id:
                partner_id = a
            if partner_id:
                partner = self.pool.get_agent(partner_id)
                if partner and partner.is_idle:
                    return partner_id
        return None

    async def assign_next_task(self) -> dict | None:
        if not self._pending_task_ids:
            return None
        task_id = self._pending_task_ids[0]
        task = await self.db.get_task(task_id)
        if not task:
            self._pending_task_ids.pop(0)
            return None

        best_role = self._best_role_for_task(task.title, task.description)
        idle = self.pool.get_idle_agents()
        agent = None

        if task.project and self.rel_engine:
            for a in self.pool.agents:
                if a.is_working and a.data.current_task_id is not None:
                    current_task = await self.db.get_task(a.data.current_task_id)
                    if current_task and current_task.project == task.project:
                        duo_id = await self._find_duo_partner_idle(a.data.id)
                        if duo_id:
                            agent = self.pool.get_agent(duo_id)
                            break

        if not agent:
            for a in idle:
                if a.data.role == best_role:
                    agent = a
                    break

        if not agent and idle:
            agent = idle[0]

        if not agent:
            return None

        self._pending_task_ids.pop(0)
        await agent.assign_task(task_id=task.id, title=task.title, description=task.description)
        return {
            "type": "task_assigned",
            "agent": agent.data.id,
            "task_id": task.id,
            "task_title": task.title,
        }
