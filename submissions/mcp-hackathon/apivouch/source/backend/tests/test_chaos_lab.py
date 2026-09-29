"""Focused contracts for the deterministic Chaos & Refusal Lab."""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.core import signing
from app.main import app
from app.services import outcomes

client = TestClient(app)

EXPECTED_IDS = (
    "consensus-success",
    "provider-disagreement",
    "schema-invalid",
    "upstream-failure",
    "over-budget",
    "origin-convergence",
)

EXPECTED_VERDICTS = {
    "consensus-success": "VERIFIED",
    "provider-disagreement": "UNVERIFIED",
    "schema-invalid": "UNVERIFIED",
    "upstream-failure": "UNVERIFIED",
    "over-budget": "UNVERIFIED",
    "origin-convergence": "UNVERIFIED",
}


def test_catalog_returns_exactly_six_allowlisted_scenarios():
    response = client.get("/api/outcomes/lab")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["evidence"] == "deterministic-fixture"
    assert [item["id"] for item in body["scenarios"]] == list(EXPECTED_IDS)
    for item in body["scenarios"]:
        assert set(item) >= {"id", "title", "description", "expected_verdict"}
        assert item["expected_verdict"] == EXPECTED_VERDICTS[item["id"]]


def test_unknown_scenario_returns_404():
    response = client.post("/api/outcomes/lab/unknown-scenario")
    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown lab scenario"}


def test_every_scenario_matches_expected_verdict_with_valid_receipt():
    for scenario_id in EXPECTED_IDS:
        body = client.post(f"/api/outcomes/lab/{scenario_id}").json()
        assert body["schema_version"] == 1
        assert body["scenario"]["id"] == scenario_id
        assert body["observed_verdict"] == EXPECTED_VERDICTS[scenario_id]
        assert body["scenario"]["expected_verdict"] == EXPECTED_VERDICTS[scenario_id]
        assert body["passed"] is True
        assert body["integrity_valid_after_storage"] is True
        assert outcomes.verify_receipt(body["receipt"]) is True
        assert all(check["passed"] for check in body["checks"])


def test_every_scenario_is_deterministic():
    for scenario_id in EXPECTED_IDS:
        first = client.post(f"/api/outcomes/lab/{scenario_id}").json()
        second = client.post(f"/api/outcomes/lab/{scenario_id}").json()
        assert first["observed_verdict"] == second["observed_verdict"]
        assert first["scenario"]["expected_verdict"] == second["scenario"]["expected_verdict"]
        assert first["passed"] == second["passed"] is True
        assert first["receipt"]["result"] == second["receipt"]["result"]
        assert first["receipt"]["selected_provider"] == second["receipt"]["selected_provider"]
        # Full determinism: identical canonical receipt JSON, ID, and fingerprint.
        assert outcomes.canonical_json(first["receipt"]) == outcomes.canonical_json(second["receipt"])
        assert first["receipt"]["receipt_id"] == second["receipt"]["receipt_id"]
        assert first["receipt"]["integrity"]["fingerprint"] == second["receipt"]["integrity"]["fingerprint"]
        assert first["receipt"]["created_at"] == "2026-01-01T00:00:00Z"


def test_every_receipt_retrievable_unchanged_after_storage():
    for scenario_id in EXPECTED_IDS:
        produced = client.post(f"/api/outcomes/lab/{scenario_id}").json()["receipt"]
        stored = client.get(f"/api/outcomes/receipts/{produced['receipt_id']}")
        assert stored.status_code == 200
        envelope = stored.json()
        assert envelope["receipt"] == produced
        assert envelope["integrity_valid"] is True
        assert outcomes.canonical_json(envelope["receipt"]) == outcomes.canonical_json(produced)


def test_success_selects_only_eligible_agreeing_provider():
    body = client.post("/api/outcomes/lab/consensus-success").json()
    receipt = body["receipt"]
    assert receipt["verdict"] == "VERIFIED"
    assert receipt["selected_provider"] in {"Lab Alpha", "Lab Beta"}
    selected = next(item for item in receipt["attempts"] if item["name"] == receipt["selected_provider"])
    assert selected["status"] == "SELECTED"
    assert receipt["agreement"]["providers"] >= receipt["agreement"]["required"] >= 2


def test_refusal_scenarios_select_no_provider_or_result():
    for scenario_id in ("provider-disagreement", "schema-invalid", "upstream-failure",
                        "over-budget", "origin-convergence"):
        receipt = client.post(f"/api/outcomes/lab/{scenario_id}").json()["receipt"]
        assert receipt["verdict"] == "UNVERIFIED"
        assert receipt["selected_provider"] is None
        assert receipt["result"] is None
        assert receipt["selected_price_usd"] == 0


def test_over_budget_performs_zero_provider_calls(monkeypatch):
    async def no_network(*args, **kwargs):
        pytest.fail("Over-budget scenario must never call the provider transport")

    monkeypatch.setattr(outcomes, "safe_request", no_network)
    body = client.post("/api/outcomes/lab/over-budget").json()
    assert body["passed"] is True
    assert body["observed_verdict"] == "UNVERIFIED"
    assert next(check for check in body["checks"] if check["id"] == "zero-provider-calls")["passed"] is True


def test_origin_convergence_proves_final_origin_rejection():
    body = client.post("/api/outcomes/lab/origin-convergence").json()
    receipt = body["receipt"]
    assert receipt["provider_independence"]["required"] is True
    assert any("independence" in str(item.get("reason") or "").lower() for item in receipt["attempts"])
    assert next(check for check in body["checks"] if check["id"] == "final-origin-rejection")["passed"] is True


def test_no_lab_scenario_performs_real_network_access(monkeypatch):
    async def no_network(*args, **kwargs):
        pytest.fail("Lab scenarios must use the deterministic in-process transport")

    monkeypatch.setattr(outcomes, "safe_request", no_network)
    for scenario_id in EXPECTED_IDS:
        body = client.post(f"/api/outcomes/lab/{scenario_id}").json()
        assert body["passed"] is True, scenario_id


def test_signed_lab_receipt_remains_correct(monkeypatch):
    secret = base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode("ascii")
    for name in ("REQUIRE_SIGNED_RECEIPTS", "RECEIPT_SIGNING_PRIVATE_KEY_B64", "RECEIPT_SIGNING_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RECEIPT_SIGNING_PRIVATE_KEY_B64", secret)
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.load_signing_config())
    signed_client = TestClient(app)
    for scenario_id in EXPECTED_IDS:
        body = signed_client.post(f"/api/outcomes/lab/{scenario_id}").json()
        receipt = body["receipt"]
        assert receipt["format"] == "apivouch-outcome-receipt-v2"
        assert body["passed"] is True
        stored = signed_client.get(f"/api/outcomes/receipts/{receipt['receipt_id']}").json()
        assert stored["authenticity"] == {"state": "signed", "valid": True}


def test_safe_failure_formatting_contains_no_secrets_or_diagnostics():
    response = client.post("/api/outcomes/lab/does-not-exist")
    assert response.status_code == 404
    for forbidden in ("Traceback", "SELECT", ".py", "/tmp/", "BEGIN PRIVATE", "secret"):
        assert forbidden not in response.text
    for scenario_id in EXPECTED_IDS:
        text = json.dumps(client.post(f"/api/outcomes/lab/{scenario_id}").json())
        for forbidden in ("Traceback", "BEGIN PRIVATE", ".py:"):
            assert forbidden not in text


def test_lab_frontend_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    index = (root / "frontend/index.html").read_text(encoding="utf-8")
    app_js = (root / "frontend/app.js").read_text(encoding="utf-8")
    assert "Chaos &amp; Refusal Lab" in index or "Chaos & Refusal Lab" in index
    assert "Deterministic in-process safety evidence" in index
    assert "Run all safety scenarios" in index
    assert 'id="labRunAll"' in index
    assert 'id="labCards"' in index
    assert 'id="labSummary"' in index
    assert "safety scenarios behaved as expected" in app_js
    assert "View proof" in app_js
    assert "runAllLabScenarios" in app_js
    assert 'request(`/api/outcomes/lab/${scenario.id}`, {method: "POST"})' in app_js
    assert "canonical JSON round-trip exactly equal" in index
