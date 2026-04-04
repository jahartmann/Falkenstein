import asyncio
import json
import re
from pathlib import Path
from backend.sub_agent import SubAgent
from backend.obsidian_writer import ObsidianWriter
from backend.models import TaskData, TaskStatus
from backend.scheduler import ScheduledTask, Scheduler, _parse_frontmatter
from backend.memory.fact_memory import FactMemory, extract_and_store_facts
from backend.llm_router import LLMRouter

_ENRICH_PROMPT_SYSTEM = (
    "Du bist ein Prompt-Engineer. Der Nutzer gibt dir eine kurze Aufgabenbeschreibung "
    "für einen wiederkehrenden KI-Agenten. Deine Aufgabe:\n\n"
    "1. Wandle die kurze Anweisung in einen ausführlichen, klaren Prompt um\n"
    "2. Der Prompt soll dem Agenten genau sagen, was er tun soll\n"
    "3. Definiere Struktur und Format der erwarteten Ausgabe\n"
    "4. Füge sinnvolle Aspekte hinzu, die der Nutzer meinen könnte\n"
    "5. Schreibe auf Deutsch\n\n"
    "Antworte NUR mit dem fertigen Prompt-Text (kein JSON, keine Erklärung)."
)

_SCHEDULE_META_SYSTEM = (
    "Du analysierst eine Aufgabenbeschreibung für einen wiederkehrenden Task und bestimmst:\n"
    "1. schedule: Deutsche Schedule-Angabe (z.B. 'täglich 08:00', 'alle 30 Minuten', "
    "'Mo-Fr 09:00', 'wöchentlich montag 10:00')\n"
    "2. agent: Passender Agent-Typ (coder/researcher/writer/ops)\n"
    "3. name: Kurzer, prägnanter Name für den Task\n"
    "4. active_hours: Zeitfenster wenn sinnvoll (z.B. '08:00-22:00'), oder leer\n\n"
    "Antworte NUR mit JSON:\n"
    '{"schedule": "...", "agent": "...", "name": "...", "active_hours": ""}'
)

# Load SOUL.md once at import time
_SOUL_PATH = Path(__file__).parent.parent / "SOUL.md"
_SOUL_CONTENT = _SOUL_PATH.read_text(encoding="utf-8") if _SOUL_PATH.exists() else ""

_CLASSIFY_SYSTEM = (
    "Du bist Falki, ein intelligenter Assistent-Router. Analysiere die Nachricht und entscheide:\n\n"
    "1. quick_reply — Direkt beantwortbar (Fragen, Status, Smalltalk, kurze Infos)\n"
    "2. action — Der Nutzer will, dass du etwas TUST (optimiere, erstelle, ändere, konfiguriere, "
    "installiere, repariere). Hier wird KEIN Report geschrieben — du führst einfach aus.\n"
    "3. content — Der Nutzer will ein ERGEBNIS sehen (Recherche, Analyse, Guide, Zusammenfassung, "
    "Code schreiben). Hier wird das Ergebnis nach Obsidian geschrieben.\n\n"
    "WICHTIG: Wenn der Nutzer sagt 'optimiere X', 'stelle X ein', 'mach X' → das ist eine ACTION.\n"
    "Nur wenn er 'recherchiere', 'analysiere', 'erstelle einen Report/Guide' sagt → das ist CONTENT.\n\n"
    "Bei quick_reply: Beantworte die Frage direkt.\n"
    "Bei action/content: Bestimme den passenden Agent-Typ.\n\n"
    "Agent-Typen: coder, researcher, writer, ops\n"
    "Ergebnis-Typen (nur bei content): recherche, guide, cheat-sheet, code, report\n\n"
    "Antworte NUR mit JSON:\n"
    '- quick_reply: {"type": "quick_reply", "answer": "<deine Antwort>"}\n'
    '- action: {"type": "action", "agent": "<typ>", "title": "<kurzer Titel>"}\n'
    '- content: {"type": "content", "agent": "<typ>", "result_type": "<typ>", "title": "<kurzer Titel>"}'
)


class MainAgent:
    def __init__(self, llm, tools, db, obsidian_writer: ObsidianWriter,
                 telegram=None, ws_callback=None, fact_memory: FactMemory | None = None,
                 scheduler: Scheduler | None = None,
                 llm_router: LLMRouter | None = None):
        self.llm = llm
        self.llm_router = llm_router
        self.tools = tools
        self.db = db
        self.obsidian_writer = obsidian_writer
        self.telegram = telegram
        self.ws_callback = ws_callback
        self.fact_memory = fact_memory
        self.scheduler = scheduler
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
        # Build system prompt: SOUL + facts + classify instructions + status
        parts = []
        if _SOUL_CONTENT:
            parts.append(_SOUL_CONTENT)
        if self.fact_memory:
            try:
                fact_block = await self.fact_memory.get_context_block()
                if fact_block:
                    parts.append(fact_block)
            except Exception:
                pass
        parts.append(_CLASSIFY_SYSTEM)
        parts.append(f"\n## Aktueller System-Status\n{context}")
        system = "\n\n".join(parts)
        llm = self.llm_router.get_client("classify") if self.llm_router else self.llm
        response = await llm.chat(
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

    # ── Telegram /commands ──────────────────────────────────────────
    _COMMANDS: dict[str, str] = {
        "/status": "Aktive Agents + offene Tasks",
        "/tasks": "Offene Tasks aus der DB",
        "/inbox": "Obsidian Inbox anzeigen",
        "/memory": "Gespeicherte Fakten anzeigen",
        "/schedule": "Schedules verwalten (list/create/edit/toggle/delete/run)",
        "/cancel": "Agent abbrechen — /cancel <agent_id>",
        "/help": "Alle Befehle anzeigen",
    }

    async def _cmd_help(self, chat_id: str) -> str:
        lines = ["*Verfügbare Befehle:*"]
        for cmd, desc in self._COMMANDS.items():
            lines.append(f"`{cmd}` — {desc}")
        return "\n".join(lines)

    async def _cmd_status(self, chat_id: str) -> str:
        lines = []
        # Active agents
        if self.active_agents:
            lines.append("*Aktive Agents:*")
            for aid, info in self.active_agents.items():
                lines.append(f"• `{aid}` — {info['type']}: {info['task']}")
        else:
            lines.append("Keine aktiven Agents.")
        # Open tasks
        try:
            open_tasks = await self.db.get_open_tasks()
            if open_tasks:
                lines.append(f"\n*Offene Tasks ({len(open_tasks)}):*")
                for t in open_tasks[:10]:
                    lines.append(f"• #{t.id} {t.title} ({t.status.value})")
            else:
                lines.append("\nKeine offenen Tasks.")
        except Exception:
            pass
        return "\n".join(lines)

    async def _cmd_tasks(self, chat_id: str) -> str:
        try:
            open_tasks = await self.db.get_open_tasks()
            if not open_tasks:
                return "Keine offenen Tasks."
            lines = [f"*Offene Tasks ({len(open_tasks)}):*"]
            for t in open_tasks[:20]:
                lines.append(f"• #{t.id} {t.title} — {t.status.value}")
            return "\n".join(lines)
        except Exception as e:
            return f"Fehler beim Laden der Tasks: {e}"

    async def _cmd_inbox(self, chat_id: str) -> str:
        try:
            inbox = self.obsidian_writer.kanban_path.parent / "Inbox.md"
            if not inbox.exists():
                return "Keine Inbox-Datei gefunden."
            content = inbox.read_text(encoding="utf-8")
            todos = [l.strip() for l in content.splitlines() if l.strip().startswith("- [ ]")]
            if not todos:
                return "Inbox ist leer."
            lines = [f"*Inbox ({len(todos)} Einträge):*"]
            for t in todos[:20]:
                lines.append(t)
            return "\n".join(lines)
        except Exception as e:
            return f"Fehler beim Laden der Inbox: {e}"

    async def _cmd_memory(self, chat_id: str) -> str:
        if not self.fact_memory:
            return "Memory-System nicht aktiv."
        try:
            facts = await self.fact_memory.get_all_active()
            if not facts:
                return "Noch keine Fakten gespeichert."
            count = len(facts)
            lines = [f"*Falkis Memory ({count} Fakten):*"]
            grouped: dict[str, list] = {}
            for f in facts[:30]:
                grouped.setdefault(f.category, []).append(f)
            for cat, items in grouped.items():
                lines.append(f"\n*{cat.title()}:*")
                for f in items:
                    lines.append(f"• [{f.id}] {f.content}")
            return "\n".join(lines)
        except Exception as e:
            return f"Fehler beim Laden des Memory: {e}"

    # ── /schedule sub-commands ───────────────────────────────────

    async def _cmd_schedule(self, args: str, chat_id: str) -> str:
        if not self.scheduler:
            return "Scheduler nicht aktiv."
        parts = args.strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        sub_args = parts[1] if len(parts) > 1 else ""

        dispatch = {
            "list": self._schedule_list,
            "create": self._schedule_create,
            "edit": self._schedule_edit,
            "toggle": self._schedule_toggle,
            "delete": self._schedule_delete,
            "run": self._schedule_run,
        }
        handler = dispatch.get(sub)
        if not handler:
            return (
                "Nutzung: /schedule <sub-command>\n"
                "`list` — Alle Schedules anzeigen\n"
                "`create <Beschreibung>` — Neuen Schedule erstellen\n"
                "`edit <Name> | <Änderung>` — Schedule bearbeiten\n"
                "`toggle <Name>` — An/Aus schalten\n"
                "`delete <Name>` — Schedule löschen\n"
                "`run <Name>` — Sofort ausführen"
            )
        return await handler(sub_args, chat_id)

    async def _schedule_list(self, args: str, chat_id: str) -> str:
        tasks = self.scheduler.get_all_tasks_info()
        if not tasks:
            return "Keine Schedules vorhanden."
        lines = [f"*Schedules ({len(tasks)}):*"]
        for t in tasks:
            status = "✅" if t["active"] else "⏸"
            next_r = t["next_run"][:16] if t["next_run"] else "—"
            lines.append(
                f"{status} *{t['name']}*\n"
                f"   Schedule: {t['schedule']} | Agent: {t['agent']}\n"
                f"   Nächster Lauf: {next_r}"
            )
        return "\n".join(lines)

    async def _enrich_prompt(self, user_instruction: str) -> str:
        """Turn a short user instruction into a detailed agent prompt."""
        response = await self.llm.chat(
            system_prompt=_ENRICH_PROMPT_SYSTEM,
            messages=[{"role": "user", "content": user_instruction}],
            temperature=0.3,
        )
        return response.strip()

    async def _extract_schedule_meta(self, user_instruction: str) -> dict:
        """Extract schedule, agent, name from user instruction via LLM."""
        response = await self.llm.chat(
            system_prompt=_SCHEDULE_META_SYSTEM,
            messages=[{"role": "user", "content": user_instruction}],
            temperature=0.1,
        )
        try:
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"schedule": "täglich 09:00", "agent": "researcher", "name": "Neuer Task", "active_hours": ""}

    async def _schedule_create(self, args: str, chat_id: str) -> str:
        if not args.strip():
            return "Was soll der Schedule tun? Beispiel:\n`/schedule create Erstelle täglich eine Analyse der aktuellen KI-News`"

        # Step 1: Extract metadata (schedule, agent, name)
        if self.telegram:
            await self.telegram.send_message("⏳ Erstelle Schedule...", chat_id=chat_id or None)

        meta, enriched = await asyncio.gather(
            self._extract_schedule_meta(args),
            self._enrich_prompt(args),
        )

        name = meta.get("name", "Neuer Task")
        schedule = meta.get("schedule", "täglich 09:00")
        agent = meta.get("agent", "researcher")
        active_hours = meta.get("active_hours", "")

        # Build the schedule file
        slug = re.sub(r"[^\w\s-]", "", name.lower())
        slug = re.sub(r"\s+", "-", slug.strip())[:60]
        filename = f"{slug}.md"
        filepath = self.scheduler.schedules_dir / filename

        frontmatter_lines = [
            "---",
            f"name: {name}",
            f"schedule: {schedule}",
            f"agent: {agent}",
            "active: true",
        ]
        if active_hours:
            frontmatter_lines.append(f"active_hours: {active_hours}")
        frontmatter_lines.append("---")

        file_content = "\n".join(frontmatter_lines) + f"\n\n{enriched}\n"

        # Write to Obsidian Schedules dir
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(file_content, encoding="utf-8")

        # Reload scheduler
        self.scheduler.reload_tasks()

        return (
            f"✅ Schedule erstellt: *{name}*\n"
            f"📋 Schedule: {schedule}\n"
            f"🤖 Agent: {agent}\n"
            f"📁 Datei: {filename}\n\n"
            f"*Generierter Prompt:*\n{enriched[:500]}"
        )

    async def _schedule_edit(self, args: str, chat_id: str) -> str:
        if "|" not in args:
            return "Format: `/schedule edit <Name> | <Änderung>`\nBeispiel: `/schedule edit Morning Briefing | schedule auf Mo-Fr 08:30 ändern`"

        name_part, change = args.split("|", 1)
        name_query = name_part.strip().lower()
        change = change.strip()

        # Find the task
        found = None
        for fname, task in self.scheduler.tasks.items():
            if name_query in task.name.lower() or name_query in fname.lower():
                found = task
                break
        if not found:
            return f"Schedule '{name_part.strip()}' nicht gefunden."

        # Read current file
        current_content = found.file_path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(current_content)

        # Let LLM figure out what to change
        edit_prompt = (
            f"Aktuelle Schedule-Konfiguration:\n"
            f"Name: {found.name}\n"
            f"Schedule: {found.schedule_str}\n"
            f"Agent: {found.agent}\n"
            f"Active Hours: {meta.get('active_hours', 'keine')}\n"
            f"Aktueller Prompt:\n{body[:1000]}\n\n"
            f"Gewünschte Änderung: {change}\n\n"
            f"Erstelle die aktualisierte Schedule-Datei im Markdown-Format mit YAML-Frontmatter. "
            f"Gib NUR den kompletten Dateiinhalt zurück, nichts anderes."
        )
        new_content = await self.llm.chat(
            system_prompt=(
                "Du bearbeitest Schedule-Dateien für einen KI-Assistenten. "
                "Format: YAML-Frontmatter (name, schedule, agent, active, active_hours) + Prompt-Body. "
                "Gib NUR den aktualisierten Dateiinhalt zurück."
            ),
            messages=[{"role": "user", "content": edit_prompt}],
            temperature=0.1,
        )

        # Validate it has frontmatter
        new_content = new_content.strip()
        if not new_content.startswith("---"):
            return f"Bearbeitung fehlgeschlagen — ungültiges Format. Bitte manuell in Obsidian anpassen."

        found.file_path.write_text(new_content + "\n", encoding="utf-8")
        self.scheduler.reload_tasks()

        # Show what changed
        new_meta, new_body = _parse_frontmatter(new_content)
        return (
            f"✏️ Schedule *{found.name}* aktualisiert:\n"
            f"Schedule: {new_meta.get('schedule', '?')}\n"
            f"Agent: {new_meta.get('agent', '?')}\n"
            f"Active Hours: {new_meta.get('active_hours', 'keine')}"
        )

    async def _schedule_toggle(self, args: str, chat_id: str) -> str:
        name_query = args.strip().lower()
        if not name_query:
            return "Welchen Schedule? `/schedule toggle <Name>`"
        for fname, task in self.scheduler.tasks.items():
            if name_query in task.name.lower() or name_query in fname.lower():
                new_state = self.scheduler.toggle_task(fname)
                status = "aktiviert ✅" if new_state else "pausiert ⏸"
                return f"Schedule *{task.name}* {status}."
        return f"Schedule '{args.strip()}' nicht gefunden."

    async def _schedule_delete(self, args: str, chat_id: str) -> str:
        name_query = args.strip().lower()
        if not name_query:
            return "Welchen Schedule? `/schedule delete <Name>`"
        for fname, task in self.scheduler.tasks.items():
            if name_query in task.name.lower() or name_query in fname.lower():
                if task.file_path.exists():
                    task.file_path.unlink()
                self.scheduler.reload_tasks()
                return f"🗑 Schedule *{task.name}* gelöscht."
        return f"Schedule '{args.strip()}' nicht gefunden."

    async def _schedule_run(self, args: str, chat_id: str) -> str:
        name_query = args.strip().lower()
        if not name_query:
            return "Welchen Schedule? `/schedule run <Name>`"
        for fname, task in self.scheduler.tasks.items():
            if name_query in task.name.lower() or name_query in fname.lower():
                if self.telegram:
                    await self.telegram.send_message(
                        f"▶️ Starte Schedule *{task.name}* manuell...",
                        chat_id=chat_id or None,
                    )
                # Run async — don't block the command response
                asyncio.create_task(self.handle_scheduled(task))
                return f"Schedule *{task.name}* gestartet."
        return f"Schedule '{args.strip()}' nicht gefunden."

    async def _cmd_cancel(self, args: str, chat_id: str) -> str:
        agent_id = args.strip()
        if not agent_id:
            if not self.active_agents:
                return "Keine aktiven Agents zum Abbrechen."
            lines = ["Welchen Agent abbrechen? Verfügbar:"]
            for aid, info in self.active_agents.items():
                lines.append(f"• `/cancel {aid}`")
            return "\n".join(lines)
        info = self.active_agents.get(agent_id)
        if not info:
            return f"Agent `{agent_id}` nicht gefunden."
        sub = info.get("sub_agent")
        if sub and hasattr(sub, "cancel"):
            sub.cancel()
        self.active_agents.pop(agent_id, None)
        # Update DB task status
        task_id = info.get("task_id")
        if task_id:
            try:
                await self.db.update_task_status(task_id, TaskStatus.FAILED)
            except Exception:
                pass
        return f"Agent `{agent_id}` abgebrochen."

    async def _handle_command(self, text: str, chat_id: str) -> str | None:
        """Parse and execute a /command. Returns response text, or None if not a command."""
        if not text.startswith("/"):
            return None
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/help": lambda: self._cmd_help(chat_id),
            "/status": lambda: self._cmd_status(chat_id),
            "/tasks": lambda: self._cmd_tasks(chat_id),
            "/inbox": lambda: self._cmd_inbox(chat_id),
            "/memory": lambda: self._cmd_memory(chat_id),
            "/schedule": lambda: self._cmd_schedule(args, chat_id),
            "/cancel": lambda: self._cmd_cancel(args, chat_id),
        }
        handler = handlers.get(cmd)
        if handler:
            return await handler()
        return None

    async def handle_message(self, text: str, chat_id: str = "",
                             agent_type_hint: str | None = None,
                             project_hint: str | None = None):
        # Check for /commands first (no LLM call needed)
        cmd_response = await self._handle_command(text, chat_id)
        if cmd_response is not None:
            if self.telegram:
                await self.telegram.send_message(cmd_response[:4000], chat_id=chat_id or None)
            return

        if agent_type_hint:
            # Inbox tag provided — skip LLM classification
            classification = {
                "type": "content",
                "agent": agent_type_hint,
                "title": text[:80],
                "result_type": "report",
            }
        else:
            classification = await self.classify(text)
        msg_type = classification.get("type", "quick_reply")

        if msg_type == "quick_reply":
            answer = classification.get("answer", "Ich habe keine Antwort.")
            if self.telegram:
                await self.telegram.send_message(answer[:4000], chat_id=chat_id or None)
            # Fire-and-forget: extract facts from this exchange
            if self.fact_memory:
                asyncio.create_task(
                    extract_and_store_facts(self.llm, self.fact_memory, text, answer)
                )
        elif msg_type == "action":
            asyncio.create_task(self._handle_action(classification, text, chat_id, project=project_hint))
            return classification.get("title", "Agent gestartet")
        elif msg_type == "content":
            asyncio.create_task(self._handle_content(classification, text, chat_id, project=project_hint))
            return classification.get("title", "Agent gestartet")
        elif msg_type == "task":
            asyncio.create_task(self._handle_content(classification, text, chat_id, project=project_hint))
            return classification.get("title", "Agent gestartet")

    def _get_llm_for(self, task_type: str):
        """Get the right LLM for a task type via router, fallback to default."""
        if self.llm_router:
            return self.llm_router.get_client(task_type)
        return self.llm

    def _build_system_context(self) -> str:
        """Build system knowledge block so SubAgents know about the environment."""
        vault = self.obsidian_writer.vault
        schedules_dir = ""
        if self.scheduler:
            schedules_dir = str(self.scheduler.schedules_dir)
        return (
            f"## Systemwissen\n"
            f"- Obsidian Vault: {vault}\n"
            f"- Schedules-Verzeichnis: {schedules_dir}\n"
            f"- Schedule-Format: YAML-Frontmatter (name, schedule, agent, active, active_hours) + Prompt-Body\n"
            f"- Kanban: {self.obsidian_writer.kanban_path}\n"
            f"- Inbox: {self.obsidian_writer.inbox_path}\n"
            f"- Konfiguration: .env im Projektverzeichnis\n"
            f"- Du kannst Dateien direkt lesen und schreiben mit deinen Tools.\n"
            f"- Wenn du etwas nicht weißt oder keinen Zugriff hast, frag den Nutzer.\n"
        )

    async def _handle_action(self, classification: dict, original_text: str, chat_id: str, project: str | None = None):
        """Handle action tasks — execute and report back, NO Obsidian report."""
        try:
            agent_type = classification.get("agent", "ops")
            title = classification.get("title", original_text[:80])

            task = TaskData(title=title, description=original_text, status=TaskStatus.OPEN)
            task_id = await self.db.create_task(task)

            if self.telegram:
                await self.telegram.send_message(
                    f"👍 Mache ich: {title}",
                    chat_id=chat_id or None,
                )

            await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, agent_type)

            sys_context = self._build_system_context()
            enriched_desc = (
                f"{sys_context}\n"
                f"Aufgabe: {title}\n"
                f"Details: {original_text}\n\n"
                f"WICHTIG: Führe die Aufgabe direkt aus. Nutze deine Tools um Dateien zu lesen, "
                f"zu bearbeiten und Befehle auszuführen. Schreibe KEINEN Report oder Guide — "
                f"tu einfach was verlangt wird. Antworte am Ende kurz was du gemacht hast."
            )
            sub = SubAgent(
                agent_type=agent_type,
                task_description=enriched_desc,
                llm=self._get_llm_for("action"),
                tools=self.tools,
                db=self.db,
            )
            self.active_agents[sub.agent_id] = {
                "type": agent_type, "task": title,
                "task_id": task_id, "sub_agent": sub,
            }

            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_spawned", "agent_id": sub.agent_id,
                    "agent_type": agent_type, "task": title,
                })

            try:
                result = await sub.run()
                await self.db.update_task_result(task_id, result[:5000])
                await self.db.update_task_status(task_id, TaskStatus.DONE)

                if self.telegram:
                    summary = result[:800] if len(result) <= 800 else result[:797] + "..."
                    await self.telegram.send_message(
                        f"✅ Erledigt: {title}\n\n{summary}",
                        chat_id=chat_id or None,
                    )

                if self.ws_callback:
                    await self.ws_callback({
                        "type": "agent_done", "agent_id": sub.agent_id,
                        "agent_type": agent_type, "task": title,
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
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error_msg = f"❌ Agent-Fehler: {e}"
            if self.telegram:
                await self.telegram.send_message(error_msg[:4000], chat_id=chat_id or None)

    async def _handle_content(self, classification: dict, original_text: str, chat_id: str, project: str | None = None):
        """Handle content tasks — research/write and save result to Obsidian."""
        try:
            agent_type = classification.get("agent", "researcher")
            result_type = classification.get("result_type", "report")
            title = classification.get("title", original_text[:80])

            task = TaskData(title=title, description=original_text, status=TaskStatus.OPEN)
            task_id = await self.db.create_task(task)

            task_path = self.obsidian_writer.create_task_note(
                title=title, typ=result_type, agent=agent_type,
            )
            self.obsidian_writer.kanban_move(title, "backlog")
            self.obsidian_writer.remove_from_inbox(original_text)

            if self.telegram:
                await self.telegram.send_message(
                    f"👍 Arbeite daran: {title}\n🤖 Agent: {agent_type}",
                    chat_id=chat_id or None,
                )

            await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, agent_type)
            self.obsidian_writer.kanban_move(title, "in_progress")
            self.obsidian_writer.update_task_status(task_path, "in_progress")

            sys_context = self._build_system_context()
            enriched_desc = (
                f"{sys_context}\n"
                f"Aufgabe: {title}\n"
                f"Typ: {result_type}\n"
                f"Details: {original_text}\n\n"
                f"Erstelle ein ausführliches, strukturiertes Ergebnis auf Deutsch."
            )
            sub = SubAgent(
                agent_type=agent_type,
                task_description=enriched_desc,
                llm=self._get_llm_for("content"),
                tools=self.tools,
                db=self.db,
            )
            self.active_agents[sub.agent_id] = {
                "type": agent_type, "task": title,
                "task_id": task_id, "sub_agent": sub,
            }

            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_spawned", "agent_id": sub.agent_id,
                    "agent_type": agent_type, "task": title,
                })

            try:
                result = await sub.run()

                self.obsidian_writer.write_result(
                    title=title, typ=result_type, content=result, project=project,
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
                        "type": "agent_done", "agent_id": sub.agent_id,
                        "agent_type": agent_type, "task": title,
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
        except asyncio.CancelledError:
            raise
        except Exception as e:
            error_msg = f"❌ Agent-Fehler: {e}"
            if self.telegram:
                await self.telegram.send_message(error_msg[:4000], chat_id=chat_id or None)

    async def handle_scheduled(self, task: ScheduledTask):
        """Run a scheduled task through a SubAgent. Suppress Telegram/Obsidian for HEARTBEAT_OK."""
        sub = SubAgent(
            agent_type=task.agent,
            task_description=task.prompt,
            llm=self._get_llm_for("scheduled"),
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
