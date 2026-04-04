from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    success: bool
    output: str


class Tool:
    name: str = ""
    description: str = ""
    # Tools declare if they mutate state (files, shell, etc.)
    mutating: bool = False

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

    def read_only_tools(self) -> list[Tool]:
        """Tools that don't mutate state — safe for concurrent execution."""
        return [t for t in self._tools.values() if not t.mutating]

    def mutating_tools(self) -> list[Tool]:
        """Tools that change state — must run serially."""
        return [t for t in self._tools.values() if t.mutating]

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

    async def execute_concurrent(self, calls: list[dict]) -> list[ToolResult]:
        """Execute multiple read-only tool calls concurrently, mutating ones serially.
        Claude Code pattern: read-only concurrent, mutating serial."""
        read_tasks = []
        mutating_calls = []

        for call in calls:
            func = call.get("function", {})
            tool = self.get(func.get("name", ""))
            if not tool:
                continue
            if tool.mutating:
                mutating_calls.append((tool, func.get("arguments", {})))
            else:
                read_tasks.append(tool.execute(func.get("arguments", {})))

        results = []
        # Run read-only tools concurrently
        if read_tasks:
            results.extend(await asyncio.gather(*read_tasks))

        # Run mutating tools serially
        for tool, args in mutating_calls:
            results.append(await tool.execute(args))

        return results
