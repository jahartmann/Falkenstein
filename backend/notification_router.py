from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RoutingRule:
    telegram: bool
    obsidian: bool
    hybrid_check: bool = False


# Routing table: event_type -> RoutingRule
ROUTING_TABLE: dict[str, RoutingRule] = {
    "task_assigned":       RoutingRule(telegram=True,  obsidian=False, hybrid_check=False),
    "task_completed":      RoutingRule(telegram=True,  obsidian=True,  hybrid_check=True),
    "escalation_success":  RoutingRule(telegram=True,  obsidian=True,  hybrid_check=False),
    "escalation_failed":   RoutingRule(telegram=True,  obsidian=True,  hybrid_check=False),
    "budget_warning":      RoutingRule(telegram=True,  obsidian=False, hybrid_check=False),
    "daily_report":        RoutingRule(telegram=True,  obsidian=True,  hybrid_check=False),
    "todo_from_telegram":  RoutingRule(telegram=True,  obsidian=True,  hybrid_check=False),
    "todo_from_obsidian":  RoutingRule(telegram=True,  obsidian=False, hybrid_check=False),
    "subtask_completed":   RoutingRule(telegram=False, obsidian=True,  hybrid_check=False),
    "project_created":     RoutingRule(telegram=True,  obsidian=True,  hybrid_check=False),
}


class NotificationRouter:
    """Routes sim events to Telegram and/or Obsidian based on a routing table.

    Uses an optional LLM hybrid check to decide if short task_completed results
    are worth documenting in Obsidian.
    """

    def __init__(self, telegram, obsidian, llm, llm_routing_enabled: bool = True):
        self.telegram = telegram
        self.obsidian = obsidian
        self.llm = llm
        self.llm_routing_enabled = llm_routing_enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route_event(self, event_type: str, payload: dict) -> None:
        """Route an event to the appropriate notification targets."""
        rule = ROUTING_TABLE.get(event_type)
        if rule is None:
            logger.debug("Unknown event type '%s' — ignored", event_type)
            return

        write_obsidian = rule.obsidian
        if rule.obsidian and rule.hybrid_check:
            content = self._get_hybrid_content(event_type, payload)
            if len(content) < 100:
                write_obsidian = await self._should_write_obsidian(event_type, content)

        if rule.telegram and self.telegram.enabled:
            msg = self._format_telegram(event_type, payload)
            if msg:
                await self.telegram.send_message(msg)

        if write_obsidian:
            await self._write_obsidian(event_type, payload)

    # ------------------------------------------------------------------
    # Telegram formatting
    # ------------------------------------------------------------------

    def _format_telegram(self, event_type: str, payload: dict) -> str | None:
        name = payload.get("agent_name", "Agent")
        title = payload.get("task_title", "")
        result = payload.get("result", "")
        content = payload.get("content", "")
        used = payload.get("used", 0)
        budget = payload.get("budget", 0)
        reason = payload.get("reason", "")
        project_name = payload.get("project_name", "")

        match event_type:
            case "task_assigned":
                return f"📋 *{name}* arbeitet an: {title}"
            case "task_completed":
                return f"✅ *{name}* fertig: {title}\n_{result[:200]}_"
            case "escalation_success":
                return f"⚡ *Eskalation* bei {name}: CLI hat übernommen für {title}"
            case "escalation_failed":
                return f"❌ *Eskalation gescheitert* bei {name}: {title}\n_{reason[:200]}_"
            case "budget_warning":
                return f"⚠️ *Budget-Warnung*: {used:,}/{budget:,} Tokens"
            case "daily_report":
                return content[:2000]
            case "todo_from_telegram":
                return f"✅ Todo eingetragen: {content[:200]}"
            case "todo_from_obsidian":
                return f"📝 Neuer Todo aus Obsidian: {content[:200]}"
            case "project_created":
                return f"📁 Projekt erstellt: {project_name}"
            case _:
                return None

    # ------------------------------------------------------------------
    # Obsidian writing
    # ------------------------------------------------------------------

    async def _write_obsidian(self, event_type: str, payload: dict) -> None:
        title = payload.get("task_title", "")
        agent = payload.get("agent_name", "")
        result = payload.get("result", "")
        content = payload.get("content", "")
        project = payload.get("project", "")
        details = payload.get("details", "")
        source_file = payload.get("source_file", "")
        project_name = payload.get("project_name", "")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        match event_type:
            case "task_completed":
                if project:
                    md = (
                        f"\n## {title}\n"
                        f"- **Agent**: {agent}\n"
                        f"- **Zeit**: {timestamp}\n"
                        f"- **Ergebnis**: {result[:300]}\n"
                    )
                    await self.obsidian.execute({
                        "action": "append",
                        "path": f"Falkenstein/Projekte/{project}/Tasks.md",
                        "content": md,
                    })
                else:
                    await self.obsidian.execute({
                        "action": "inbox",
                        "content": f"[DONE] {title}: {result[:300]}",
                    })

            case "escalation_success" | "escalation_failed":
                await self.obsidian.execute({
                    "action": "daily_report",
                    "content": details or content,
                })

            case "daily_report":
                await self.obsidian.execute({
                    "action": "daily_report",
                    "content": content,
                })

            case "todo_from_telegram":
                await self.obsidian.execute({
                    "action": "todo",
                    "content": content,
                    "project": project,
                })

            case "subtask_completed":
                if project:
                    await self.obsidian.execute({
                        "action": "append",
                        "path": f"Falkenstein/Projekte/{project}/Tasks.md",
                        "content": f"\n- [x] {title} ({timestamp})\n",
                    })
                else:
                    await self.obsidian.execute({
                        "action": "append",
                        "path": "Falkenstein/Tasks/Subtasks.md",
                        "content": f"\n- [x] {title} ({timestamp})\n",
                    })

            case "project_created":
                await self.obsidian.execute({
                    "action": "project",
                    "project_name": project_name,
                })

    # ------------------------------------------------------------------
    # LLM hybrid check
    # ------------------------------------------------------------------

    def _get_hybrid_content(self, event_type: str, payload: dict) -> str:
        """Extract the content string used for the hybrid LLM check."""
        return payload.get("result", payload.get("content", ""))

    async def _should_write_obsidian(self, event_type: str, content: str) -> bool:
        """Ask LLM whether short content is worth documenting in Obsidian.

        Returns True by default on error or when llm_routing_enabled is False.
        """
        if not self.llm_routing_enabled:
            return True

        try:
            system = (
                "Du entscheidest, ob ein Aufgabenergebnis dokumentationswürdig ist. "
                "Antworte NUR mit 'Ja' oder 'Nein'."
            )
            user_msg = (
                f"Ist dieses Ergebnis detailliert genug für eine Dokumentation in Obsidian?\n\n"
                f"Ergebnis: {content}\n\nJa oder Nein?"
            )
            response = await self.llm.chat(
                system_prompt=system,
                messages=[{"role": "user", "content": user_msg}],
                model=self.llm.model_light,
                temperature=0.0,
            )
            return "ja" in response.lower()
        except Exception as exc:
            logger.warning("LLM hybrid check failed: %s — defaulting to True", exc)
            return True
