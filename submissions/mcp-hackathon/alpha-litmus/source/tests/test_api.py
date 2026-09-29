from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import provenance, transport
from app.contracts import Report, Verification
from app.demo import fixture
from app.main import Health, Proof, app
from pydantic import ValidationError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    monkeypatch.delenv("ALPHALITMUS_ENABLE_NEXUS", raising=False)
    monkeypatch.delenv("ALPHALITMUS_ENV", raising=False)
    with TestClient(app, raise_server_exceptions=False) as result:
        yield result


def test_dashboard_health_proof(client: TestClient) -> None:
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert 'rel="icon"' in dashboard.text
    assert "data:image/svg+xml" in dashboard.text
    health = client.get("/health").json()
    proof = client.get("/.well-known/xagent-verification.json").json()
    assert health["no_execution"] is True
    assert health["service"] == "alpha-litmus"
    assert proof["slug"] == "alpha-litmus"
    assert health["commit"] == proof["commit"]
    assert health["commit_reviewable"] == proof["commit_reviewable"]
    assert proof["provenance_basis"] == "syntax_only_not_authenticated"


def test_capabilities(client: TestClient) -> None:
    data = client.get("/v1/capabilities").json()
    assert len(data["tools"]) == 8
    assert "evaluate_live_nexus_candidate" in data["tools"]
    assert data["tools"][0] == "evaluate_strategy_release"
    assert set(data["tools"]) == {
        "evaluate_strategy_release", "challenge_nexus_strategy", "find_failure_boundary",
            "verify_failure_certificate", "get_demo_fixture", "run_nexus_window_stability",
            "replay_recorded_nexus_evidence", "evaluate_live_nexus_candidate",
        }
    assert data["side_effects"] == ["opt_in_nexus_backtest_compute"]
    assert data["nexus_enabled"] is False
    assert "reverse proxy" in data["deployment"]


def test_missing_key_fails_closed(client: TestClient) -> None:
    response = client.post("/v1/audit", json={"symbol": "BTC/USDT"})
    assert response.status_code == 200
    assert response.json()["decision"] == "WAIT"
    assert response.json()["evidence"]["signal"]["reason"] == "NEXUS_NOT_CONFIGURED"


def test_nexus_disabled_with_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_API_KEY", "secret-never-return")

    async def forbidden(symbol: str) -> dict[str, object]:
        raise AssertionError("network attempted")

    monkeypatch.setattr(transport, "read_nexus", forbidden)
    response = client.post("/v1/challenge", json={"mode": "nexus"})
    assert response.status_code == 200
    assert "secret-never-return" not in response.text
    Report.model_validate(response.json())
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("endpoint", ["challenge", "find-failure-boundary"])
def test_report_and_verification(client: TestClient, endpoint: str) -> None:
    response = client.post("/v1/" + endpoint, json={"mode": "nexus"})
    assert response.status_code == 200
    report = Report.model_validate(response.json())
    assert report.provenance.commit == client.get("/health").json()["commit"]
    checked = client.post("/v1/verify-report", json=report.model_dump(mode="json"))
    assert checked.status_code == 200
    assert Verification.model_validate(checked.json()).valid
    damaged = report.model_dump(mode="json")
    damaged["report_id"] = "0" * 64
    assert client.post("/v1/verify-report", json=damaged).json()["valid"] is False


def test_reference_report(client: TestClient) -> None:
    response = client.post("/v1/challenge", json={
        "research": fixture().model_dump(mode="json"),
        "additional_cost_max_bps": 0, "bootstrap_iterations": 50,
    })
    assert response.status_code == 200
    report = Report.model_validate(response.json())
    assert report.analysis is not None
    assert report.nexus_validated is False


@pytest.mark.parametrize("scenario", ["mixed", "shock"])
def test_demo_fixture(client: TestClient, scenario: str) -> None:
    response = client.get("/v1/demo/" + scenario)
    assert response.status_code == 200
    report = Report.model_validate(response.json())
    assert report.request.research == fixture(scenario)
    assert report.analysis is not None
    assert report.evidence_classification == "synthetic_reference"
    assert client.post("/v1/verify-report", json=response.json()).json()["valid"] is True


def test_invalid_input_and_demo_boundary(client: TestClient) -> None:
    assert client.post("/v1/research", json={"candles": []}).status_code == 422
    assert client.get("/v1/demo/fragile").status_code == 404
    response = client.post("/v1/challenge", json={"mode": "nexus", "secret": "never-echo"})
    assert response.status_code == 422
    assert "never-echo" not in response.text
    assert client.post("/v1/challenge", json={"mode": "nexus", "bootstrap_iterations": "50"}).status_code == 422


def test_legacy_research(client: TestClient) -> None:
    response = client.post("/v1/research", json=fixture().model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["deprecated"] is True
    assert response.json()["mode"] == "independent_research"


def test_audit_drops_raw_upstream(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "true")

    async def upstream(symbol: str) -> dict[str, object]:
        return {"signal": {"status": "received", "data": {"secret": "never-echo"}},
                "metrics": {"status": "unavailable", "reason": "never-echo"}}

    monkeypatch.setattr(transport, "read_nexus", upstream)
    response = client.post("/v1/audit", json={})
    assert response.status_code == 200
    assert "never-echo" not in response.text
    assert "data" not in response.json()["evidence"]["signal"]


def test_safe_exception(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> None:
        raise RuntimeError("secret-never-echo")

    monkeypatch.setattr(transport, "challenge", broken)
    response = client.post("/v1/challenge", json={"mode": "nexus"})
    assert response.status_code == 500
    assert response.json() == {"detail": "INTERNAL_ERROR"}


def test_commit_snapshot_and_production(monkeypatch: pytest.MonkeyPatch) -> None:
    provenance._snapshot.cache_clear()
    monkeypatch.delenv("ALPHALITMUS_COMMIT", raising=False)
    monkeypatch.setenv("TRADEPROOF_COMMIT", "c" * 40)
    try:
        assert provenance.commit_state() == {"commit": "local-dev", "commit_reviewable": False}
        monkeypatch.setenv("ALPHALITMUS_ENV", "production")
        with pytest.raises(RuntimeError):
            with TestClient(app):
                pass
        for invalid in ("0" * 40, "A" * 40, "abc", "secret-token"):
            provenance._snapshot.cache_clear()
            monkeypatch.setenv("ALPHALITMUS_COMMIT", invalid)
            with pytest.raises(RuntimeError):
                provenance.validate_startup()
        provenance._snapshot.cache_clear()
        monkeypatch.setenv("ALPHALITMUS_COMMIT", "a" * 40)
        with TestClient(app) as client:
            monkeypatch.setenv("ALPHALITMUS_COMMIT", "b" * 40)
            assert client.get("/health").json()["commit"] == "a" * 40
            report = client.post("/v1/challenge", json={"mode": "nexus"}).json()
            assert report["provenance"]["commit"] == "a" * 40
    finally:
        provenance._snapshot.cache_clear()


def test_openapi_strict_models(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for name in ("Report-Input", "Report-Output", "ChallengeRequest-Input", "ResearchRequest", "LegacyResearch", "LegacyAudit", "Verification"):
        assert schema["components"]["schemas"][name]["additionalProperties"] is False
    assert schema["paths"]["/v1/audit"]["post"]["deprecated"] is True


@pytest.mark.parametrize("model", [Health, Proof])
@pytest.mark.parametrize("commit,reviewable", [("abc123", True), ("a" * 40, False), ("0" * 40, True)])
def test_health_proof_provenance_contract(model: type[Health] | type[Proof], commit: str, reviewable: bool) -> None:
    with pytest.raises(ValidationError):
        model(commit=commit, commit_reviewable=reviewable)
