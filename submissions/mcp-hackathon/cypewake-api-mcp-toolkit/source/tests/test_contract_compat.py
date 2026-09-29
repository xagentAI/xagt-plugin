"""
test_contract_compat.py · contract signature compatibility and tool inventory tests

Background: delivery spec item 6 requires call_registered_api(name, operation_id, **params),
while FastMCP 4.0.3 natively rejects a VAR_KEYWORD signature. This file locks in that the workaround works
and records the framework limitation itself as a test, so nobody rediscovers it the hard way.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from fastmcp import Client, FastMCP

import server
from fastmcp_kwargs import PARAMS_KEY, make_kwargs_tool, merge_params

# The 7 tools named in contract section 4 must match exactly
CONTRACT_REQUIRED_TOOLS = {
    "call_rest_api",
    "parse_openapi_spec",
    "list_operations",
    "generate_mcp_tool_code",
    "register_api_from_spec",
    "call_registered_api",
    "health_check",
}


def _tool_names() -> list[str]:
    async def run() -> list[str]:
        async with Client(server.mcp) as c:
            return [t.name for t in await c.list_tools()]

    return asyncio.run(run())


def test_all_contract_required_tools_exist():
    names = set(_tool_names())
    missing = CONTRACT_REQUIRED_TOOLS - names
    assert not missing, f"tools required by the contract are missing: {sorted(missing)}"


def test_fastmcp_natively_rejects_kwargs_tools():
    """Pin this framework limitation as an executable fact, documenting why the workaround is necessary."""
    probe = FastMCP("probe")

    with pytest.raises(ValueError, match=r"\*\*kwargs"):

        @probe.tool()
        async def bad(name: str, **params):  # pragma: no cover - only used to trigger the limitation
            return {}


def test_kwargs_tool_accepts_flat_and_nested_params():
    """Both the literal contract form (flat) and the equivalent form (params object) must work."""
    captured: dict = {}

    async def impl(name: str, operation_id: str, params=None, **extra) -> dict:
        captured.clear()
        captured.update({"name": name, "operation_id": operation_id, "merged": merge_params(params, extra)})
        return dict(captured)

    mcp = FastMCP("compat")
    mcp.add_tool(
        make_kwargs_tool(
            name="call_registered_api",
            description="test double",
            fn=impl,
        )
    )

    async def run() -> tuple[dict, dict, dict]:
        async with Client(mcp) as c:
            tools = await c.list_tools()
            flat = await c.call_tool(
                "call_registered_api", {"name": "petstore", "operation_id": "getPetById", "petId": 1}
            )
            nested = await c.call_tool(
                "call_registered_api",
                {"name": "petstore", "operation_id": "getPetById", PARAMS_KEY: {"petId": 2}},
            )
            return tools[0].input_schema, flat.data, nested.data

    schema, flat, nested = asyncio.run(run())

    assert schema["additionalProperties"] is True, "extra attributes must be allowed, otherwise the contract signature cannot be expressed"
    assert flat["merged"] == {"petId": 1}, "the flat form (literal contract) did not take effect"
    assert nested["merged"] == {"petId": 2}, "the params object form did not take effect"


def test_flat_params_override_nested():
    assert merge_params({"petId": 1, "x": 1}, {"petId": 9}) == {"petId": 9, "x": 1}


def test_kwargs_tool_surfaces_errors_as_result_not_crash():
    async def boom(**kwargs):
        raise RuntimeError("nope")

    mcp = FastMCP("compat-err")
    mcp.add_tool(make_kwargs_tool("boom", "d", boom, required=[]))

    async def run() -> dict:
        async with Client(mcp) as c:
            return (await c.call_tool("boom", {})).data

    assert "RuntimeError" in asyncio.run(run())["error"]


def test_health_check_shape():
    health = server.core.health_check()
    assert health["status"] == "ok"
    assert "version" in health and "registered_apis" in health


def test_server_tools_are_async():
    """Every regular tool must be a coroutine, so synchronous IO cannot block the event loop (the v1 defect)."""
    for name in ("verify_api", "call_rest_api", "parse_openapi_spec", "generate_mcp_bundle"):
        fn = getattr(server, name)
        assert inspect.iscoroutinefunction(fn), f"{name} is not a coroutine function"
