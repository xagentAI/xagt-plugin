import json

import pytest

from app.services import outcomes
from app.services.http_client import SafeResponse


def provider(name, value, *, price=0.01, schema=None):
    return {
        "name": name,
        "url": f"https://{name.lower()}.example.com/quote?api_key=opaque-test-value",
        "result_path": "quote.value",
        "expected_schema": schema or {"type": "number"},
        "price_usd": price,
        "_value": value,
    }


def request(providers, *, minimum=2, tolerance=1):
    cleaned = [{key: value for key, value in item.items() if key != "_value"} for item in providers]
    return {
        "goal": "Return a verified quote",
        "providers": cleaned,
        "constraints": {"max_price_usd": 1, "max_latency_ms": 5000, "minimum_agreement": minimum, "numeric_tolerance_percent": tolerance},
    }


@pytest.mark.asyncio
async def test_router_rejects_broken_provider_and_selects_best_agreeing_result(monkeypatch):
    providers = [provider("Atlas", 18.40, price=0.004), provider("Beacon", 18.44, price=0.003), provider("Broken", "call us", price=0.001)]
    values = {item["url"]: item["_value"] for item in providers}

    async def fake_request(_method, url):
        payload = {"quote": {"value": values[url]}}
        return SafeResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode(), url)

    monkeypatch.setattr(outcomes, "safe_request", fake_request)
    receipt = await outcomes.execute_verified_outcome(request(providers))

    assert receipt["verdict"] == "VERIFIED"
    assert receipt["selected_provider"] == "Beacon"
    assert receipt["result"] == 18.44
    assert receipt["selected_price_usd"] == 0.003
    assert receipt["settlement"]["charged"] is False
    assert receipt["agreement"] == {"providers": 2, "required": 2}
    assert next(item for item in receipt["attempts"] if item["name"] == "Broken")["status"] == "REJECTED"
    assert all("opaque-test-value" not in item["url"] for item in receipt["attempts"])
    assert outcomes.verify_receipt(receipt) is True


@pytest.mark.asyncio
async def test_router_refuses_to_claim_verified_without_independent_agreement(monkeypatch):
    providers = [provider("One", 10), provider("Two", 20), provider("Three", 30)]
    values = {item["url"]: item["_value"] for item in providers}

    async def fake_request(_method, url):
        return SafeResponse(200, {}, json.dumps({"quote": {"value": values[url]}}).encode(), url)

    monkeypatch.setattr(outcomes, "safe_request", fake_request)
    receipt = await outcomes.execute_verified_outcome(request(providers, tolerance=0))

    assert receipt["verdict"] == "UNVERIFIED"
    assert receipt["result"] is None
    assert receipt["selected_provider"] is None
    assert receipt["selected_price_usd"] == 0
    assert all(item["reason"] == "Insufficient independent agreement" for item in receipt["attempts"])


@pytest.mark.asyncio
async def test_over_budget_provider_is_never_called(monkeypatch):
    called = []
    providers = [provider("CheapA", 10, price=0), provider("CheapB", 10, price=0), provider("Costly", 10, price=5)]

    async def fake_request(_method, url):
        called.append(url)
        return SafeResponse(200, {}, b'{"quote":{"value":10}}', url)

    monkeypatch.setattr(outcomes, "safe_request", fake_request)
    payload = request(providers)
    payload["constraints"]["max_price_usd"] = 1
    receipt = await outcomes.execute_verified_outcome(payload)

    assert len(called) == 2
    costly = next(item for item in receipt["attempts"] if item["name"] == "Costly")
    assert costly["status"] == "REJECTED"
    assert "budget" in costly["reason"]


def test_integrity_fingerprint_detects_receipt_tampering():
    receipt = {"result": 12}
    fingerprint = outcomes.receipt_fingerprint(receipt)
    receipt["receipt_id"] = fingerprint.split(":", 1)[1][:24]
    receipt["integrity"] = {"fingerprint": fingerprint}
    assert outcomes.verify_receipt(receipt)
    receipt["result"] = 99
    assert not outcomes.verify_receipt(receipt)


def test_path_extraction_supports_objects_and_arrays():
    assert outcomes.extract_path({"data": {"items": [{"price": 7}]}}, "data.items.0.price") == 7
    with pytest.raises(ValueError, match="was not present"):
        outcomes.extract_path({"data": {}}, "data.missing")


def test_receipt_preview_is_bounded_and_never_embeds_objects():
    assert outcomes.scalar_preview(18.4) == 18.4
    assert outcomes.scalar_preview("x" * 200) == "x" * 120
    assert outcomes.scalar_preview({"private": "shape"}) is None


@pytest.mark.asyncio
async def test_router_requires_distinct_provider_origins():
    providers = [provider("One", 10), provider("Two", 10)]
    providers[1]["url"] = "https://one.example.com/another-path"
    with pytest.raises(ValueError, match="distinct network origin"):
        await outcomes.execute_verified_outcome(request(providers))
