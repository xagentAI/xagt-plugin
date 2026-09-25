import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.storage import digest
from support.application import make_app
from support.storage import SQLiteTestStore
from app.evidence import EvidenceError, reproduce


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path / "research.sqlite3")


@pytest.fixture
def client(app):
    with TestClient(app) as current:
        yield current


def curve(name="A"):
    return {
        "schema_version": 1,
        "name": name,
        "strategy_id": name,
        "run_id": "test",
        "source_kind": "synthetic",
        "currency": "USDT",
        "frequency": "1d",
        "timezone": "UTC",
        "timestamp_convention": "valuation_boundary",
        "equity_kind": "mark_to_market",
        "completeness": "complete",
        "external_cash_flows": "none",
        "cost_model": "zero-v1",
        "initial": {"timestamp": "2026-01-01T00:00:00Z", "equity": "100"},
        "points": [
            {"timestamp": "2026-01-02T00:00:00Z", "equity": "120"},
            {"timestamp": "2026-01-03T00:00:00Z", "equity": "90"},
        ],
        "provenance": {"observed_before": False},
    }


def make_inputs(client):
    a = client.post("/v1/data-snapshots", json={"curve": curve()})
    b = client.post("/v1/data-snapshots", json={"curve": curve("B")})
    assert a.status_code == b.status_code == 201
    return {"baseline_snapshot_id": a.json()["snapshot_id"], "candidate_snapshot_id": b.json()["snapshot_id"]}


def make_experiment(client, **overrides):
    body = {**make_inputs(client), **overrides}
    response = client.post("/v1/experiments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_fresh_flow_evidence_offline_and_persistence(client, app, tmp_path):
    inputs = make_inputs(client)
    assert client.post("/v1/comparison-inputs/validate", json=inputs).json()["comparable"]
    record = client.post("/v1/experiments", json=inputs).json()
    assert record["result"]["status"] == "comparison_only"
    assert record["result"]["scenarios"]["baseline"]["total_return_pct"] == "-10"
    evidence = client.get(record["evidence_url"])
    assert "attachment;" in evidence.headers["content-disposition"]
    bundle = evidence.json()
    assert reproduce(bundle)["verified"]
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(bundle))
    output = subprocess.run(
        [sys.executable, "-m", "app.reproduce", str(path)], capture_output=True, text=True
    )
    assert output.returncode == 0 and json.loads(output.stdout)["verified"]
    reloaded = SQLiteTestStore(app.state.store.path)
    assert reloaded.secret == app.state.store.secret
    assert len(client.get("/v1/experiments").json()["experiments"]) == 1
    assert client.get("/v1/experiments/" + record["experiment_id"]).json() == record
    assert bundle["provenance"]["effective_mode"] == "historical_exploration"


def test_cross_session_cannot_read_or_reference(app):
    with TestClient(app) as a, TestClient(app) as b:
        record = make_experiment(a)
        assert b.get(record["evidence_url"]).status_code == 404
        assert b.get("/v1/experiments/" + record["experiment_id"]).status_code == 404
        assert b.post("/v1/experiments", json=record["config"]).status_code == 404
        assert b.get("/v1/experiments").json() == {"experiments": []}
        b.cookies.set("strategy_increment_session", "0" * 64 + "." + "0" * 64)
        assert b.get(record["evidence_url"]).status_code == 404


def test_new_experiment_preserves_old_and_exploration(client):
    first = make_experiment(client, mode="declared_holdout", data_seen=False)
    assert first["provenance"]["effective_mode"] == "declared_holdout"
    new_config = {**first["config"], "parent_experiment_id": first["experiment_id"]}
    second = client.post("/v1/experiments", json=new_config).json()
    assert first["experiment_id"] != second["experiment_id"]
    assert second["provenance"]["effective_mode"] == "historical_exploration"
    assert client.get("/v1/experiments/" + first["experiment_id"]).json() == first
    third = make_experiment(client, mode="declared_holdout", data_seen=False)
    assert third["provenance"]["effective_mode"] == "historical_exploration"


def test_invalid_import_and_incompatible_pair(client):
    bad = curve()
    bad["points"].pop(0)
    response = client.post("/v1/data-snapshots", json={"curve": bad})
    assert response.status_code == 422 and "snapshot_id" not in response.json()
    inputs = make_inputs(client)
    invalid = curve("other")
    invalid["cost_model"] = "different"
    other = client.post("/v1/data-snapshots", json={"curve": invalid}).json()
    inputs["candidate_snapshot_id"] = other["snapshot_id"]
    assert client.post("/v1/comparison-inputs/validate", json=inputs).json()["comparable"] is False
    assert client.post("/v1/experiments", json=inputs).status_code == 422
    assert not client.get("/v1/experiments").json()["experiments"]


def test_partial_criteria_and_unknown_fields_fail(client):
    inputs = make_inputs(client)
    assert (
        client.post(
            "/v1/experiments", json={**inputs, "criteria": {"min_drawdown_improvement_pp": 1}}
        ).status_code
        == 422
    )
    assert client.post("/v1/experiments", json={**inputs, "mode": "live"}).status_code == 422
    assert client.post("/v1/experiments", json={**inputs, "data_seen": "false"}).status_code == 422
    assert client.post("/v1/data-snapshots", json={"curve": curve(), "api_key": "secret"}).status_code == 422


def test_tamper_detection_even_when_outer_hash_replaced(client):
    record = make_experiment(client)
    bundle = client.get(record["evidence_url"]).json()
    bundle["result"]["status"] = "criteria_met"
    with pytest.raises(EvidenceError):
        reproduce(bundle)
    bundle["integrity"]["payload_sha256"] = digest({k: v for k, v in bundle.items() if k != "integrity"})
    with pytest.raises(EvidenceError, match="Reproduced"):
        reproduce(bundle)


def test_safe_request_boundaries_and_headers(client):
    assert (
        client.post(
            "/v1/data-snapshots", json={"curve": curve()}, headers={"origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert client.post("/v1/data-snapshots", content="{}").status_code == 415
    assert (
        client.post(
            "/v1/data-snapshots",
            content="x" * (2 * 1024 * 1024 + 1),
            headers={"content-type": "application/json"},
        ).status_code
        == 413
    )
    malformed = client.post(
        "/v1/data-snapshots", content="{invalid-secret", headers={"content-type": "application/json"}
    )
    assert malformed.status_code == 422 and "invalid-secret" not in malformed.text
    response = client.get("/health")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["commit"] is None
    assert client.get("/.well-known/xagent-verification.json").status_code == 503


def test_save_failure_not_reported_as_research_failure(client, app):
    inputs = make_inputs(client)
    # Fail the actual insert after pair reads succeed. The test store translates
    # the backend exception just as DurableStore does across its binding boundary.
    with app.state.store.connect() as con:
        con.executescript("""
            CREATE TRIGGER fail_experiment_insert BEFORE INSERT ON experiments
            BEGIN SELECT RAISE(ABORT, 'credential-MUST-NOT-LEAK'); END;
        """)
    response = client.post("/v1/experiments", json=inputs)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert "credential" not in response.text and "criteria_not_met" not in response.text
    assert client.get("/v1/experiments").json() == {"experiments": []}


def test_nexus_disabled_no_fallback(client):
    source = client.get("/v1/source-status").json()["nexus"]
    assert source["configured"] is False
    assert source["verified"] is False
    assert source["public_refs"] == []
    response = client.post("/v1/nexus/import", json={"strategy_ref": "demo"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "source_unavailable"


def test_quota_has_no_partial_insert(client, app):
    app.state.store.limit = 1
    assert client.post("/v1/data-snapshots", json={"curve": curve()}).status_code == 201
    assert client.post("/v1/data-snapshots", json={"curve": curve("B")}).status_code == 429


def test_demo_flow_and_missing_case(client):
    cases = client.get("/v1/demo-cases").json()["cases"]
    assert len(cases) >= 5
    successful = rejected = 0
    for case in cases:
        example = client.get("/v1/demo-cases/" + case["id"]).json()
        snapshots = [
            client.post("/v1/data-snapshots", json={"curve": example[key]})
            for key in ("baseline", "candidate")
        ]
        if any(r.status_code == 422 for r in snapshots):
            rejected += 1
            continue
        response = client.post(
            "/v1/experiments",
            json={
                "baseline_snapshot_id": snapshots[0].json()["snapshot_id"],
                "candidate_snapshot_id": snapshots[1].json()["snapshot_id"],
                "criteria": example["criteria"],
                "mode": "declared_holdout",
                "data_seen": False,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["provenance"]["effective_mode"] == "historical_exploration"
        successful += 1
    assert successful >= 4 and rejected == 1
    assert client.get("/v1/demo-cases/missing").status_code == 404


def test_decimal_wire_precision_and_ambiguous_json(client):
    raw = json.dumps({"curve": curve()}).replace('"equity": "100"', '"equity": 100.123456789123456789')
    response = client.post("/v1/data-snapshots", content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 201
    assert response.json()["curve"]["initial"]["equity"] == "100.123456789123456789"
    assert (
        client.post(
            "/v1/data-snapshots",
            content='{"curve":{},"curve":{}}',
            headers={"content-type": "application/json"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/data-snapshots", content='{"curve":NaN}', headers={"content-type": "application/json"}
        ).status_code
        == 422
    )
    assert client.get("/health", headers={"host": "evil.invalid"}).status_code == 400


def test_evidence_retains_original_method_after_upgrade(client, monkeypatch):
    record = make_experiment(client)
    before = client.get(record["evidence_url"]).json()
    import app.evidence as evidence_module

    monkeypatch.setattr(evidence_module, "METHOD_VERSION", "future-method/v99")
    after = client.get(record["evidence_url"]).json()
    assert before == after


def test_raw_input_preserved_and_storage_corruption_blocks(client, app):
    original = curve()
    original["initial"]["timestamp"] = "2026-01-01T00:00:00+00:00"
    snap = client.post("/v1/data-snapshots", json={"curve": original}).json()
    assert snap["raw_curve"] == original
    assert snap["curve"]["initial"]["timestamp"].endswith("Z")
    inputs = {"baseline_snapshot_id": snap["snapshot_id"], "candidate_snapshot_id": snap["snapshot_id"]}
    record = client.post("/v1/experiments", json=inputs).json()
    evidence = client.get(record["evidence_url"]).json()
    assert evidence["raw_curves"]["baseline"] == original
    assert reproduce(evidence)["verified"]
    # Simulate disk corruption without exposing any update operation in the API.
    with app.state.store.connect() as con:
        snap["curve"]["initial"]["equity"] = "999"
        con.execute("UPDATE snapshots SET payload=? WHERE id=?", (json.dumps(snap), snap["snapshot_id"]))
    assert client.post("/v1/experiments", json=inputs).status_code == 503
    assert client.get(record["evidence_url"]).status_code == 503


def test_legacy_optional_facts_and_unknown_normalization(client):
    record = make_experiment(client)
    bundle = client.get(record["evidence_url"]).json()
    bundle["result"].pop("comparison_facts")
    bundle["integrity"]["payload_sha256"] = digest({k: v for k, v in bundle.items() if k != "integrity"})
    assert reproduce(bundle)["verified"]
    bundle["normalization_version"] = "unknown/v2"
    bundle["integrity"]["payload_sha256"] = digest({k: v for k, v in bundle.items() if k != "integrity"})
    with pytest.raises(EvidenceError, match="normalization version"):
        reproduce(bundle)
