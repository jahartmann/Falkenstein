from pydantic import BaseModel
from enum import Enum


class AgentRole(str, Enum):
    PM = "pm"
    TEAM_LEAD = "team_lead"
    CODER_1 = "coder_1"
    CODER_2 = "coder_2"
    RESEARCHER = "researcher"
    WRITER = "writer"
    OPS = "ops"


class AgentState(str, Enum):
    IDLE_WANDER = "idle_wander"
    IDLE_TALK = "idle_talk"
    IDLE_COFFEE = "idle_coffee"
    IDLE_PHONE = "idle_phone"
    IDLE_SIT = "idle_sit"
    WORK_SIT = "work_sit"
    WORK_TYPE = "work_type"
    WORK_TOOL = "work_tool"
    WORK_REVIEW = "work_review"


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class MessageType(str, Enum):
    HANDOFF = "handoff"
    QUESTION = "question"
    REVIEW = "review"
    CHAT = "chat"


class AgentTraits(BaseModel):
    social: float = 0.5
    focus: float = 0.5
    confidence: float = 0.5
    patience: float = 0.5
    curiosity: float = 0.5
    leadership: float = 0.3


class AgentMood(BaseModel):
    energy: float = 0.8
    stress: float = 0.1
    motivation: float = 0.7
    frustration: float = 0.0


class Position(BaseModel):
    x: int = 0
    y: int = 0


class AgentData(BaseModel):
    id: str
    name: str
    role: AgentRole
    state: AgentState = AgentState.IDLE_SIT
    position: Position = Position()
    traits: AgentTraits = AgentTraits()
    mood: AgentMood = AgentMood()
    current_task_id: int | None = None


class TaskData(BaseModel):
    id: int | None = None
    title: str
    description: str
    status: TaskStatus = TaskStatus.OPEN
    assigned_to: str | None = None
    project: str | None = None
    parent_task_id: int | None = None
    result: str | None = None


class MessageData(BaseModel):
    id: int | None = None
    from_agent: str
    to_agent: str
    project: str | None = None
    type: MessageType
    content: str


class RelationshipData(BaseModel):
    agent_a: str
    agent_b: str
    trust: float = 0.5
    synergy: float = 0.5
    friendship: float = 0.5
    respect: float = 0.5
