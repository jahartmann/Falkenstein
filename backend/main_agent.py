import asyncio
import json
import re
from backend.sub_agent import SubAgent
from backend.obsidian_writer import ObsidianWriter
from backend.models import TaskData, TaskStatus
from backend.scheduler import ScheduledTask

_CLASSIFY_SYSTEM = (
    "Du bist ein Assistent-Router. Analysiere die Nachricht und entscheide:\n"
    "1. quick_reply — Direkt beantwortbar (Fragen, Status, Smalltalk, kurze Infos)\n"
    "2. task — Braucht Arbeit (Recherche, Code, Texte schreiben, System-Tasks)\n\n"
    "Bei quick_reply: Beantworte die Frage direkt.\n"
    "Bei task: Bestimme den passenden Agent-Typ und Ergebnis-Typ.\n\n"
    "Agent-Typen: coder, researcher, writer, ops\n"
    "Ergebnis-Typen: recherche, guide, cheat-sheet, code, report\n\n"
    "Antworte NUR mit JSON:\n"
    '- quick_reply: {"type": "quick_reply", "answer": "<deine Antwort>"}\n'
    '- task: {"type": "task", "agent": "<typ>", "result_type": "<typ>", "title": "<kurzer Titel>"}'
)


class MainAgent:
    def __init__(self, llm, tools, db, obsidian_writer: ObsidianWriter,
                 telegram=None, ws_callback=None):
        self.llm = llm
        self.tools = tools
        self.db = db
        self.obsidian_writer = obsidian_writer
        self.telegram = telegram
        self.ws_callback = ws_callback
        self.active_agents: dict[str, dict] = {}
        self._chat_history: dict[str, list[dict]] = {}
        self._max_history = 20

    async def _build_context(self) -> str:
        """Build system context with current status for the classify prompt."""
        lines = []
        # Active agents
        active = self.active_agents
        if active:
            agents_str = ", ".join(f"{v['type']}: {v['task']}" for v in active.values())
            lines.append(f"Aktive Agents: {agents_str}")
        else:
            lines.append("Aktive Agents: keine")
        # Open tasks from DB
        try:
            open_tasks = await self.db.get_open_tasks()
            if open_tasks:
                tasks_str = ", ".join(f"#{t.id} {t.title} ({t.status.value})" for t in open_tasks[:10])
                lines.append(f"Offene Tasks DB ({len(open_tasks)}): {tasks_str}")
            else:
                lines.append("Offene Tasks DB: keine")
        except Exception:
            pass
        # Obsidian Inbox + Kanban
        try:
            inbox = self.obsidian_writer.kanban_path.parent / "Inbox.md"
            if inbox.exists():
                content = inbox.read_text(encoding="utf-8")
                todos = [l.strip() for l in content.splitlines() if l.strip().startswith("- [ ]")]
                if todos:
                    lines.append(f"Obsidian Inbox ({len(todos)} offen):")
                    for t in todos[:10]:
                        lines.append(f"  {t}")
                else:
                    lines.append("Obsidian Inbox: leer")
            kanban = self.obsidian_writer.kanban_path
            if kanban.exists():
                content = kanban.read_text(encoding="utf-8")
                backlog = []
                in_progress = []
                in_section = None
                for line in content.splitlines():
                    if line.startswith("## Backlog"):
                        in_section = "backlog"
                    elif line.startswith("## In Progress"):
                        in_section = "in_progress"
                    elif line.startswith("## "):
                        in_section = None
                    elif in_section and line.strip().startswith("- ["):
                        if in_section == "backlog":
                            backlog.append(line.strip())
                        elif in_section == "in_progress":
                            in_progress.append(line.strip())
                if backlog:
                    lines.append(f"Kanban Backlog ({len(backlog)}):")
                    for t in backlog[:5]:
                        lines.append(f"  {t}")
                if in_progress:
                    lines.append(f"Kanban In Progress ({len(in_progress)}):")
                    for t in in_progress[:5]:
                        lines.append(f"  {t}")
                if not backlog and not in_progress:
                    lines.append("Kanban: leer")
        except Exception:
            pass
        return "\n".join(lines)

    async def classify(self, message: str) -> dict:
        context = await self._build_context()
        system = _CLASSIFY_SYSTEM + f"\n\n## Aktueller System-Status\n{context}"
        response = await self.llm.chat(
            system_prompt=system,
            messages=[{"role": "user", "content": message}],
            temperature=0.1,
        )
        try:
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"type": "quick_reply", "answer": response}

    async def handle_message(self, text: str, chat_id: str = ""):
        classification = await self.classify(text)
        msg_type = classification.get("type", "quick_reply")

        if msg_type == "quick_reply":
            answer = classification.get("answer", "Ich habe keine Antwort.")
            if self.telegram:
                await self.telegram.send_message(answer[:4000], chat_id=chat_id or None)
        elif msg_type == "task":
            await self._handle_task(classification, text, chat_id)

    async def _handle_task(self, classification: dict, original_text: str, chat_id: str):
        agent_type = classification.get("agent", "ops")
        result_type = classification.get("result_type", "report")
        title = classification.get("title", original_text[:80])

        task = TaskData(title=title, description=original_text, status=TaskStatus.OPEN)
        task_id = await self.db.create_task(task)

        task_path = self.obsidian_writer.create_task_note(
            title=title, typ=result_type, agent=agent_type,
        )
        self.obsidian_writer.kanban_move(title, "backlog")
        # Remove from Inbox if it was there
        self.obsidian_writer.remove_from_inbox(original_text)

        if self.telegram:
            await self.telegram.send_message(
                f"👍 Arbeite daran: {title}\n🤖 Agent: {agent_type}",
                chat_id=chat_id or None,
            )

        await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, agent_type)
        self.obsidian_writer.kanban_move(title, "in_progress")
        self.obsidian_writer.update_task_status(task_path, "in_progress")

        # Build enriched task description for the SubAgent
        enriched_desc = (
            f"Aufgabe: {title}\n"
            f"Typ: {result_type}\n"
            f"Details: {original_text}\n\n"
            f"Erstelle ein ausführliches, strukturiertes Ergebnis auf Deutsch."
        )
        sub = SubAgent(
            agent_type=agent_type,
            task_description=enriched_desc,
            llm=self.llm,
            tools=self.tools,
            db=self.db,
        )
        self.active_agents[sub.agent_id] = {
            "type": agent_type,
            "task": title,
            "task_id": task_id,
            "sub_agent": sub,
        }

        if self.ws_callback:
            await self.ws_callback({
                "type": "agent_spawned",
                "agent_id": sub.agent_id,
                "agent_type": agent_type,
                "task": title,
            })

        try:
            result = await sub.run()

            result_path = self.obsidian_writer.write_result(
                title=title, typ=result_type, content=result,
            )

            await self.db.update_task_result(task_id, result[:5000])
            await self.db.update_task_status(task_id, TaskStatus.DONE)
            self.obsidian_writer.kanban_move(title, "done")
            self.obsidian_writer.update_task_status(task_path, "done")

            if self.telegram:
                summary = result[:500] if len(result) <= 500 else result[:497] + "..."
                await self.telegram.send_message(
                    f"✅ Fertig: {title}\n\n{summary}\n\n📁 Ergebnis in Obsidian",
                    chat_id=chat_id or None,
                )

            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_done",
                    "agent_id": sub.agent_id,
                    "agent_type": agent_type,
                    "task": title,
                })

        except Exception as e:
            await self.db.update_task_status(task_id, TaskStatus.FAILED)
            if self.telegram:
                await self.telegram.send_message(
                    f"❌ Fehler bei: {title}\n{str(e)[:300]}",
                    chat_id=chat_id or None,
                )
        finally:
            self.active_agents.pop(sub.agent_id, None)

    async def handle_scheduled(self, task: ScheduledTask):
        """Run a scheduled task through a SubAgent. Suppress Telegram/Obsidian for HEARTBEAT_OK."""
        sub = SubAgent(
            agent_type=task.agent,
            task_description=task.prompt,
            llm=self.llm,
            tools=self.tools,
            db=self.db,
        )
        try:
            result = await sub.run()
        except Exception as e:
            if self.telegram:
                await self.telegram.send_message(
                    f"❌ Scheduled Task Fehler: {task.name}\n{str(e)[:300]}"
                )
            return

        if result.startswith("HEARTBEAT_OK"):
            # Suppress Telegram and Obsidian — silent success
            return

        # Write result to Obsidian
        self.obsidian_writer.write_result(
            title=task.name,
            typ="report",
            content=result,
        )

        # Send Telegram summary
        if self.telegram:
            summary = result[:500] if len(result) <= 500 else result[:497] + "..."
            await self.telegram.send_message(
                f"🕐 Scheduled: {task.name}\n\n{summary}"
            )

    def get_status(self) -> dict:
        return {
            "active_agents": [
                {"agent_id": aid, "type": info["type"], "task": info["task"]}
                for aid, info in self.active_agents.items()
            ],
        }
