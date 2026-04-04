import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.sub_agent import SubAgent, SUB_AGENT_TOOLS


def test_tool_sets_are_defined():
    assert "coder" in SUB_AGENT_TOOLS
    assert "researcher" in SUB_AGENT_TOOLS
    assert "writer" in SUB_AGENT_TOOLS
    assert "ops" in SUB_AGENT_TOOLS


def test_coder_has_correct_tools():
    assert "shell_runner" in SUB_AGENT_TOOLS["coder"]
    assert "code_executor" in SUB_AGENT_TOOLS["coder"]


def test_researcher_has_correct_tools():
    assert "web_research" in SUB_AGENT_TOOLS["researcher"]
    assert "vision" in SUB_AGENT_TOOLS["researcher"]


def test_writer_has_correct_tools():
    assert "obsidian_manager" in SUB_AGENT_TOOLS["writer"]


def test_ops_has_correct_tools():
    assert "shell_runner" in SUB_AGENT_TOOLS["ops"]


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(return_value={
        "content": "Done. Here is the result.",
    })
    return llm


@pytest.fixture
def mock_tools():
    registry = MagicMock()
    tool = AsyncMock()
    tool.execute = AsyncMock(return_value=MagicMock(success=True, output="tool output"))
    tool.schema.return_value = {"type": "object", "properties": {}}
    registry.get.return_value = tool
    return registry


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.log_tool_use = AsyncMock()
    return db


def test_sub_agent_creation(mock_llm, mock_tools, mock_db):
    agent = SubAgent(
        agent_type="coder",
        task_description="Write a backup script",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    assert agent.agent_type == "coder"
    assert agent.agent_id.startswith("sub_coder_")


@pytest.mark.asyncio
async def test_sub_agent_run_returns_result(mock_llm, mock_tools, mock_db):
    mock_llm.chat_with_tools = AsyncMock(return_value={
        "content": "The backup script is: rsync -av ...",
    })
    agent = SubAgent(
        agent_type="coder",
        task_description="Write a backup script",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    result = await agent.run()
    assert "rsync" in result
    assert agent.done


@pytest.mark.asyncio
async def test_sub_agent_max_iterations(mock_llm, mock_tools, mock_db):
    mock_llm.chat_with_tools = AsyncMock(return_value={
        "content": "",
        "tool_calls": [{"function": {"name": "shell_runner", "arguments": {"command": "ls"}}}],
    })
    agent = SubAgent(
        agent_type="coder",
        task_description="Infinite loop task",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
        max_iterations=3,
    )
    result = await agent.run()
    assert agent.done
    assert mock_llm.chat_with_tools.call_count <= 4
