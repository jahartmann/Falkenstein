"""Pydantic models for MCP server configuration and status."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    id: str
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    auto_restart: bool = True


class ServerStatus(BaseModel):
    config: MCPServerConfig
    status: str = "stopped"
    pid: int | None = None
    tools_count: int = 0
    last_call: datetime | None = None
    last_error: str | None = None
    uptime_seconds: float = 0.0


class ToolSchema(BaseModel):
    name: str
    description: str
    server_id: str
    input_schema: dict = Field(default_factory=dict)
