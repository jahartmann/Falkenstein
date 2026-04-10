"""Converts MCP tool schemas into CrewAI BaseTool instances.

Dynamically generates _run() methods with typed parameter signatures
from MCP input_schema, so CrewAI auto-generates the correct args_schema.
"""
from __future__ import annotations
import logging
from typing import Any
from crewai.tools import BaseTool
from backend.mcp.config import ToolSchema

log = logging.getLogger(__name__)

# JSON Schema type → Python type name for code generation
_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}

# Default values per type for optional params
_DEFAULT_MAP = {
    "string": '""',
    "integer": "0",
    "number": "0.0",
    "boolean": "False",
    "array": "[]",
    "object": "{}",
}


def _make_tool_class(schema: ToolSchema, bridge: Any) -> type[BaseTool]:
    server_id = schema.server_id
    mcp_tool_name = schema.name
    tool_name = f"mcp_{server_id.replace('-', '_')}_{mcp_tool_name}"
    tool_desc = f"{schema.description} [{server_id}]"

    props = schema.input_schema.get("properties", {})
    required = set(schema.input_schema.get("required", []))

    if props:
        # Build _run signature: required params first, then optional
        req_params = []
        opt_params = []
        for pname, pdef in props.items():
            py_type = _TYPE_MAP.get(pdef.get("type", "string"), "str")
            default = _DEFAULT_MAP.get(pdef.get("type", "string"), '""')
            if pname in required:
                req_params.append(f"{pname}: {py_type}")
            else:
                opt_params.append(f"{pname}: {py_type} = {default}")

        params = ", ".join(["self"] + req_params + opt_params)
        # Collect all param names for forwarding
        all_names = list(props.keys())
        kwargs_dict = "{" + ", ".join(f'"{n}": {n}' for n in all_names) + "}"

        run_body = f"return _call({kwargs_dict})"
    else:
        params = "self, **kwargs"
        run_body = "return _call(kwargs)"

    def _call(kwargs: dict) -> str:
        result = bridge.call_tool_threadsafe(server_id, mcp_tool_name, kwargs)
        if result.success:
            return result.output
        return f"Error: {result.output}"

    # Build the whole class via exec so _run is in the class body (satisfies ABC)
    local_ns: dict[str, Any] = {"BaseTool": BaseTool, "_call": _call}
    class_code = "\n".join([
        "class MCPDynamicTool(BaseTool):",
        f"    name: str = {tool_name!r}",
        f"    description: str = {tool_desc!r}",
        f"    def _run({params}) -> str:",
        f"        {run_body}",
    ])
    exec(class_code, local_ns)  # noqa: S102
    return local_ns["MCPDynamicTool"]


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
