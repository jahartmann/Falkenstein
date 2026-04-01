from dataclasses import dataclass


@dataclass
class ToolResult:
    success: bool
    output: str


class Tool:
    name: str = ""
    description: str = ""

    async def execute(self, params: dict) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas_for_ollama(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema(),
                },
            }
            for t in self._tools.values()
        ]
