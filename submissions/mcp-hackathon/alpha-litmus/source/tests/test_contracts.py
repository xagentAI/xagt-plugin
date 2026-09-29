import pytest
from pydantic import ValidationError

from app.contracts import ChallengeRequest, Metrics, Report


@pytest.mark.parametrize("field,value", [
    ("mode", "other"), ("attempted_variants", True), ("attempted_variants", "4"),
    ("attempted_variants", 1.0), ("attempted_variants", 0), ("attempted_variants", 1_000_001),
    ("bootstrap_iterations", True), ("bootstrap_iterations", 49),
    ("bootstrap_iterations", 501), ("bootstrap_iterations", "200"),
    ("additional_cost_max_bps", 201), ("additional_cost_max_bps", -1),
    ("additional_cost_max_bps", float("nan")), ("additional_cost_max_bps", float("inf")),
    ("cost_resolution_bps", .49), ("cost_resolution_bps", 10.01),
    ("cost_resolution_bps", "1"), ("symbol", "btc/usdt"), ("extra", 1),
])
def test_request_rejects_invalid(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ChallengeRequest.model_validate({"mode": "nexus", field: value})


def test_reference_requires_research() -> None:
    with pytest.raises(ValidationError):
        ChallengeRequest()


def test_defaults() -> None:
    req = ChallengeRequest(mode="nexus")
    assert req.symbol == "BTC/USDT"
    assert req.attempted_variants is None
    assert req.additional_cost_max_bps == 100
    assert req.cost_resolution_bps == 1
    assert req.bootstrap_iterations == 200


@pytest.mark.parametrize("cost,resolution,iterations", [(0, .5, 50), (200, 10, 500)])
def test_inclusive_bounds(cost: float, resolution: float, iterations: int) -> None:
    ChallengeRequest(mode="nexus", additional_cost_max_bps=cost,
                     cost_resolution_bps=resolution, bootstrap_iterations=iterations)


@pytest.mark.parametrize("field,value", [("return_pct", float("inf")), ("max_drawdown_pct", 101),
                                         ("trade_count", True), ("observations", 0), ("extra", 0)])
def test_nested_metrics_strict(field: str, value: object) -> None:
    data: dict[str, object] = {"return_pct": 0.0, "max_drawdown_pct": 0.0, "trade_count": 0, "observations": 1}
    data[field] = value
    with pytest.raises(ValidationError):
        Metrics.model_validate(data)


def test_report_export() -> None:
    assert Report.model_config["extra"] == "forbid"


@pytest.mark.parametrize("stamp", [
    "2025-02-29T00:00:00+00:00", "2024-02-30T00:00:00+00:00",
    "0000-01-01T00:00:00+00:00", "2025-13-01T00:00:00+00:00",
    "2025-01-01T24:00:00+00:00", "2025-01-01T00:00:60+00:00",
    "2025-01-01T00:00:00Z", "2025-01-01T00:00:00+01:00",
    "2025-01-01T00:00:00.000+00:00", "2025-01-01 00:00:00+00:00",
])
def test_report_calendar_validation(stamp: str) -> None:
    from app.lab import challenge
    payload = challenge(ChallengeRequest(mode="nexus")).model_dump()
    payload["created_at"] = stamp
    with pytest.raises(ValidationError):
        Report.model_validate(payload)


def test_report_accepts_leap_day() -> None:
    from app.lab import challenge
    payload = challenge(ChallengeRequest(mode="nexus")).model_dump()
    payload["created_at"] = "2024-02-29T23:59:59+00:00"
    assert Report.model_validate(payload).created_at == payload["created_at"]
