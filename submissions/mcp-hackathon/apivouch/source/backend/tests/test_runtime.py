import json

import pytest

from app.services import runtime
from app.services.http_client import SafeResponse


def endpoint(method="GET", schema=None):
    return {
        "method": method,
        "path": "/status",
        "operation_id": "getStatus" if method == "GET" else "createStatus",
        "base_url": "https://example.com",
        "parameters": [],
        "response_schema": schema,
    }


def response(status, payload, content_type="application/json"):
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return SafeResponse(status, {"content-type": content_type}, content, "https://example.com/status")


@pytest.mark.asyncio
async def test_runtime_returns_stable_success_envelope(monkeypatch):
    async def fake_request(*_args, **_kwargs):
        return response(200, {"ok": True})

    monkeypatch.setattr(runtime, "safe_request", fake_request)
    schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
    result = await runtime.execute_operation(endpoint(schema=schema))
    assert result["success"] is True
    assert result["error"] is None
    assert result["meta"]["contract_validated"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(401, "UPSTREAM_AUTH_ERROR", False), (403, "UPSTREAM_AUTH_ERROR", False), (429, "UPSTREAM_RATE_LIMIT", True), (503, "UPSTREAM_HTTP_ERROR", True)],
)
async def test_runtime_normalizes_upstream_http_errors(monkeypatch, status, code, retryable):
    async def fake_request(*_args, **_kwargs):
        return response(status, {"error": "upstream"})

    monkeypatch.setattr(runtime, "safe_request", fake_request)
    result = await runtime.execute_operation(endpoint())
    assert result["error"]["code"] == code
    assert result["error"]["retryable"] is retryable


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_json(monkeypatch):
    async def fake_request(*_args, **_kwargs):
        return response(200, b"{broken")

    monkeypatch.setattr(runtime, "safe_request", fake_request)
    result = await runtime.execute_operation(endpoint())
    assert result["error"]["code"] == "INVALID_UPSTREAM_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "status"), [("HEAD", 200), ("GET", 204)])
async def test_runtime_accepts_success_without_a_response_body(monkeypatch, method, status):
    async def fake_request(*_args, **_kwargs):
        return response(status, b"")

    monkeypatch.setattr(runtime, "safe_request", fake_request)
    result = await runtime.execute_operation(endpoint(method=method))
    assert result["success"] is True
    assert result["data"] is None
    assert result["error"] is None


@pytest.mark.asyncio
async def test_runtime_rejects_schema_mismatch(monkeypatch):
    async def fake_request(*_args, **_kwargs):
        return response(200, {"count": "one"})

    monkeypatch.setattr(runtime, "safe_request", fake_request)
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    result = await runtime.execute_operation(endpoint(schema=schema))
    assert result["error"]["code"] == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_runtime_blocks_side_effect_before_network(monkeypatch):
    called = False

    async def fake_request(*_args, **_kwargs):
        nonlocal called
        called = True
        return response(200, {})

    monkeypatch.setattr(runtime, "safe_request", fake_request)
    result = await runtime.execute_operation(endpoint(method="POST"))
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert called is False


@pytest.mark.asyncio
async def test_runtime_validates_arguments_before_network(monkeypatch):
    called = False

    async def fake_request(*_args, **_kwargs):
        nonlocal called
        called = True
        return response(200, {})

    checked = endpoint()
    checked["parameters"] = [{"name": "limit", "in": "query", "required": True, "schema": {"type": "integer"}}]
    monkeypatch.setattr(runtime, "safe_request", fake_request)
    result = await runtime.execute_operation(checked, {"limit": "ten"})
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert called is False
