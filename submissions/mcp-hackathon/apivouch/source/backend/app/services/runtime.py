from __future__ import annotations

import json
import time
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.security import is_safe_method
from app.services.http_client import safe_request
from app.services.schemas import validate_instance
from app.services.tester import prepare_request
from app.services.tools import input_schema_for_endpoint


def error_result(code: str, message: str, retryable: bool = False, **meta: Any) -> dict[str, Any]:
    return {"success": False, "data": None, "error": {"code": code, "message": message, "retryable": retryable}, "meta": meta}


async def execute_operation(endpoint: dict[str, Any], arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if not is_safe_method(endpoint["method"]):
        return error_result(
            "CONFIRMATION_REQUIRED",
            f"{endpoint['method']} operations are disabled in the public adapter because they may change external state.",
            False,
            operation_id=endpoint["operation_id"],
        )
    input_errors = validate_instance(arguments or {}, input_schema_for_endpoint(endpoint))
    if input_errors:
        return error_result("INVALID_ARGUMENT", "; ".join(input_errors[:3]), False, operation_id=endpoint["operation_id"])
    try:
        prepared = prepare_request(endpoint, arguments)
    except ValueError as exc:
        return error_result("INVALID_ARGUMENT", str(exc), False, operation_id=endpoint["operation_id"])
    started = time.perf_counter()
    try:
        response = await safe_request(endpoint["method"], prepared["url"], params=prepared["params"], headers=prepared["headers"])
    except (httpx.HTTPError, HTTPException, OSError, ValueError) as exc:
        message = str(exc)[:300]
        code = "UPSTREAM_TIMEOUT" if "timeout" in message.lower() else "UPSTREAM_UNAVAILABLE"
        return error_result(code, message, True, operation_id=endpoint["operation_id"])
    latency_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code == 429:
        return error_result("UPSTREAM_RATE_LIMIT", "The upstream API returned 429.", True, operation_id=endpoint["operation_id"], latency_ms=latency_ms, upstream_status=429)
    if response.status_code in {401, 403}:
        return error_result("UPSTREAM_AUTH_ERROR", f"The upstream API returned {response.status_code}.", False, operation_id=endpoint["operation_id"], latency_ms=latency_ms, upstream_status=response.status_code)
    if not 200 <= response.status_code < 300:
        return error_result("UPSTREAM_HTTP_ERROR", f"The upstream API returned {response.status_code}.", response.status_code >= 500, operation_id=endpoint["operation_id"], latency_ms=latency_ms, upstream_status=response.status_code)
    if endpoint["method"] == "HEAD" or response.status_code == 204 or not response.content:
        data = None
    else:
        try:
            data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return error_result("INVALID_UPSTREAM_RESPONSE", "The upstream response was not valid JSON.", False, operation_id=endpoint["operation_id"], latency_ms=latency_ms)
    schema_errors = validate_instance(data, endpoint.get("response_schema"))
    if schema_errors:
        return error_result(
            "SCHEMA_VALIDATION_FAILED",
            "; ".join(schema_errors[:3]),
            False,
            operation_id=endpoint["operation_id"],
            latency_ms=latency_ms,
            upstream_status=response.status_code,
        )
    return {
        "success": True,
        "data": data,
        "error": None,
        "meta": {
            "operation_id": endpoint["operation_id"],
            "latency_ms": latency_ms,
            "upstream_status": response.status_code,
            "contract_validated": bool(endpoint.get("response_schema")),
        },
    }
