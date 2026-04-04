import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.agent_identity import AgentIdentity
from backend.dynamic_agent import DynamicAgent


@pytest.fixture
def identity():
    return AgentIdentity(
        name="Mira",
        role="Recherche-Analystin",
        personality="Wissensdurstig",
        tool_priority=["web_research", "cli_bridge"],
    )


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat_with_tools = AsyncMock(return_value={"content": "Ergebnis der Recherche."})
    return llm


@pytest.fixture
def mock_tools():
    registry = MagicMock()
    tool = MagicMock()
    tool.name = "web_research"
    tool.description = "Web search"
    tool.schema.return_value = {"type": "object", "properties": {}}
    tool.execute = AsyncMock(return_value=MagicMock(success=True, output="search results"))
    registry.all_tools.return_value = [tool]
    registry.get.return_value = tool
    return registry


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.log_tool_use = AsyncMock()
    return db


def test_dynamic_agent_has_identity(identity, mock_llm, mock_tools, mock_db):
    agent = DynamicAgent(
        identity=identity,
        task_description="Recherchiere MLX",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    assert agent.identity.name == "Mira"
    assert "mira" in agent.agent_id


def test_dynamic_agent_has_all_tools(identity, mock_llm, mock_tools, mock_db):
    agent = DynamicAgent(
        identity=identity,
        task_description="Test",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    assert len(agent._tool_schemas) == 1  # mock has 1 tool


@pytest.mark.asyncio
async def test_dynamic_agent_run_no_tools(identity, mock_llm, mock_tools, mock_db):
    agent = DynamicAgent(
        identity=identity,
        task_description="Was ist MLX?",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    result = await agent.run()
    assert result == "Ergebnis der Recherche."
    assert agent.done


@pytest.mark.asyncio
async def test_dynamic_agent_run_with_tool_call(identity, mock_llm, mock_tools, mock_db):
    mock_llm.chat_with_tools = AsyncMock(side_effect=[
        {
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "web_research", "arguments": {"query": "MLX"}},
            }],
        },
        {"content": "MLX ist ein ML Framework von Apple."},
    ])
    agent = DynamicAgent(
        identity=identity,
        task_description="Recherchiere MLX",
        llm=mock_llm,
        tools=mock_tools,
        db=mock_db,
    )
    result = await agent.run()
    assert "MLX" in result
    assert mock_db.log_tool_use.called
