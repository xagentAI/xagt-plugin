"""Strict public contracts for the bounded AlphaLitmus experiment."""
import math
import re
from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.research import ResearchRequest


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ChallengeRequest(StrictModel):
    mode: Literal["reference", "nexus"] = "reference"
    research: ResearchRequest | None = None
    symbol: str = Field(default="BTC/USDT", pattern=r"^[A-Z0-9]{2,12}/[A-Z0-9]{2,12}$")
    attempted_variants: int | None = Field(default=None, ge=1, le=1_000_000)
    additional_cost_max_bps: float = Field(default=100.0, ge=0, le=200)
    cost_resolution_bps: float = Field(default=1.0, ge=0.5, le=10)
    bootstrap_iterations: int = Field(default=200, ge=50, le=500)
    as_of: float | None = Field(default=None, ge=0, le=253402214400)

    @model_validator(mode="after")
    def mode_and_domain(self) -> Self:
        if (self.mode == "reference") != (self.research is not None):
            raise ValueError("research is required for reference and forbidden for nexus")
        if self.research is not None:
            if self.symbol != self.research.symbol:
                raise ValueError("challenge and research symbols must match")
            # Bound the arithmetic independently of the research module's validation.
            prices = [p for b in self.research.candles for p in (b.o, b.h, b.l, b.c)]
            if not all(math.isfinite(p) and 1e-8 <= p <= 1e12 for p in prices):
                raise ValueError("prices must be finite and within [1e-8, 1e12]")
            if max(prices) / min(prices) > 1e6:
                raise ValueError("dataset price ratio exceeds bounded numeric domain")
        return self


class Metrics(StrictModel):
    return_pct: float
    max_drawdown_pct: float = Field(ge=0, le=100)
    trade_count: int = Field(ge=0, le=3000)
    observations: int = Field(ge=1, le=3000)
    trade_expectancy_pct: float | None = None
    profit_factor: float | None = Field(default=None, ge=0, le=1e12)
    profit_factor_status: Literal["defined", "no_losses", "no_trades", "bounded"] = "no_trades"
    profit_factor_basis: Literal["equal_notional_net_trade_returns"] = "equal_notional_net_trade_returns"


class Fold(StrictModel):
    name: Literal["train", "validation", "test"]
    start_index: int = Field(ge=0, le=3000)
    end_index: int = Field(ge=1, le=3000)
    baseline: Metrics
    guarded: Metrics
    buy_hold: Metrics


class ParameterTrial(StrictModel):
    fast: int = Field(ge=18, le=22)
    slow: int = Field(ge=45, le=55)
    metrics: Metrics


class DelayTrial(StrictModel):
    delay_bars: int = Field(ge=0, le=3)
    metrics: Metrics


class CostTrial(StrictModel):
    additional_bps: float = Field(ge=0, le=200)
    metrics: Metrics


class CostFrontier(StrictModel):
    resolution_bps: float = Field(ge=0.5, le=10)
    trials: list[CostTrial] = Field(min_length=1, max_length=402)
    status: Literal["fails_at_baseline", "bracketed", "survives_bound"]
    last_profitable_bps: float | None = Field(default=None, ge=0, le=200)
    first_nonpositive_bps: float | None = Field(default=None, ge=0, le=200)
    expectancy_break_even: "BreakEven"
    profit_factor_break_even: "BreakEven"


class BreakEven(StrictModel):
    status: Literal["fails_at_baseline", "bracketed", "survives_bound", "unavailable", "observed_failure"]
    last_passing_bps: float | None = Field(default=None, ge=0, le=200)
    first_failing_bps: float | None = Field(default=None, ge=0, le=200)
    threshold: float
    unavailable_bps: list[float] = Field(default_factory=list, max_length=402)


class Resampling(StrictModel):
    seed: int = Field(ge=0, le=2**32 - 1)
    iterations: int = Field(ge=50, le=500)
    observations: int = Field(ge=0, le=3000)
    bootstrap_return_p05_pct: float | None
    bootstrap_return_p95_pct: float | None
    permutation_drawdown_p95_pct: float | None = Field(ge=0, le=100)
    method: Literal["iid_net_trade_log_return_bootstrap_and_order_permutation"] = "iid_net_trade_log_return_bootstrap_and_order_permutation"
    sample_policy: Literal["minimum_30_closed_test_trades"] = "minimum_30_closed_test_trades"
    status: Literal["sufficient", "insufficient"]
    bootstrap_status: Literal["available", "no_trades", "numeric_domain_exceeded"] = "available"


class Regime(StrictModel):
    trend: Literal["trending", "sideways"]
    volatility: Literal["high", "lower"]
    bar_count: int = Field(ge=0, le=3000)
    trade_count: int = Field(ge=0, le=3000)
    trade_expectancy_pct: float | None
    status: Literal["descriptive_only", "insufficient"]


class RegimeAnalysis(StrictModel):
    trend_threshold: float = Field(ge=0)
    volatility_threshold: float = Field(ge=0)
    threshold_policy: Literal["training_medians_of_absolute_20_day_log_return_and_20_day_volatility"] = "training_medians_of_absolute_20_day_log_return_and_20_day_volatility"
    attribution: Literal["prior_close_regime_at_trade_entry"] = "prior_close_regime_at_trade_entry"
    regimes: list[Regime] = Field(min_length=4, max_length=4)


class Boundary(StrictModel):
    dimension: Literal["additional_cost_bps", "delay_bars", "ema_fast", "ema_slow"]
    baseline: float
    delta: float | None
    boundary: float | None
    effect: float | None
    effect_metric: Literal["test_return_delta_percentage_points"] = "test_return_delta_percentage_points"
    domain: list[float] = Field(min_length=1, max_length=402)
    resolution: float = Field(gt=0)
    status: Literal["baseline_failure", "discovered", "not_discovered"]
    interpretation: Literal["smallest discovered failing perturbation within this dimension's tested domain; not a global minimum"] = "smallest discovered failing perturbation within this dimension's tested domain; not a global minimum"


class TestMatrixRow(StrictModel):
    name: str
    status: Literal["passed", "failed", "unavailable", "descriptive"]
    reason: str


class ReferenceAnalysis(StrictModel):
    engine: Literal["alphalitmus-ema-v1"] = "alphalitmus-ema-v1"
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    train_volatility_limit: float = Field(ge=0)
    one_way_cost_bps: float = Field(ge=0, le=400)
    folds: list[Fold] = Field(min_length=3, max_length=3)
    neighborhood: list[ParameterTrial] = Field(min_length=9, max_length=9)
    delays: list[DelayTrial] = Field(min_length=4, max_length=4)
    cost_frontier: CostFrontier
    resampling: Resampling
    regimes: RegimeAnalysis


class ReconciliationCheck(StrictModel):
    code: str = Field(max_length=120)
    status: Literal["MATCH", "MISMATCH", "INSUFFICIENT_EVIDENCE", "UNAVAILABLE"]
    claimed: str | int | float | bool | None
    recomputed: str | int | float | bool | None
    tolerance: float | None = Field(ge=0)
    evidence_path: str = Field(max_length=300)
    explanation: str = Field(max_length=2000)


class ReconciliationMetrics(StrictModel):
    signal_age_seconds: float | None = None
    recent_trade_count: int | None = Field(default=None, ge=0)
    recent_wins: int | None = Field(default=None, ge=0)
    recent_losses: int | None = Field(default=None, ge=0)
    recent_breakeven: int | None = Field(default=None, ge=0)
    recent_gross_profit: float | None = None
    recent_gross_loss: float | None = None
    recent_pnl: float | None = None
    recent_profit_factor: float | None = None
    recent_win_rate_pct: float | None = None
    equity_point_count: int | None = Field(default=None, ge=0)
    equity_change: float | None = None
    equity_return_pct: float | None = None
    sampled_max_drawdown_pct: float | None = None


class ReconciliationResult(StrictModel):
    results: list[ReconciliationCheck] = Field(max_length=1000)
    summary: ReconciliationMetrics
    inconsistent: bool
    limitations: list[str] = Field(max_length=30)
    unavailable: list[str] = Field(max_length=30)


class ReconciliationSummary(StrictModel):
    evidence_supplied: bool
    result_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal["missing", "reconciled", "unavailable", "invalid"]
    mismatch_count: int = Field(default=0, ge=0, le=1000)
    insufficient_count: int = Field(default=0, ge=0, le=1000)
    # Reconciliation alone cannot establish robustness of the bound strategy.
    strategy_replayed: Literal[False] = False
    as_of: float | None = Field(ge=0, le=253402214400)
    freshness_basis: Literal["caller_supplied_as_of", "unavailable"]
    evidence: dict[str, JsonValue]
    result: ReconciliationResult | None


class Provenance(StrictModel):
    """Syntax-only build claim; local-dev is the sole unreviewable sentinel."""

    model_config = ConfigDict(revalidate_instances="always")

    commit: str = Field(default="local-dev", max_length=40)
    commit_reviewable: bool = False

    @model_validator(mode="after")
    def consistent_commit(self) -> Self:
        if self.commit_reviewable:
            if re.fullmatch(r"[0-9a-f]{40}", self.commit) is None or self.commit == "0" * 40:
                raise ValueError("reviewable commit requires a nonzero lowercase 40-character SHA")
        elif self.commit != "local-dev":
            raise ValueError("unreviewable commit must be local-dev")
        return self


Reason = Literal[
    "SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE", "INSUFFICIENT_TEST_TRADES",
    "NEXUS_STRATEGY_NOT_REPLAYED", "MISSING_NEXUS_EVIDENCE",
    "RECONCILIATION_UNAVAILABLE", "RECONCILIATION_INVALID", "NUMERIC_DOMAIN_EXCEEDED",
    "TEST_NOT_PROFITABLE", "VALIDATION_NOT_PROFITABLE", "GUARD_DID_NOT_IMPROVE_TEST_RETURN",
    "GUARD_WORSENED_TEST_DRAWDOWN", "TEST_DRAWDOWN_ABOVE_LIMIT",
    "COST_STRESS_NOT_PROFITABLE", "DELAY_STRESS_NOT_PROFITABLE",
    "PARAMETER_NEIGHBORHOOD_UNSTABLE", "BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE",
    "PERMUTATION_DRAWDOWN_ABOVE_LIMIT",
    "NEXUS_RECONCILIATION_MISMATCH",
    "INSUFFICIENT_BOOTSTRAP_TRADES",
    "BOOTSTRAP_NUMERIC_DOMAIN_EXCEEDED",
]

Verdict = Literal["UNPROVEN", "FRAGILE", "SURVIVED_TESTS", "INCONSISTENT"]
CertificateType = Literal["Failure Certificate", "Evidence Limitation Certificate", "Survival Report"]
EvidenceClassification = Literal["synthetic_reference", "caller_labeled_historical_reference", "nexus_snapshot", "missing"]


class Report(StrictModel):
    schema_version: Literal["alphalitmus-1"] = "alphalitmus-1"
    created_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
    report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_version: Literal["AlphaLitmus-2.0"] = "AlphaLitmus-2.0"
    certificate_type: CertificateType
    dataset_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_classification: EvidenceClassification
    request: ChallengeRequest
    mode: Literal["reference", "nexus"]
    symbol: str
    verdict: Verdict
    eligible: bool
    reason_codes: list[Reason] = Field(max_length=20)
    observed_failures: list[Reason] = Field(max_length=20)
    analysis: ReferenceAnalysis | None
    reconciliation: ReconciliationSummary | None
    provenance: Provenance
    nexus_validated: Literal[False] = False
    no_execution: Literal[True] = True
    authenticity_claimed: Literal[False] = False
    selection_adjustment: Literal["unknown", "not_estimated"]
    limitations: list[str] = Field(min_length=1, max_length=20)
    minimal_failure_boundary: list[Boundary] = Field(max_length=4)
    test_matrix: list[TestMatrixRow] = Field(max_length=40)
    unavailable_tests: list[str] = Field(max_length=40)

    @field_validator("created_at")
    @classmethod
    def calendar_utc_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo != timezone.utc or parsed.isoformat(timespec="seconds") != value:
            raise ValueError("created_at must be an exact UTC calendar timestamp with second precision")
        return value


class Verification(StrictModel):
    valid: bool
    report_id: str | None = None
    errors: list[str]
    authenticity_verified: Literal[False] = False


ReleaseDecision = Literal["BLOCK_DEPLOYMENT", "INSUFFICIENT_EVIDENCE", "SURVIVED_BOUNDED_TESTS"]
ReleaseAction = Literal["DO_NOT_DEPLOY", "COLLECT_MORE_EVIDENCE", "CONTINUE_PAPER_VALIDATION"]


class ReleaseGateResult(StrictModel):
    """Machine-actionable projection of an authoritative Report.

    This model never authorizes trading. It only restates the source verdict
    as a bounded release-gate decision with deterministic ordering.
    """

    schema_version: Literal["alphalitmus-release-gate-1"] = "alphalitmus-release-gate-1"
    decision: ReleaseDecision
    recommended_action: ReleaseAction
    source_verdict: Verdict
    evidence_classification: EvidenceClassification
    reason_codes: list[Reason] = Field(max_length=20)
    observed_failures: list[Reason] = Field(max_length=20)
    unavailable_tests: list[str] = Field(max_length=40)
    report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    no_execution: Literal[True] = True
    profitability_claimed: Literal[False] = False
    # Mandatory attestation: no default, so absence is never inferred as True.
    # Identity-checked (`is True`), so 1/"true" cannot coerce to an attestation.
    source_report_verified: Literal[True]
    report: Report

    @field_validator("source_report_verified", mode="before")
    @classmethod
    def verified_must_be_exact_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("source_report_verified must be exactly true")
        return value
    disclaimer: Literal[
        "This result is not financial advice and is not deployment approval. "
        "SURVIVED_BOUNDED_TESTS means only survival of the stated bounded tests."
    ] = (
        "This result is not financial advice and is not deployment approval. "
        "SURVIVED_BOUNDED_TESTS means only survival of the stated bounded tests."
    )
