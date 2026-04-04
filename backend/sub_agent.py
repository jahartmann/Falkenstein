import uuid
from backend.tools.base import ToolRegistry, ToolResult

SUB_AGENT_TOOLS: dict[str, list[str]] = {
    "coder": ["shell_runner", "system_shell", "code_executor", "cli_bridge", "self_config"],
    "researcher": ["web_research", "vision", "cli_bridge", "system_shell"],
    "writer": ["obsidian_manager", "cli_bridge"],
    "ops": ["shell_runner", "system_shell", "ollama_manager", "self_config", "cli_bridge", "obsidian_manager"],
}

_SYSTEM_PROMPTS: dict[str, str] = {
    "coder": (
        "Du bist ein Coding-Agent im Falkenstein-System. "
        "Du schreibst, debuggst und optimierst Code. "
        "Nutze deine Tools aktiv: shell_runner/system_shell für Befehle, code_executor zum Testen, "
        "self_config um Konfigurationsdateien zu lesen/schreiben. "
        "WICHTIG: Lies zuerst die relevanten Dateien bevor du Änderungen machst. "
        "Wenn du keinen Zugriff hast, sag das klar. Erfinde nichts. "
        "Antworte kurz und präzise auf Deutsch — nur was du gemacht hast."
    ),
    "researcher": (
        "Du bist ein Research-Agent im Falkenstein-System. "
        "Du recherchierst Themen gründlich im Web und analysierst Informationen. "
        "Nutze web_research für Suche und Scraping, system_shell für lokale Prüfungen. "
        "Strukturiere deine Ergebnisse klar mit Überschriften und Bulletpoints. "
        "Antworte auf Deutsch."
    ),
    "writer": (
        "Du bist ein Writer-Agent im Falkenstein-System. "
        "Du erstellst Texte, Dokumentation und strukturierte Inhalte. "
        "Nutze obsidian_manager um Dateien in der Obsidian-Vault zu lesen und schreiben. "
        "Antworte mit dem fertigen Text auf Deutsch."
    ),
    "ops": (
        "Du bist ein Ops-Agent im Falkenstein-System. "
        "Du verwaltest Systeme, konfigurierst Dienste und löst Probleme. "
        "Nutze deine Tools aktiv:\n"
        "- system_shell: Befehle überall auf dem System ausführen\n"
        "- shell_runner: Befehle im Workspace\n"
        "- ollama_manager: Ollama-Modelle verwalten (list, pull, remove, status)\n"
        "- self_config: .env, SOUL.md und andere Konfigdateien lesen/schreiben\n\n"
        "WICHTIG: Führe Aufgaben direkt aus. Lies zuerst den aktuellen Zustand, "
        "dann ändere was nötig ist. Schreibe KEINEN Guide oder Report — "
        "tu es einfach. Wenn du etwas nicht kannst, sag das klar statt einen "
        "Leitfaden zu schreiben. Antworte kurz was du gemacht hast."
    ),
}


class SubAgent:
    def __init__(self, agent_type: str, task_description: str, llm, tools: ToolRegistry, db,
                 max_iterations: int = 10, progress_callback=None):
        self.agent_type = agent_type
        self.agent_id = f"sub_{agent_type}_{uuid.uuid4().hex[:8]}"
        self.task_description = task_description
        self.llm = llm
        self.tools = tools
        self.db = db
        self.max_iterations = max_iterations
        self.done = False
        self._messages: list[dict] = []
        self._progress_callback = progress_callback

        allowed = SUB_AGENT_TOOLS.get(agent_type, [])
        self._tool_schemas = []
        self._tool_map: dict[str, object] = {}
        for name in allowed:
            tool = tools.get(name)
            if tool:
                self._tool_map[name] = tool
                self._tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.schema(),
                    },
                })

    async def run(self) -> str:
        system = _SYSTEM_PROMPTS.get(self.agent_type, _SYSTEM_PROMPTS["ops"])
        self._messages = [{"role": "user", "content": self.task_description}]

        for _ in range(self.max_iterations):
            if self._tool_schemas:
                response = await self.llm.chat_with_tools(
                    system_prompt=system, messages=self._messages, tools=self._tool_schemas,
                )
            else:
                content = await self.llm.chat(system_prompt=system, messages=self._messages)
                response = {"content": content}

            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")

            if not tool_calls:
                self.done = True
                return content or "Task abgeschlossen (keine Ausgabe)."

            self._messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args = func.get("arguments", {})
                tool_call_id = tc.get("id", tool_name)
                tool = self._tool_map.get(tool_name)
                if tool:
                    result = await tool.execute(args)
                    await self.db.log_tool_use(self.agent_id, tool_name, args, result.output, result.success)
                    if self._progress_callback:
                        await self._progress_callback(tool_name, result.success)
                    output = result.output
                    if len(output) > 5000:
                        output = output[:4900] + "\n\n[... AUSGABE GEKÜRZT, weitere Inhalte abgeschnitten ...]"
                    self._messages.append({"role": "tool", "content": output, "tool_call_id": tool_call_id})
                else:
                    self._messages.append({"role": "tool", "content": f"Tool '{tool_name}' nicht verfügbar.", "tool_call_id": tool_call_id})

        self.done = True
        # Find last assistant message (not tool result) for a coherent summary
        for msg in reversed(self._messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return "Max Iterationen erreicht — kein zusammenfassendes Ergebnis."
