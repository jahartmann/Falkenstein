from __future__ import annotations

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
    depends_on: list[int] = []  # task IDs that must be DONE before this runs
    result: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MessageData(BaseModel):
    id: int | None = None
    from_agent: str
    to_agent: str
    project: str | None = None
    type: MessageType
    content: str


class Memory(BaseModel):
    id: int | None = None
    layer: str          # 'user', 'self', 'relationship'
    category: str       # e.g. 'preferences', 'experiences', 'dynamics'
    key: str
    value: str
    confidence: float = 0.8
    source: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None


class Reminder(BaseModel):
    id: int | None = None
    chat_id: str
    text: str
    due_at: str
    delivered: bool = False
    follow_up: bool = False
    created_at: str | None = None


class PlannedTask(BaseModel):
    id: int | None = None
    name: str
    chat_id: str
    status: str = "pending"
    steps: list["TaskStep"] = []


class TaskStep(BaseModel):
    id: int | None = None
    planned_task_id: int | None = None
    step_order: int = 0
    agent_prompt: str = ""
    scheduled_at: str | None = None
    depends_on_step: int | None = None
    status: str = "pending"
    result: str | None = None
    completed_at: str | None = None


class DailyProfile(BaseModel):
    wake_up: str = "07:30"
    peak_hours: str = "10:00-13:00"
    lunch_break: str = "13:00-14:00"
    evening_active: str = "20:00-23:30"
    sleep: str = "00:00"
    weekend_shift_hours: float = 1.5
