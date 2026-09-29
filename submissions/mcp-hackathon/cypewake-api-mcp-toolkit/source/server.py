"""
server.py · MCPForge v2 — API-to-MCP factory (X-Agent AI MCP Hackathon 2026 · Open Innovation track)

Maps directly onto the official flow: Build → Verify → MCPize → Monetize:

  BUILD     parse_openapi_spec / list_operations / call_rest_api
  VERIFY    verify_api (real 2xx assertion, not "got a response means pass")
  MCPize    generate_mcp_tool_code / generate_mcp_bundle (complete deployable package)
  MONETIZE  build_manifest / usage_report / simulate_invoice (real metering → invoice)
  Core      register_api_from_spec / call_registered_api / list_registered_apis / health_check

Compliance: pure API/MCP engineering. No security, audit, or on-chain surface — the disqualifying categories do not apply.

Run:
    pip install -r requirements.txt
    fastmcp dev server.py                                   # stdio inspector
    fastmcp run server.py --transport streamable-http --port 8080   # expose over HTTP
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

import core
import metering
from fastmcp_kwargs import make_kwargs_tool, merge_params

mcp = FastMCP("MCPForge")


# ============================== BUILD ====================================== #
@mcp.tool()
async def parse_openapi_spec(spec_source: str) -> dict:
    """[BUILD] Parse an OpenAPI/Swagger description and return a structured operation list.

    spec_source accepts three sources: http(s) URL, local file path, or JSON/YAML text pasted directly.
    Expands local $ref, merges path-level with operation-level parameters, and detects auth schemes and pagination.
    Each operation carries an input_schema (JSON Schema) ready for tool argument validation.
    """
    return await core.parse_openapi_spec_async(spec_source)


@mcp.tool()
async def list_operations(spec_source: str) -> str:
    """[BUILD] List every callable operation of an API (method / path / operation_id), flagged for auth, pagination, and deprecation."""
    return await core.list_operations_async(spec_source)


@mcp.tool()
async def call_rest_api(
    base_url: str,
    path: str,
    method: str = "GET",
    query: Optional[dict] = None,
    body: Optional[dict] = None,
) -> dict:
    """[BUILD] Generic REST call: reach any public API and return status code, latency, and a response preview (first 2000 chars).

    This is the online-callable capability itself — an agent can call any REST endpoint through it
    without having a spec first. Outbound requests carry SSRF protection (loopback, private, and link-local addresses are refused by default).
    """
    return await core.call_rest_api_async(base_url, path, method, query, body)


# ============================== VERIFY ===================================== #
@mcp.tool()
async def verify_api(
    spec_source: str,
    max_ops: int = 20,
    timeout: float = 8.0,
    concurrency: int = 8,
    scope: Optional[dict] = None,
) -> dict:
    """[VERIFY] Concurrently call the first max_ops operations for real and report a checkable pass/fail verdict.

    The verdict is real, not "got a response therefore reachable":
      2xx        → passed
      401/403         → auth_required (endpoint is up, needs credentials)
      404        → not_found
      429        → rate_limited
      other 4xx      → bad_request (placeholder parameters fail business validation)
      5xx        → server_error
      network/timeout → unreachable

    scope curates first so unrelated endpoints are not probed pointlessly.
    """
    return await core.verify_api_async(spec_source, max_ops, timeout, concurrency, scope)


# ============================== MCPize ===================================== #
@mcp.tool()
async def generate_mcp_tool_code(
    spec_source: str,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """[MCPize] Generate deployable FastMCP tool code for one operation.

    Generated code builds URLs from a template plus str.replace, so non-identifier placeholders like {account-id} are safe;
    it retries 3 times and reads auth headers. Save as server.py and run `fastmcp dev server.py`.
    """
    return await core.generate_tool_code_async(spec_source, operation_id, server_name, require_auth)


@mcp.tool()
async def generate_mcp_bundle(
    spec_source: str,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """[MCPize] Generate a complete deployable bundle from a spec, written to output_dir/name/.

    Produces server.py + requirements.txt (major version line pinned) + README.md + manifest.json,
    runnable out of the box with `fastmcp run`. Names and output directories are allowlisted and guarded against traversal.

    scope drives tool curation: export only GET operations tagged pet, or take the top 5 by intent,
    instead of pushing 100 endpoints into the agent context window.
    """
    return await core.generate_bundle_async(
        spec_source, name, server_name, require_auth, output_dir, scope
    )


@mcp.tool()
async def preview_scope(spec_source: str, scope: Optional[dict] = None) -> dict:
    """[MCPize] Preview scope curation: raw operation count vs. filtered tool count, plus recommended dimensions.

    Experiment here before generating a bundle, so nothing lands on disk repeatedly.
    """
    return await core.preview_scope_async(spec_source, scope)


# ============================== MONETIZE =================================== #
@mcp.tool()
async def build_manifest(
    name: str,
    spec_source: str = "",
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    base_url: str = "",
    currency: str = "",
    scope: Optional[dict] = None,
) -> dict:
    """[MONETIZE] Build a marketplace-ready listing: per-tool JSON Schema, auth requirements, capability stats, pricing tier and quota.

    The difference from "print a price table": every tool carries a verifiable input_schema,
    and pricing is wired to the real metered numbers from usage_report, so an invoice can be checked against it.

    scope can curate before the listing is built, keeping the published tool set small.
    """
    return await core.build_manifest_async(
        name,
        source=spec_source,
        base_url=base_url,
        category=category,
        pricing_tier=pricing_tier,
        description=description,
        currency=currency or None,
        scope=scope,
    )


@mcp.tool()
async def usage_report(api_name: str = "", days: int = 0) -> dict:
    """[MONETIZE] Report real usage: total calls, success rate, per-operation call counts and average latency.

    Numbers come from real metering on every call through this service (usage.json), not estimates.
    Leave api_name empty to aggregate all registered APIs; with days > 0, only APIs active in the last N days are counted.
    """
    return metering.get_meter().report(api_name or None, days or None)


@mcp.tool()
async def simulate_invoice(
    api_name: str,
    pricing_tier: str = "basic",
    basis: str = "actual",
    projected_calls: int = 0,
) -> dict:
    """[MONETIZE] Convert real usage into an invoice by tier: quota, overage calls, unit price, amount due, and per-operation lines.

    Billing basis:
      actual (default)    → bill the recorded real call count
      projected_monthly   → extrapolate the observed daily average to 30 days, for real quote modeling
    With projected_calls > 0, bill a specified call volume directly (capacity and quote modeling).

    This turns "commercializable" into a checkable number: register and call to produce real usage, then invoice it.
    """
    return metering.get_meter().simulate_invoice(api_name, pricing_tier, basis, projected_calls)


# ============================== core ======================================= #
@mcp.tool()
async def register_api_from_spec(name: str, spec_source: str) -> dict:
    """Register a full OpenAPI spec with this service (persisted to registry.json, atomic write, survives restart).

    After registration, call it by operation_id through call_registered_api;
    re-registering the same name returns overwrote_existing=true (never a silent overwrite).
    """
    result = await core._registry.register_async(name, spec_source)
    result["hint"] = "Call it through call_registered_api, or export a standalone service with generate_mcp_bundle."
    return result


async def _call_registered(name: str, operation_id: str, params: Optional[dict] = None, **extra) -> dict:
    """Implementation: accepts both a params object and top-level flat parameters, and records real usage."""
    merged = merge_params(params, extra)
    return await core._registry.call_async(name, operation_id, merged)


# The contract asks for call_registered_api(name, operation_id, **params);
# FastMCP has no native **kwargs support (see the measured notes in fastmcp_kwargs.py), so KwargsTool implements it.
mcp.add_tool(
    make_kwargs_tool(
        name="call_registered_api",
        description=(
            "Call one operation of a registered API, return the real response, and meter it."
            "Arguments may be flat (petId=1) or nested in a params object (params={\"petId\": 1});"
            "put the request body in params[\"__body__\"]."
        ),
        fn=_call_registered,
    )
)


@mcp.tool()
async def list_registered_apis() -> dict:
    """List every API registered with this service: name, base URL, operation count, auth schemes, registration time."""
    names = core._registry.list_names()
    items = []
    for n in names:
        entry = core._registry.get(n) or {}
        items.append(
            {
                "name": n,
                "base_url": entry.get("base_url"),
                "operation_count": len(entry.get("operations", [])),
                "auth_schemes": [s.get("name") for s in entry.get("auth_schemes", [])],
                "registered_at": entry.get("registered_at"),
            }
        )
    return {"count": len(items), "apis": items}


@mcp.tool()
async def health_check() -> dict:
    """Health check (the live evidence the submission requires). status=ok means the service is online and callable."""
    return core.health_check()


if __name__ == "__main__":
    mcp.run()
