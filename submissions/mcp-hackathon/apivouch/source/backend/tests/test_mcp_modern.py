import base64
import json
import runpy

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import mcp
from app.core import config, signing
from app.main import app
from app.services import outcomes, runtime
from app.services.http_client import SafeResponse

client = TestClient(app)
VERSION = "2026-07-28"
PREFIX = "io.modelcontextprotocol/"


def wire(method="tools/list", **params):
    params["_meta"] = {PREFIX + "protocolVersion": VERSION, PREFIX + "clientCapabilities": {}}
    body = {"jsonrpc": "2.0", "id": "test-1", "method": method, "params": params}
    headers = {"MCP-Protocol-Version": VERSION, "Mcp-Method": method,
               "Accept": "application/json, text/event-stream"}
    if "name" in params:
        headers["Mcp-Name"] = params["name"]
    return body, headers


@pytest.fixture(params=[False, True], ids=["product", "dynamic"])
def endpoint(request):
    if not request.param:
        yield "/mcp"
        return
    spec = {"openapi": "3.0.3", "info": {"title": "Modern", "version": "1"},
            "servers": [{"url": "https://example.com"}], "paths": {
                "/status": {"get": {"operationId": "getStatus", "responses": {"200": {"description": "ok"}}}},
                "/write": {"post": {"operationId": "write", "responses": {"200": {"description": "ok"}}}}}}
    pid = client.post("/api/projects", json={"name": "Modern", "openapi_json": spec}).json()["id"]
    client.post(f"/api/projects/{pid}/contract").raise_for_status()
    try:
        yield f"/mcp/{pid}"
    finally:
        client.delete(f"/api/projects/{pid}").raise_for_status()


def test_discovery_and_direct_list(endpoint):
    # List first, without discovery or initialization.
    for method in ("tools/list", "server/discover"):
        body, headers = wire(method)
        response = client.post(endpoint, json=body, headers=headers)
        assert response.status_code == 200
        assert "mcp-session-id" not in response.headers
        result = response.json()["result"]
        assert result["resultType"] == "complete"
        assert result["ttlMs"] == 0 and result["cacheScope"] == "private"
        assert result["_meta"][PREFIX + "serverInfo"]["version"]
        if method == "server/discover":
            assert result["supportedVersions"] == [VERSION, *mcp.LEGACY_VERSIONS]
            assert result["capabilities"] == {"tools": {"listChanged": False}}
        else:
            assert result["tools"]


@pytest.mark.parametrize("fault,code", [
    ("missing_meta", -32602), ("null_meta", -32602), ("missing_version", -32602),
    ("bad_version", -32602), ("missing_capabilities", -32602), ("bad_capabilities", -32602),
    ("bad_identity", -32602), ("missing_version_header", -32020),
    ("missing_method_header", -32020), ("version_mismatch", -32020),
    ("method_mismatch", -32020), ("unsupported", -32022),
    ("bad_params", -32602), ("bad_rpc", -32600), ("bad_id", -32600),
])
def test_invalid_modern_requests(endpoint, fault, code):
    body, headers = wire()
    meta = body["params"]["_meta"]
    if fault == "missing_meta":
        del body["params"]["_meta"]
    elif fault == "null_meta":
        body["params"]["_meta"] = None
    elif fault == "missing_version":
        del meta[PREFIX + "protocolVersion"]
    elif fault == "bad_version":
        meta[PREFIX + "protocolVersion"] = 2026
    elif fault == "missing_capabilities":
        del meta[PREFIX + "clientCapabilities"]
    elif fault == "bad_capabilities":
        meta[PREFIX + "clientCapabilities"] = []
    elif fault == "bad_identity":
        meta[PREFIX + "clientInfo"] = {"name": "test"}
    elif fault == "missing_version_header":
        del headers["MCP-Protocol-Version"]
    elif fault == "missing_method_header":
        del headers["Mcp-Method"]
    elif fault == "version_mismatch":
        headers["MCP-Protocol-Version"] = "2025-06-18"
    elif fault == "method_mismatch":
        headers["Mcp-Method"] = "TOOLS/LIST"
    elif fault == "unsupported":
        headers["MCP-Protocol-Version"] = meta[PREFIX + "protocolVersion"] = "1900-01-01"
    elif fault == "bad_params":
        body["params"] = []
    elif fault == "bad_rpc":
        body["jsonrpc"] = "1.0"
    else:
        body["id"] = True
    response = client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    if code == -32022:
        assert response.json()["error"]["data"] == {
            "requested": "1900-01-01", "supported": [VERSION, *mcp.LEGACY_VERSIONS]}


@pytest.mark.parametrize("name_header", [None, "other", "=?base64?!!!!?=", " padded "])
def test_name_header_rejected(endpoint, name_header):
    body, headers = wire("tools/call", name="missing", arguments={})
    if name_header is None:
        del headers["Mcp-Name"]
    else:
        headers["Mcp-Name"] = name_header
    response = client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32020


@pytest.mark.parametrize("name", ["missing", "\u2603", "=?base64?literal?="])
def test_encoded_unknown_tool(endpoint, name):
    body, headers = wire("tools/call", name=name)
    headers["Mcp-Name"] = "=?base64?" + base64.b64encode(name.encode()).decode() + "?="
    response = client.post(endpoint, json=body, headers=headers)
    assert response.json()["error"]["code"] == -32602
    assert response.json()["id"] == body["id"]


@pytest.mark.parametrize("method", ["unknown", "initialize", "ping", "notifications/initialized"])
def test_modern_never_uses_legacy_methods(endpoint, method):
    body, headers = wire(method)
    response = client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == -32601


def test_malformed_envelopes_and_arguments(endpoint):
    for content, code in [("{", -32700), ("[]", -32600), ("null", -32600)]:
        response = client.post(endpoint, content=content)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == code
    for arguments in (None, [], False, ""):
        body, headers = wire("tools/call", name="missing", arguments=arguments)
        response = client.post(endpoint, json=body, headers=headers)
        assert response.json()["error"]["code"] == -32602


@pytest.fixture(params=[VERSION, *mcp.LEGACY_VERSIONS])
def raw_wire(request):
    body, headers = wire()
    if request.param != VERSION:
        body["params"] = {}
        headers = {"MCP-Protocol-Version": request.param}
    headers["Content-Type"] = "application/json"
    return body, headers


@pytest.mark.parametrize("fragment", [
    "NaN", "Infinity", "-Infinity",
    "1e999", "-1e999",
    '"private-\\ud800"', '"private-\\udfff"',
    '{"private-\\ud800":1}', '{"private-\\udfff":1}',
    '{"private-key":1,"private-key":2}',
    '{"key":1,"\\u006bey":2}',
])
@pytest.mark.parametrize("location", ["id", "params", "meta", "arguments", "array"])
def test_strict_json_at_every_level(endpoint, raw_wire, fragment, location):
    body, headers = raw_wire
    if location == "id":
        body["id"] = "PLACEHOLDER"
    elif location == "params":
        body["params"]["extra"] = "PLACEHOLDER"
    elif location == "meta":
        body["params"].setdefault("_meta", {})["extra"] = "PLACEHOLDER"
    elif location == "arguments":
        body["params"]["arguments"] = {"nested": "PLACEHOLDER"}
    else:
        body["params"]["arguments"] = {"nested": [{"value": "PLACEHOLDER"}]}
    content = json.dumps(body).replace('"PLACEHOLDER"', fragment).encode()
    response = client.post(endpoint, content=content, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}


@pytest.mark.parametrize("fault", [
    "empty", "truncated", "trailing", "invalid_utf8", "utf16", "deep", "deep_surrogate",
    "duplicate_id", "duplicate_method", "duplicate_params",
])
def test_raw_parse_errors_are_sanitized(endpoint, raw_wire, fault):
    body, headers = raw_wire
    content = json.dumps(body).encode()
    if fault == "empty":
        content = b""
    elif fault == "truncated":
        content = content[:-1]
    elif fault == "trailing":
        content += b" private diagnostic"
    elif fault == "invalid_utf8":
        content = content.replace(b"test-1", b"\xff")
    elif fault == "utf16":
        content = content.decode().encode("utf-16")
    elif fault == "deep":
        content = b"[" * 2000 + b"0"
    elif fault == "deep_surrogate":
        body["params"]["extra"] = "PLACEHOLDER"
        content = json.dumps(body).encode().replace(
            b'"PLACEHOLDER"', b"[" * 2000 + b'"\\ud800"' + b"]" * 2000)
    else:
        key = fault.removeprefix("duplicate_")
        content = content[:-1] + (',"' + key + '":null}').encode()
    response = client.post(endpoint, content=content, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}


def test_valid_paired_unicode_and_finite_floats(endpoint, raw_wire):
    body, headers = raw_wire
    paired = "\U0001f600"
    body["id"] = paired
    body["params"]["extra"] = {paired: [{"value": paired, "numbers": [1e308, -1e308, 1.5]}]}
    content = json.dumps(body).encode()
    assert b"\\ud83d\\ude00" in content
    response = client.post(endpoint, content=content, headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == paired
    assert "result" in response.json()


@pytest.mark.parametrize("request_id", [True, False, 1.0, 1.5, None, [], {}])
def test_request_id_rejects_non_string_non_integer(endpoint, raw_wire, request_id):
    body, headers = raw_wire
    body["id"] = request_id
    response = client.post(endpoint, content=json.dumps(body).encode(), headers=headers)
    assert response.status_code == 400
    assert response.json() == {"jsonrpc": "2.0", "error": {
        "code": -32600, "message": "Invalid JSON-RPC request"}}


@pytest.mark.parametrize("request_id", [0, -1, 42, 9007199254740993, "", "0", "001", "-1", "1.0", "\u2603"])
def test_request_id_round_trips_exactly(endpoint, raw_wire, request_id):
    body, headers = raw_wire
    body["id"] = request_id
    response = client.post(endpoint, content=json.dumps(body).encode(), headers=headers)
    assert response.status_code == 200
    assert "result" in response.json()
    assert response.json()["id"] == request_id
    assert type(response.json()["id"]) is type(request_id)


@pytest.mark.parametrize("method", ["tools/list", "notifications/initialized"])
def test_absent_id_semantics_preserved(endpoint, raw_wire, method):
    body, headers = raw_wire
    del body["id"]
    body["method"] = method
    modern = headers["MCP-Protocol-Version"] == VERSION
    if modern:
        headers["Mcp-Method"] = method
    response = client.post(endpoint, content=json.dumps(body).encode(), headers=headers)
    if not modern and method == "notifications/initialized":
        assert response.status_code == 202 and not response.content
    else:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32600
        assert "id" not in response.json()


@pytest.mark.parametrize("version", mcp.LEGACY_VERSIONS)
def test_legacy_preserved(endpoint, version):
    response = client.post(endpoint, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": version}})
    assert response.json()["result"]["protocolVersion"] == version
    assert "resultType" not in response.json()["result"]
    notification = client.post(endpoint, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notification.status_code == 202 and not notification.content
    assert client.post(endpoint, json={"jsonrpc": "2.0", "id": 2, "method": "ping"}).json()["result"] == {}
    response = client.post(endpoint, json={"jsonrpc": "2.0", "id": 3, "method": "initialize",
                                           "params": {"protocolVersion": VERSION}})
    assert "error" in response.json()


@pytest.mark.parametrize("headers", [{}, *[{"MCP-Protocol-Version": v} for v in mcp.LEGACY_VERSIONS]])
@pytest.mark.parametrize("meta", [{}, {"progressToken": "progress-1"}, {"example.com/context": "legacy"}])
def test_legacy_metadata(endpoint, headers, meta):
    for method, params in [("initialize", {"protocolVersion": "2025-06-18"}),
                           ("ping", {}), ("tools/list", {}),
                           ("tools/call", {"name": "missing", "arguments": {}}),
                           ("notifications/initialized", {})]:
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if method != "notifications/initialized":
            body["id"] = 1
        baseline = client.post(endpoint, json=body, headers=headers)
        params["_meta"] = meta
        response = client.post(endpoint, json=body, headers=headers)
        assert response.status_code == baseline.status_code
        assert response.content == baseline.content
        assert response.status_code in (200, 202)


@pytest.mark.parametrize("meta,code", [
    ({PREFIX + "protocolVersion": None}, -32602),
    ({PREFIX + "clientCapabilities": []}, -32602),
    ({PREFIX + "clientInfo": {}}, -32602),
    ({PREFIX + "protocolVersion": VERSION, PREFIX + "clientCapabilities": {}}, -32020),
])
def test_headerless_modern_metadata_never_falls_back(endpoint, meta, code):
    response = client.post(endpoint, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"_meta": meta}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_modern_cors_preflight(endpoint, monkeypatch):
    origin = "https://client.example"
    monkeypatch.setattr(config, "CORS_ORIGINS", [origin])
    cors_client = TestClient(runpy.run_path(main.__file__)["app"])
    headers = {"Origin": origin, "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "content-type,mcp-protocol-version,mcp-method,mcp-name"}
    response = cors_client.options(endpoint, headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    allowed = {value.strip().lower() for value in response.headers["access-control-allow-headers"].split(",")}
    assert {"content-type", "mcp-protocol-version", "mcp-method", "mcp-name"} <= allowed
    response = cors_client.options(endpoint, headers={**headers, "Origin": "https://evil.example"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    response = cors_client.options(endpoint, headers={**headers, "Access-Control-Request-Headers": "x-unapproved"})
    assert response.status_code == 400


def test_product_direct_call_refusal_and_receipt(monkeypatch):
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.SigningConfig())
    args = {"goal": "Refuse over budget", "providers": [
        {"name": name, "url": f"https://{name}.example/value", "price_usd": 1}
        for name in ("a", "b")], "constraints": {"max_price_usd": 0}}
    body, headers = wire("tools/call", name="apivouch_resolve_verified_outcome", arguments=args)
    result = client.post("/mcp", json=body, headers=headers).json()["result"]
    assert result["resultType"] == "complete" and result["isError"]
    receipt = result["structuredContent"]
    assert receipt["verdict"] == "UNVERIFIED" and outcomes.verify_receipt(receipt)
    body, headers = wire("tools/call", name="apivouch_verify_receipt", arguments={"receipt_id": receipt["receipt_id"]})
    result = client.post("/mcp", json=body, headers=headers).json()["result"]
    assert not result["isError"] and result["structuredContent"]["integrity_valid"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    for name, arguments in [("apivouch_resolve_verified_outcome", {}),
                            ("apivouch_verify_receipt", {"receipt_id": "0" * 24})]:
        body, headers = wire("tools/call", name=name, arguments=arguments)
        assert client.post("/mcp", json=body, headers=headers).json()["result"]["isError"]


def test_dynamic_execution_and_refusal(endpoint, monkeypatch):
    if endpoint == "/mcp":
        return
    async def fake_request(method, url, **kwargs):
        return SafeResponse(200, {"content-type": "application/json"}, b'{"ok":true}', url)
    monkeypatch.setattr(runtime, "safe_request", fake_request)
    for name, error in [("get_status", False), ("write", True), ("apivouch_prove_exhaustive_claim", True)]:
        body, headers = wire("tools/call", name=name, arguments={})
        result = client.post(endpoint, json=body, headers=headers).json()["result"]
        assert result["resultType"] == "complete" and result["isError"] is error
        if name == "write":
            assert result["structuredContent"]["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_signing_unavailable_is_modern_tool_error(monkeypatch):
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.SigningConfig(required=True))
    body, headers = wire("tools/call", name="apivouch_resolve_verified_outcome", arguments={
        "goal": "Resolve value", "providers": [{"name": n, "url": f"https://{n}.example/value"} for n in ("a", "b")]})
    response = client.post("/mcp", json=body, headers=headers)
    assert response.status_code == 200 and response.json()["result"]["isError"]


def test_origin_and_duplicate_headers(endpoint):
    body, headers = wire()
    response = client.post(endpoint, json=body, headers={**headers, "Origin": "https://evil.example"})
    assert response.status_code == 403
    response = client.post(endpoint, json=body, headers=[*headers.items(), ("mcp-method", "tools/list")])
    assert response.status_code == 400 and response.json()["error"]["code"] == -32020


def test_product_direct_success(monkeypatch):
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.SigningConfig())
    async def fake_request(method, url):
        return SafeResponse(200, {"content-type": "application/json"}, b'{"value":42}', url)
    monkeypatch.setattr(outcomes, "safe_request", fake_request)
    body, headers = wire("tools/call", name="apivouch_resolve_verified_outcome", arguments={
        "goal": "Resolve agreeing value", "providers": [
            {"name": n, "url": f"https://{n}.example/value", "result_path": "value"} for n in ("a", "b")]})
    result = client.post("/mcp", json=body, headers=headers).json()["result"]
    assert not result["isError"] and result["resultType"] == "complete"
    assert result["structuredContent"]["verdict"] == "VERIFIED"
    assert outcomes.verify_receipt(result["structuredContent"])


def test_per_request_validation_and_cursor(endpoint):
    body, headers = wire()
    body["params"]["_meta"][PREFIX + "clientInfo"] = {"name": "test", "version": "1"}
    assert client.post(endpoint, json=body, headers=headers).status_code == 200
    del body["params"]["_meta"][PREFIX + "clientCapabilities"]
    assert client.post(endpoint, json=body, headers=headers).json()["error"]["code"] == -32602
    body, headers = wire(cursor="unknown")
    assert client.post(endpoint, json=body, headers=headers).json()["error"]["code"] == -32602


def test_internal_error_is_sanitized(monkeypatch):
    async def broken(request):
        raise RuntimeError("private diagnostic")
    monkeypatch.setattr(mcp, "capability_mcp", broken)
    body, headers = wire()
    response = client.post("/mcp", json=body, headers=headers)
    assert response.status_code == 500
    assert response.json()["error"] == {"code": -32603, "message": "Internal error"}


def test_mcp_request_body_limit(endpoint, monkeypatch):
    monkeypatch.setattr(mcp, "MAX_MCP_REQUEST_BYTES", 64)
    marker = "must-not-be-echoed"
    response = client.post(endpoint, content=(marker * 8).encode(),
                           headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json() == {
        "jsonrpc": "2.0",
        "error": {"code": -32600, "message": "Request body too large"},
    }
    assert marker not in response.text
