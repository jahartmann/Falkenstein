"""Dynamic Agent — personality-driven task executor replacing SubAgent."""
from __future__ import annotations
import uuid
from backend.agent_identity import AgentIdentity
from backend.tools.base import ToolRegistry


class DynamicAgent:
    def __init__(
        self,
        identity: AgentIdentity,
        task_description: str,
        llm,
        tools: ToolRegistry,
        db,
        soul_content: str = "",
        max_iterations: int = 10,
        progress_callback=None,
    ):
        self.identity = identity
        self.agent_id = f"agent_{identity.name.lower()}_{uuid.uuid4().hex[:8]}"
        self.task_description = task_description
        self.llm = llm
        self.tools = tools
        self.db = db
        self.soul_content = soul_content
        self.max_iterations = max_iterations
        self.done = False
        self._messages: list[dict] = []
        self._progress_callback = progress_callback

        # Register ALL tools (not just identity's priority list)
        self._tool_schemas = []
        self._tool_map: dict[str, object] = {}
        for tool in tools.all_tools():
            self._tool_map[tool.name] = tool
            self._tool_schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema(),
                },
            })

        # Sort schemas so priority tools come first
        priority_set = set(identity.tool_priority)
        self._tool_schemas.sort(
            key=lambda s: (0 if s["function"]["name"] in priority_set else 1)
        )

    async def run(self) -> str:
        system = self.identity.build_system_prompt(
            soul_content=self.soul_content,
            task_context=self.task_description,
        )
        self._messages = [{"role": "user", "content": self.task_description}]

        for _ in range(self.max_iterations):
            if self._tool_schemas:
                response = await self.llm.chat_with_tools(
                    system_prompt=system,
                    messages=self._messages,
                    tools=self._tool_schemas,
                )
            else:
                content = await self.llm.chat(system_prompt=system, messages=self._messages)
                response = {"content": content}

            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")

            if not tool_calls:
                self.done = True
                return content or "Task abgeschlossen (keine Ausgabe)."

            self._messages.append({
                "role": "assistant", "content": content, "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                args = func.get("arguments", {})
                tool_call_id = tc.get("id", tool_name)
                tool = self._tool_map.get(tool_name)
                if tool:
                    result = await tool.execute(args)
                    await self.db.log_tool_use(
                        self.agent_id, tool_name, args, result.output, result.success,
                    )
                    if self._progress_callback:
                        await self._progress_callback(tool_name, result.success)
                    output = result.output
                    if len(output) > 5000:
                        output = output[:4900] + "\n\n[... AUSGABE GEKUERZT ...]"
                    self._messages.append({
                        "role": "tool", "content": output, "tool_call_id": tool_call_id,
                    })
                else:
                    self._messages.append({
                        "role": "tool",
                        "content": f"Tool '{tool_name}' nicht verfuegbar.",
                        "tool_call_id": tool_call_id,
                    })

        self.done = True
        for msg in reversed(self._messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return "Max Iterationen erreicht — kein zusammenfassendes Ergebnis."
