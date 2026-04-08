"""MCP (Model Context Protocol) integration for Falkenstein."""

from backend.mcp.bridge import MCPBridge, ToolResult
from backend.mcp.config import MCPServerConfig, ServerStatus, ToolSchema
from backend.mcp.registry import MCPRegistry
from backend.mcp.tool_adapter import create_mcp_tool, create_all_mcp_tools

__all__ = [
    "MCPBridge",
    "MCPRegistry",
    "MCPServerConfig",
    "ServerStatus",
    "ToolResult",
    "ToolSchema",
    "create_mcp_tool",
    "create_all_mcp_tools",
]
