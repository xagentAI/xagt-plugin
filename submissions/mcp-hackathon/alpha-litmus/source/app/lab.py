"""Bounded deterministic reference tests. Never a replay of the Nexus strategy."""
import math
import random
import statistics
from datetime import datetime, timezone
from typing import Any, Literal

from app.contracts import (
    Boundary,
    BreakEven,
    CertificateType,
    ChallengeRequest,
    CostFrontier,
    CostTrial,
    DelayTrial,
    EvidenceClassification,
    Fold,
    Metrics,
    ParameterTrial,
    Provenance,
    Reason,
    ReconciliationResult,
    ReconciliationSummary,
    ReferenceAnalysis,
    Regime,
    RegimeAnalysis,
    Report,
    Resampling,
    TestMatrixRow,
    Verdict,
)
from app.research import Candle

NEIGHBORHOOD = [(18, 45), (18, 50), (18, 55), (20, 45), (20, 50),
                (20, 55), (22, 45), (22, 50), (22, 55)]
LIMITATIONS = [
    "Reference EMA replay is not the Nexus strategy; Nexus is never validated by this report.",
    "Hashes establish content integrity, not authenticity, authorship, or historical data provenance.",
    "Historical labels and attempted variant counts are caller supplied; selection bias is not estimated.",
    "Fixed chronological 60/20/20 split; repeated inspection can contaminate held-out data.",
    "Unlevered daily spot replay; no funding, borrow, capacity, order-book or intraday risk model.",
    "IID closed-trade bootstrap ignores dependence; trade-order permutation tests ordering risk, not return significance. Samples below 30 trades are descriptive only.",
    "Thirty test trades are an eligibility floor, not proof of statistical independence or future profit.",
    "Cost frontier is a bounded grid, not an exact break-even estimate; delay uses stale signals.",
    "Replay cumulative or individual trade log returns outside [-100, 100] make the entire reference analysis unavailable; partial replay results are not retained. Bootstrap bound failures only suppress bootstrap statistics.",
    "Undefined or numerically bounded profit factors are not passes; later observed failures remain visible without a bracket across unavailable trials.",
]


class NumericDomainError(ValueError):
    pass


def _percent(log_return: float) -> float:
    if not math.isfinite(log_return) or abs(log_return) > 100:
        raise NumericDomainError("cumulative log return outside [-100, 100]")
    return math.expm1(log_return) * 100


def _features(bars: list[Candle], fast: int, slow: int) -> tuple[list[bool], list[float | None]]:
    ef = es = bars[0].c
    changes: list[float] = []
    signals: list[bool] = []
    volatility: list[float | None] = []
    for i, bar in enumerate(bars):
        ef += 2 / (fast + 1) * (bar.c - ef)
        es += 2 / (slow + 1) * (bar.c - es)
        if i:
            changes.append(math.log(bar.c) - math.log(bars[i - 1].c))
        signals.append(i >= slow and ef > es)
        volatility.append(statistics.pstdev(changes[-20:]) if i >= 20 else None)
    return signals, volatility


def _replay(bars: list[Candle], signals: list[bool], volatility: list[float | None],
            start: int, end: int, cost_bps: float, limit: float | None = None,
            delay: int = 0, buy_hold: bool = False,
            closed_trades: list[tuple[int, float]] | None = None) -> tuple[Metrics, list[float]]:
    """Each fold starts flat; close signals execute no earlier than next open.

    Work in log equity, including the overnight mark before any open fill.
    Liquidation at the final close pays the exit cost, including one-bar trades.
    """
    position = False
    equity = peak = drawdown = 0.0
    trades = 0
    entry_equity = 0.0
    entry_index = start
    returns: list[float] = []
    entry_cost = math.log1p(cost_bps / 10000)
    exit_cost = math.log1p(-cost_bps / 10000)
    for i in range(start, end):
        source = i - 1 - delay
        source_vol = volatility[source] if source >= 0 else None
        want = buy_hold or (source >= 0 and signals[source] and
                           (limit is None or (source_vol is not None and source_vol <= limit)))
        change = math.log(bars[i].o) - math.log(bars[i - 1].c) if position else 0.0
        if position and not want:
            change += exit_cost
            trades += 1
        elif want and not position:
            entry_equity = equity
            entry_index = i
            change -= entry_cost
        position = want
        if position:
            change += math.log(bars[i].c) - math.log(bars[i].o)
        if i == end - 1 and position:
            change += exit_cost
            trades += 1
            position = False
        equity += change
        _percent(equity)
        peak = max(peak, equity)
        drawdown = max(drawdown, -math.expm1(equity - peak) * 100)
        if trades > len(returns):
            trade_return = equity - entry_equity
            returns.append(trade_return)
            if closed_trades is not None:
                closed_trades.append((entry_index, trade_return))
    simple_returns = [_percent(r) for r in returns]
    gains = math.fsum(r for r in simple_returns if r > 0)
    losses = -math.fsum(r for r in simple_returns if r < 0)
    pf = gains / losses if losses else None
    if pf is not None and pf > 1e12:
        pf = None
    return Metrics(return_pct=_percent(equity), max_drawdown_pct=drawdown,
                   trade_count=trades, observations=end - start,
                   trade_expectancy_pct=statistics.mean(simple_returns) if simple_returns else None,
                   profit_factor=pf,
                   profit_factor_status="no_trades" if not returns else "no_losses" if not losses else "bounded" if pf is None else "defined"), returns


def _drawdown(changes: list[float]) -> float:
    value = peak = worst = 0.0
    for change in changes:
        value += change
        peak = max(peak, value)
        worst = max(worst, -math.expm1(value - peak) * 100)
    return worst


def _reference(req: ChallengeRequest) -> ReferenceAnalysis:
    from app.certificates import canonical_hash

    research = req.research
    assert research is not None
    bars = research.candles
    n = len(bars)
    train_end, test_start = int(n * .6), int(n * .8)
    signals, vol = _features(bars, 20, 50)
    training_vol = sorted(v for v in vol[55:train_end] if v is not None)
    limit = training_vol[int((len(training_vol) - 1) * .8)]
    cost = research.fee_bps + research.slippage_bps
    folds: list[Fold] = []
    test_returns: list[float] = []
    test_trades: list[tuple[int, float]] = []
    fold_specs: list[tuple[Literal["train", "validation", "test"], int, int]] = [("train", 56, train_end), ("validation", train_end, test_start), ("test", test_start, n)]
    for name, start, end in fold_specs:
        baseline, _ = _replay(bars, signals, vol, start, end, cost)
        guarded, changes = _replay(bars, signals, vol, start, end, cost, limit,
                                   closed_trades=test_trades if name == "test" else None)
        hold, _ = _replay(bars, signals, vol, start, end, cost, buy_hold=True)
        folds.append(Fold(name=name, start_index=start, end_index=end,
                          baseline=baseline, guarded=guarded, buy_hold=hold))
        if name == "test":
            test_returns = changes
    neighborhood = []
    for fast, slow in NEIGHBORHOOD:
        trial_signals, _ = _features(bars, fast, slow)
        metrics, _ = _replay(bars, trial_signals, vol, test_start, n, cost, limit)
        neighborhood.append(ParameterTrial(fast=fast, slow=slow, metrics=metrics))
    delays = [DelayTrial(delay_bars=d, metrics=_replay(bars, signals, vol, test_start, n, cost, limit, d)[0])
              for d in range(4)]
    # Include the exact requested bound even when it is not a grid multiple.
    grid = [i * req.cost_resolution_bps for i in range(math.floor(req.additional_cost_max_bps / req.cost_resolution_bps) + 1)]
    if grid[-1] < req.additional_cost_max_bps:
        grid.append(req.additional_cost_max_bps)
    trials = [CostTrial(additional_bps=bps, metrics=_replay(bars, signals, vol, test_start, n, cost + bps, limit)[0]) for bps in grid]
    first_fail = next((i for i, trial in enumerate(trials) if trial.metrics.return_pct <= 0), None)
    frontier = CostFrontier(
        resolution_bps=req.cost_resolution_bps,
        trials=trials,
        status="survives_bound" if first_fail is None else "fails_at_baseline" if first_fail == 0 else "bracketed",
        last_profitable_bps=trials[-1].additional_bps if first_fail is None else trials[first_fail - 1].additional_bps if first_fail else None,
        first_nonpositive_bps=trials[first_fail].additional_bps if first_fail is not None else None,
        expectancy_break_even=_break_even(trials, "trade_expectancy_pct", 0),
        profit_factor_break_even=_break_even(trials, "profit_factor", 1),
    )
    dataset_hash = canonical_hash([bar.model_dump(mode="json") for bar in bars])
    seed = int(dataset_hash[:8], 16)
    resampling = _resample(test_returns, seed, req.bootstrap_iterations)
    trend = [abs(math.log(bars[i].c) - math.log(bars[max(0, i - 20)].c)) for i in range(n)]
    trend_limit = statistics.median(trend[55:train_end])
    vol_limit = statistics.median(training_vol)
    regimes: list[Regime] = []
    for trending in (True, False):
        for high in (True, False):
            indices = {i for i in range(test_start, n)
                       if (trend[i - 1] > trend_limit) == trending
                       and ((vol[i - 1] or 0) > vol_limit) == high}
            values = [_percent(r) for i, r in test_trades if i in indices]
            regimes.append(Regime(trend="trending" if trending else "sideways",
                                  volatility="high" if high else "lower", bar_count=len(indices),
                                  trade_count=len(values), trade_expectancy_pct=statistics.mean(values) if values else None,
                                  status="descriptive_only" if len(values) >= 30 else "insufficient"))
    return ReferenceAnalysis(dataset_sha256=dataset_hash, train_volatility_limit=limit,
                             one_way_cost_bps=cost, folds=folds, neighborhood=neighborhood,
                             delays=delays, cost_frontier=frontier, resampling=resampling,
                             regimes=RegimeAnalysis(trend_threshold=trend_limit, volatility_threshold=vol_limit, regimes=regimes))


def _resample(returns: list[float], seed: int, iterations: int) -> Resampling:
    rng = random.Random(seed)
    boot: list[float] = []
    perm: list[float] = []
    numeric_failure = False
    for _ in range(iterations if returns else 0):
        sampled = math.fsum(rng.choices(returns, k=len(returns)))
        try:
            boot.append(_percent(sampled))
        except NumericDomainError:
            numeric_failure = True
        shuffled = returns.copy()
        rng.shuffle(shuffled)
        perm.append(_drawdown(shuffled))
    # Never publish quantiles of a selectively truncated bootstrap distribution.
    if numeric_failure:
        boot.clear()
    boot.sort()
    perm.sort()
    return Resampling(seed=seed, iterations=iterations, observations=len(returns),
                      bootstrap_return_p05_pct=boot[math.floor((len(boot) - 1) * .05)] if boot else None,
                      bootstrap_return_p95_pct=boot[math.ceil((len(boot) - 1) * .95)] if boot else None,
                      permutation_drawdown_p95_pct=perm[math.ceil((len(perm) - 1) * .95)] if perm else None,
                      status="sufficient" if len(returns) >= 30 else "insufficient",
                      bootstrap_status="numeric_domain_exceeded" if numeric_failure else "available" if returns else "no_trades")


def _break_even(trials: list[CostTrial], metric: Literal["trade_expectancy_pct", "profit_factor"], threshold: float) -> BreakEven:
    last: float | None = None
    unavailable: list[float] = []
    for trial in trials:
        value = trial.metrics.trade_expectancy_pct if metric == "trade_expectancy_pct" else trial.metrics.profit_factor
        if value is None:
            unavailable.append(trial.additional_bps)
            last = None
            continue
        if value <= threshold:
            return BreakEven(status="fails_at_baseline" if trial.additional_bps == 0 else "observed_failure" if unavailable else "bracketed",
                             last_passing_bps=None if unavailable else last, first_failing_bps=trial.additional_bps,
                             threshold=threshold, unavailable_bps=unavailable)
        last = trial.additional_bps
    return BreakEven(status="unavailable" if unavailable else "survives_bound",
                     last_passing_bps=last, threshold=threshold, unavailable_bps=unavailable)


def _decision(req: ChallengeRequest, analysis: ReferenceAnalysis | None,
              reconciliation: ReconciliationSummary | None) -> tuple[Verdict, bool, list[Reason], list[Reason]]:
    insufficient: list[Reason] = []
    failures: list[Reason] = []
    if req.mode == "nexus":
        insufficient.append("NEXUS_STRATEGY_NOT_REPLAYED")
        if reconciliation is None or reconciliation.status == "missing":
            insufficient.append("MISSING_NEXUS_EVIDENCE")
        elif reconciliation.status in ("invalid", "unavailable"):
            insufficient.append("RECONCILIATION_INVALID" if reconciliation.status == "invalid" else "RECONCILIATION_UNAVAILABLE")
        if reconciliation is not None and reconciliation.mismatch_count:
            failures.append("NEXUS_RECONCILIATION_MISMATCH")
    else:
        assert req.research is not None
        if req.research.data_kind == "synthetic":
            insufficient.append("SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE")
        if analysis is None:
            insufficient.append("NUMERIC_DOMAIN_EXCEEDED")
        else:
            test, base = analysis.folds[2].guarded, analysis.folds[2].baseline
            if test.trade_count < 30:
                insufficient.append("INSUFFICIENT_TEST_TRADES")
            sample = analysis.resampling
            if sample.status == "insufficient":
                insufficient.append("INSUFFICIENT_BOOTSTRAP_TRADES")
            if sample.bootstrap_status == "numeric_domain_exceeded":
                insufficient.append("BOOTSTRAP_NUMERIC_DOMAIN_EXCEEDED")
            checks: list[tuple[bool, Reason]] = [
                (test.return_pct <= 0, "TEST_NOT_PROFITABLE"),
                (analysis.folds[1].guarded.return_pct <= 0, "VALIDATION_NOT_PROFITABLE"),
                (test.return_pct <= base.return_pct, "GUARD_DID_NOT_IMPROVE_TEST_RETURN"),
                (test.max_drawdown_pct > base.max_drawdown_pct, "GUARD_WORSENED_TEST_DRAWDOWN"),
                (test.max_drawdown_pct > 15, "TEST_DRAWDOWN_ABOVE_LIMIT"),
                (analysis.cost_frontier.trials[-1].metrics.return_pct <= 0, "COST_STRESS_NOT_PROFITABLE"),
                (any(d.metrics.return_pct <= 0 for d in analysis.delays), "DELAY_STRESS_NOT_PROFITABLE"),
                (sum(t.metrics.return_pct > 0 for t in analysis.neighborhood) < 5, "PARAMETER_NEIGHBORHOOD_UNSTABLE"),
                (sample.status == "sufficient" and sample.bootstrap_return_p05_pct is not None and sample.bootstrap_return_p05_pct <= 0, "BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE"),
                (sample.status == "sufficient" and sample.permutation_drawdown_p95_pct is not None and sample.permutation_drawdown_p95_pct > 15, "PERMUTATION_DRAWDOWN_ABOVE_LIMIT"),
            ]
            failures = [reason for failed, reason in checks if failed]
    return ("INCONSISTENT" if reconciliation is not None and reconciliation.mismatch_count else "UNPROVEN" if insufficient else "FRAGILE" if failures else "SURVIVED_TESTS",
            not insufficient, insufficient + failures, failures)


def _challenge_impl(req: ChallengeRequest, evidence: dict[str, Any] | None, created_at_iso: str) -> Report:
    """Internal deterministic core; public callers must use challenge().

    The recorded-evidence replay passes the snapshot capture time so repeated
    replays are byte-identical. REST/MCP never supply this value, so public
    callers cannot choose arbitrary provenance timestamps.
    """
    from app.certificates import content_hash

    # Revalidate even model_construct/model_copy instances at the trust boundary.
    req = ChallengeRequest.model_validate(req.model_dump(mode="python"))
    # Strict second-precision UTC calendar timestamp; Report validates the shape.
    created = datetime.fromisoformat(created_at_iso)
    if created.tzinfo != timezone.utc or created.isoformat(timespec="seconds") != created_at_iso:
        raise ValueError("captured time must be exact UTC second precision")
    analysis = None
    reconciliation = None
    if req.mode == "reference":
        if evidence is not None:
            raise ValueError("Nexus evidence cannot be attached to reference replay")
        try:
            analysis = _reference(req)
        except NumericDomainError:
            # _decision emits NUMERIC_DOMAIN_EXCEEDED and the matrix explains
            # that replay results are unavailable, not evidence of survival.
            analysis = None
    else:
        reconciliation = _reconcile(req, evidence or {})
    from app.provenance import commit_state
    provenance = Provenance.model_validate(commit_state())
    verdict, eligible, reasons, failures = _decision(req, analysis, reconciliation)
    boundaries, matrix = _presentation(analysis, reconciliation, failures)
    classification, dataset_hash = _evidence_identity(req, reconciliation)
    report = Report(created_at=created_at_iso, report_id="0" * 64, canonical_report_hash="0" * 64, request=req,
                    mode=req.mode, symbol=req.symbol, verdict=verdict, eligible=eligible,
                    reason_codes=reasons, observed_failures=failures, analysis=analysis,
                    reconciliation=reconciliation, provenance=provenance,
                    selection_adjustment="unknown" if req.attempted_variants is None else "not_estimated",
                    limitations=LIMITATIONS.copy(), certificate_type=_certificate_type(verdict),
                    dataset_sha256=dataset_hash, evidence_classification=classification,
                    minimal_failure_boundary=boundaries, test_matrix=matrix,
                    unavailable_tests=[row.name for row in matrix if row.status == "unavailable"])
    report.report_id = content_hash(report)
    report.canonical_report_hash = report.report_id
    return report


def challenge(req: ChallengeRequest, evidence: dict[str, Any] | None = None) -> Report:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return _challenge_impl(req, evidence, now.isoformat())


def _reconcile(req: ChallengeRequest, evidence: dict[str, Any]) -> ReconciliationSummary:
    from app.certificates import canonical_hash
    from app.nexus import SURFACES, sanitize
    from app.reconcile import reconcile

    # Retain only the public sanitized surfaces, never raw transport metadata.
    cleaned: dict[str, Any] = {}
    for label in SURFACES:
        surface = evidence.get(label)
        if isinstance(surface, dict) and surface.get("status") == "received":
            data = sanitize(label, surface.get("data"))
            if data:
                cleaned[label] = {"status": "received", "data": data}
    result = ReconciliationResult.model_validate(reconcile(cleaned, req.symbol, req.as_of if req.as_of is not None else 0.0))
    if req.as_of is None:
        result.summary.signal_age_seconds = None
        for check in result.results:
            if check.code == "SIGNAL_FRESH":
                check.status = "UNAVAILABLE"
                check.recomputed = None
                check.explanation = "Freshness requires an explicit caller-supplied as_of Unix timestamp."
        if "freshness" not in result.unavailable:
            result.unavailable.append("freshness")
    mismatch_count = sum(c.status == "MISMATCH" for c in result.results)
    result.inconsistent = bool(mismatch_count)
    return ReconciliationSummary(evidence_supplied=bool(cleaned), status="reconciled" if cleaned else "missing",
                                 result_sha256=canonical_hash(result.model_dump(mode="json")),
                                 mismatch_count=mismatch_count,
                                 insufficient_count=sum(c.status in ("INSUFFICIENT_EVIDENCE", "UNAVAILABLE") for c in result.results),
                                 as_of=req.as_of, freshness_basis="caller_supplied_as_of" if req.as_of is not None else "unavailable",
                                 evidence=cleaned, result=result)


def _certificate_type(verdict: Verdict) -> CertificateType:
    if verdict in ("FRAGILE", "INCONSISTENT"):
        return "Failure Certificate"
    return "Survival Report" if verdict == "SURVIVED_TESTS" else "Evidence Limitation Certificate"


def _evidence_identity(req: ChallengeRequest, reconciliation: ReconciliationSummary | None) -> tuple[EvidenceClassification, str | None]:
    from app.certificates import canonical_hash

    if req.research is not None:
        return ("synthetic_reference" if req.research.data_kind == "synthetic" else "caller_labeled_historical_reference",
                canonical_hash([bar.model_dump(mode="json") for bar in req.research.candles]))
    return ("nexus_snapshot" if reconciliation is not None and reconciliation.evidence_supplied else "missing", None)


def _presentation(analysis: ReferenceAnalysis | None, reconciliation: ReconciliationSummary | None,
                  failures: list[Reason]) -> tuple[list[Boundary], list[TestMatrixRow]]:
    matrix: list[TestMatrixRow] = []
    boundaries: list[Boundary] = []
    checks: list[tuple[str, list[Reason]]] = [
        ("chronological_folds", ["TEST_NOT_PROFITABLE", "VALIDATION_NOT_PROFITABLE", "GUARD_DID_NOT_IMPROVE_TEST_RETURN", "GUARD_WORSENED_TEST_DRAWDOWN", "TEST_DRAWDOWN_ABOVE_LIMIT"]),
        ("cost_frontier", ["COST_STRESS_NOT_PROFITABLE"]),
        ("delay", ["DELAY_STRESS_NOT_PROFITABLE"]),
        ("ema_neighborhood", ["PARAMETER_NEIGHBORHOOD_UNSTABLE"]),
        ("trade_bootstrap", ["BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE"]),
        ("trade_permutation", ["PERMUTATION_DRAWDOWN_ABOVE_LIMIT"]),
    ]
    for name, codes in checks:
        unavailable = analysis is None or (name in ("trade_bootstrap", "trade_permutation") and analysis.resampling.status == "insufficient")
        numeric_bootstrap = name == "trade_bootstrap" and analysis is not None and analysis.resampling.bootstrap_status == "numeric_domain_exceeded"
        unavailable = unavailable or numeric_bootstrap
        failed = any(code in failures for code in codes)
        small = analysis is not None and analysis.folds[2].guarded.trade_count < 30
        matrix.append(TestMatrixRow(name=name, status="unavailable" if unavailable else "failed" if failed else "descriptive" if small else "passed",
                                    reason="Bootstrap numeric domain exceeded; all bootstrap quantiles withheld; other analyses retained" if numeric_bootstrap else "Reference replay unavailable: not requested or replay numeric domain exceeded; partial replay results are not retained" if analysis is None else "Fewer than 30 closed test trades" if unavailable else "Observed failure" if failed else "Bounded observations; not a statistical proof"))
    matrix.append(TestMatrixRow(name="regimes", status="unavailable" if analysis is None else "descriptive",
                                reason="Training-only thresholds; per-regime trade counts govern insufficiency; no statistical pass claims"))
    matrix.append(TestMatrixRow(name="selection_adjustment", status="unavailable", reason="No selection-adjusted significance estimate; attempted variants are caller supplied"))
    matrix.append(TestMatrixRow(name="nexus_strategy_replay", status="unavailable", reason="Reference EMA is not Nexus"))
    matrix.append(TestMatrixRow(name="reconciliation", status="unavailable" if reconciliation is None else "failed" if reconciliation.mismatch_count else "descriptive",
                                reason="Conditional arithmetic only; no authenticity claim"))
    if reconciliation is not None and reconciliation.result is not None:
        for check in reconciliation.result.results:
            matrix.append(TestMatrixRow(name="reconciliation:" + check.code,
                                        status="failed" if check.status == "MISMATCH" else "descriptive" if check.status == "MATCH" else "unavailable",
                                        reason=check.explanation))
    if analysis is not None:
        base = analysis.folds[2].guarded.return_pct
        dimensions: list[tuple[Literal["additional_cost_bps", "delay_bars", "ema_fast", "ema_slow"], float, float, list[tuple[float, float]]]] = [
            ("additional_cost_bps", 0, analysis.cost_frontier.resolution_bps, [(t.additional_bps, t.metrics.return_pct) for t in analysis.cost_frontier.trials]),
            ("delay_bars", 0, 1, [(float(t.delay_bars), t.metrics.return_pct) for t in analysis.delays]),
            ("ema_fast", 20, 2, [(float(t.fast), t.metrics.return_pct) for t in analysis.neighborhood if t.slow == 50]),
            ("ema_slow", 50, 5, [(float(t.slow), t.metrics.return_pct) for t in analysis.neighborhood if t.fast == 20]),
        ]
        for dimension, baseline, resolution, trials in dimensions:
            failed_trials = sorted((t for t in trials if t[1] <= 0), key=lambda t: (abs(t[0] - baseline), t[0]))
            discovered = failed_trials[0] if failed_trials else None
            boundaries.append(Boundary(dimension=dimension, baseline=float(baseline),
                                       boundary=discovered[0] if discovered else None,
                                       delta=discovered[0] - baseline if discovered else None,
                                       effect=discovered[1] - base if discovered else None,
                                       domain=[t[0] for t in trials], resolution=resolution,
                                       status="baseline_failure" if discovered is not None and discovered[0] == baseline else "discovered" if discovered else "not_discovered"))
    return boundaries, matrix
