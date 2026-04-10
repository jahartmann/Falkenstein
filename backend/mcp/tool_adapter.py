"""Converts MCP tool schemas into CrewAI BaseTool instances."""
from __future__ import annotations
import logging
from typing import Any
from crewai.tools import BaseTool
from pydantic import BaseModel, create_model
from backend.mcp.config import ToolSchema

log = logging.getLogger(__name__)

# JSON Schema type → actual Python type for args_schema generation
_PY_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _make_tool_class(schema: ToolSchema, bridge: Any) -> type[BaseTool]:
    server_id = schema.server_id
    mcp_tool_name = schema.name
    tool_name = f"mcp_{server_id.replace('-', '_')}_{mcp_tool_name}"
    tool_desc = f"{schema.description} [{server_id}]"

    props = schema.input_schema.get("properties", {})
    required = set(schema.input_schema.get("required", []))

    if props:
        args_schema_fields: dict[str, tuple[Any, Any]] = {}
        for pname, pdef in props.items():
            json_type = pdef.get("type", "string")
            py_runtime_type = _PY_TYPE_MAP.get(json_type, str)
            if pname in required:
                args_schema_fields[pname] = (py_runtime_type, ...)
            else:
                args_schema_fields[pname] = (py_runtime_type | None, None)
        args_schema = create_model(f"{tool_name.title().replace('_', '')}Args", **args_schema_fields)
    else:
        args_schema = None

    def _call(kwargs: dict) -> str:
        result = bridge.call_tool_threadsafe(server_id, mcp_tool_name, kwargs)
        if result.success:
            return result.output
        return f"Error: {result.output}"

    def _run(self, **kwargs: Any) -> str:
        return _call({k: v for k, v in kwargs.items() if v is not None})

    annotations: dict[str, Any] = {
        "name": str,
        "description": str,
    }
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "__annotations__": annotations,
        "name": tool_name,
        "description": tool_desc,
        "_run": _run,
    }

    if args_schema is not None:
        annotations["args_schema"] = type[BaseModel]
        attrs["args_schema"] = args_schema

    return type("MCPDynamicTool", (BaseTool,), attrs)


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
