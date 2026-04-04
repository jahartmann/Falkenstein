from pydantic import BaseModel
from enum import Enum


class AgentRole(str, Enum):
    MAIN = "main"
    CODER = "coder"
    RESEARCHER = "researcher"
    WRITER = "writer"
    OPS = "ops"


class AgentState(str, Enum):
    IDLE = "idle"
    WORKING = "working"


class SubAgentType(str, Enum):
    CODER = "coder"
    RESEARCHER = "researcher"
    WRITER = "writer"
    OPS = "ops"


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


class Position(BaseModel):
    x: int = 0
    y: int = 0


class AgentData(BaseModel):
    id: str
    name: str
    role: AgentRole
    state: AgentState = AgentState.IDLE
    position: Position = Position()
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
