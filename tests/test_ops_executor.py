import pytest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, patch
from backend.tools.ops_executor import OpsExecutor, CommandPlan


@pytest.fixture
def tool(tmp_path):
    return OpsExecutor(project_root=tmp_path)


# ── Recipes ──────────────────────────────────────────────────────────

def test_recipes_exist(tool):
    assert "update" in tool.OPS_RECIPES
    assert "restart" in tool.OPS_RECIPES
    assert "logs" in tool.OPS_RECIPES
    assert "status" in tool.OPS_RECIPES


def test_recipe_update_contains_git_pull(tool):
    update_cmds = tool.OPS_RECIPES["update"]
    assert any("git pull" in cmd for cmd in update_cmds)


# ── CommandPlan ──────────────────────────────────────────────────────

def test_command_plan_format():
    plan = CommandPlan(
        description="Update project",
        commands=["git pull", "pip install -r requirements.txt"],
        needs_confirmation=True,
        risk_level="medium",
        restart_after=False,
    )
    assert plan.description == "Update project"
    assert len(plan.commands) == 2
    assert plan.needs_confirmation is True
    assert plan.risk_level == "medium"
    assert plan.restart_after is False


def test_command_plan_defaults():
    plan = CommandPlan(description="test", commands=["ls"])
    assert plan.needs_confirmation is True
    assert plan.risk_level == "medium"
    assert plan.restart_after is False


# ── Safety ───────────────────────────────────────────────────────────

def test_safe_commands_allowed(tool):
    assert tool._is_safe_command("git status") is True
    assert tool._is_safe_command("git pull") is True
    assert tool._is_safe_command("ls -la") is True


def test_dangerous_commands_blocked(tool):
    assert tool._is_safe_command("rm -rf /") is False
    assert tool._is_safe_command("mkfs.ext4 /dev/sda") is False
    assert tool._is_safe_command("dd if=/dev/zero of=/dev/sda") is False


def test_additional_blocklist(tool):
    assert tool._is_safe_command("shutdown -h now") is False
    assert tool._is_safe_command("reboot") is False


# ── inspect_environment ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inspect_environment_returns_useful_output(tool, tmp_path):
    # Create some files so ls has output
    (tmp_path / "start.sh").write_text("#!/bin/bash\npython -m backend.main")
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    result = await tool.inspect_environment()
    assert isinstance(result, str)
    assert len(result) > 0
    # Should contain at least some system info
    assert "python" in result.lower() or "uname" in result.lower() or "start.sh" in result.lower()


# ── execute ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_safe_command(tool, tmp_path):
    (tmp_path / "hello.txt").write_text("world")
    result = await tool.execute({"command": "ls"})
    assert result.success
    assert "hello.txt" in result.output


@pytest.mark.asyncio
async def test_execute_blocked_command(tool):
    result = await tool.execute({"command": "rm -rf /"})
    assert not result.success
    assert "Blockiert" in result.output


@pytest.mark.asyncio
async def test_execute_with_cwd(tool, tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "test.txt").write_text("x")
    result = await tool.execute({"command": "ls", "cwd": str(sub)})
    assert result.success
    assert "test.txt" in result.output


# ── Tool metadata ────────────────────────────────────────────────────

def test_tool_name(tool):
    assert tool.name == "ops_executor"


def test_tool_mutating(tool):
    assert tool.mutating is True


def test_schema(tool):
    s = tool.schema()
    assert "command" in s["properties"]
