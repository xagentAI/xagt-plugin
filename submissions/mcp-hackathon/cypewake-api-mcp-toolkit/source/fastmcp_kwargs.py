"""
fastmcp_kwargs.py · gives FastMCP a **kwargs-shaped tool (required for contract fidelity)

Why this file exists
------------------
The delivery spec requires this signature for tool #6:

    call_registered_api(name, operation_id, **params)

the parameter names are unknown at compile time, so they must pass through JSON Schema additionalProperties.
But FastMCP 4.0.3's Tool.from_function() and the FastMCP.tool() decorator both reject
any function carrying VAR_KEYWORD (measured error text):

    ValueError: Functions with **kwargs are not supported as tools

So the signature cannot be produced with the usual decorators. Both common workarounds were measured and ruled out:

    Tool.from_function(fn, parameters={...})  -> TypeError: unexpected keyword argument 'parameters'
    print(mcp.tool(parameters={...}))          -> TypeError: unexpected keyword argument 'parameters'

Solution
----
fastmcp.tools.Tool is a Pydantic model whose fields include parameters, and its execution entry point
is an overridable run(arguments: dict) -> ToolResult. So we subclass Tool directly:

  - declare additionalProperties=true through an explicit inputSchema;
  - expand arguments as kwargs verbatim inside run() and hand them to the target function.

Both call shapes pass over the MCP protocol stack (see tests/test_contract_compat.py):
    {"name":"petstore","operation_id":"getPetById","petId":1}      # literal contract form
    {"name":"petstore","operation_id":"getPetById","params":{...}} # equivalent form

This is a deliberate, bounded workaround: it touches argument encode/decode for one tool and no other FastMCP behavior.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from fastmcp.tools import Tool, ToolResult

# Lets callers pass operation parameters as an object under these keys (flat form still supported)
PARAMS_KEY = "params"


class KwargsTool(Tool):
    """A tool that expands arbitrary extra attributes into keyword arguments.

    `fn` accepts (name, operation_id, params=None, **extra);
    both call shapes collapse into one parameter dict.
    """

    fn: Callable[..., Any]

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            data = self.fn(**arguments)
            if inspect.isawaitable(data):
                data = await data
        except Exception as e:  # noqa: BLE001 - tool-level errors return as results instead of breaking the session
            data = {"error": f"{type(e).__name__}: {e}"}
        if not isinstance(data, dict):
            data = {"result": data}
        return ToolResult(structured_content=data)


def make_kwargs_tool(
    name: str,
    description: str,
    fn: Callable[..., Any],
    required: Optional[list[str]] = None,
    properties: Optional[dict[str, Any]] = None,
) -> KwargsTool:
    """Build a tool that accepts arbitrary extra attributes."""
    schema = {
        "type": "object",
        "properties": properties
        or {
            "name": {"type": "string", "description": "Name of the registered API"},
            "operation_id": {"type": "string", "description": "operation identifier"},
            PARAMS_KEY: {
                "type": "object",
                "description": "Path and query parameters bundled into one object (also accepted as top-level attributes)",
                "additionalProperties": True,
            },
        },
        "required": required or ["name", "operation_id"],
        "additionalProperties": True,
    }
    return KwargsTool(name=name, description=description, parameters=schema, fn=fn)


def merge_params(params: Optional[dict], extra: dict) -> dict:
    """Merge the params object with top-level flat parameters (flat wins, so callers can override)."""
    merged: dict[str, Any] = dict(params or {})
    merged.update({k: v for k, v in extra.items() if k != PARAMS_KEY})
    return merged
