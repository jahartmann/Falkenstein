from __future__ import annotations

import asyncio
import json
from pathlib import Path
from backend.obsidian_writer import ObsidianWriter
from backend.models import TaskData, TaskStatus
from backend.dynamic_agent import DynamicAgent
from backend.agent_identity import select_agent, load_agent_pool
from backend.memory.soul_memory import SoulMemory
from backend.review_gate import ReviewGate, ReviewResult
from backend.intent_engine import IntentEngine, ParsedIntent
from backend.smart_scheduler import SmartScheduler


from backend.memory.fact_memory import FactMemory, extract_and_store_facts
from backend.llm_router import LLMRouter
from backend.security.input_guard import InputGuard

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
    "4. multi_step — Der Nutzer will eine Aufgabe, die mehrere Schritte erfordert "
    "(z.B. 'Recherchiere X und schreibe dann einen Blogpost', 'Vergleiche A und B und erstelle eine Zusammenfassung'). "
    "Hier werden mehrere Agents nacheinander ausgeführt.\n\n"
    "5. ops_command — Der Nutzer will einen System-/Server-Befehl ausführen "
    "(git pull, cd, ls, server starten/stoppen, update, logs anzeigen, Ordner ansehen). "
    "Auch wenn er es umgangssprachlich formuliert ('pull mal', 'update den code', 'zeig mir den ordner', "
    "'starte das skript'). Nutze dafür das ops_executor Tool.\n\n"
    "WICHTIG: Wenn der Nutzer sagt 'optimiere X', 'stelle X ein', 'mach X' → das ist eine ACTION.\n"
    "Nur wenn er 'recherchiere', 'analysiere', 'erstelle einen Report/Guide' sagt → das ist CONTENT.\n\n"
    "Bei quick_reply: Beantworte die Frage direkt.\n"
    "Bei action/content: Bestimme den passenden Agent-Typ.\n\n"
    "Der passende Agent wird automatisch ausgewählt.\n"
    "Ergebnis-Typen (nur bei content): recherche, guide, cheat-sheet, code, report\n\n"
    "Antworte NUR mit JSON:\n"
    '- quick_reply: {"type": "quick_reply", "answer": "<deine Antwort>"}\n'
    '- action: {"type": "action", "agent": "<typ>", "title": "<kurzer Titel>"}\n'
    '- content: {"type": "content", "agent": "<typ>", "result_type": "<typ>", "title": "<kurzer Titel>"}\n'
    '- multi_step: {"type": "multi_step", "title": "<Titel>", "steps": [{"agent": "<typ>", "task": "<Beschreibung>"}, ...]}\n'
    '- ops_command: {"type": "ops_command", "command_hint": "<was der user will>", "title": "<kurzer Titel>"}\n'
)


class MainAgent:
    def __init__(self, llm, tools, db, obsidian_writer: ObsidianWriter | None = None,
                 telegram=None, ws_callback=None,
                 soul_memory: SoulMemory | None = None,
                 review_gate: ReviewGate | None = None,
                 intent_engine: IntentEngine | None = None,
                 scheduler: SmartScheduler | Scheduler | None = None,
                 llm_router: LLMRouter | None = None,
                 config_service=None,
                 fact_memory: FactMemory | None = None,  # legacy
                 allowlist=None):
        self.llm = llm
        self.llm_router = llm_router
        self.tools = tools
        self.db = db
        self.obsidian_writer = obsidian_writer
        self.telegram = telegram
        self.ws_callback = ws_callback
        self.soul_memory = soul_memory
        self.review_gate = review_gate
        self.intent_engine = intent_engine
        self.fact_memory = fact_memory  # legacy
        self.scheduler = scheduler
        self.config_service = config_service
        self.allowlist = allowlist
        self._input_guard = InputGuard()
        self.active_agents: dict[str, dict] = {}
        self._pending_tasks: dict[int, asyncio.Task] = {}
        self._agent_pool = load_agent_pool()

    async def _build_context(self) -> str:
        """Build system context from DB for the classify prompt."""
        parts = []
        # Active agents from self.active_agents dict
        if self.active_agents:
            lines = ["Aktive Agents:"]
            for aid, info in self.active_agents.items():
                lines.append(f"  - {aid}: {info.get('task', '?')}")
            parts.append("\n".join(lines))
        # Open tasks from DB
        try:
            open_tasks = await self.db.get_open_tasks()
            if open_tasks:
                lines = ["Offene Tasks:"]
                for t in open_tasks[:10]:
                    title = t.title if hasattr(t, 'title') else t.get('title', '?')
                    status = t.status if hasattr(t, 'status') else t.get('status', '?')
                    lines.append(f"  - [{status}] {title}")
                parts.append("\n".join(lines))
        except Exception:
            pass
        return "\n\n".join(parts) if parts else "Keine aktiven Tasks."

    async def classify(self, message: str, chat_id: str = "") -> dict:
        context = await self._build_context()
        # Build system prompt: SOUL + facts + classify instructions + status
        parts = []
        if _SOUL_CONTENT:
            parts.append(_SOUL_CONTENT)
        if self.soul_memory:
            try:
                memory_block = await self.soul_memory.get_context_block()
                if memory_block:
                    parts.append(memory_block)
            except Exception:
                pass
        elif self.fact_memory:
            try:
                fact_block = await self.fact_memory.get_context_block()
                if fact_block:
                    parts.append(fact_block)
            except Exception:
                pass
        # Episodic memory: similar past tasks
        try:
            past = await self.db.search_past_tasks(message, limit=3)
            if past:
                past_block = "## Ähnliche vergangene Aufgaben\n"
                for p in past:
                    past_block += f"- #{p['id']} {p['title']}: {p['result'][:200]}\n"
                parts.append(past_block)
        except Exception:
            pass
        parts.append(_CLASSIFY_SYSTEM)
        parts.append(f"\n## Aktueller System-Status\n{context}")
        system = "\n\n".join(parts)
        llm = self.llm_router.get_client("classify") if self.llm_router else self.llm
        history = await self.db.get_chat_history(chat_id or "default", limit=10)
        messages = history + [{"role": "user", "content": message}]
        response = await llm.chat(
            system_prompt=system,
            messages=messages,
            temperature=0.1,
        )
        try:
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Retry once with JSON format hint
            try:
                response2 = await llm.chat(
                    system_prompt=system,
                    messages=[
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": response},
                        {"role": "user", "content": "Antworte NUR mit validem JSON. Kein Text davor oder danach."},
                    ],
                    temperature=0.0,
                )
                text2 = response2.strip()
                if "{" in text2:
                    text2 = text2[text2.index("{"):text2.rindex("}") + 1]
                return json.loads(text2)
            except Exception:
                # Final fallback: treat as quick_reply with cleaned response
                clean = response[:500] if len(response) > 500 else response
                return {"type": "quick_reply", "answer": clean}

    # ── Telegram /commands ──────────────────────────────────────────
    _COMMANDS: dict[str, str] = {
        "/status": "Aktive Agents + offene Tasks",
        "/tasks": "Offene Tasks aus der DB",
        "/inbox": "Offene Tasks anzeigen",
        "/memory": "Gespeicherte Fakten anzeigen",
        "/schedule": "Schedules verwalten (list/create/edit/toggle/delete/run)",
        "/cancel": "Agent abbrechen — /cancel <agent_id>",
        "/task": "Task-Details anzeigen — /task <ID>",
        "/allow": "Chat-ID zur Allowlist hinzufügen (nur Owner) — /allow <chat_id>",
        "/revoke": "Chat-ID aus Allowlist entfernen (nur Owner) — /revoke <chat_id>",
        "/allowed": "Alle erlaubten Chat-IDs anzeigen",
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
        tasks = await self.db.get_open_tasks()
        if not tasks:
            return "Keine offenen Tasks."
        lines = ["Offene Tasks:"]
        for t in tasks:
            title = t.title if hasattr(t, 'title') else t.get('title', '?')
            lines.append(f"  - {title}")
        return "\n".join(lines)

    async def _cmd_task(self, args: str, chat_id: str) -> str:
        tid = args.strip()
        if not tid:
            return "Nutzung: /task <ID>"
        try:
            task = await self.db.get_task(int(tid))
            if not task:
                return f"Task #{tid} nicht gefunden."
            raw = task.result or "Kein Ergebnis"
            formatted = self._format_for_telegram(raw)
            header = f"*Task #{task.id}: {task.title}*\nStatus: {task.status.value}\n\n"
            full_text = header + formatted
            # Split into 4096-char chunks for Telegram
            if len(full_text) <= 4096:
                return full_text
            # Send first chunk as return, rest via telegram directly
            chunks = self._split_telegram_message(full_text)
            if self.telegram:
                for chunk in chunks[1:]:
                    await self.telegram.send_message(chunk, chat_id=chat_id or None)
            return chunks[0]
        except Exception as e:
            return f"Fehler: {e}"

    @staticmethod
    def _format_for_telegram(text: str) -> str:
        """Convert markdown to Telegram-compatible legacy Markdown."""
        import re
        lines = text.split("\n")
        out = []
        in_frontmatter = False
        for line in lines:
            stripped = line.strip()
            # Strip YAML frontmatter
            if stripped == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            # Headings → bold
            if stripped.startswith("#"):
                heading = re.sub(r"^#{1,6}\s*", "", stripped)
                out.append(f"*{heading}*")
            # **bold** → *bold* (Telegram legacy Markdown)
            elif "**" in line:
                out.append(re.sub(r"\*\*(.+?)\*\*", r"*\1*", line))
            else:
                out.append(line)
        result = "\n".join(out)
        # Strip [[wiki links]] → just the text
        result = re.sub(r"\[\[([^\]]+)\]\]", r"\1", result)
        return result

    @staticmethod
    def _split_telegram_message(text: str, max_len: int = 4096) -> list[str]:
        """Split text into Telegram-safe chunks, preferring line breaks."""
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Find last newline within limit
            split_at = text.rfind("\n", 0, max_len)
            if split_at <= 0:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def _cmd_memory(self, chat_id: str) -> str:
        if self.soul_memory:
            try:
                block = await self.soul_memory.get_context_block()
                if not block:
                    return "Noch keine Erinnerungen gespeichert."
                count = await self.soul_memory.count()
                return f"*Falkis Memory ({count} Einträge):*\n\n{block}"
            except Exception as e:
                return f"Fehler beim Laden des Memory: {e}"
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
            return "Bitte Beschreibung angeben: /schedule create <beschreibung>"

        meta, enriched = await asyncio.gather(
            self._extract_schedule_meta(args),
            self._enrich_prompt(args),
        )

        name = meta.get("name", "Neuer Task")
        schedule = meta.get("schedule", "täglich 09:00")
        agent_type = meta.get("agent", "researcher")
        active_hours = meta.get("active_hours", "")

        await self.db.create_schedule(
            name=name, schedule=schedule, agent_type=agent_type,
            prompt=enriched, active=True, active_hours=active_hours or None,
        )
        if self.scheduler:
            await self.scheduler.reload_tasks()

        return f"Schedule '{name}' erstellt ({schedule}, {agent_type})"

    async def _schedule_edit(self, args: str, chat_id: str) -> str:
        if not self.scheduler:
            return "Scheduler nicht aktiv."
        if "|" not in args:
            return "Format: `/schedule edit <Name> | <Änderung>`\nBeispiel: `/schedule edit Morning Briefing | schedule auf Mo-Fr 08:30 ändern`"

        name_part, change = args.split("|", 1)
        name_query = name_part.strip().lower()
        change = change.strip()

        # Find the task in scheduler.tasks (list[dict])
        task = next((t for t in self.scheduler.tasks if t["name"].lower() == name_query), None)
        if not task:
            # Fuzzy match
            task = next((t for t in self.scheduler.tasks if name_query in t["name"].lower()), None)
        if not task:
            return f"Schedule '{name_part.strip()}' nicht gefunden."

        # Let LLM figure out what to change — return JSON with updated fields
        edit_prompt = (
            f"Aktuelle Schedule-Konfiguration:\n"
            f"Name: {task['name']}\n"
            f"Schedule: {task['schedule']}\n"
            f"Agent: {task.get('agent_type', 'researcher')}\n"
            f"Active Hours: {task.get('active_hours', 'keine')}\n"
            f"Aktueller Prompt:\n{task.get('prompt', '')[:1000]}\n\n"
            f"Gewünschte Änderung: {change}\n\n"
            f"Gib NUR ein JSON zurück mit den geänderten Feldern. "
            f"Mögliche Felder: name, schedule, agent_type, prompt, active_hours.\n"
            f"Beispiel: {{\"schedule\": \"Mo-Fr 08:30\"}}"
        )
        response = await self.llm.chat(
            system_prompt=(
                "Du bearbeitest Schedule-Konfigurationen für einen KI-Assistenten. "
                "Gib NUR ein JSON mit den geänderten Feldern zurück, nichts anderes."
            ),
            messages=[{"role": "user", "content": edit_prompt}],
            temperature=0.1,
        )

        try:
            text = response.strip()
            if "{" in text:
                text = text[text.index("{"):text.rindex("}") + 1]
            updates = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return "Bearbeitung fehlgeschlagen — ungültiges LLM-Ergebnis."

        await self.db.update_schedule(task["id"], **updates)
        await self.scheduler.reload_tasks()

        return f"Schedule '{task['name']}' aktualisiert: {', '.join(f'{k}={v}' for k, v in updates.items())}"

    async def _schedule_toggle(self, args: str, chat_id: str) -> str:
        if not self.scheduler:
            return "Scheduler nicht aktiv."
        name = args.strip()
        task = next((t for t in self.scheduler.tasks if t["name"].lower() == name.lower()), None)
        if not task:
            return f"Schedule '{name}' nicht gefunden."
        new_state = await self.db.toggle_schedule(task["id"])
        await self.scheduler.reload_tasks()
        return f"Schedule '{name}' {'aktiviert' if new_state else 'pausiert'}."

    async def _schedule_delete(self, args: str, chat_id: str) -> str:
        if not self.scheduler:
            return "Scheduler nicht aktiv."
        name = args.strip()
        task = next((t for t in self.scheduler.tasks if t["name"].lower() == name.lower()), None)
        if not task:
            return f"Schedule '{name}' nicht gefunden."
        await self.db.delete_schedule(task["id"])
        await self.scheduler.reload_tasks()
        return f"Schedule '{name}' gelöscht."

    async def _schedule_run(self, args: str, chat_id: str) -> str:
        if not self.scheduler:
            return "Scheduler nicht aktiv."
        name = args.strip()
        task = next((t for t in self.scheduler.tasks if t["name"].lower() == name.lower()), None)
        if not task:
            return f"Schedule '{name}' nicht gefunden."
        await self.scheduler.mark_run(task)
        asyncio.create_task(self.handle_scheduled(task))
        return f"Schedule '{name}' manuell gestartet."

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
        # Cancel the asyncio task running this agent
        asyncio_task = info.get("asyncio_task")
        if asyncio_task and not asyncio_task.done():
            asyncio_task.cancel()
        self.active_agents.pop(agent_id, None)
        # Update DB task status
        task_id = info.get("task_id")
        if task_id:
            try:
                await self.db.update_task_status(task_id, TaskStatus.FAILED)
            except Exception:
                pass
        return f"Agent `{agent_id}` abgebrochen."

    # ── Allowlist /commands ──────────────────────────────────────────────────

    async def _cmd_allow(self, args: str, chat_id: str) -> str:
        """Add a chat_id to the allowlist. Owner-only."""
        if not self.allowlist:
            return "Allowlist nicht aktiv."
        if not self.allowlist.is_owner(chat_id):
            return "Nur der Owner kann Chat-IDs hinzufügen."
        target = args.strip()
        if not target:
            return "Nutzung: /allow <chat_id>"
        self.allowlist.add(target)
        return f"Chat-ID `{target}` zur Allowlist hinzugefügt."

    async def _cmd_revoke(self, args: str, chat_id: str) -> str:
        """Remove a chat_id from the allowlist. Owner-only."""
        if not self.allowlist:
            return "Allowlist nicht aktiv."
        if not self.allowlist.is_owner(chat_id):
            return "Nur der Owner kann Chat-IDs entfernen."
        target = args.strip()
        if not target:
            return "Nutzung: /revoke <chat_id>"
        try:
            self.allowlist.remove(target)
        except ValueError as exc:
            return str(exc)
        return f"Chat-ID `{target}` aus der Allowlist entfernt."

    async def _cmd_allowed(self, chat_id: str) -> str:
        """Show all allowed chat IDs."""
        if not self.allowlist:
            return "Allowlist nicht aktiv."
        ids = self.allowlist.list_allowed()
        lines = ["*Erlaubte Chat-IDs:*"]
        for cid in ids:
            suffix = " (Owner)" if self.allowlist.is_owner(cid) else ""
            lines.append(f"• `{cid}`{suffix}")
        return "\n".join(lines)

    async def _handle_command(self, text: str, chat_id: str) -> str | None:
        """Parse and execute a /command. Returns response text, or None if not a command."""
        # Handle ops confirmation callbacks
        if text.startswith("ops_confirm_") or text.startswith("ops_cancel_"):
            plan_id = text.split("_", 2)[-1]
            plans = getattr(self, "_pending_ops_plans", {})
            plan = plans.pop(plan_id, None)
            if not plan:
                return "Plan abgelaufen oder nicht gefunden."
            if text.startswith("ops_cancel_"):
                return "Ops abgebrochen."
            asyncio.create_task(self._execute_ops_plan(plan, chat_id))
            return "Wird ausgeführt..."
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
            "/task": lambda: self._cmd_task(args, chat_id),
            "/allow": lambda: self._cmd_allow(args, chat_id),
            "/revoke": lambda: self._cmd_revoke(args, chat_id),
            "/allowed": lambda: self._cmd_allowed(chat_id),
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

        text = text.strip()

        # Prompt injection guard — runs before any LLM call
        guard_result = self._input_guard.check_patterns(text)
        if guard_result.action == "BLOCK":
            block_msg = f"Anfrage blockiert: {guard_result.reason}"
            if self.telegram:
                await self.telegram.send_message(block_msg[:4000], chat_id=chat_id or None)
            try:
                await self.db.log_tool_use(
                    "main_agent", "input_guard",
                    {"text": text[:200]},
                    guard_result.reason,
                    False,
                )
            except Exception:
                pass
            return
        if guard_result.action == "WARN":
            try:
                await self.db.log_tool_use(
                    "main_agent", "input_guard_warn",
                    {"text": text[:200]},
                    guard_result.reason,
                    True,
                )
            except Exception:
                pass

        await self.db.append_chat(chat_id or "default", "user", text)

        # Activity logging
        if self.soul_memory:
            try:
                await self.soul_memory.log_activity(chat_id or "default")
            except Exception:
                pass

        # Intent engine parsing (before classification)
        intent = None
        if self.intent_engine and not agent_type_hint:
            try:
                daily_profile = None
                memory_context = ""
                if self.soul_memory:
                    daily_profile = await self.soul_memory.compute_daily_profile(chat_id or "default")
                    memory_context = await self.soul_memory.get_context_block()
                intent = await self.intent_engine.parse(
                    text, daily_profile=daily_profile, user_memory_context=memory_context,
                )
                if intent.type == "reminder" and self.scheduler:
                    time_expr = intent.time_expressions[0] if intent.time_expressions else ""
                    await self.scheduler.add_reminder(
                        chat_id=chat_id, text=intent.enriched_prompt, due_at=time_expr,
                    )
                    if self.telegram:
                        await self.telegram.send_message(
                            f"Erinnerung eingerichtet: {intent.enriched_prompt}",
                            chat_id=chat_id or None,
                        )
                    return
                if intent.type == "planned_task" and intent.steps and self.scheduler:
                    steps = [{"agent_prompt": s["prompt"], "scheduled_at": s.get("scheduled_at")} for s in intent.steps]
                    await self.scheduler.add_planned_task(
                        name=text[:80], chat_id=chat_id, steps=steps,
                    )
                    if self.telegram:
                        await self.telegram.send_message(
                            f"Geplant: {len(steps)} Schritte", chat_id=chat_id or None,
                        )
                    return
                if intent.needs_clarification and intent.confidence < 0.5:
                    if self.telegram:
                        await self.telegram.send_message(
                            intent.clarification_question or "Kannst du das genauer beschreiben?",
                            chat_id=chat_id or None,
                        )
                    return
            except Exception:
                pass

        if agent_type_hint:
            # Inbox tag provided — skip LLM classification
            classification = {
                "type": "content",
                "agent": agent_type_hint,
                "title": text[:80],
                "result_type": "report",
            }
        else:
            classification = await self.classify(text, chat_id=chat_id)
        msg_type = classification.get("type", "quick_reply")

        if msg_type == "quick_reply":
            answer = classification.get("answer", "Ich habe keine Antwort.")
            # Review gate for quick replies
            if self.review_gate:
                try:
                    review = await self.review_gate.review(
                        answer=answer, original_request=text, review_level="light",
                    )
                    if review.verdict == "REVISE" and review.revised:
                        answer = review.revised
                except Exception:
                    pass
            await self.db.append_chat(chat_id or "default", "assistant", answer)
            if self.telegram:
                await self.telegram.send_message(answer[:4000], chat_id=chat_id or None)
            # Fire-and-forget: extract memories from this exchange
            if self.soul_memory:
                asyncio.create_task(
                    self.soul_memory.extract_memories(self.llm, text, answer)
                )
            elif self.fact_memory:
                asyncio.create_task(
                    extract_and_store_facts(self.llm, self.fact_memory, text, answer)
                )
        elif msg_type == "action":
            task = asyncio.create_task(self._handle_action(classification, text, chat_id, project=project_hint))
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Agent gestartet")
        elif msg_type == "content":
            task = asyncio.create_task(self._handle_content(classification, text, chat_id, project=project_hint))
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Agent gestartet")
        elif msg_type == "task":
            task = asyncio.create_task(self._handle_content(classification, text, chat_id, project=project_hint))
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Agent gestartet")
        elif msg_type == "multi_step":
            task = asyncio.create_task(self._handle_multi_step(classification, text, chat_id, project=project_hint))
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Multi-Step gestartet")
        elif msg_type == "ops_command":
            task = asyncio.create_task(
                self._handle_ops_command(classification, text, chat_id)
            )
            self._pending_tasks[id(task)] = task
            task.add_done_callback(lambda t: self._pending_tasks.pop(id(t), None))
            return classification.get("title", "Ops gestartet")

    def _get_llm_for(self, task_type: str):
        """Get the right LLM for a task type via router, fallback to default."""
        if self.llm_router:
            return self.llm_router.get_client(task_type)
        return self.llm

    def _make_progress_callback(self, agent_id: str, title: str, chat_id: str = ""):
        _tool_labels = {
            "web_research": "Suche im Web", "shell_runner": "Führe Befehl aus",
            "system_shell": "Systembefehl", "code_executor": "Teste Code",
            "obsidian_manager": "Lese/Schreibe Obsidian", "vision": "Analysiere Bild",
            "ollama_manager": "Ollama-Verwaltung", "self_config": "Konfiguration",
            "cli_bridge": "Premium LLM", "file_manager": "Dateiverwaltung",
            "ops_executor": "Ops-Befehl",
        }
        async def callback(tool_name: str, success: bool):
            label = _tool_labels.get(tool_name, tool_name)
            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_progress", "agent_id": agent_id,
                    "tool": tool_name, "label": label, "success": success,
                })
        return callback

    def _build_system_context(self) -> str:
        """Build system knowledge block so SubAgents know about the environment."""
        parts = []
        if self.config_service:
            vault = self.config_service.get("obsidian_vault_path", "")
            if vault:
                parts.append(f"Obsidian Vault: {vault}")
        elif self.obsidian_writer and hasattr(self.obsidian_writer, "vault"):
            parts.append(f"Obsidian Vault: {self.obsidian_writer.vault}")
        parts.append("Ergebnisse werden automatisch in Obsidian gespeichert.")
        return "\n".join(parts)

    async def _handle_action(self, classification: dict, original_text: str, chat_id: str, project: str | None = None):
        """Handle action tasks — execute and report back, NO Obsidian report."""
        try:
            agent_type = classification.get("agent", "ops")
            title = classification.get("title", original_text[:80])

            task = TaskData(title=title, description=original_text, status=TaskStatus.OPEN)
            task_id = await self.db.create_task(task)

            if self.ws_callback:
                await self.ws_callback({"type": "task_created", "task_id": task_id, "title": title})

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
            identity = select_agent(original_text, self._agent_pool)
            sub = DynamicAgent(
                identity=identity,
                task_description=enriched_desc,
                llm=self._get_llm_for("action"),
                tools=self.tools,
                db=self.db,
                soul_content=_SOUL_CONTENT,
            )
            sub._progress_callback = self._make_progress_callback(sub.agent_id, title, chat_id)
            self.active_agents[sub.agent_id] = {
                "type": identity.role, "task": title,
                "task_id": task_id, "sub_agent": sub,
                "asyncio_task": asyncio.current_task(),
            }

            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_spawned", "agent_id": sub.agent_id,
                    "agent_type": identity.role, "task": title,
                })

            try:
                result = await sub.run()

                # Review gate before sending
                if self.review_gate:
                    try:
                        review = await self.review_gate.review(
                            answer=result, original_request=original_text,
                        )
                        if review.verdict == "REVISE" and review.revised:
                            result = review.revised
                    except Exception:
                        pass

                await self.db.update_task_result(task_id, result[:5000])
                await self.db.update_task_status(task_id, TaskStatus.DONE)

                if self.telegram:
                    summary = result[:500] + ("..." if len(result) > 500 else "")
                    if hasattr(self.telegram, 'send_message_with_buttons'):
                        await self.telegram.send_message_with_buttons(
                            f"Erledigt: {title}\n\n{summary}",
                            [[{"text": "Details", "callback_data": f"/task {task_id}"}]],
                            chat_id=chat_id or None,
                        )
                    else:
                        await self.telegram.send_message(
                            f"Erledigt: {title}\n\n{summary}",
                            chat_id=chat_id or None,
                        )

                if self.ws_callback:
                    await self.ws_callback({
                        "type": "agent_done", "agent_id": sub.agent_id,
                        "agent_type": identity.role, "task": title,
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

    def _obsidian_enabled(self) -> bool:
        """Check if Obsidian writing is enabled and available."""
        if not self.obsidian_writer:
            return False
        if self.config_service and not self.config_service.get_bool("obsidian_enabled"):
            return False
        return True

    async def _handle_content(self, classification: dict, original_text: str, chat_id: str, project: str | None = None):
        """Handle content tasks — research/write and save result to Obsidian."""
        try:
            agent_type = classification.get("agent", "researcher")
            result_type = classification.get("result_type", "report")
            title = classification.get("title", original_text[:80])

            # 1. Create DB task
            task = TaskData(title=title, description=original_text, status=TaskStatus.OPEN)
            task_id = await self.db.create_task(task)

            if self.ws_callback:
                await self.ws_callback({"type": "task_created", "task_id": task_id, "title": title})

            # 2. Send confirmation to Telegram
            if self.telegram:
                await self.telegram.send_message(
                    f"👍 Arbeite daran: {title}\n🤖 Agent: {agent_type}",
                    chat_id=chat_id or None,
                )

            await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS, agent_type)

            # 3. Run SubAgent
            sys_context = self._build_system_context()
            enriched_desc = (
                f"{sys_context}\n"
                f"Aufgabe: {title}\n"
                f"Typ: {result_type}\n"
                f"Details: {original_text}\n\n"
                f"Erstelle ein ausführliches, strukturiertes Ergebnis auf Deutsch."
            )
            identity = select_agent(original_text, self._agent_pool)
            sub = DynamicAgent(
                identity=identity,
                task_description=enriched_desc,
                llm=self._get_llm_for("content"),
                tools=self.tools,
                db=self.db,
                soul_content=_SOUL_CONTENT,
            )
            sub._progress_callback = self._make_progress_callback(sub.agent_id, title, chat_id)
            self.active_agents[sub.agent_id] = {
                "type": identity.role, "task": title,
                "task_id": task_id, "sub_agent": sub,
                "asyncio_task": asyncio.current_task(),
            }

            if self.ws_callback:
                await self.ws_callback({
                    "type": "agent_spawned", "agent_id": sub.agent_id,
                    "agent_type": identity.role, "task": title,
                })

            try:
                result = await sub.run()

                # Review gate before sending
                if self.review_gate:
                    try:
                        review = await self.review_gate.review(
                            answer=result, original_request=original_text,
                        )
                        if review.verdict == "REVISE" and review.revised:
                            result = review.revised
                    except Exception:
                        pass

                # 4. Update DB with result
                await self.db.update_task_result(task_id, result[:5000])
                await self.db.update_task_status(task_id, TaskStatus.DONE)

                # 5. Write result to Obsidian if enabled
                if self._obsidian_enabled():
                    try:
                        await asyncio.to_thread(
                            self.obsidian_writer.write_result,
                            title=title, typ=result_type, content=result, project=project,
                        )
                    except Exception as e:
                        print(f"Obsidian write failed: {e}")

                # 6. Send short summary to Telegram, full report in Obsidian
                if self.telegram:
                    # Extract first paragraph as summary (max 300 chars)
                    paragraphs = [p.strip() for p in result.split("\n\n") if p.strip() and not p.strip().startswith("#")]
                    summary = paragraphs[0][:300] if paragraphs else result[:300]
                    if len(summary) < len(paragraphs[0] if paragraphs else result):
                        summary += "..."
                    if hasattr(self.telegram, 'send_message_with_buttons'):
                        await self.telegram.send_message_with_buttons(
                            f"✅ Fertig: *{title}*\n\n{summary}\n\n📁 Vollständiger Bericht in Obsidian",
                            [[{"text": "📋 Details in Telegram", "callback_data": f"/task {task_id}"}]],
                            chat_id=chat_id or None,
                        )
                    else:
                        await self.telegram.send_message(
                            f"✅ Fertig: *{title}*\n\n{summary}\n\n📁 Vollständiger Bericht in Obsidian",
                            chat_id=chat_id or None,
                        )

                # 7. Broadcast WS event
                if self.ws_callback:
                    await self.ws_callback({
                        "type": "agent_done", "agent_id": sub.agent_id,
                        "agent_type": identity.role, "task": title,
                    })

                # 8. Check if any blocked tasks are now unblocked
                await self._dispatch_unblocked_tasks(chat_id)

            except Exception as e:
                await self.db.update_task_status(task_id, TaskStatus.FAILED)
                if self.telegram:
                    await self.telegram.send_message(
                        f"Fehler bei: {title}\n{str(e)[:300]}",
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

    async def _handle_multi_step(self, classification: dict, original_text: str, chat_id: str, project: str | None = None):
        """Handle multi-step tasks — run SubAgents sequentially, pass results between steps."""
        try:
            title = classification.get("title", original_text[:80])
            steps = classification.get("steps", [])
            if not steps:
                return await self._handle_content(classification, original_text, chat_id, project)

            task = TaskData(title=title, description=original_text, status=TaskStatus.OPEN)
            parent_task_id = await self.db.create_task(task)
            await self.db.update_task_status(parent_task_id, TaskStatus.IN_PROGRESS)

            if self.ws_callback:
                await self.ws_callback({"type": "task_created", "task_id": parent_task_id, "title": title})

            if self.telegram:
                step_list = "\n".join(f"  {i+1}. {s.get('task', '')[:60]}" for i, s in enumerate(steps))
                await self.telegram.send_message(f"📋 Plan: {title}\n{step_list}", chat_id=chat_id or None)

            accumulated_context = ""
            for i, step in enumerate(steps):
                agent_type = step.get("agent", "researcher")
                step_desc = step.get("task", "")

                if self.telegram:
                    await self.telegram.send_message(
                        f"⏳ Schritt {i+1}/{len(steps)}: {step_desc[:80]}",
                        chat_id=chat_id or None,
                    )

                enriched = (
                    f"{self._build_system_context()}\n"
                    f"Gesamtaufgabe: {title}\n"
                    f"Aktueller Schritt ({i+1}/{len(steps)}): {step_desc}\n"
                )
                if accumulated_context:
                    enriched += f"\nErgebnisse vorheriger Schritte:\n{accumulated_context[:3000]}\n"

                identity = select_agent(step_desc, self._agent_pool)
                sub = DynamicAgent(
                    identity=identity, task_description=enriched,
                    llm=self._get_llm_for("content"), tools=self.tools, db=self.db,
                    soul_content=_SOUL_CONTENT,
                )
                sub._progress_callback = self._make_progress_callback(sub.agent_id, step_desc, chat_id)

                if self.ws_callback:
                    await self.ws_callback({
                        "type": "agent_spawned", "agent_id": sub.agent_id,
                        "agent_type": identity.role, "task": f"[{i+1}/{len(steps)}] {step_desc[:60]}",
                    })

                try:
                    result = await sub.run()
                    accumulated_context += f"\n### Schritt {i+1}: {step_desc}\n{result[:2000]}\n"

                    if self.ws_callback:
                        await self.ws_callback({"type": "agent_done", "agent_id": sub.agent_id, "task": step_desc[:60]})
                except Exception as e:
                    accumulated_context += f"\n### Schritt {i+1}: FEHLER — {e}\n"
                    if self.ws_callback:
                        await self.ws_callback({"type": "agent_error", "agent_id": sub.agent_id, "error": str(e)})

            # Save final result
            await self.db.update_task_result(parent_task_id, accumulated_context[:5000])
            await self.db.update_task_status(parent_task_id, TaskStatus.DONE)

            if self._obsidian_enabled():
                try:
                    await asyncio.to_thread(
                        self.obsidian_writer.write_result,
                        title=title, typ="report", content=accumulated_context, project=project,
                    )
                except Exception:
                    pass

            # Review gate before sending
            if self.review_gate:
                try:
                    review = await self.review_gate.review(
                        answer=accumulated_context, original_request=original_text,
                    )
                    if review.verdict == "REVISE" and review.revised:
                        accumulated_context = review.revised
                except Exception:
                    pass

            if self.telegram:
                summary = accumulated_context[:500] + ("..." if len(accumulated_context) > 500 else "")
                await self.telegram.send_message(f"✅ Fertig: {title}\n\n{summary}", chat_id=chat_id or None)

        except Exception as e:
            if self.telegram:
                await self.telegram.send_message(f"❌ Multi-Step Fehler: {e}", chat_id=chat_id or None)

    async def _dispatch_unblocked_tasks(self, chat_id: str) -> None:
        """Check for OPEN tasks whose dependencies are now all DONE, and dispatch them."""
        try:
            blocked = await self.db.get_blocked_tasks()
            for task in blocked:
                if await self.db.dependencies_met(task):
                    dep_context = await self.db.get_dependency_results(task)
                    # Build a classification-like dict and dispatch
                    classification = {
                        "type": "content",
                        "agent": task.assigned_to or "researcher",
                        "result_type": "report",
                        "title": task.title,
                    }
                    if self.telegram:
                        dep_ids = ", ".join(f"#{d}" for d in task.depends_on)
                        await self.telegram.send_message(
                            f"🔓 *{task.title}* — Abhängigkeiten erfüllt ({dep_ids}), starte...",
                            chat_id=chat_id or None,
                        )
                    # Enrich description with dependency results
                    enriched_text = (
                        f"{task.description}\n\n"
                        f"## Ergebnisse der Vorgänger-Tasks:\n{dep_context}"
                    )
                    asyncio.create_task(
                        self._handle_content(classification, enriched_text, chat_id, project=task.project)
                    )
        except Exception as e:
            print(f"Dependency dispatch error: {e}")

    async def handle_scheduled(self, task: dict) -> None:
        """Run a scheduled task through a DynamicAgent with full visibility."""
        prompt = task.get("prompt", "")
        name = task.get("name", "scheduled")
        schedule_id = task.get("id")

        # 1. Create DB task
        db_task = TaskData(title=f"[Schedule] {name}", description=prompt, status=TaskStatus.OPEN)
        task_id = await self.db.create_task(db_task)

        if self.ws_callback:
            await self.ws_callback({"type": "task_created", "task_id": task_id, "title": f"[Schedule] {name}"})

        await self.db.update_task_status(task_id, TaskStatus.IN_PROGRESS)

        # 2. Register in active_agents
        llm = self._get_llm_for("scheduled")
        identity = select_agent(prompt, self._agent_pool)
        sub = DynamicAgent(
            identity=identity, task_description=prompt,
            llm=llm, tools=self.tools, db=self.db,
            soul_content=_SOUL_CONTENT,
        )
        sub._progress_callback = self._make_progress_callback(sub.agent_id, name, "")
        self.active_agents[sub.agent_id] = {"type": identity.role, "task": name, "task_id": task_id}

        # 3. Send WS event
        if self.ws_callback:
            await self.ws_callback({"type": "agent_spawned", "agent_id": sub.agent_id, "agent_type": identity.role, "task": name})

        if self.ws_callback:
            await self.ws_callback({"type": "schedule_fired", "schedule_id": schedule_id, "name": name})

        try:
            result = await sub.run()

            # 4. Update DB task
            await self.db.update_task_status(task_id, TaskStatus.DONE)
            await self.db.update_task_result(task_id, (result or "")[:5000])

            # 5. Update schedule result status
            if schedule_id:
                if result and result.strip().startswith("HEARTBEAT_OK"):
                    await self.db.update_schedule_result(schedule_id, "ok")
                else:
                    await self.db.update_schedule_result(schedule_id, "done")

            # 6. Send WS done event
            if self.ws_callback:
                await self.ws_callback({"type": "agent_done", "agent_id": sub.agent_id, "task": name})

            # Skip output for heartbeats
            if not result or result.strip().startswith("HEARTBEAT_OK"):
                return

            # 7. Write to Obsidian if enabled
            if self._obsidian_enabled():
                try:
                    await asyncio.to_thread(self.obsidian_writer.write_result, title=name, typ="Recherche", content=result)
                except Exception as e:
                    print(f"Obsidian write failed for scheduled '{name}': {e}")

            # 8. Send result to Telegram
            if self.telegram:
                summary = result[:500] + ("..." if len(result) > 500 else "")
                await self.telegram.send_message(f"Schedule '{name}':\n{summary}")

        except Exception as e:
            await self.db.update_task_status(task_id, TaskStatus.FAILED)
            await self.db.update_task_result(task_id, f"ERROR: {e}")
            if schedule_id:
                await self.db.update_schedule_result(schedule_id, "error", str(e))
            if self.ws_callback:
                await self.ws_callback({"type": "agent_error", "agent_id": sub.agent_id, "error": str(e)})
        finally:
            self.active_agents.pop(sub.agent_id, None)

    async def _handle_ops_command(self, classification: dict, original_text: str, chat_id: str):
        """Handle ops commands with Telegram confirmation."""
        try:
            command_hint = classification.get("command_hint", original_text)
            title = classification.get("title", command_hint[:80])

            ops_tool = self.tools.get("ops_executor")
            if not ops_tool:
                if self.telegram:
                    await self.telegram.send_message("OpsExecutor nicht verfügbar.", chat_id=chat_id or None)
                return

            # Let LLM inspect environment and generate command plan
            env_info = await ops_tool.inspect_environment()
            llm = self._get_llm_for("action")

            plan_prompt = (
                f"Du bist ein DevOps-Agent. Der Nutzer will: {original_text}\n\n"
                f"Aktuelle Umgebung:\n{env_info}\n\n"
                f"Projekt-Root: {ops_tool.project_root}\n"
                f"Start-Script: {ops_tool.project_root}/start.sh\n\n"
                f"Erstelle eine Liste von Shell-Befehlen um das auszuführen. "
                f"Beachte: Befehle laufen im Projekt-Root. Nutze relative Pfade. "
                f"Das venv ist unter ./venv/. Der Server wird mit ./start.sh gestartet.\n\n"
                f"Antworte NUR mit JSON:\n"
                f'{{"description": "Was wird gemacht", "commands": ["cmd1", "cmd2"], '
                f'"risk_level": "low|medium|high", "restart_after": true/false}}'
            )

            response = await llm.chat(
                system_prompt="Du generierst Shell-Befehle für einen Linux/macOS Server. Nur JSON zurückgeben.",
                messages=[{"role": "user", "content": plan_prompt}],
                temperature=0.1,
            )

            import json as _json
            try:
                text = response.strip()
                if "{" in text:
                    text = text[text.index("{"):text.rindex("}") + 1]
                plan_data = _json.loads(text)
            except (_json.JSONDecodeError, ValueError):
                if self.telegram:
                    await self.telegram.send_message(f"Konnte keinen Befehlsplan erstellen für: {title}", chat_id=chat_id or None)
                return

            commands = plan_data.get("commands", [])
            description = plan_data.get("description", title)
            risk = plan_data.get("risk_level", "medium")

            if not commands:
                if self.telegram:
                    await self.telegram.send_message("Keine Befehle generiert.", chat_id=chat_id or None)
                return

            # Ask for confirmation via Telegram
            plan_text = f"*Ops: {description}*\n\nBefehle:\n"
            for i, cmd in enumerate(commands, 1):
                plan_text += f"`{i}. {cmd}`\n"
            plan_text += f"\nRisiko: {risk}"

            import uuid
            plan_id = uuid.uuid4().hex[:8]
            self._pending_ops_plans = getattr(self, "_pending_ops_plans", {})
            self._pending_ops_plans[plan_id] = {
                "commands": commands,
                "description": description,
                "chat_id": chat_id,
                "restart_after": plan_data.get("restart_after", False),
            }

            if self.telegram:
                await self.telegram.send_message_with_buttons(
                    plan_text,
                    [[
                        {"text": "Ausführen", "callback_data": f"ops_confirm_{plan_id}"},
                        {"text": "Abbrechen", "callback_data": f"ops_cancel_{plan_id}"},
                    ]],
                    chat_id=chat_id or None,
                )
        except Exception as e:
            if self.telegram:
                await self.telegram.send_message(f"Ops-Fehler: {str(e)[:300]}", chat_id=chat_id or None)

    async def _execute_ops_plan(self, plan: dict, chat_id: str):
        """Execute a confirmed ops plan."""
        ops_tool = self.tools.get("ops_executor")
        if not ops_tool:
            return
        for cmd in plan["commands"]:
            if self.telegram:
                await self.telegram.send_message(f"`{cmd}`", chat_id=chat_id or None)
            result = await ops_tool._run_shell(cmd, str(ops_tool.project_root))
            if self.telegram:
                status = "ok" if "Exit" not in result and "Fehler" not in result else "FEHLER"
                await self.telegram.send_message(
                    f"[{status}] `{cmd}`\n```\n{result[:500]}\n```",
                    chat_id=chat_id or None,
                )
        summary = f"*Ops abgeschlossen: {plan['description']}*\n{len(plan['commands'])} Befehle ausgeführt."
        if self.telegram:
            await self.telegram.send_message(summary, chat_id=chat_id or None)

    def get_status(self) -> dict:
        return {
            "active_agents": [
                {"agent_id": aid, "type": info["type"], "task": info["task"]}
                for aid, info in self.active_agents.items()
            ],
        }
