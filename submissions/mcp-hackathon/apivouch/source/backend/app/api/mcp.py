from __future__ import annotations

import base64
import json
import math
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import (
    APP_VERSION,
    CORS_ORIGINS,
    MAX_MCP_REQUEST_BYTES,
    PUBLIC_BASE_URL,
)
from app.models.db import ProjectRow, engine
from app.schemas.api import (
    ExhaustiveClaimRequest,
    MCPRequest,
    OutcomeRequest,
    ReceiptLookupRequest,
)
from app.services.exhaustiveness import prove_exhaustive_claim
from app.services.importer import extract_endpoints
from app.services.outcomes import (
    execute_verified_outcome,
    load_receipt,
    receipt_authenticity,
    store_receipt,
    verify_receipt,
)
from app.services.runtime import execute_operation

router = APIRouter()
MODERN_VERSION = "2026-07-28"
LEGACY_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
META_PREFIX = "io.modelcontextprotocol/"


class _RequestBodyTooLarge(Exception):
    pass


async def _read_limited_body(request: Request) -> bytes:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_MCP_REQUEST_BYTES:
                raise _RequestBodyTooLarge
        except ValueError:
            # The ASGI server normally rejects malformed framing. Do not trust an
            # invalid value here; the streamed byte limit remains authoritative.
            pass

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_MCP_REQUEST_BYTES:
            raise _RequestBodyTooLarge
        body.extend(chunk)
    return bytes(body)

OUTCOME_TOOL = {
    "name": "apivouch_resolve_verified_outcome",
    "title": "Resolve a verified outcome",
    "description": "Call 2-5 independent public providers, enforce price and latency limits, reject invalid or disagreeing results, select the best eligible provider, and return a tamper-evident receipt.",
    "inputSchema": OutcomeRequest.model_json_schema(),
    "outputSchema": {"type": "object", "required": ["verdict", "attempts", "integrity"], "properties": {"verdict": {"type": "string", "enum": ["VERIFIED", "UNVERIFIED"]}, "result": {}, "selected_provider": {"type": ["string", "null"]}, "attempts": {"type": "array"}, "integrity": {"type": "object"}}},
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
}

RECEIPT_TOOL = {
    "name": "apivouch_verify_receipt",
    "title": "Verify a stored APIVouch receipt",
    "description": "Retrieve a stored outcome receipt and recompute its SHA-256 integrity fingerprint before returning it to the agent.",
    "inputSchema": ReceiptLookupRequest.model_json_schema(),
    "outputSchema": {
        "type": "object",
        "required": ["receipt", "integrity_valid", "authenticity"],
        "properties": {
            "receipt": {"type": "object"},
            "integrity_valid": {"type": "boolean"},
            "authenticity": {"type": "object", "required": ["state", "valid"], "properties": {
                "state": {"enum": ["unsigned", "signed", "invalid", "unavailable"]}, "valid": {"type": "boolean"}}},
        },
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
}


def _load_project(pid: str) -> tuple[ProjectRow, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    db = Session(engine, expire_on_commit=False)
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    try:
        repair_bundle = json.loads(row.repairs_json or "{}")
        if not isinstance(repair_bundle, dict):
            repair_bundle = {"changes": repair_bundle if isinstance(repair_bundle, list) else [], "contract": None}
        source_spec = json.loads(row.spec_json or "{}")
        spec = repair_bundle.get("contract") or source_spec
        tools = json.loads(row.tools_json or "[]")
    finally:
        db.close()
    return row, spec, tools, source_spec


def _result(request_id: str | int | None, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id: str | int | None, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _save_proof(pid: str, outcome: dict[str, Any]) -> None:
    db = Session(engine, expire_on_commit=False)
    row = db.get(ProjectRow, pid)
    if row:
        row.proof_json = json.dumps(outcome)
        db.add(row)
        db.commit()
    db.close()


async def capability_mcp(request: MCPRequest):
    """Product-level MCP server for APIVouch's verified-outcome capability."""
    if request.method == "initialize":
        requested_version = request.params.get("protocolVersion")
        supported = LEGACY_VERSIONS
        protocol_version = requested_version if requested_version in supported else "2025-06-18"
        return _result(request.id, {"protocolVersion": protocol_version, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "APIVouch Outcome Router", "version": APP_VERSION}, "instructions": "Resolve public API outcomes only when independent evidence satisfies the caller's constraints."})
    if request.method == "notifications/initialized":
        return Response(status_code=202)
    if request.method == "ping":
        return _result(request.id, {})
    if request.method == "tools/list":
        return _result(request.id, {"tools": [OUTCOME_TOOL, RECEIPT_TOOL]})
    if request.method == "tools/call":
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments") or {}
        if tool_name == OUTCOME_TOOL["name"]:
            try:
                body = OutcomeRequest.model_validate(arguments)
            except ValidationError as exc:
                return _error(request.id, -32602, "Invalid outcome request", {"detail": str(exc)[:500]})
            try:
                receipt = await execute_verified_outcome(body.model_dump())
            except ValueError as exc:
                return _error(request.id, -32602, "Invalid provider set", {"detail": str(exc)})
            store_receipt(receipt)
            return _result(request.id, {"content": [{"type": "text", "text": json.dumps(receipt, ensure_ascii=False)}], "structuredContent": receipt, "isError": receipt["verdict"] != "VERIFIED"})
        if tool_name == RECEIPT_TOOL["name"]:
            try:
                lookup = ReceiptLookupRequest.model_validate(arguments)
            except ValidationError as exc:
                return _error(request.id, -32602, "Invalid receipt lookup", {"detail": str(exc)[:500]})
            receipt = load_receipt(lookup.receipt_id)
            if receipt is None:
                return _error(request.id, -32004, "Receipt not found", {"receipt_id": lookup.receipt_id})
            outcome = {"receipt": receipt, "integrity_valid": verify_receipt(receipt), "authenticity": receipt_authenticity(receipt)}
            return _result(
                request.id,
                {
                    "content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False)}],
                    "structuredContent": outcome,
                    "isError": not outcome["integrity_valid"] or outcome["authenticity"]["state"] in {"invalid", "unavailable"},
                },
            )
        return _error(request.id, -32602, "Unknown tool", {"name": tool_name})
    return _error(request.id, -32601, "Method not found", {"method": request.method})


async def mcp_endpoint(pid: str, request: MCPRequest):
    _row, spec, tools, source_spec = _load_project(pid)
    if request.method == "initialize":
        requested_version = request.params.get("protocolVersion")
        supported = LEGACY_VERSIONS
        protocol_version = requested_version if requested_version in supported else "2025-06-18"
        return _result(
            request.id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "APIVouch Agent Adapter", "version": APP_VERSION},
                "instructions": "Generated read-only tools call the inspected upstream API through a bounded, schema-validating adapter.",
            },
        )
    if request.method == "notifications/initialized":
        return Response(status_code=202)
    if request.method == "ping":
        return _result(request.id, {})
    if request.method == "tools/list":
        return _result(request.id, {"tools": tools})
    if request.method == "tools/call":
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments") or {}
        tool = next((item for item in tools if item.get("name") == tool_name), None)
        if not tool:
            return _error(request.id, -32602, "Unknown tool", {"name": tool_name})
        if (tool.get("_meta") or {}).get("kind") == "exhaustiveness_gate":
            try:
                claim = ExhaustiveClaimRequest.model_validate(arguments)
            except ValidationError as exc:
                return _error(request.id, -32602, "Invalid exhaustive claim", {"detail": str(exc)[:500]})
            endpoint = next((item for item in extract_endpoints(source_spec) if item.get("operation_id") == claim.operation_id), None)
            if not endpoint:
                return _error(request.id, -32602, "Unknown proof operation", {"operation_id": claim.operation_id})
            outcome = await prove_exhaustive_claim(endpoint, claim.model_dump())
            _save_proof(pid, outcome)
            return _result(
                request.id,
                {
                    "content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False)}],
                    "structuredContent": outcome,
                    "isError": not outcome.get("success", False),
                },
            )
        operation_id = (tool.get("_meta") or {}).get("operation_id")
        endpoint = next((item for item in extract_endpoints(spec) if item.get("operation_id") == operation_id), None)
        if not endpoint:
            return _error(request.id, -32603, "Generated tool has no matching operation")
        outcome = await execute_operation(endpoint, arguments)
        return _result(
            request.id,
            {
                "content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False)}],
                "structuredContent": outcome,
                "isError": not outcome.get("success", False),
            },
        )
    return _error(request.id, -32601, "Method not found", {"method": request.method})


@router.post("/mcp")
@router.post("/mcp/{pid}")
async def mcp_http(request: Request, pid: str | None = None):
    """Validate the HTTP binding before dispatch; no modern session state is kept."""
    request_id = None

    def reject(code: int, message: str, data: Any = None, status: int = 400):
        payload = _error(request_id, code, message, data)
        if request_id is None:
            payload.pop("id")
        return JSONResponse(payload, status_code=status)

    origin = request.headers.get("origin")
    # Do not trust the caller-controlled Host header to authorize browser origins.
    if origin is not None and (not origin or origin not in [*CORS_ORIGINS, PUBLIC_BASE_URL]):
        return reject(-32600, "Origin not allowed", status=403)

    def reject_constant(value: str):
        raise ValueError("Non-finite JSON constant")

    def finite_float(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Non-finite JSON number")
        return result

    def validate_strings(value: Any) -> None:
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
        elif isinstance(value, dict):
            for key, item in value.items():
                validate_strings(key)
                validate_strings(item)
        elif isinstance(value, list):
            for item in value:
                validate_strings(item)

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    try:
        raw_body = await _read_limited_body(request)
    except _RequestBodyTooLarge:
        return reject(-32600, "Request body too large", status=413)
    try:
        body = json.loads(raw_body.decode("utf-8"),
                          parse_constant=reject_constant, parse_float=finite_float,
                          object_pairs_hook=unique_object)
        validate_strings(body)
    except (ValueError, RecursionError):
        return reject(-32700, "Parse error")
    if not isinstance(body, dict):
        return reject(-32600, "Expected a single JSON-RPC request")
    raw_id = body.get("id")
    if type(raw_id) in (str, int):
        request_id = raw_id
    if (body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str)
            or "result" in body or "error" in body
            or ("id" in body and request_id is None)):
        return reject(-32600, "Invalid JSON-RPC request")
    params = body.get("params", {})
    if not isinstance(params, dict):
        return reject(-32602, "params must be an object")
    method = body["method"]
    version_header = request.headers.get("mcp-protocol-version")
    meta = params.get("_meta")
    # Legacy metadata (for example progressToken) does not select modern MCP.
    # Modern signals must
    # never fall through to the old initialize handshake, even when malformed.
    modern = ((isinstance(meta, dict) and any(key.startswith(META_PREFIX) for key in meta))
              or method == "server/discover"
              or "mcp-method" in request.headers or "mcp-name" in request.headers
              or (version_header is not None and version_header not in LEGACY_VERSIONS)
              or (method == "initialize" and params.get("protocolVersion") == MODERN_VERSION))
    if modern:
        if request_id is None:
            return reject(-32600, "Modern HTTP requests require an id")
        if not isinstance(meta, dict):
            return reject(-32602, "params._meta must be an object")
        version = meta.get(META_PREFIX + "protocolVersion")
        capabilities = meta.get(META_PREFIX + "clientCapabilities")
        if not isinstance(version, str) or not isinstance(capabilities, dict):
            return reject(-32602, "_meta requires protocolVersion string and clientCapabilities object")
        info = meta.get(META_PREFIX + "clientInfo")
        if META_PREFIX + "clientInfo" in meta and (
            not isinstance(info, dict) or not isinstance(info.get("name"), str)
            or not isinstance(info.get("version"), str)
        ):
            return reject(-32602, "clientInfo requires name and version strings")
        for header, expected in (("mcp-protocol-version", version), ("mcp-method", method)):
            values = request.headers.getlist(header)
            if (len(values) != 1 or values[0] != expected or not values[0]
                    or any(not 0x21 <= ord(char) <= 0x7E for char in values[0])):
                return reject(-32020, f"Missing, malformed or mismatched {header}")
        name_field = "uri" if method == "resources/read" else "name"
        if method in {"tools/call", "resources/read", "prompts/get"} or "mcp-name" in request.headers:
            expected = params.get(name_field)
            if not isinstance(expected, str):
                return reject(-32602, f"{name_field} must be a string")
            values = request.headers.getlist("mcp-name")
            if len(values) != 1:
                return reject(-32020, "Missing or duplicate Mcp-Name")
            value = values[0]
            if (value != value.strip() or any(
                    not (0x20 <= ord(char) <= 0x7E or char == "\t") for char in value)):
                return reject(-32020, "Malformed Mcp-Name")
            if value.startswith("=?base64?") and value.endswith("?="):
                try:
                    value = base64.b64decode(value[9:-2], validate=True).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    return reject(-32020, "Malformed Base64 Mcp-Name")
            if value != expected:
                return reject(-32020, "Mcp-Name does not match the body")
        if version != MODERN_VERSION:
            return reject(-32022, "Unsupported protocol version", {
                "supported": [MODERN_VERSION, *LEGACY_VERSIONS], "requested": version})
        if method not in {"server/discover", "tools/list", "tools/call"}:
            return reject(-32601, "Method not found", {"method": method}, status=404)
        if method == "tools/list" and "cursor" in params:
            return reject(-32602, "Invalid cursor: this server returns the complete tool list")
    if method == "tools/call" and (
        not isinstance(params.get("name"), str)
        or ("arguments" in params and not isinstance(params["arguments"], dict))
    ):
        return reject(-32602, "tools/call requires a name string and optional arguments object")
    if not modern and method == "notifications/initialized" and "id" not in body:
        return Response(status_code=202)
    if request_id is None:
        return reject(-32600, "Request id required")
    # model_construct preserves JSON-RPC numeric IDs without Pydantic coercion.
    rpc = MCPRequest.model_construct(jsonrpc="2.0", id=request_id, method=method, params=params)
    try:
        if modern and method == "server/discover":
            if pid is not None:
                _load_project(pid)
            response = _result(request_id, {
                "supportedVersions": [MODERN_VERSION, *LEGACY_VERSIONS],
                "capabilities": {"tools": {"listChanged": False}},
            })
        else:
            response = await capability_mcp(rpc) if pid is None else await mcp_endpoint(pid, rpc)
    except HTTPException as exc:
        if not modern:
            raise
        if exc.status_code == 404:
            return reject(-32602, "Project not found", status=exc.status_code)
        response = _result(request_id, {"content": [{"type": "text", "text": "Tool execution unavailable"}], "isError": True})
    except Exception:
        if not modern:
            raise
        return reject(-32603, "Internal error", status=500)
    if modern:
        # Unknown tools are protocol errors; actionable input/lookup failures are
        # tool errors. Keep legacy error contracts unchanged for existing clients.
        if "error" in response:
            error = response["error"]
            if error["message"] in {"Invalid outcome request", "Invalid provider set", "Invalid receipt lookup",
                                    "Receipt not found", "Invalid exhaustive claim", "Unknown proof operation"}:
                detail = (error.get("data") or {}).get("detail")
                text = error["message"] + (f": {detail}" if detail else "")
                response = _result(request_id, {"content": [{"type": "text", "text": text}], "isError": True})
        if "result" in response:
            result = response["result"]
            result["resultType"] = "complete"
            result["_meta"] = {META_PREFIX + "serverInfo": {
                "name": "APIVouch Outcome Router" if pid is None else "APIVouch Agent Adapter", "version": APP_VERSION}}
            if method in {"server/discover", "tools/list"}:
                result.update(ttlMs=0, cacheScope="private")
    return response
