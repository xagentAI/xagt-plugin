"""Typed REST API. See app.transport for public deployment requirements."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field

from app.audit import audit
from app.certificates import verify_report
from app.contracts import ChallengeRequest, Provenance, ReleaseGateResult, Report, StrictModel, Verification
from app.demo import fixture
from app.lab import challenge
from app.live_nexus import LiveNexusResult, live_nexus_enabled
from app.nexus_compute import WindowExperimentReport, WindowExperimentRequest
from app.provenance import commit_state, validate_startup
from app.recorded_nexus import RecordedNexusReplay
from app.research import ResearchRequest, research
from app.transport import (
    JSONBoundary,
    TransportError,
    ValidateRequest,
    admission,
    compute,
    nexus_enabled,
    nexus_evidence,
    run_challenge,
    run_live_nexus_candidate,
    run_recorded_replay,
    run_release_gate,
    run_window_compute,
)


class Health(Provenance):
    status: Literal["ok"] = "ok"
    service: Literal["alpha-litmus"] = "alpha-litmus"
    no_execution: Literal[True] = True
    provenance_basis: Literal["syntax_only_not_authenticated"] = "syntax_only_not_authenticated"


class Proof(Provenance):
    schemaVersion: Literal[1] = 1
    slug: Literal["alpha-litmus"] = "alpha-litmus"
    provenance_basis: Literal["syntax_only_not_authenticated"] = "syntax_only_not_authenticated"


class Capabilities(StrictModel):
    name: Literal["AlphaLitmus"] = "AlphaLitmus"
    tools: list[str] = Field(default_factory=lambda: [
        "evaluate_strategy_release", "challenge_nexus_strategy", "find_failure_boundary",
        "verify_failure_certificate", "get_demo_fixture",
        "run_nexus_window_stability", "replay_recorded_nexus_evidence",
        "evaluate_live_nexus_candidate",
    ])
    side_effects: list[Literal["opt_in_nexus_backtest_compute"]] = Field(
        default=["opt_in_nexus_backtest_compute"], max_length=1,
    )
    execution: Literal["paper_only"] = "paper_only"
    nexus_enabled: bool
    live_candidate_enabled: bool
    max_body_bytes: Literal[4000000] = 4_000_000
    max_json_depth: Literal[32] = 32
    max_concurrent_per_process: Literal[2] = 2
    max_intake_per_process: Literal[8] = 8
    body_timeout_seconds: Literal[10] = 10
    health_policy: str = "GET /health never reads or waits on an upload and bypasses intake and compute admission; declared bodies are rejected."
    deployment: str = "Require an authenticating, rate-limiting TLS reverse proxy before enabling Nexus."


class LegacyMetrics(StrictModel):
    return_pct: float
    max_drawdown_pct: float
    sharpe: float | None
    trade_count: int
    win_rate_pct: float | None
    profit_factor: float | None
    execution_cost_usdt: float
    exposure_pct: float
    blocked_days: int


class LegacyPoint(StrictModel):
    t: int
    equity: float


class LegacyTrade(StrictModel):
    entry_t: int
    exit_t: int
    pnl: float
    return_pct: float
    exit: Literal["signal", "fold_end"]


class LegacyReplay(StrictModel):
    metrics: LegacyMetrics
    equity: list[LegacyPoint]
    trades: list[LegacyTrade]


class LegacyFold(StrictModel):
    start: int
    end: int
    bars: int
    baseline: LegacyReplay
    guarded: LegacyReplay
    buy_hold: LegacyReplay


class LegacyFolds(StrictModel):
    train: LegacyFold
    validation: LegacyFold
    test: LegacyFold


class LegacyStress(LegacyMetrics):
    one_way_cost_bps: float


class LegacyStrategy(StrictModel):
    id: Literal["ema-daily-v1"]
    timeframe: Literal["1d"]
    rules: str
    gate: str
    volatility_limit: float
    parameters_frozen: Literal[True]


class LegacyCosts(StrictModel):
    fee_bps: float
    slippage_bps: float
    model: str


class LegacyComparison(StrictModel):
    test_return_delta_pp: float
    test_drawdown_reduction_pp: float


class LegacyResearch(StrictModel):
    schema_version: Literal["AlphaLitmus.legacy.v1"]
    product: Literal["AlphaLitmus"]
    deprecated: Literal[True]
    mode: Literal["independent_research"]
    nexus_validated: Literal[False]
    symbol: str
    data_kind: Literal["synthetic", "historical"]
    source: str
    dataset_sha256: str
    report_id: str
    decision: Literal["WAIT", "PAPER_CANDIDATE"]
    reason_codes: list[str]
    strategy: LegacyStrategy
    costs: LegacyCosts
    folds: LegacyFolds
    stress: list[LegacyStress]
    comparison: LegacyComparison
    no_execution: Literal[True]
    limitations: list[str]


class AuditCheck(StrictModel):
    code: str
    status: Literal["PASS", "UNVERIFIED"]
    detail: str


class AuditSurface(StrictModel):
    status: Literal["received", "unavailable"]
    reason: Literal["NEXUS_NOT_CONFIGURED", "NEXUS_DISABLED", "NEXUS_UNAVAILABLE"] | None = None


class AuditEvidence(StrictModel):
    signal: AuditSurface
    metrics: AuditSurface
    equity: AuditSurface
    trades: AuditSurface


class LegacyAudit(StrictModel):
    mode: Literal["nexus_live"]
    symbol: str
    decision: Literal["WAIT"]
    no_execution: Literal[True]
    signal_age_seconds: float | None
    checks: list[AuditCheck]
    reason_codes: list[str]
    evidence: AuditEvidence
    limitations: list[str]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    validate_startup()
    commit_state()
    yield


app = FastAPI(
    title="AlphaLitmus", version="2.0.0", lifespan=lifespan,
    description="Bounded paper-only evidence tests. Nexus reads require explicit opt-in and an authenticating, rate-limiting TLS reverse proxy. Commit reviewability checks syntax, not Git existence or authenticity.",
)
app.add_middleware(JSONBoundary)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse({"detail": "INVALID_REQUEST"}, status_code=422)


@app.exception_handler(TransportError)
async def transport_error(request: Request, exc: TransportError) -> JSONResponse:
    return JSONResponse({"detail": exc.code}, status_code=exc.status)


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": "INTERNAL_ERROR"}, status_code=500)


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).with_name("dashboard.html"))


@app.get("/health", response_model=Health)
async def health() -> Health:
    return Health(**commit_state())


@app.get("/.well-known/xagent-verification.json", response_model=Proof)
async def verification() -> Proof:
    return Proof(**commit_state())


@app.get("/v1/capabilities", response_model=Capabilities)
async def capabilities() -> Capabilities:
    return Capabilities(nexus_enabled=nexus_enabled(), live_candidate_enabled=live_nexus_enabled())


@app.post("/v1/challenge", response_model=Report)
async def challenge_strategy(request: ChallengeRequest) -> Report:
    return await run_challenge(request)


@app.post("/v1/find-failure-boundary", response_model=Report)
async def find_failure_boundary(request: ChallengeRequest) -> Report:
    """Return the complete report, including its bounded per-dimension frontier."""
    return await run_challenge(request)


@app.post("/v1/verify-report", response_model=Verification)
async def verify_certificate(report: Report) -> Verification:
    return await compute(lambda: verify_report(report))


@app.post("/v1/nexus/window-stability", response_model=WindowExperimentReport)
async def window_stability(request: WindowExperimentRequest) -> WindowExperimentReport:
    """Start bounded, explicitly confirmed Nexus backtest compute, never trading."""
    return await run_window_compute(request)


@app.post("/v1/audit", response_model=LegacyAudit, deprecated=True)
async def audit_nexus(request: ValidateRequest) -> LegacyAudit:
    async with admission.slot():
        evidence = await nexus_evidence(request.symbol)

        def sanitized_audit() -> LegacyAudit:
            result = audit(evidence, request.symbol)
            safe: dict[str, AuditSurface] = {}
            for name in ("signal", "metrics", "equity", "trades"):
                envelope = evidence.get(name, {})
                if isinstance(envelope, dict) and envelope.get("status") == "received":
                    safe[name] = AuditSurface(status="received")
                else:
                    reason = envelope.get("reason") if isinstance(envelope, dict) else None
                    safe[name] = AuditSurface(
                        status="unavailable",
                        reason=reason if reason in ("NEXUS_NOT_CONFIGURED", "NEXUS_DISABLED") else "NEXUS_UNAVAILABLE",
                    )
            result["evidence"] = AuditEvidence.model_validate(safe)
            return LegacyAudit.model_validate(result)

        return await anyio.to_thread.run_sync(sanitized_audit, abandon_on_cancel=False)


@app.post("/v1/research", response_model=LegacyResearch, deprecated=True)
async def independent_research(request: ResearchRequest) -> LegacyResearch:
    return await compute(lambda: LegacyResearch.model_validate(research(request)))


@app.get("/v1/demo/{scenario}", response_model=Report)
async def demo(scenario: str) -> Report:
    if scenario not in ("mixed", "shock"):
        raise HTTPException(404, "UNKNOWN_SCENARIO")
    return await compute(lambda: challenge(ChallengeRequest(research=fixture(scenario))))


@app.post("/v1/release-gate", response_model=ReleaseGateResult)
async def release_gate(request: ChallengeRequest) -> ReleaseGateResult:
    """Evaluate a strategy release through the existing engine plus pure projection."""
    return await run_release_gate(request)


@app.get("/v1/release-gate/demo/{scenario}", response_model=ReleaseGateResult)
async def release_gate_demo(scenario: str) -> ReleaseGateResult:
    """Synthetic release-gate demo. Synthetic evidence stays INSUFFICIENT_EVIDENCE."""
    if scenario not in ("mixed", "shock"):
        raise HTTPException(404, "UNKNOWN_SCENARIO")
    return await run_release_gate(ChallengeRequest(research=fixture(scenario)))


@app.get("/v1/nexus/replay/candidate-v1", response_model=RecordedNexusReplay)
async def replay_candidate(request: Request) -> RecordedNexusReplay:
    """Replay recorded historical Nexus evidence; never live, never synthetic fallback.

    No request body, query parameters, or caller-selected snapshot are allowed.
    Missing or invalid snapshots fail closed with a bounded public code.
    """
    if request.query_params:
        raise HTTPException(400, "QUERY_PARAMETERS_NOT_ALLOWED")
    if await request.body():
        raise HTTPException(400, "BODY_NOT_ALLOWED")

    result = await run_recorded_replay()
    return RecordedNexusReplay.model_validate(result.model_dump(mode="python"))


@app.get("/v1/nexus/live/candidate-v1", response_model=LiveNexusResult)
async def live_candidate(request: Request) -> LiveNexusResult:
    """Run the fixed Candidate v1 read-only live Nexus release gate.

    No body, query parameters, caller-selected symbol, strategy, or fallback.
    """
    if request.query_params:
        raise HTTPException(400, "QUERY_PARAMETERS_NOT_ALLOWED")
    if await request.body():
        raise HTTPException(400, "BODY_NOT_ALLOWED")
    return await run_live_nexus_candidate()
