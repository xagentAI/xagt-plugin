import pytest
from fastapi.testclient import TestClient

from life_exchange_rate import __version__
from life_exchange_rate import main
from life_exchange_rate.providers.fixtures import demo_profile


@pytest.fixture(scope="module")
def client():
    # MCP's session manager is single-use: one lifespan for this app instance.
    with TestClient(main.app, base_url="http://localhost:8000") as test_client:
        yield test_client


def test_health_and_verification(client, monkeypatch):
    monkeypatch.setenv("REVIEW_COMMIT", "review-test-commit")
    monkeypatch.setenv("APP_VERSION", "ignored-stale-version")
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["mcp"] == "enabled"
    proof = client.get("/.well-known/xagent-verification.json")
    assert proof.status_code == 200
    assert proof.json()["schemaVersion"] == 1
    assert health.json()["commit"] == proof.json()["commit"] == "review-test-commit"
    assert health.json()["version"] == proof.json()["version"] == __version__
    assert proof.json()["mcp"].endswith("/mcp/")


def test_demo_events_and_radar_are_available(client):
    events = client.get("/v1/events/demo")
    assert events.status_code == 200
    assert len(events.json()) == 3
    radar = client.get("/v1/radar/demo")
    assert radar.status_code == 200
    assert len(radar.json()) == 3
    assert radar.json()[0]["priority_score"] >= radar.json()[-1]["priority_score"]


@pytest.mark.parametrize("path", ["policy-rate", "energy"])
def test_structured_providers_have_reproducible_fixture_mode(client, path):
    response = client.get(f"/v1/events/{path}", params={"mode": "fixture"})
    assert response.status_code == 200
    event = response.json()
    assert event["provenance"]["source_type"] == "synthetic_fixture"
    assert event["provenance"]["source_url"] is None
    assert event["metadata"]["synthetic"] is True
    assert event["confidence"] == "scenario"
    assert event["window_start"] <= event["window_end"]


@pytest.mark.parametrize("path,params", [
    ("/v1/events/fx", {"base": "SEK", "quote": "SEK"}),
    ("/v1/events/fx", {"base": "12!", "quote": "JPY"}),
    ("/v1/events/fx", {"base": "SEK", "quote": "JPY", "lookback_days": 1}),
    ("/v1/events/policy-rate", {"mode": "invent"}),
    ("/v1/events/energy", {"lookback_days": 366}),
    ("/v1/headlines/official", {"source": "untrusted"}),
    ("/v1/headlines/official", {"source": "fed", "limit": 0}),
])
def test_provider_inputs_are_validated_before_fetch(client, path, params):
    assert client.get(path, params=params).status_code == 422


@pytest.mark.parametrize("path,provider,params", [
    ("/v1/events/fx", "get_live_fx_event", {"base": "SEK", "quote": "JPY"}),
    ("/v1/events/policy-rate", "get_policy_rate_event", {"mode": "live"}),
    ("/v1/events/energy", "get_energy_event", {"mode": "live"}),
    ("/v1/headlines/official", "get_official_headlines", {"source": "fed"}),
])
def test_upstream_errors_do_not_expose_sensitive_urls(client, monkeypatch, path, provider, params):
    async def failing_provider(*args, **kwargs):
        raise RuntimeError("request failed: https://upstream.invalid/?api_key=DO_NOT_LEAK")

    monkeypatch.setattr(main, provider, failing_provider)
    response = client.get(path, params=params)
    assert response.status_code == 502
    assert "DO_NOT_LEAK" not in response.text
    assert "upstream.invalid" not in response.text


def test_headline_cannot_be_used_as_quantified_event(client):
    response = client.post("/v1/translate", json={
        "event": {"headline_id": "headline-only", "title": "An official policy announcement", "requires_quantification": True},
        "profile": demo_profile().model_dump(mode="json"),
    })
    assert response.status_code == 422


def test_public_url_builds_narrow_mcp_allowlist(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://review.example:9443/service")
    settings = main._transport_security()
    assert settings.enable_dns_rebinding_protection
    assert "review.example:9443" in settings.allowed_hosts
    assert "review.example" in settings.allowed_hosts
    assert "https://review.example:9443" in settings.allowed_origins
    assert "*" not in settings.allowed_hosts
    assert "review.example:*" not in settings.allowed_hosts


def test_mcp_mount_accepts_localhost_and_rejects_other_hosts_and_origins(client):
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "rest-mount-test", "version": "1"},
    }}
    headers = {"Accept": "application/json, text/event-stream"}
    response = client.post("/mcp/", json=request, headers=headers)
    assert response.status_code == 200
    assert response.json()["result"]["protocolVersion"] == "2025-11-25"
    denied_host = client.post("/mcp/", json=request, headers={**headers, "Host": "untrusted.example"})
    assert denied_host.status_code == 421
    denied_origin = client.post("/mcp/", json=request, headers={**headers, "Origin": "https://untrusted.example"})
    assert denied_origin.status_code == 403


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_json_input_returns_safe_validation_error(client, value):
    import json
    from life_exchange_rate.providers.fixtures import demo_events
    event = demo_events()[0].model_dump(mode="json")
    event["new_value"] = value
    body = json.dumps({"event": event, "profile": demo_profile().model_dump(mode="json")})
    response = client.post("/v1/translate", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["detail"]
