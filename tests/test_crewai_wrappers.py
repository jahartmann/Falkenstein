"""
Tests for CrewAI BaseTool wrappers in backend/tools/crewai_wrappers.py.
Checks: correct name, non-empty description, BaseTool inheritance,
and error behaviour when no executor is set.
"""

import pytest
from crewai.tools import BaseTool

from backend.tools.crewai_wrappers import (
    CodeExecutorTool,
    ShellRunnerTool,
    SystemShellTool,
    ObsidianTool,
    OllamaManagerTool,
    SelfConfigTool,
    OpsExecutorTool,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

ALL_WRAPPER_CLASSES = [
    CodeExecutorTool,
    ShellRunnerTool,
    SystemShellTool,
    ObsidianTool,
    OllamaManagerTool,
    SelfConfigTool,
    OpsExecutorTool,
]

EXPECTED_NAMES = {
    CodeExecutorTool: "code_executor",
    ShellRunnerTool: "shell_runner",
    SystemShellTool: "system_shell",
    ObsidianTool: "obsidian",
    OllamaManagerTool: "ollama_manager",
    SelfConfigTool: "self_config",
    OpsExecutorTool: "ops_executor",
}


# ── Name tests ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", ALL_WRAPPER_CLASSES)
def test_tool_name(cls):
    tool = cls()
    assert tool.name == EXPECTED_NAMES[cls]


# ── Description tests ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", ALL_WRAPPER_CLASSES)
def test_tool_has_description(cls):
    tool = cls()
    assert isinstance(tool.description, str)
    assert len(tool.description) > 0


# ── Inheritance tests ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", ALL_WRAPPER_CLASSES)
def test_tool_is_base_tool_instance(cls):
    tool = cls()
    assert isinstance(tool, BaseTool)


# ── No-executor error tests ───────────────────────────────────────────────────

def test_code_executor_no_executor():
    tool = CodeExecutorTool()
    result = tool._run(code="print('hi')")
    assert result.startswith("Error:")


def test_shell_runner_no_executor():
    tool = ShellRunnerTool()
    result = tool._run(command="echo hi")
    assert result.startswith("Error:")


def test_system_shell_no_executor():
    tool = SystemShellTool()
    result = tool._run(command="echo hi")
    assert result.startswith("Error:")


def test_obsidian_no_executor():
    tool = ObsidianTool()
    result = tool._run(action="list")
    assert result.startswith("Error:")


def test_ollama_manager_no_executor():
    tool = OllamaManagerTool()
    result = tool._run(action="list")
    assert result.startswith("Error:")


def test_self_config_no_executor():
    tool = SelfConfigTool()
    result = tool._run(action="list")
    assert result.startswith("Error:")


def test_ops_executor_no_executor():
    tool = OpsExecutorTool()
    result = tool._run(plan="status")
    assert result.startswith("Error:")


# ── set_executor smoke test ───────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, success, output):
        self.success = success
        self.output = output


class _FakeExecutor:
    async def execute(self, params: dict):
        return _FakeResult(success=True, output=f"ok:{params}")


def test_set_executor_delegates():
    tool = ShellRunnerTool()
    tool.set_executor(_FakeExecutor())
    result = tool._run(command="ls")
    assert result.startswith("ok:")


def test_set_executor_failure_returns_error_prefix():
    class _FailExecutor:
        async def execute(self, params: dict):
            return _FakeResult(success=False, output="something went wrong")

    tool = CodeExecutorTool()
    tool.set_executor(_FailExecutor())
    result = tool._run(code="bad code")
    assert result.startswith("Error:")
