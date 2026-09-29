from app.demo import fixture
from app.research import research
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.research import Candle, DAY_MS, MAX_TIMESTAMP, ResearchRequest, bounded_ratio
from tools.fetch_history import fetch_candles


def test_fixture_is_reproducible_and_fail_closed() -> None:
    a = research(fixture("mixed"))
    b = research(fixture("mixed"))
    assert a["report_id"] == b["report_id"]
    assert a["nexus_validated"] is False
    assert a["no_execution"] is True
    assert a["decision"] in ("WAIT", "PAPER_CANDIDATE")


def test_shock_fixture_not_silently_promoted() -> None:
    result = research(fixture("shock"))
    assert result["decision"] == "WAIT"
    assert result["reason_codes"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("t", True),
        ("t", "1640995200000"),
        ("t", 1640995200000.0),
        ("t", -1),
        ("t", MAX_TIMESTAMP + 1),
        ("o", "100"),
        ("o", True),
        ("o", 1e-10),
        ("h", 1e12 + 1),
        ("c", float("inf")),
        ("l", float("nan")),
        ("v", -1),
        ("v", 1e18 + 1000),
        ("unexpected", 1),
    ],
)
def test_candle_strict_bounds(field: str, value: Any) -> None:
    data = {"t": 1640995200000, "o": 100, "h": 110, "l": 90, "c": 100, "v": 1}
    payload: dict[str, Any] = dict(data)
    payload[field] = value
    with pytest.raises(ValidationError):
        Candle.model_validate(payload)


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   ",
        "x" * 161,
        "venue\nname",
        "api_key=abc",
        "Bearer abc",
        "https://user:pass@example.org/data",
        "https://example.org/data?token=abc",
        "ghp_abcdef123456",
        "password: abc",
    ],
)
def test_source_rejects_blank_and_secret_like_content(source: str) -> None:
    data = fixture().model_dump()
    data["source"] = source
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate(data)


def test_request_requires_explicit_classification_and_strict_costs() -> None:
    data = fixture().model_dump()
    del data["data_kind"]
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate(data)
    data["data_kind"] = "historical"
    for value in ("10", True, float("inf"), -1, 201):
        data["fee_bps"] = value
        with pytest.raises(ValidationError):
            ResearchRequest.model_validate(data)


def test_shifted_daily_grid_and_open_days_are_rejected() -> None:
    data = fixture().model_dump()
    for candle in data["candles"]:
        candle["t"] += 1
    with pytest.raises(ValidationError, match="UTC midnight"):
        ResearchRequest.model_validate(data)
    for candle in data["candles"]:
        candle["t"] += 20000 * DAY_MS - 1
    with pytest.raises(ValidationError, match="fully closed"):
        ResearchRequest.model_validate(data)


def test_assignment_and_bypassed_copy_validation() -> None:
    request = fixture()
    with pytest.raises(ValidationError):
        request.fee_bps = -1
    with pytest.raises(ValidationError):
        request.candles[0].v = float("inf")
    invalid = request.model_copy(update={"source": "secret=abc"}, deep=True)
    with pytest.raises(ValidationError):
        research(invalid)
    request.candles[1] = request.candles[0].model_copy()
    with pytest.raises(ValidationError, match="gap-free"):
        research(request)


def test_legacy_branding_and_bounded_ratios() -> None:
    result = research(fixture())
    assert result["schema_version"] == "AlphaLitmus.legacy.v1"
    assert result["product"] == "AlphaLitmus"
    assert result["deprecated"] is True
    assert result["source"].startswith("AlphaLitmus")
    assert bounded_ratio(1, 0) is None
    assert bounded_ratio(1, 1e-20) is None
    assert bounded_ratio(float("inf"), 1) is None
    assert bounded_ratio(3, 2) == 1.5


@pytest.mark.parametrize(
    "fault", ["", "empty", "truncated", "duplicate", "gap", "outside", "timestamp", "close", "boolean", "oversized"]
)
def test_fetch_requires_complete_requested_coverage_without_network(fault: str) -> None:
    start = 1640995200000
    end = start + 250 * DAY_MS - 1
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        cursor = int(request.url.params["startTime"])
        rows: list[list[Any]] = [
            [t, "100", "110", "90", "100", "1", t + DAY_MS - 1]
            for t in range(cursor, min(cursor + 125 * DAY_MS, end + 1), DAY_MS)
        ]
        if fault == "empty" or (fault == "truncated" and calls == 2):
            rows = []
        elif fault == "duplicate":
            rows[1] = rows[0]
        elif fault == "gap":
            rows.pop(1)
        elif fault == "outside":
            rows[0][0] = end + 1
        elif fault == "timestamp":
            rows[0][0] = str(cursor)
        elif fault == "close":
            rows[0][6] -= 1
        elif fault == "boolean":
            rows[0][1] = True
        elif fault == "oversized":
            return httpx.Response(200, content=b" " * 2_000_001)
        return httpx.Response(200, json=rows)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if fault:
            with pytest.raises(ValueError):
                fetch_candles(client, start, end)
        else:
            candles = fetch_candles(client, start, end)
            assert calls == 2
            assert len(candles) == 250
            assert candles[0].t == start
            assert candles[-1].t + DAY_MS - 1 == end
