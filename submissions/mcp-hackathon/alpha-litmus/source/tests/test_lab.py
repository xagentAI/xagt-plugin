import math
import sys
import types
from itertools import pairwise
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from app.contracts import ChallengeRequest, CostTrial, Metrics, Report
from app.lab import (
    NEIGHBORHOOD,
    NumericDomainError,
    _break_even,
    _decision,
    _percent,
    _replay,
    _resample,
    challenge,
)
from app.research import Candle, ResearchRequest


def request(kind: Literal["historical", "synthetic"] = "historical", n: int = 300, **kwargs: Any) -> ChallengeRequest:
    bars: list[Candle] = []
    for i in range(n):
        close = 100 * math.exp(.0005 * i + .12 * math.sin(i / 9))
        opening = 100 if not bars else bars[-1].c
        bars.append(Candle(t=1_577_836_800_000 + i * 86_400_000, o=opening,
                           h=max(opening, close) * 1.01, l=min(opening, close) * .99,
                           c=close, v=1000))
    return ChallengeRequest(research=ResearchRequest(candles=bars, data_kind=kind),
                            additional_cost_max_bps=2.5, cost_resolution_bps=1,
                            bootstrap_iterations=50, **kwargs)


@pytest.fixture(scope="module")
def report() -> Report:
    return challenge(request())


def test_repeatable(report: Report) -> None:
    again = challenge(request())
    assert report.report_id == again.report_id
    assert report.analysis == again.analysis


def test_small_sample_unproven(report: Report) -> None:
    assert report.verdict == "UNPROVEN"
    assert not report.eligible
    assert "INSUFFICIENT_TEST_TRADES" in report.reason_codes


def test_synthetic_preserves_failures() -> None:
    result = challenge(request("synthetic"))
    assert result.verdict == "UNPROVEN"
    assert "SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE" in result.reason_codes
    assert result.observed_failures
    assert set(result.observed_failures) <= set(result.reason_codes)


def test_exact_neighborhood(report: Report) -> None:
    assert report.analysis is not None
    assert [(t.fast, t.slow) for t in report.analysis.neighborhood] == NEIGHBORHOOD
    assert report.analysis.neighborhood[4].metrics == report.analysis.folds[2].guarded


def test_delays(report: Report) -> None:
    assert report.analysis is not None
    assert [t.delay_bars for t in report.analysis.delays] == [0, 1, 2, 3]
    assert report.analysis.delays[0].metrics == report.analysis.folds[2].guarded


def test_cost_grid_exact_bound(report: Report) -> None:
    assert report.analysis is not None
    trials = report.analysis.cost_frontier.trials
    assert [t.additional_bps for t in trials] == [0, 1, 2, 2.5]
    assert all(a.metrics.return_pct >= b.metrics.return_pct for a, b in pairwise(trials))


def test_cost_zero_bound() -> None:
    req = request().model_copy(update={"additional_cost_max_bps": 0.0})
    analysis = challenge(req).analysis
    assert analysis is not None
    assert len(analysis.cost_frontier.trials) == 1


def test_folds_disjoint(report: Report) -> None:
    assert report.analysis is not None
    train, validation, test = report.analysis.folds
    assert train.end_index == validation.start_index
    assert validation.end_index == test.start_index
    assert test.end_index == 300
    assert test.guarded.observations == 60


def test_train_only_threshold(report: Report) -> None:
    req = request()
    assert req.research is not None
    for i in range(240, len(req.research.candles)):
        bar = req.research.candles[i]
        req.research.candles[i] = Candle.model_validate({**bar.model_dump(),
            **{key: getattr(bar, key) * 1.2 for key in ("o", "h", "l", "c")}})
    changed = challenge(req)
    assert changed.analysis is not None and report.analysis is not None
    assert changed.analysis.train_volatility_limit == report.analysis.train_volatility_limit
    assert changed.analysis.folds[:2] == report.analysis.folds[:2]


def test_resampling_has_distinct_statistics(report: Report) -> None:
    assert report.analysis is not None
    sample = report.analysis.resampling
    assert sample.iterations == 50
    assert sample.observations == report.analysis.folds[2].guarded.trade_count
    assert sample.status == "insufficient"
    assert sample.bootstrap_return_p05_pct is not None and sample.bootstrap_return_p95_pct is not None
    assert sample.permutation_drawdown_p95_pct is not None
    assert sample.bootstrap_return_p05_pct <= sample.bootstrap_return_p95_pct
    assert 0 <= sample.permutation_drawdown_p95_pct <= 100


def test_next_open_and_liquidation() -> None:
    bars = [Candle(t=(i + 1) * 86_400_000, o=p, h=p, l=p, c=p, v=0)
            for i, p in enumerate([100, 200, 400, 800])]
    metrics, _ = _replay(bars, [True] * 4, [0.] * 4, 1, 4, 0)
    assert metrics.return_pct == pytest.approx(300)
    assert metrics.trade_count == 1
    delayed, _ = _replay(bars, [False, True, False, False], [0.] * 4, 1, 4, 0)
    assert delayed.return_pct == pytest.approx(100)


def test_both_sides_cost_single_bar() -> None:
    bars = [Candle(t=(i + 1) * 86_400_000, o=100, h=100, l=100, c=100, v=0) for i in range(3)]
    metric, _ = _replay(bars, [True] * 3, [0.] * 3, 1, 2, 100)
    assert metric.return_pct == pytest.approx((.99 / 1.01 - 1) * 100)
    assert metric.trade_count == 1


def test_each_fold_starts_flat() -> None:
    bars = [Candle(t=(i + 1) * 86_400_000, o=p, h=p, l=p, c=p, v=0) for i, p in enumerate([1, 100, 100])]
    metric, _ = _replay(bars, [True] * 3, [0.] * 3, 1, 3, 0)
    assert metric.return_pct == 0


def test_nexus_calls_reconciler(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.reconcile import reconcile as actual_reconcile
    calls: list[tuple[dict[str, Any], str, float]] = []
    def reconcile(evidence: dict[str, Any], symbol: str, now: float) -> dict[str, Any]:
        calls.append((evidence, symbol, now))
        return actual_reconcile(evidence, symbol, now)
    monkeypatch.setitem(sys.modules, "app.reconcile", types.SimpleNamespace(reconcile=reconcile))
    result = challenge(ChallengeRequest(mode="nexus"), {"test": 1})
    assert len(calls) == 1
    assert calls[0][:2] == ({}, "BTC/USDT")
    assert isinstance(calls[0][2], float)
    assert result.verdict == "UNPROVEN"
    assert result.analysis is None
    assert not result.nexus_validated


def test_missing_nexus() -> None:
    result = challenge(ChallengeRequest(mode="nexus"))
    assert "MISSING_NEXUS_EVIDENCE" in result.reason_codes
    assert result.verdict == "UNPROVEN"


def test_nexus_mismatches_visible() -> None:
    result = challenge(ChallengeRequest(mode="nexus"), {
        "equity": {"status": "received", "data": {"run_id": "run-a"}},
        "trades": {"status": "received", "data": {"run_id": "run-b"}},
    })
    assert result.verdict == "INCONSISTENT"
    assert result.reconciliation is not None
    assert result.reconciliation.mismatch_count == 1
    assert result.observed_failures == ["NEXUS_RECONCILIATION_MISMATCH"]


def test_commit_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "app.provenance", types.SimpleNamespace(
        commit_state=lambda: {"commit": "abc123", "commit_reviewable": True}))
    with pytest.raises(ValidationError):
        challenge(ChallengeRequest(mode="nexus"))


def test_reference_rejects_evidence() -> None:
    with pytest.raises(ValueError):
        challenge(request(), {})


def test_nexus_forbids_research() -> None:
    with pytest.raises(ValidationError):
        ChallengeRequest(mode="nexus", research=request().research)


def test_symbol_match() -> None:
    with pytest.raises(ValidationError):
        request(symbol="ETH/USDT")


def test_known_attempts_not_decorative_psr() -> None:
    result = challenge(request(attempted_variants=3))
    assert result.selection_adjustment == "not_estimated"
    assert "psr" not in result.model_dump_json().lower()


@pytest.mark.parametrize("value", [101, -101, float("inf"), float("nan")])
def test_numeric_cumulative_bound(value: float) -> None:
    with pytest.raises(NumericDomainError):
        _percent(value)


def test_extreme_price_rejected() -> None:
    req = request()
    assert req.research is not None
    req.research.candles[0] = req.research.candles[0].model_copy(update={"o": 1e-100})
    with pytest.raises(ValidationError):
        challenge(req)


def test_fragile_requires_eligibility(report: Report) -> None:
    assert report.analysis is not None
    analysis = report.analysis.model_copy(deep=True)
    analysis.folds[2].guarded.trade_count = 30
    analysis.folds[2].guarded.return_pct = -1
    analysis.resampling.status = "sufficient"
    verdict, eligible, _, failures = _decision(request(), analysis, None)
    assert (verdict, eligible) == ("FRAGILE", True)
    assert "TEST_NOT_PROFITABLE" in failures


def test_numeric_insufficiency(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: ChallengeRequest) -> None:
        raise NumericDomainError()
    monkeypatch.setattr("app.lab._reference", fail)
    result = challenge(request())
    assert result.verdict == "UNPROVEN"
    assert "NUMERIC_DOMAIN_EXCEEDED" in result.reason_codes


def test_closed_trade_returns_compound_to_equity() -> None:
    req = request()
    assert req.research is not None
    bars = req.research.candles
    signals = [i % 6 < 3 for i in range(len(bars))]
    trades: list[tuple[int, float]] = []
    metrics, returns = _replay(bars, signals, [0.] * len(bars), 240, 300, 15, closed_trades=trades)
    assert len(returns) == metrics.trade_count == len(trades)
    assert _percent(math.fsum(returns)) == pytest.approx(metrics.return_pct)
    assert metrics.trade_expectancy_pct == pytest.approx(sum(_percent(r) for r in returns) / len(returns))
    assert metrics.profit_factor is not None


def test_regime_counts_and_no_small_sample_pass(report: Report) -> None:
    assert report.analysis is not None
    regimes = report.analysis.regimes.regimes
    assert sum(r.bar_count for r in regimes) == 60
    assert sum(r.trade_count for r in regimes) == report.analysis.folds[2].guarded.trade_count
    assert all(r.status == "insufficient" for r in regimes)
    assert all(row.status != "passed" for row in report.test_matrix)
    assert "trade_bootstrap" in report.unavailable_tests


def test_boundaries_keep_dimensions_separate(report: Report) -> None:
    boundaries = report.minimal_failure_boundary
    assert [b.dimension for b in boundaries] == ["additional_cost_bps", "delay_bars", "ema_fast", "ema_slow"]
    for boundary in boundaries:
        assert "smallest discovered" in boundary.interpretation
        if boundary.boundary is not None:
            assert boundary.boundary in boundary.domain
            assert boundary.delta == boundary.boundary - boundary.baseline
    assert boundaries[2].domain == [18, 20, 22]
    assert boundaries[3].domain == [45, 50, 55]


def test_zero_domain_preserves_requested_resolution() -> None:
    req = request().model_copy(update={"additional_cost_max_bps": 0., "cost_resolution_bps": .5})
    assert challenge(req).minimal_failure_boundary[0].resolution == .5


def test_cost_frontier_expectancy_and_pf(report: Report) -> None:
    assert report.analysis is not None
    frontier = report.analysis.cost_frontier
    assert frontier.expectancy_break_even.threshold == 0
    assert frontier.profit_factor_break_even.threshold == 1
    for trial in frontier.trials:
        assert trial.metrics.trade_expectancy_pct is not None
        assert trial.metrics.profit_factor is None or trial.metrics.profit_factor >= 0


def test_nexus_as_of_deterministic_and_explicit() -> None:
    evidence = {"signal": {"status": "received", "data": {"symbol": "BTC/USDT", "timestamp": 1700000000}}}
    req = ChallengeRequest(mode="nexus", as_of=1700000100.)
    first, second = challenge(req, evidence), challenge(req, evidence)
    assert first.report_id == second.report_id
    assert first.reconciliation is not None and first.reconciliation.result is not None
    assert first.reconciliation.result.summary.signal_age_seconds == 100
    assert first.reconciliation.freshness_basis == "caller_supplied_as_of"
    unspecified = challenge(ChallengeRequest(mode="nexus"), evidence)
    assert unspecified.reconciliation is not None and unspecified.reconciliation.result is not None
    fresh = next(c for c in unspecified.reconciliation.result.results if c.code == "SIGNAL_FRESH")
    assert fresh.status == "UNAVAILABLE"
    assert fresh.recomputed is None


def test_mismatch_overrides_missing_other_surfaces() -> None:
    result = challenge(ChallengeRequest(mode="nexus"), {
        "equity": {"status": "received", "data": {"run_id": "run-a"}},
        "trades": {"status": "received", "data": {"run_id": "run-b"}},
    })
    assert result.verdict == "INCONSISTENT"
    assert result.certificate_type == "Failure Certificate"
    assert not result.eligible
    assert result.reconciliation is not None and result.reconciliation.result is not None
    assert "metrics" in result.reconciliation.result.unavailable


def test_survival_label_policy(report: Report) -> None:
    assert report.analysis is not None
    analysis = report.analysis.model_copy(deep=True)
    analysis.folds[2].guarded.trade_count = 30
    analysis.folds[2].guarded.return_pct = 10
    analysis.folds[2].guarded.max_drawdown_pct = 1
    analysis.folds[2].baseline.return_pct = 5
    analysis.folds[2].baseline.max_drawdown_pct = 2
    analysis.folds[1].guarded.return_pct = 5
    analysis.resampling.status = "sufficient"
    analysis.resampling.bootstrap_return_p05_pct = 1
    analysis.resampling.permutation_drawdown_p95_pct = 2
    analysis.cost_frontier.trials[-1].metrics.return_pct = 1
    for trial in analysis.delays:
        trial.metrics.return_pct = 1
    for neighbor in analysis.neighborhood:
        neighbor.metrics.return_pct = 1
    verdict, eligible, reasons, _ = _decision(request(), analysis, None)
    assert (verdict, eligible, reasons) == ("SURVIVED_TESTS", True, [])


def test_no_trades_resampling_unavailable() -> None:
    req = request()
    assert req.research is not None
    req.research.candles = [Candle(t=b.t, o=100, h=100, l=100, c=100, v=0) for b in req.research.candles]
    result = challenge(req)
    assert result.analysis is not None
    sample = result.analysis.resampling
    assert sample.observations == 0
    assert sample.bootstrap_return_p05_pct is None
    assert sample.permutation_drawdown_p95_pct is None
    assert sample.status == "insufficient"


@pytest.mark.parametrize("values,expected", [
    ([None, .8], "observed_failure"), ([None, 2., .8], "observed_failure"),
    ([2., None, .8], "observed_failure"), ([2., .8], "bracketed"),
    ([.8], "fails_at_baseline"), ([None, 2.], "unavailable"),
])
def test_pf_frontier_keeps_later_failures(values: list[float | None], expected: str) -> None:
    trials = [CostTrial(additional_bps=float(i), metrics=Metrics(
        return_pct=1., max_drawdown_pct=0., trade_count=2, observations=10,
        profit_factor=value, profit_factor_status="no_losses" if value is None else "defined"))
        for i, value in enumerate(values)]
    boundary = _break_even(trials, "profit_factor", 1.)
    assert boundary.status == expected
    if expected == "observed_failure":
        assert boundary.first_failing_bps == len(values) - 1
        assert boundary.last_passing_bps is None
        assert boundary.unavailable_bps


def test_resampling_numeric_bound_preserves_permutation() -> None:
    sample = _resample([10., -10.] * 30, 7, 500)
    assert sample.bootstrap_status == "numeric_domain_exceeded"
    assert sample.bootstrap_return_p05_pct is None
    assert sample.bootstrap_return_p95_pct is None
    assert sample.permutation_drawdown_p95_pct is not None


def test_bootstrap_numeric_bound_preserves_analysis(monkeypatch: pytest.MonkeyPatch, report: Report) -> None:
    original = _resample
    def bounded(returns: list[float], seed: int, iterations: int) -> Any:
        result = original(returns, seed, iterations)
        return result.model_copy(update={"bootstrap_status": "numeric_domain_exceeded",
                                        "bootstrap_return_p05_pct": None, "bootstrap_return_p95_pct": None})
    monkeypatch.setattr("app.lab._resample", bounded)
    result = challenge(request())
    assert result.analysis is not None and report.analysis is not None
    assert result.analysis.folds == report.analysis.folds
    assert result.analysis.cost_frontier == report.analysis.cost_frontier
    assert result.observed_failures == report.observed_failures
    assert "BOOTSTRAP_NUMERIC_DOMAIN_EXCEEDED" in result.reason_codes
    row = next(row for row in result.test_matrix if row.name == "trade_bootstrap")
    assert row.status == "unavailable"
    assert "numeric domain" in row.reason


def test_invalid_provenance_not_silently_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "app.provenance", types.SimpleNamespace(
        commit_state=lambda: {"commit": 123, "commit_reviewable": "yes"}))
    with pytest.raises(ValidationError):
        challenge(ChallengeRequest(mode="nexus"))
