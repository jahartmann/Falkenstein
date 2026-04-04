from backend.models import AgentData, AgentRole, AgentState, SubAgentType


def test_agent_role_has_main():
    assert AgentRole.MAIN == "main"


def test_agent_role_has_sub_types():
    assert AgentRole.CODER == "coder"
    assert AgentRole.RESEARCHER == "researcher"
    assert AgentRole.WRITER == "writer"
    assert AgentRole.OPS == "ops"


def test_agent_state_simplified():
    assert AgentState.IDLE == "idle"
    assert AgentState.WORKING == "working"


def test_sub_agent_type():
    assert SubAgentType.CODER == "coder"
    assert SubAgentType.RESEARCHER == "researcher"
    assert SubAgentType.WRITER == "writer"
    assert SubAgentType.OPS == "ops"


def test_agent_data_no_traits_or_mood():
    agent = AgentData(id="pm", name="PM", role=AgentRole.MAIN)
    assert not hasattr(agent, "traits")
    assert not hasattr(agent, "mood")
    assert agent.state == AgentState.IDLE
