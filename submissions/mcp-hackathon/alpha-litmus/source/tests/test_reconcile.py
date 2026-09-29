import json
from typing import Any

import pytest

from app.reconcile import reconcile
from app.contracts import ChallengeRequest
from app.lab import challenge


def evidence() -> dict[str, Any]:
    return {label: {"status": "received", "data": data} for label, data in {
        "signal": {"symbol": "BTC/USDT", "trade_intent": "BUY", "timestamp": 1000},
        "metrics": {"trade_count": 3, "win_rate_pct": 100 / 3, "profit_factor": 2,
                    "max_drawdown": "9.09%", "total_return_pct": 10},
        "equity": {"run_id": "bt-a", "points": [{"t": 1, "equity": 100}, {"t": 2, "equity": 110},
                                                       {"t": 3, "equity": 100}, {"t": 4, "equity": 110}]},
        "trades": {"run_id": "bt-a", "trades": [{"symbol": "BTC/USDT", "pnl": pnl} for pnl in (20, -10, 0)]},
    }.items()}


def checks(report: dict[str, Any]) -> dict[str, Any]:
    return {row["code"]: row for row in report["results"]}


def test_hand_calculated_summary_and_contract() -> None:
    report = reconcile(evidence(), "BTC/USDT", now=1000)
    summary = report["summary"]
    assert summary["recent_trade_count"] == 3
    assert summary["recent_wins"] == summary["recent_losses"] == summary["recent_breakeven"] == 1
    assert summary["recent_gross_profit"] == 20
    assert summary["recent_gross_loss"] == 10
    assert summary["recent_pnl"] == summary["equity_change"] == 10
    assert summary["recent_profit_factor"] == 2
    assert summary["sampled_max_drawdown_pct"] == pytest.approx(100 / 11)
    assert report["inconsistent"] is False
    assert report["unavailable"] == []
    assert checks(report)["METRICS_SIGNAL_RUN_BINDING"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert all(set(row) == {"code", "status", "claimed", "recomputed", "tolerance", "evidence_path", "explanation"} for row in report["results"])
    assert "Conditional" in checks(report)["TRADE_COUNT"]["explanation"]
    for code in ("TRADE_COUNT", "WIN_RATE_PCT", "PROFIT_FACTOR", "TOTAL_RETURN_PCT", "MAX_DRAWDOWN", "PNL_EQUITY_CHANGE"):
        assert checks(report)[code]["status"] == "INSUFFICIENT_EVIDENCE"
        assert "agreement" in checks(report)[code]["explanation"]


@pytest.mark.parametrize(("now", "status"), [(1000, "MATCH"), (1900, "MATCH"), (1900.001, "MISMATCH"), (999, "MISMATCH"), (0, "MISMATCH")])
def test_exact_freshness(now: float, status: str) -> None:
    assert checks(reconcile(evidence(), "BTC/USDT", now))["SIGNAL_FRESH"]["status"] == status


def test_recent_subset_is_not_mismatch() -> None:
    ev = evidence()
    ev["metrics"]["data"]["trade_count"] = 40
    report = reconcile(ev, "BTC/USDT", 1000)
    for code in ("TRADE_COUNT", "WIN_RATE_PCT", "PROFIT_FACTOR", "PNL_EQUITY_CHANGE"):
        assert checks(report)[code]["status"] == "INSUFFICIENT_EVIDENCE"
    assert not report["inconsistent"]


def test_excess_count_is_unbound_discrepancy() -> None:
    ev = evidence()
    ev["metrics"]["data"]["trade_count"] = 2
    report = reconcile(ev, "BTC/USDT", 1000)
    assert checks(report)["TRADE_COUNT"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert "discrepancy" in checks(report)["TRADE_COUNT"]["explanation"]
    assert not report["inconsistent"]


@pytest.mark.parametrize("field", ["profit_factor", "win_rate_pct", "total_return_pct", "max_drawdown"])
def test_conditional_numeric_mismatch(field: str) -> None:
    ev = evidence()
    ev["metrics"]["data"][field] = "99%" if field == "max_drawdown" else 99
    report = reconcile(ev, "BTC/USDT", 1000)
    row = checks(report)[field.upper()]
    assert row["status"] == "INSUFFICIENT_EVIDENCE"
    assert row["claimed"] == 99
    assert row["recomputed"] is not None
    assert row["tolerance"] == 0.01
    assert "discrepancy" in row["explanation"]
    assert not report["inconsistent"]


def test_run_mismatch_blocks_cross_surface_comparisons() -> None:
    ev = evidence()
    ev["trades"]["data"]["run_id"] = "bt-b"
    result = checks(reconcile(ev, "BTC/USDT", 1000))
    assert result["RUN_CONSISTENCY"]["status"] == "MISMATCH"
    assert result["PROFIT_FACTOR"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_symbol_mismatch() -> None:
    ev = evidence()
    ev["signal"]["data"]["symbol"] = "ETH/USDT"
    ev["trades"]["data"]["trades"][0]["symbol"] = "ETH/USDT"
    result = checks(reconcile(ev, "BTC/USDT", 1000))
    assert result["SIGNAL_SYMBOL"]["status"] == result["TRADE_SYMBOLS"]["status"] == "MISMATCH"
    assert result["WIN_RATE_PCT"]["status"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("points", [[], [{"t": 1, "equity": 100}], [{"t": 1, "equity": 100}, {"t": 1, "equity": 110}], [{"t": 2, "equity": 100}, {"t": 1, "equity": 110}], [{"t": 1, "equity": 0}, {"t": 2, "equity": 110}], [None, {}]])
def test_bad_equity(points: list[Any]) -> None:
    ev = evidence()
    ev["equity"]["data"]["points"] = points
    report = reconcile(ev, "BTC/USDT", 1000)
    assert checks(report)["EQUITY_INTEGRITY"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert "equity_change" not in report["summary"]


@pytest.mark.parametrize("pnls", [[], [0, 0], [1, 2], [-1, -2]])
def test_empty_zero_and_one_sided_pnl(pnls: list[int]) -> None:
    ev = evidence()
    ev["trades"]["data"]["trades"] = [{"symbol": "BTC/USDT", "pnl": pnl} for pnl in pnls]
    report = reconcile(ev, "BTC/USDT", 1000)
    assert report["summary"]["recent_profit_factor"] == (0 if pnls == [-1, -2] else None)
    json.dumps(report, allow_nan=False)


def test_unavailable_and_untrusted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "nxk_test_hidden"
    monkeypatch.setenv("NEXUS_API_KEY", key)
    ev = evidence()
    ev["equity"]["data"]["run_id"] = key
    ev["signal"]["data"]["reasoning_log"] = key
    ev["metrics"] = {"status": "unavailable", "reason": key}
    report = reconcile(ev, "BTC/USDT", 1000)
    assert "metrics" in report["unavailable"]
    assert key not in json.dumps(report)
    assert checks(report)["RUN_CONSISTENCY"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_missing_all() -> None:
    report = reconcile({}, "BTC/USDT", 1000)
    assert len(report["unavailable"]) == 4
    assert not report["inconsistent"]
    assert not any(row["status"] == "MATCH" for row in report["results"])


def test_numeric_bounds_and_nonfinite() -> None:
    ev = evidence()
    ev["trades"]["data"]["trades"][0]["pnl"] = float("nan")
    ev["metrics"]["data"]["profit_factor"] = True
    ev["signal"]["data"]["timestamp"] = float("inf")
    report = reconcile(ev, "BTC/USDT", 1000)
    assert "recent_pnl" not in report["summary"]
    json.dumps(report, allow_nan=False)


def test_does_not_mutate_input() -> None:
    ev = evidence()
    before = json.dumps(ev, sort_keys=True)
    reconcile(ev, "BTC/USDT", 1000)
    assert json.dumps(ev, sort_keys=True) == before


def test_offline_certificate_independent_of_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    req = ChallengeRequest(mode="nexus", symbol="BTC/USDT", as_of=1000)
    ev = evidence()
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    baseline = challenge(req, ev)
    expected = baseline.model_dump(mode="json", exclude={"created_at"})
    for key in ("bt-a", "BTC", "1000", "BUY", "3", "unrelated"):
        monkeypatch.setenv("NEXUS_API_KEY", key)
        actual = challenge(req, ev)
        assert actual.report_id == baseline.report_id
        assert actual.model_dump(mode="json", exclude={"created_at"}) == expected


def test_pnl_discrepancy_cannot_make_certificate_inconsistent() -> None:
    ev = evidence()
    ev["trades"]["data"]["trades"][0]["pnl"] = 500
    report = reconcile(ev, "BTC/USDT", 1000)
    row = checks(report)["PNL_EQUITY_CHANGE"]
    assert row["status"] == "INSUFFICIENT_EVIDENCE"
    assert row["claimed"] == 490
    assert row["recomputed"] == 10
    assert "discrepancy" in row["explanation"]
    assert not report["inconsistent"]
    assert challenge(ChallengeRequest(mode="nexus", as_of=1000), ev).verdict == "UNPROVEN"


@pytest.mark.parametrize("contradiction", ["run", "signal_symbol", "trade_symbol"])
def test_material_contradiction_certificate(contradiction: str) -> None:
    ev = evidence()
    if contradiction == "run":
        ev["trades"]["data"]["run_id"] = "bt-b"
    elif contradiction == "signal_symbol":
        ev["signal"]["data"]["symbol"] = "ETH/USDT"
    else:
        ev["trades"]["data"]["trades"][0]["symbol"] = "ETH/USDT"
    assert reconcile(ev, "BTC/USDT", 1000)["inconsistent"]
    assert challenge(ChallengeRequest(mode="nexus", as_of=1000), ev).verdict == "INCONSISTENT"
