from backend.agent import Agent
from backend.agent_pool import AgentPool
from backend.database import Database
from backend.llm_client import LLMClient
from backend.models import TaskData, TaskStatus, AgentRole
from backend.relationships import RelationshipEngine
from backend.tools.cli_bridge import CLIBudgetTracker
from backend.pm_logic import PMLogic
from backend.team_lead import TeamLeadLogic

ROLE_KEYWORDS = {
    AgentRole.CODER_1: ["code", "implementier", "bug", "fix", "programm", "api", "endpoint"],
    AgentRole.CODER_2: ["test", "code", "implementier", "backend", "frontend"],
    AgentRole.RESEARCHER: ["recherch", "such", "find", "analys", "vergleich"],
    AgentRole.WRITER: ["schreib", "doku", "text", "report", "artikel", "zusammenfass"],
    AgentRole.OPS: ["deploy", "server", "docker", "pipeline", "install", "config", "shell"],
}


class Orchestrator:
    def __init__(self, pool: AgentPool, db: Database, llm: LLMClient,
                 relationship_engine: RelationshipEngine | None = None,
                 budget_tracker: CLIBudgetTracker | None = None):
        self.pool = pool
        self.db = db
        self.llm = llm
        self.rel_engine = relationship_engine
        self.budget = budget_tracker
        self.pm = PMLogic(llm, db)
        self.team_lead = TeamLeadLogic(db, pool)
        self._pending_task_ids: list[int] = []

    async def submit_task(self, title: str, description: str, project: str | None = None) -> int:
        task = TaskData(title=title, description=description, project=project)
        task_id = await self.db.create_task(task)

        # PM auto-decomposition for complex tasks
        task.id = task_id
        if await self.pm.should_decompose(task):
            subtask_ids = await self.pm.decompose_task(task)
            if subtask_ids:
                # Queue subtasks instead of parent
                self._pending_task_ids.extend(subtask_ids)
                return task_id

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
            # All agents busy — spawn a sub-agent if possible
            sub = self.pool.spawn_sub_agent(best_role)
            if sub:
                agent = sub
            else:
                return None

        self._pending_task_ids.pop(0)
        await agent.assign_task(task_id=task.id, title=task.title, description=task.description)
        return {
            "type": "task_assigned",
            "agent": agent.data.id,
            "task_id": task.id,
            "task_title": task.title,
            "is_sub_agent": agent.data.id.startswith("sub_"),
        }

    async def process_work_event(self, event: dict) -> list[dict]:
        """Process a work_step event. Handle escalation, review, completion.

        Returns list of additional events to broadcast.
        """
        extra_events = []
        agent_id = event.get("agent", "")
        agent = self.pool.get_agent(agent_id)
        if not agent:
            return extra_events

        # Check if agent needs escalation after repeated failures
        if event.get("needs_escalation"):
            escalation_event = await self._handle_escalation(agent)
            if escalation_event:
                extra_events.append(escalation_event)

        # Check budget warning
        if self.budget and self.budget.warning_threshold:
            extra_events.append({
                "type": "budget_warning",
                "used": self.budget.used,
                "budget": self.budget.daily_budget,
            })

        return extra_events

    async def _handle_escalation(self, agent: Agent) -> dict | None:
        """Escalate a stuck agent's work to CLI-Bridge."""
        cli_tool = agent.tools.get("cli_bridge")
        if not cli_tool:
            return None

        task = await self.db.get_task(agent.data.current_task_id) if agent.data.current_task_id else None
        if not task:
            return None

        # Build context from agent's session
        context = "\n".join(
            m.get("content", "")[:200]
            for m in agent.session_messages[-6:]
            if m.get("content")
        )

        result = await cli_tool.execute({
            "prompt": f"Der lokale Agent ist gescheitert. Löse diese Aufgabe:\n{task.title}\n{task.description}",
            "context": context,
        })

        if result.success:
            # Feed CLI result back into agent session
            agent.session_messages.append({
                "role": "user",
                "content": f"[CLI-Ergebnis]:\n{result.output[:2000]}"
            })
            agent.retry_count = 0
            return {
                "type": "escalation_success",
                "agent": agent.data.id,
                "task_id": task.id,
                "output_preview": result.output[:100],
            }
        else:
            return {
                "type": "escalation_failed",
                "agent": agent.data.id,
                "task_id": task.id,
                "reason": result.output[:200],
            }

    async def run_work_tick(self) -> list[dict]:
        """Run one work step for all working agents. Returns all events."""
        events = []
        for agent in self.pool.agents:
            if not agent.is_working:
                continue
            try:
                event = await agent.work_step()
                events.append(event)

                # Process escalation / budget warnings
                extra = await self.process_work_event(event)
                events.extend(extra)

                # If agent produced a final response (no tool call), do confidence check
                if event.get("type") == "work_response":
                    content = event.get("content", "")
                    review = await agent.review_result(content)
                    events.append(review)

                    if review["needs_escalation"]:
                        esc = await self._handle_escalation(agent)
                        if esc:
                            events.append(esc)
                    elif review["score"] >= 7:
                        # Good enough — complete the task
                        task_id = agent.data.current_task_id
                        await agent.complete_task(content)
                        events.append({
                            "type": "task_completed",
                            "agent": agent.data.id,
                            "task_id": task_id,
                        })

                        # Check if this subtask completes a parent project
                        if task_id:
                            task = await self.db.get_task(task_id)
                            if task and task.parent_task_id:
                                await self.db.update_task_result(task_id, content)
                                proj_event = await self.team_lead.check_subtask_completion(
                                    task.parent_task_id
                                )
                                if proj_event:
                                    events.append(proj_event)

            except Exception as e:
                events.append({
                    "type": "work_error",
                    "agent": agent.data.id,
                    "error": str(e)[:200],
                })
        return events
