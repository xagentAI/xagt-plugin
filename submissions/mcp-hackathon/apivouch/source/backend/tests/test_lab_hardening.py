"""Release-hardening regression tests for the Chaos Lab.

Covers the P1 blocker: lab traffic must never evict production evidence, and
each server-owned fixture must be fully deterministic (identical canonical
receipt JSON, receipt_id, fingerprint, and signature across runs).
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.outcomes import LAB_FIXED_CREATED_AT, LAB_FIXED_LATENCY_MS
from app.core import signing
from app.main import app
from app.models.db import OutcomeLabReceiptRow, OutcomeReceiptRow, engine
from app.schemas.api import OutcomeRequest
from app.services import outcomes
from app.services.http_client import SafeResponse
from app.services.outcomes import LabTiming

client = TestClient(app)

EXPECTED_IDS = (
    "consensus-success",
    "provider-disagreement",
    "schema-invalid",
    "upstream-failure",
    "over-budget",
    "origin-convergence",
)


def _production_rows():
    db = Session(engine)
    try:
        return {row.id: row.receipt_json for row in db.query(OutcomeReceiptRow).all()}
    finally:
        db.close()


def _lab_ids():
    db = Session(engine)
    try:
        return sorted(row.id for row in db.query(OutcomeLabReceiptRow).all())
    finally:
        db.close()


def test_repeated_runs_produce_identical_canonical_receipt_and_id():
    for scenario_id in EXPECTED_IDS:
        first = client.post(f"/api/outcomes/lab/{scenario_id}").json()
        second = client.post(f"/api/outcomes/lab/{scenario_id}").json()
        assert first["passed"] is True and second["passed"] is True
        assert outcomes.canonical_json(first["receipt"]) == outcomes.canonical_json(second["receipt"])
        assert first["receipt"]["receipt_id"] == second["receipt"]["receipt_id"]
        assert first["receipt"]["integrity"]["fingerprint"] == second["receipt"]["integrity"]["fingerprint"]
        assert first["receipt"]["created_at"] == LAB_FIXED_CREATED_AT
        # Probed providers use the fixed fixture latency; over-budget
        # providers are never called and keep latency_ms 0.
        for item in first["receipt"]["attempts"]:
            if "latency_ms" in item:
                assert item["latency_ms"] in (LAB_FIXED_LATENCY_MS, 0), item
        if scenario_id != "over-budget":
            assert any(item.get("latency_ms") == LAB_FIXED_LATENCY_MS
                       for item in first["receipt"]["attempts"])


def test_signed_repeated_runs_produce_identical_signature(monkeypatch):
    secret = base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode("ascii")
    for name in ("REQUIRE_SIGNED_RECEIPTS", "RECEIPT_SIGNING_PRIVATE_KEY_B64", "RECEIPT_SIGNING_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RECEIPT_SIGNING_PRIVATE_KEY_B64", secret)
    monkeypatch.setattr(signing, "SIGNING_CONFIG", signing.load_signing_config())
    signed_client = TestClient(app)
    for scenario_id in EXPECTED_IDS:
        first = signed_client.post(f"/api/outcomes/lab/{scenario_id}").json()
        second = signed_client.post(f"/api/outcomes/lab/{scenario_id}").json()
        assert first["passed"] is True and second["passed"] is True
        assert outcomes.canonical_json(first["receipt"]) == outcomes.canonical_json(second["receipt"])
        assert first["receipt"]["integrity"]["signature"] == second["receipt"]["integrity"]["signature"]


def test_different_scenarios_have_different_receipt_ids():
    ids = [client.post(f"/api/outcomes/lab/{scenario_id}").json()["receipt"]["receipt_id"]
           for scenario_id in EXPECTED_IDS]
    assert len(set(ids)) == len(EXPECTED_IDS)


def test_lab_traffic_never_evicts_production_receipts(monkeypatch):
    """Reproduction of the P1 blocker: with a tiny production limit, repeated
    lab runs must leave every production row ID and receipt JSON unchanged."""
    monkeypatch.setattr(outcomes, "MAX_OUTCOME_RECEIPTS", 2)
    first_prod = client.post("/api/outcomes/demo").json()
    second_prod = client.post("/api/outcomes/demo").json()
    assert first_prod["receipt_id"] != second_prod["receipt_id"]
    before = _production_rows()
    assert set(before) == {first_prod["receipt_id"], second_prod["receipt_id"]}
    for _ in range(3):
        for scenario_id in EXPECTED_IDS:
            body = client.post(f"/api/outcomes/lab/{scenario_id}").json()
            assert body["passed"] is True
    assert _production_rows() == before
    # Deterministic fixtures merge onto one deterministic lab row per
    # scenario for a fixed deployment commit and signing configuration; the
    # lab table may also hold signed variants from other tests, but
    # production is exactly untouched.
    current_lab_ids = set(_lab_ids())
    for scenario_id in EXPECTED_IDS:
        lab_id = client.post(f"/api/outcomes/lab/{scenario_id}").json()["receipt"]["receipt_id"]
        assert lab_id in current_lab_ids


def test_lab_retention_is_bounded_independently(monkeypatch):
    """Lab eviction counts lab rows only and never touches production."""
    monkeypatch.setattr(outcomes, "MAX_LAB_RECEIPTS", 3)
    before_production = _production_rows()
    # Start from an empty lab table so the bound is exercised precisely;
    # other tests recreate the scenario rows they need via the API.
    db = Session(engine)
    try:
        db.query(OutcomeLabReceiptRow).delete()
        db.commit()
    finally:
        db.close()
    for index in range(5):
        outcomes.store_lab_receipt({
            "receipt_id": f"{index:024x}",
            "created_at": LAB_FIXED_CREATED_AT,
            "marker": index,
        })
    assert _lab_ids() == [f"{index:024x}" for index in (2, 3, 4)]
    assert _production_rows() == before_production


def test_lab_storage_failure_cannot_delete_production(monkeypatch):
    seeded = client.post("/api/outcomes/demo").json()
    before = _production_rows()
    assert seeded["receipt_id"] in before

    def _boom(receipt):
        raise RuntimeError("lab storage unavailable")

    monkeypatch.setattr("app.api.outcomes.store_lab_receipt", _boom)
    quiet = TestClient(app, raise_server_exceptions=False)
    response = quiet.post("/api/outcomes/lab/consensus-success")
    assert response.status_code == 500
    assert "lab storage unavailable" not in response.text
    assert _production_rows() == before


def test_production_and_lab_receipts_share_public_retrieval():
    production = client.post("/api/outcomes/demo").json()
    lab = client.post("/api/outcomes/lab/consensus-success").json()["receipt"]
    for receipt_id in (production["receipt_id"], lab["receipt_id"]):
        response = client.get(f"/api/outcomes/receipts/{receipt_id}")
        assert response.status_code == 200
        assert response.json()["integrity_valid"] is True
    # Production takes precedence on retrieval.
    assert client.get(f"/api/outcomes/receipts/{production['receipt_id']}").json()["receipt"] == production


def test_caller_supplied_json_is_rejected_and_changes_nothing():
    before_lab = _lab_ids()
    before_production = _production_rows()
    evil_bodies = (
        {},
        {"expected_verdict": "VERIFIED"},
        {"urls": ["https://evil.example/quote"], "responses": [1]},
        {"timing": {"created_at": "2000-01-01T00:00:00Z", "latency_ms": 9999}},
    )
    for evil in evil_bodies:
        response = client.post("/api/outcomes/lab/consensus-success", json=evil)
        assert response.status_code == 400
        assert response.json() == {"detail": "Lab scenarios accept no request body"}
    raw = client.post("/api/outcomes/lab/consensus-success", content=b"{}")
    assert raw.status_code == 400
    assert _lab_ids() == before_lab
    assert _production_rows() == before_production
    # The documented no-body contract still serves clean runs.
    assert client.post("/api/outcomes/lab/consensus-success").json()["passed"] is True


@pytest.mark.asyncio
async def test_production_execution_uses_real_default_timing(monkeypatch):
    from datetime import UTC as _UTC
    from datetime import datetime as _real_datetime

    from app.api.outcomes import _lab_mapping, _lab_payload

    mapping = _lab_mapping("consensus-success")

    async def _in_process(_method, url):
        status, payload, final_url = mapping[url]
        return SafeResponse(status, {"content-type": "application/json"},
                            json.dumps(payload).encode("utf-8"), final_url or url)

    payload = OutcomeRequest.model_validate(_lab_payload("consensus-success")).model_dump()

    class _FrozenClock:
        @staticmethod
        def now(tz=None):
            return _real_datetime(2025, 5, 5, 12, 0, 0, tzinfo=_UTC)

    monkeypatch.setattr(outcomes, "datetime", _FrozenClock)
    # Default path consults the real clock call; the fixture clock is unused.
    production = await outcomes.execute_verified_outcome(payload, request_fn=_in_process)
    assert production["created_at"] == "2025-05-05T12:00:00Z"
    assert production["created_at"] != LAB_FIXED_CREATED_AT

    timing = LabTiming(created_at=LAB_FIXED_CREATED_AT, latency_ms=LAB_FIXED_LATENCY_MS)
    lab_first = await outcomes.execute_verified_outcome(payload, request_fn=_in_process, lab_timing=timing)
    lab_second = await outcomes.execute_verified_outcome(payload, request_fn=_in_process, lab_timing=timing)
    assert lab_first["created_at"] == LAB_FIXED_CREATED_AT
    assert outcomes.canonical_json(lab_first) == outcomes.canonical_json(lab_second)
    assert lab_first["receipt_id"] == lab_second["receipt_id"]


def test_all_six_verdicts_and_behavioral_checks_still_pass(monkeypatch):
    async def _no_network(*args, **kwargs):
        pytest.fail("Lab scenarios must use the deterministic in-process transport")

    monkeypatch.setattr(outcomes, "safe_request", _no_network)
    expected = {"consensus-success": "VERIFIED", "provider-disagreement": "UNVERIFIED",
                "schema-invalid": "UNVERIFIED", "upstream-failure": "UNVERIFIED",
                "over-budget": "UNVERIFIED", "origin-convergence": "UNVERIFIED"}
    for scenario_id, verdict in expected.items():
        body = client.post(f"/api/outcomes/lab/{scenario_id}").json()
        assert body["observed_verdict"] == verdict
        assert body["passed"] is True
        assert body["evidence"] == "deterministic-fixture"
        assert body["integrity_valid_after_storage"] is True
        assert all(check["passed"] for check in body["checks"])
