import uuid
from backend.tools.base import ToolRegistry, ToolResult
from backend.prompts.subagent import build_subagent_prompt

SUB_AGENT_TOOLS: dict[str, list[str]] = {
    "coder": ["shell_runner", "system_shell", "code_executor", "cli_bridge", "self_config"],
    "researcher": ["web_research", "vision", "cli_bridge", "system_shell"],
    "writer": ["obsidian_manager", "cli_bridge"],
    "ops": ["shell_runner", "system_shell", "ollama_manager", "self_config", "cli_bridge", "obsidian_manager"],
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
        system = build_subagent_prompt(self.agent_type, self.task_description)
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
