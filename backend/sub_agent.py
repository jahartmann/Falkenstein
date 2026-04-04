import uuid
from backend.tools.base import ToolRegistry, ToolResult

SUB_AGENT_TOOLS: dict[str, list[str]] = {
    "coder": ["shell_runner", "code_executor", "cli_bridge"],
    "researcher": ["web_research", "vision", "cli_bridge"],
    "writer": ["obsidian_manager", "cli_bridge"],
    "ops": ["shell_runner", "cli_bridge"],
}

_SYSTEM_PROMPTS: dict[str, str] = {
    "coder": (
        "Du bist ein Coding-Agent. Du schreibst, debuggst und optimierst Code. "
        "Nutze die verfügbaren Tools um die Aufgabe zu erledigen. "
        "Antworte am Ende mit einer klaren Zusammenfassung des Ergebnisses auf Deutsch."
    ),
    "researcher": (
        "Du bist ein Research-Agent. Du recherchierst Themen gründlich im Web. "
        "Nutze die verfügbaren Tools um Informationen zu sammeln. "
        "Antworte am Ende mit einem strukturierten Ergebnis auf Deutsch."
    ),
    "writer": (
        "Du bist ein Writer-Agent. Du erstellst Texte, Dokumentation und Reports. "
        "Nutze die verfügbaren Tools um Inhalte zu erstellen. "
        "Antworte am Ende mit dem fertigen Text auf Deutsch."
    ),
    "ops": (
        "Du bist ein Ops-Agent. Du verwaltest Systeme, führst Befehle aus und löst Infrastruktur-Probleme. "
        "Nutze die verfügbaren Tools um die Aufgabe zu erledigen. "
        "Antworte am Ende mit einer klaren Zusammenfassung auf Deutsch."
    ),
}


class SubAgent:
    def __init__(self, agent_type: str, task_description: str, llm, tools: ToolRegistry, db, max_iterations: int = 10):
        self.agent_type = agent_type
        self.agent_id = f"sub_{agent_type}_{uuid.uuid4().hex[:8]}"
        self.task_description = task_description
        self.llm = llm
        self.tools = tools
        self.db = db
        self.max_iterations = max_iterations
        self.done = False
        self._messages: list[dict] = []

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
                tool = self._tool_map.get(tool_name)
                if tool:
                    result = await tool.execute(args)
                    await self.db.log_tool_use(self.agent_id, tool_name, args, result.output, result.success)
                    self._messages.append({"role": "tool", "content": result.output[:5000]})
                else:
                    self._messages.append({"role": "tool", "content": f"Tool '{tool_name}' nicht verfügbar."})

        self.done = True
        last_content = self._messages[-1].get("content", "") if self._messages else ""
        return last_content or "Max Iterationen erreicht."
