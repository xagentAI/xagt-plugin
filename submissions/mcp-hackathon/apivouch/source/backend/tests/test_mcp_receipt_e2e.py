import json

from fastapi.testclient import TestClient

from app.main import app
from app.services import outcomes
from app.services.http_client import SafeResponse

client = TestClient(app)


def test_mcp_resolve_store_and_reverify_receipt(monkeypatch):
    values = {
        "https://atlas.example.com/value?api_key=opaque-atlas": 18.40,
        "https://beacon.example.com/value?api_key=opaque-beacon": 18.44,
        "https://legacy.example.com/value?api_key=opaque-legacy": "unavailable",
    }

    async def fake_request(_method, url):
        body = json.dumps({"quote": {"value": values[url]}}).encode()
        return SafeResponse(200, {"content-type": "application/json"}, body, url)

    monkeypatch.setattr(outcomes, "safe_request", fake_request)

    initialized = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    ).json()
    assert initialized["result"]["protocolVersion"] == "2025-06-18"

    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()
    assert [tool["name"] for tool in listed["result"]["tools"]] == [
        "apivouch_resolve_verified_outcome",
        "apivouch_verify_receipt",
    ]

    arguments = {
        "goal": "Return a verified delivery quote",
        "providers": [
            {
                "name": name,
                "url": url,
                "result_path": "quote.value",
                "expected_schema": {"type": "number"},
                "price_usd": price,
            }
            for name, url, price in (
                ("Atlas", "https://atlas.example.com/value?api_key=opaque-atlas", 0.004),
                ("Beacon", "https://beacon.example.com/value?api_key=opaque-beacon", 0.003),
                ("Legacy", "https://legacy.example.com/value?api_key=opaque-legacy", 0.001),
            )
        ],
        "constraints": {
            "max_price_usd": 0.01,
            "max_latency_ms": 5000,
            "minimum_agreement": 2,
            "numeric_tolerance_percent": 1,
        },
    }
    resolved = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "apivouch_resolve_verified_outcome", "arguments": arguments},
        },
    ).json()["result"]
    receipt = resolved["structuredContent"]

    assert resolved["isError"] is False
    assert receipt["verdict"] == "VERIFIED"
    assert receipt["selected_provider"] == "Beacon"
    assert receipt["integrity"]["verifiable"] is True
    assert "opaque-" not in json.dumps(receipt)
    assert json.loads(resolved["content"][0]["text"]) == receipt

    verified = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "apivouch_verify_receipt", "arguments": {"receipt_id": receipt["receipt_id"]}},
        },
    ).json()["result"]
    assert verified["isError"] is False
    assert verified["structuredContent"] == {"receipt": receipt, "integrity_valid": True, "authenticity": {"state": "unsigned", "valid": False}}

    rest_copy = client.get(f"/api/outcomes/receipts/{receipt['receipt_id']}")
    assert rest_copy.status_code == 200
    assert rest_copy.json() == verified["structuredContent"]


def test_mcp_receipt_lookup_rejects_missing_receipt():
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "apivouch_verify_receipt", "arguments": {"receipt_id": "0" * 24}},
        },
    ).json()
    assert response["error"] == {
        "code": -32004,
        "message": "Receipt not found",
        "data": {"receipt_id": "0" * 24},
    }
