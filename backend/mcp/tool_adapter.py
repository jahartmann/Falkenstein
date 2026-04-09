"""Converts MCP tool schemas into CrewAI BaseTool instances."""
from __future__ import annotations
import logging
from typing import Any
from crewai.tools import BaseTool
from backend.mcp.config import ToolSchema

log = logging.getLogger(__name__)


def _make_tool_class(schema: ToolSchema, bridge: Any) -> type[BaseTool]:
    server_id = schema.server_id
    mcp_tool_name = schema.name
    tool_name = f"mcp_{server_id.replace('-', '_')}_{mcp_tool_name}"
    tool_desc = f"{schema.description} [{server_id}]"

    class MCPDynamicTool(BaseTool):
        name: str = tool_name
        description: str = tool_desc

        def _run(self, **kwargs) -> str:
            result = bridge.call_tool_threadsafe(server_id, mcp_tool_name, kwargs)
            if result.success:
                return result.output
            return f"Error: {result.output}"

    return MCPDynamicTool


def create_mcp_tool(schema: ToolSchema, bridge: Any) -> BaseTool:
    cls = _make_tool_class(schema, bridge)
    return cls()


def create_all_mcp_tools(schemas: list[ToolSchema], bridge: Any) -> list[BaseTool]:
    tools = []
    for schema in schemas:
        try:
            tools.append(create_mcp_tool(schema, bridge))
        except Exception as e:
            log.error("Failed to create tool for %s/%s: %s",
                      schema.server_id, schema.name, e)
    return tools
