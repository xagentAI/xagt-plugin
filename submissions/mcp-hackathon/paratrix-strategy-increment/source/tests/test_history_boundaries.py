"""Exploration history follows actual UTC intervals, including fractional seconds."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from support.application import make_app


def save_declared_experiment(client, start):
    initial = datetime.fromisoformat(start.replace("Z", "+00:00"))
    curve = {
        "schema_version": 1,
        "name": "Declared research input",
        "strategy_id": "research-a",
        "run_id": "fractional-clock",
        "source_kind": "inline_simulation",
        "currency": "USDT",
        "frequency": "1d",
        "timezone": "UTC",
        "timestamp_convention": "valuation_boundary",
        "equity_kind": "mark_to_market",
        "completeness": "complete",
        "external_cash_flows": "none",
        "cost_model": "zero-fees-v1",
        "initial": {"timestamp": start, "equity": "100"},
        "points": [
            {
                "timestamp": (initial + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "equity": "102",
            }
        ],
        "provenance": {"observed_before": False},
    }
    snapshot = client.post("/v1/data-snapshots", json={"curve": curve})
    assert snapshot.status_code == 201, snapshot.text
    identifier = snapshot.json()["snapshot_id"]
    response = client.post(
        "/v1/experiments",
        json={
            "baseline_snapshot_id": identifier,
            "candidate_snapshot_id": identifier,
            "mode": "declared_holdout",
            "data_seen": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("first_start", "second_start", "overlaps"),
    [
        ("2026-01-01T00:00:00.500000Z", "2026-01-02T00:00:00Z", True),
        ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00.500000Z", False),
        ("2026-01-01T00:00:00.500000Z", "2026-01-02T00:00:00.500000+00:00", False),
        ("2026-01-01T00:00:00.500000Z", "2026-01-02T00:00:00.499999Z", True),
    ],
    ids=["overlap-half-second", "separate-half-second", "touching-boundary", "overlap-microsecond"],
)
def test_history_uses_chronological_interval_boundaries(tmp_path, first_start, second_start, overlaps):
    with TestClient(make_app(tmp_path / "history.sqlite3")) as client:
        first = save_declared_experiment(client, first_start)
        assert first["provenance"]["effective_mode"] == "declared_holdout"
        first_evidence = client.get(first["evidence_url"]).json()

        second = save_declared_experiment(client, second_start)
        provenance = second["provenance"]
        expected_mode = "historical_exploration" if overlaps else "declared_holdout"
        assert provenance["effective_mode"] == expected_mode
        assert any("overlapping interval" in reason for reason in provenance["exploration_reasons"]) is overlaps
        assert provenance["requested_mode"] == "declared_holdout"

        # Reclassification of the new experiment never mutates the old declaration or evidence.
        assert client.get("/v1/experiments/" + first["experiment_id"]).json() == first
        assert client.get(first["evidence_url"]).json() == first_evidence
