from __future__ import annotations

"""
CrewAI BaseTool wrappers for Falkenstein-specific tools.
Bridges existing Tool executors (async execute(params: dict) -> ToolResult)
to CrewAI's synchronous _run() interface.
"""

import asyncio
from typing import Optional

from crewai.tools import BaseTool


def _run_executor(executor, params: dict) -> str:
    """Run an async executor synchronously and return output string."""
    result = asyncio.run(executor.execute(params))
    if result.success:
        return result.output
    return f"Error: {result.output}"


class CodeExecutorTool(BaseTool):
    name: str = "code_executor"
    description: str = (
        "Execute Python or shell code in a sandboxed workspace. "
        "Parameters: code (required), language ('python' or 'shell', default 'python')."
    )
    _executor: object = None

    def set_executor(self, executor) -> None:
        self._executor = executor

    def _run(self, code: str, language: str = "python") -> str:
        if self._executor is None:
            return "Error: executor not set"
        return _run_executor(self._executor, {"code": code, "language": language})


class ShellRunnerTool(BaseTool):
    name: str = "shell_runner"
    description: str = (
        "Run shell commands in the workspace directory. "
        "Destructive commands are blocked. Parameter: command (required)."
    )
    _executor: object = None

    def set_executor(self, executor) -> None:
        self._executor = executor

    def _run(self, command: str) -> str:
        if self._executor is None:
            return "Error: executor not set"
        return _run_executor(self._executor, {"command": command})


class SystemShellTool(BaseTool):
    name: str = "system_shell"
    description: str = (
        "Run shell commands anywhere on the system (not limited to workspace). "
        "Destructive commands targeting system directories are blocked. "
        "Parameters: command (required), cwd (optional)."
    )
    _executor: object = None

    def set_executor(self, executor) -> None:
        self._executor = executor

    def _run(self, command: str) -> str:
        if self._executor is None:
            return "Error: executor not set"
        return _run_executor(self._executor, {"command": command})


class ObsidianTool(BaseTool):
    name: str = "obsidian"
    description: str = (
        "Manage the Obsidian knowledge base: read/write notes, list folders, "
        "create daily reports and projects. "
        "Actions: read, write, append, list, daily_report, project, init_vault. "
        "Parameters: action (required), path, content, query."
    )
    _executor: object = None

    def set_executor(self, executor) -> None:
        self._executor = executor

    def _run(
        self,
        action: str,
        path: str = "",
        content: str = "",
        query: str = "",
    ) -> str:
        if self._executor is None:
            return "Error: executor not set"
        return _run_executor(
            self._executor,
            {"action": action, "path": path, "content": content, "query": query},
        )


class OllamaManagerTool(BaseTool):
    name: str = "ollama_manager"
    description: str = (
        "Manage Ollama models: list, pull, remove, show details, check running models. "
        "Actions: list, pull, remove, show, ps, status. "
        "Parameters: action (required), model (optional)."
    )
    _executor: object = None

    def set_executor(self, executor) -> None:
        self._executor = executor

    def _run(self, action: str, model: str = "") -> str:
        if self._executor is None:
            return "Error: executor not set"
        return _run_executor(self._executor, {"action": action, "model": model})


class SelfConfigTool(BaseTool):
    name: str = "self_config"
    description: str = (
        "Read and edit Falkenstein's own configuration files (.env, SOUL.md, etc.). "
        "Actions: list, read, write, env_get, env_set. "
        "Parameters: action (required), key, value."
    )
    _executor: object = None

    def set_executor(self, executor) -> None:
        self._executor = executor

    def _run(self, action: str, key: str = "", value: str = "") -> str:
        if self._executor is None:
            return "Error: executor not set"
        return _run_executor(self._executor, {"action": action, "key": key, "value": value})


class OpsExecutorTool(BaseTool):
    name: str = "ops_executor"
    description: str = (
        "Execute project operations using natural language plans or recipes. "
        "Supports: update, restart, logs, status, or any safe shell command. "
        "Parameter: plan (required) — description or command to execute."
    )
    _executor: object = None

    def set_executor(self, executor) -> None:
        self._executor = executor

    def _run(self, plan: str) -> str:
        if self._executor is None:
            return "Error: executor not set"
        return _run_executor(self._executor, {"command": plan})
