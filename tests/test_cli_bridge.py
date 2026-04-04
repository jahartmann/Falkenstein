import pytest
import datetime
from unittest.mock import AsyncMock, patch
from backend.tools.cli_bridge import CLIBridgeTool, CLIBudgetTracker


@pytest.fixture
def budget():
    return CLIBudgetTracker(daily_budget=10000)


@pytest.fixture
def tool(tmp_path, budget):
    return CLIBridgeTool(
        workspace_path=tmp_path, budget_tracker=budget,
        provider="claude", timeout=10,
    )


# --- CLIBudgetTracker Tests ---

def test_budget_initial_state(budget):
    assert budget.used == 0
    assert budget.remaining == 10000
    assert not budget.over_budget
    assert not budget.warning_threshold


def test_budget_record_usage(budget):
    budget.record_usage(5000)
    assert budget.used == 5000
    assert budget.remaining == 5000


def test_budget_warning_at_80_pct(budget):
    budget.record_usage(8000)
    assert budget.warning_threshold
    assert not budget.over_budget


def test_budget_over(budget):
    budget.record_usage(10000)
    assert budget.over_budget
    assert budget.remaining == 0


def test_budget_resets_daily(budget):
    budget.record_usage(5000)
    # Simulate day change
    budget._today = "2020-01-01"
    assert budget.used == 0  # resets on check


def test_budget_accumulates(budget):
    budget.record_usage(3000)
    budget.record_usage(2000)
    assert budget.used == 5000


# --- CLIBridgeTool Tests ---

@pytest.mark.asyncio
async def test_no_prompt(tool):
    result = await tool.execute({"prompt": ""})
    assert not result.success
    assert "Prompt" in result.output


@pytest.mark.asyncio
async def test_over_budget_blocks(tool, budget):
    budget.record_usage(10000)
    result = await tool.execute({"prompt": "Write code"})
    assert not result.success
    assert "Budget" in result.output


@pytest.mark.asyncio
async def test_unknown_provider(tool):
    result = await tool.execute({"prompt": "test", "provider": "gpt"})
    assert not result.success
    assert "Unbekannter" in result.output


@pytest.mark.asyncio
async def test_cli_not_found(tool):
    async def mock_subprocess(*args, **kwargs):
        raise FileNotFoundError("No such file: 'claude'")

    with patch("backend.tools.cli_bridge.asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        result = await tool.execute({"prompt": "test"})
    assert not result.success
    assert "nicht gefunden" in result.output


@pytest.mark.asyncio
async def test_claude_call_success(tool, budget):
    async def mock_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.communicate.return_value = (b"Generated code here", b"")
        proc.returncode = 0
        return proc

    with patch("backend.tools.cli_bridge.asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        result = await tool.execute({"prompt": "Write a function"})
    assert result.success
    assert "Generated code" in result.output
    assert budget.used > 0


@pytest.mark.asyncio
async def test_context_included(tool):
    async def mock_subprocess(*args, **kwargs):
        # Capture the prompt arg
        proc = AsyncMock()
        proc.communicate.return_value = (b"result", b"")
        proc.returncode = 0
        return proc

    with patch("backend.tools.cli_bridge.asyncio.create_subprocess_exec", side_effect=mock_subprocess) as mock:
        await tool.execute({"prompt": "Fix bug", "context": "def broken():\n  pass"})
        # Verify subprocess was called
        mock.assert_called_once()


@pytest.mark.asyncio
async def test_cli_error_returncode(tool):
    async def mock_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"Error: rate limited")
        proc.returncode = 1
        return proc

    with patch("backend.tools.cli_bridge.asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        result = await tool.execute({"prompt": "test"})
    assert not result.success
    assert "rate limited" in result.output


@pytest.mark.asyncio
async def test_cli_timeout(tool):
    import asyncio as aio

    async def mock_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.communicate.side_effect = aio.TimeoutError()
        return proc

    with patch("backend.tools.cli_bridge.asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        result = await tool.execute({"prompt": "test"})
    assert not result.success
    assert "Timeout" in result.output


@pytest.mark.asyncio
async def test_budget_tracked_after_call(tool, budget):
    async def mock_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.communicate.return_value = (b"x" * 400, b"")
        proc.returncode = 0
        return proc

    with patch("backend.tools.cli_bridge.asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        await tool.execute({"prompt": "a" * 400})
    assert budget.used > 0


def test_schema(tool):
    schema = tool.schema()
    assert "prompt" in schema["properties"]
    assert "context" in schema["properties"]
    assert "provider" in schema["properties"]
    assert schema["required"] == ["prompt"]
