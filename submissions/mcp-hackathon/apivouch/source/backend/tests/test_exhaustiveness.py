import json

import pytest

from app.services import exhaustiveness
from app.services.exhaustiveness import prove_exhaustive_claim
from app.services.http_client import SafeResponse
from app.services.tools import generate_tools


def collection_endpoint():
    return {
        "method": "GET",
        "path": "/items",
        "operation_id": "listItems",
        "base_url": "https://example.com",
        "parameters": [
            {"name": "cursor", "in": "query", "schema": {"type": "string"}},
            {"name": "limit", "in": "query", "schema": {"type": "integer"}},
        ],
        "response_schema": {},
    }


def page(payload):
    return SafeResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode(), "https://example.com/items")


@pytest.mark.asyncio
async def test_server_collects_all_pages_and_proves_exact_count(monkeypatch):
    seen_params = []
    payloads = [
        {"items": [{"id": "a"}, {"id": "b"}], "has_more": True, "next_cursor": "two", "total": 3, "snapshot_id": "v1"},
        {"items": [{"id": "c"}], "has_more": False, "next_cursor": None, "total": 3, "snapshot_id": "v1"},
    ]

    async def fake_request(*_args, **kwargs):
        seen_params.append(dict(kwargs["params"]))
        return page(payloads.pop(0))

    monkeypatch.setattr(exhaustiveness, "safe_request", fake_request)
    result = await prove_exhaustive_claim(collection_endpoint(), {"operation_id": "listItems", "claim_type": "EXACT_COUNT", "expected_count": 3, "arguments": {"limit": 2}, "pagination": {}})
    assert result["verdict"] == "PROVEN"
    assert result["certified_value"] == 3
    assert result["evidence"]["source"] == "server-collected"
    assert result["evidence"]["pages_examined"] == 2
    assert result["certificate"]["certificate_id"].startswith("avp_")
    assert seen_params == [{"limit": 2}, {"limit": 2, "cursor": "two"}]


@pytest.mark.asyncio
async def test_total_mismatch_can_never_be_proven(monkeypatch):
    async def fake_request(*_args, **_kwargs):
        return page({"items": [{"id": 1}], "has_more": False, "total": 999, "snapshot_id": "v1"})

    monkeypatch.setattr(exhaustiveness, "safe_request", fake_request)
    result = await prove_exhaustive_claim(collection_endpoint(), {"operation_id": "listItems", "claim_type": "EXACT_COUNT", "expected_count": 1, "arguments": {}, "pagination": {}})
    assert result["verdict"] == "UNPROVEN"
    assert result["certificate"] is None
    assert "COUNT_INCONSISTENT" in {item["code"] for item in result["blocking_reasons"]}


@pytest.mark.asyncio
async def test_repeated_cursor_is_blocking(monkeypatch):
    calls = iter([1, 2])

    async def fake_request(*_args, **_kwargs):
        return page({"items": [{"id": next(calls)}], "has_more": True, "next_cursor": "same", "snapshot_id": "v1"})

    monkeypatch.setattr(exhaustiveness, "safe_request", fake_request)
    result = await prove_exhaustive_claim(collection_endpoint(), {"operation_id": "listItems", "claim_type": "ALL", "arguments": {}, "pagination": {}})
    assert result["verdict"] == "UNPROVEN"
    assert "CURSOR_REPEATED" in {item["code"] for item in result["blocking_reasons"]}


@pytest.mark.asyncio
async def test_caller_cannot_start_at_a_later_cursor(monkeypatch):
    called = False

    async def fake_request(*_args, **_kwargs):
        nonlocal called
        called = True
        return page({})

    monkeypatch.setattr(exhaustiveness, "safe_request", fake_request)
    result = await prove_exhaustive_claim(collection_endpoint(), {"operation_id": "listItems", "claim_type": "ALL", "arguments": {"cursor": "page-9"}, "pagination": {}})
    assert result["verdict"] == "UNPROVEN"
    assert result["blocking_reasons"][0]["code"] == "PARTIAL_START_FORBIDDEN"
    assert called is False


@pytest.mark.asyncio
async def test_missing_snapshot_is_explicitly_conditional(monkeypatch):
    async def fake_request(*_args, **_kwargs):
        return page({"items": [], "has_more": False, "total": 0})

    monkeypatch.setattr(exhaustiveness, "safe_request", fake_request)
    result = await prove_exhaustive_claim(collection_endpoint(), {"operation_id": "listItems", "claim_type": "NONE", "arguments": {}, "pagination": {}})
    assert result["verdict"] == "CONDITIONAL"
    assert result["warnings"][0]["code"] == "SNAPSHOT_NOT_DECLARED"


def test_generated_tools_include_server_owned_gate():
    tools = generate_tools([collection_endpoint()])
    gate = next(tool for tool in tools if (tool.get("_meta") or {}).get("kind") == "exhaustiveness_gate")
    assert gate["name"] == "apivouch_prove_exhaustive_claim"
    assert gate["annotations"]["readOnlyHint"] is True
    assert "records_seen" not in gate["inputSchema"]["properties"]
