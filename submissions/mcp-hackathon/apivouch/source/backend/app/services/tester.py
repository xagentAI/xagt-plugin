from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.core.config import MAX_RETRIES
from app.core.security import is_safe_method
from app.services.http_client import safe_request
from app.services.schemas import shape_signature, validate_instance


def prepare_request(endpoint: dict[str, Any], arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = dict(arguments or {})
    base_url = endpoint.get("base_url") or ""
    if not base_url:
        raise ValueError("No server URL is declared in the specification")
    path = endpoint["path"]
    query: dict[str, Any] = {}
    headers: dict[str, str] = {}
    missing: list[str] = []
    for parameter in endpoint.get("parameters") or []:
        name = str(parameter.get("name") or "")
        location = parameter.get("in")
        value = arguments.get(name)
        if parameter.get("required") and value is None:
            missing.append(name)
            continue
        if value is None:
            continue
        if location == "path":
            path = path.replace("{" + name + "}", quote(str(value), safe=""))
        elif location == "query":
            query[name] = value
        elif location == "header" and name.lower() not in {"authorization", "cookie", "proxy-authorization"}:
            headers[name] = str(value)
    if missing:
        raise ValueError("Required test arguments missing: " + ", ".join(sorted(missing)))
    if "{" in path or "}" in path:
        raise ValueError("Required path arguments are unresolved")
    return {"url": base_url.rstrip("/") + "/" + path.lstrip("/"), "params": query, "headers": headers}


async def _single_probe(endpoint: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    request = prepare_request(endpoint, arguments)
    started = time.perf_counter()
    response = await safe_request(endpoint["method"], request["url"], params=request["params"], headers=request["headers"])
    latency_ms = int((time.perf_counter() - started) * 1000)
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    expects_json = endpoint["method"] != "HEAD" and (bool(endpoint.get("response_schema")) or "json" in content_type or response.content[:1] in {b"{", b"["})
    data: Any = None
    json_valid = True
    if expects_json:
        try:
            data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            json_valid = False
    schema_errors = validate_instance(data, endpoint.get("response_schema")) if json_valid and data is not None else []
    content_type_valid = not expects_json or "json" in content_type
    success_status = 200 <= response.status_code < 300
    passed = success_status and json_valid and content_type_valid and not schema_errors
    return {
        "http_status": response.status_code,
        "latency_ms": latency_ms,
        "final_url": response.url,
        "content_type": content_type,
        "content_type_valid": content_type_valid,
        "json_valid": json_valid,
        "schema_valid": not schema_errors,
        "schema_errors": schema_errors,
        "success": passed,
        "sample_data": data if data is not None else response.content[:500].decode("utf-8", errors="replace"),
    }


async def probe_endpoint(
    endpoint: dict[str, Any],
    arguments: dict[str, Any] | None = None,
    samples: int = 2,
) -> dict[str, Any]:
    label = f"{endpoint['method']} {endpoint['path']}"
    if not is_safe_method(endpoint["method"]):
        return {"endpoint": label, "operation_id": endpoint["operation_id"], "status": "skipped", "reason": "State-changing methods are never auto-tested"}
    try:
        prepare_request(endpoint, arguments)
    except ValueError as exc:
        return {"endpoint": label, "operation_id": endpoint["operation_id"], "status": "skipped", "reason": str(exc)}

    observations: list[dict[str, Any]] = []
    last_error = ""
    for _sample in range(max(1, min(samples, 5))):
        for attempt in range(MAX_RETRIES + 1):
            try:
                observations.append(await _single_probe(endpoint, arguments or {}))
                break
            except (httpx.HTTPError, HTTPException, OSError, ValueError) as exc:
                last_error = str(exc)[:300]
                if attempt >= MAX_RETRIES:
                    observations.append({"success": False, "error": last_error})

    successful_payloads = [item.get("sample_data") for item in observations if item.get("success") and isinstance(item.get("sample_data"), (dict, list))]
    shapes = [shape_signature(payload) for payload in successful_payloads]
    shape_drift = len({json.dumps(shape, sort_keys=True) for shape in shapes}) > 1
    passed = sum(1 for item in observations if item.get("success"))
    schema_failures = sum(1 for item in observations if item.get("schema_valid") is False)
    if passed == len(observations) and observations and not shape_drift:
        status = "passed"
    elif passed:
        status = "warning"
    else:
        status = "failed"
    latencies = [item["latency_ms"] for item in observations if item.get("latency_ms") is not None]
    return {
        "endpoint": label,
        "operation_id": endpoint["operation_id"],
        "status": status,
        "samples_requested": max(1, min(samples, 5)),
        "samples_passed": passed,
        "shape_drift": shape_drift,
        "schema_failures": schema_failures,
        "latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "observations": observations,
        "reason": last_error if not passed else None,
    }


async def test_endpoint(base_url: str, endpoint: dict[str, Any]) -> dict[str, Any]:
    """Backwards-compatible wrapper retained for existing integrations."""
    copied = dict(endpoint)
    copied["base_url"] = base_url or endpoint.get("base_url")
    return await probe_endpoint(copied, samples=1)
