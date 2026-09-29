"""Opt-in, strategy-bound window experiments against the fixed Nexus endpoint.

The snapshot's literal hint "Call get_backtest_job until completed" is the
sole basis for accepting status='completed'. Only queued/running/completed
are understood; no terminal metrics or additional completion fields are assumed.
Metrics and signals are cached strategy evidence, not run-attested evidence.
Consequently this implementation cannot emit SURVIVED or FRAGILE.

Both ALPHALITMUS_ENABLE_NEXUS=true and
ALPHALITMUS_ENABLE_NEXUS_BACKTEST=true are required, alongside NEXUS_API_KEY.
The default 30-second experiment has a hard ceiling of 45 HTTP calls; the
60-second maximum permits at most 75. These include at most three submissions
and twelve evidence reads, with one-second sleeps before every job poll.
The deadline normally stops polling before the call ceiling is reached.

The process lock prevents overlapping local experiments (including across event
loops). It cannot exclude Studio/other processes, or cancel an already submitted
remote job after cancellation/timeout. No remote cancellation API is documented.
"""

import asyncio
import json
import os
import threading
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app import nexus

__all__ = ["WindowExperimentRequest", "WindowExperimentReport", "run_window_experiment",
           "NexusComputeError", "BacktestJob"]

Bars = Annotated[int, Field(ge=20, le=500)]
Finite = Annotated[float, Field(ge=-1e15, le=1e15)]
RunID = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
Code = Literal[
    "NEXUS_COMPUTE_DISABLED", "NEXUS_NOT_CONFIGURED", "NEXUS_INVALID_REQUEST",
    "NEXUS_COMPUTE_BUSY", "NEXUS_TIMEOUT", "NEXUS_HTTP_ERROR",
    "NEXUS_SCHEMA_ERROR", "NEXUS_RESPONSE_TOO_LARGE", "NEXUS_TRANSPORT_ERROR",
    "NEXUS_UNKNOWN_JOB_STATE", "NEXUS_RUN_ID_MISMATCH", "NEXUS_RUN_LIMIT",
    "NEXUS_NOT_STARTED", "NEXUS_METRICS_UNBOUND", "NEXUS_CALL_LIMIT",
]
_PROCESS_LOCK = threading.Lock()
_POLL_INTERVAL = 1.0


class NexusComputeError(Exception):
    """Stable, sanitized code only; never expose remote text or exception chains."""

    def __init__(self, code: Code, *, run_id: str | None = None) -> None:
        self.code = code
        self.run_id = run_id
        super().__init__(code)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True,
                              allow_inf_nan=False, revalidate_instances="always",
                              hide_input_in_errors=True)


class WindowExperimentRequest(_Strict):
    """Key selects the strategy; windows are an ascending, unique input grid.

    Execution starts at the largest window and descends. Timeout covers the
    entire experiment, not each job. Confirmation must be the JSON boolean true.
    """

    confirm_compute: Literal[True]
    symbol: Annotated[str, Field(max_length=33)] = "BTC/USDT"
    windows: Annotated[list[Bars], Field(min_length=1, max_length=3)] = Field(
        default_factory=lambda: [100, 250, 500])
    timeout_seconds: Annotated[int, Field(ge=5, le=60)] = 30

    @field_validator("confirm_compute", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("NEXUS_INVALID_REQUEST")
        return value

    @field_validator("windows")
    @classmethod
    def ordered_windows(cls, value: list[int]) -> list[int]:
        if value != sorted(set(value)):
            raise ValueError("NEXUS_INVALID_REQUEST")
        return value

    @field_validator("symbol")
    @classmethod
    def valid_symbol(cls, value: str) -> str:
        if nexus.sanitize("signal", {"symbol": value}).get("symbol") != value:
            raise ValueError("NEXUS_INVALID_REQUEST")
        return value


class BacktestJob(_Strict):
    """Only documented identity and state, not invented completion metrics."""

    run_id: RunID
    status: Literal["queued", "running", "completed"]


class MetricsEvidence(_Strict):
    binding: Literal["unavailable"] = "unavailable"
    total_return_pct: Finite | None = None
    profit_factor: Finite | None = None
    max_drawdown: Annotated[str, Field(max_length=25, pattern=r"^-?[0-9]{1,12}(\.[0-9]{1,10})?%$")] | None = None
    qualification: Literal["QUALIFIED_FOR_OKX_LISTING", "NOT_QUALIFIED"] | None = None
    return_nonpositive: bool | None = None
    profit_factor_at_most_one: bool | None = None
    not_qualified: bool | None = None


class SeriesEvidence(_Strict):
    binding: Literal["unavailable", "matched", "mismatched"] = "unavailable"
    run_id: RunID | None = None
    row_count: Annotated[int, Field(ge=0, le=10_000)] | None = None
    valid_rows: bool = False
    observed_return_pct: Finite | None = None
    observed_max_drawdown_pct: Finite | None = None


class SignalEvidence(_Strict):
    binding: Literal["unavailable"] = "unavailable"
    trade_intent: Literal["BUY", "SELL", "HOLD"] | None = None
    timestamp: Finite | None = None


class WindowEvidence(_Strict):
    n_bars: Bars
    run_id: RunID | None = None
    job_status: Literal["not_started", "queued", "running", "completed"] = "not_started"
    verdict: Literal["UNPROVEN", "INCONSISTENT"] = "UNPROVEN"
    reason: Code = "NEXUS_NOT_STARTED"
    metrics: MetricsEvidence = Field(default_factory=MetricsEvidence)
    equity: SeriesEvidence = Field(default_factory=SeriesEvidence)
    trades: SeriesEvidence = Field(default_factory=SeriesEvidence)
    signal: SignalEvidence = Field(default_factory=SignalEvidence)
    errors: Annotated[list[Code], Field(max_length=4)] = Field(default_factory=list)


class WindowExperimentReport(_Strict):
    """Bounded allowlisted evidence. No arbitrary upstream strings or raw rows.

    Observed failures are not confirmed counterexamples. A definitive boundary
    would require a verified surviving largest-window baseline and verified
    smaller-window failures; even then it concerns only the sampled grid.
    smallest_observed_failing_n_bars describes cached metric observations after
    completion, not a run-attested boundary. This report makes no commit or
    engine-version provenance claim.
    """

    status: Literal["UNPROVEN", "INCONSISTENT"] = "UNPROVEN"
    baseline_n_bars: Bars
    windows: Annotated[list[WindowEvidence], Field(min_length=1, max_length=3)]
    smallest_observed_failing_n_bars: Bars | None = None
    definitive_boundary_n_bars: None = None
    confirmed_counterexample: Literal[False] = False
    baseline_survived: None = None
    limitation: Literal["METRICS_NOT_RUN_ATTESTED"] = "METRICS_NOT_RUN_ATTESTED"
    boundary_scope: Literal["SAMPLED_GRID_ONLY_NOT_GLOBAL_OR_CAUSAL"] = "SAMPLED_GRID_ONLY_NOT_GLOBAL_OR_CAUSAL"
    failure_criteria: Literal["RETURN_LE_0_OR_PF_LE_1_OR_NOT_QUALIFIED"] = "RETURN_LE_0_OR_PF_LE_1_OR_NOT_QUALIFIED"
    qualification_interpretation: Literal["LISTING_CATEGORY_NOT_INDEPENDENT_PROFIT"] = "LISTING_CATEGORY_NOT_INDEPENDENT_PROFIT"
    equity_caveat: Literal["FIRST_OBSERVED_POINT_NOT_INITIAL_CAPITAL_NO_CASHFLOW_ATTESTATION"] = "FIRST_OBSERVED_POINT_NOT_INITIAL_CAPITAL_NO_CASHFLOW_ATTESTATION"
    drawdown_interpretation: Literal["DESCRIPTIVE_NO_FAILURE_THRESHOLD"] = "DESCRIPTIVE_NO_FAILURE_THRESHOLD"


def _key() -> str:
    if (os.getenv("ALPHALITMUS_ENABLE_NEXUS_BACKTEST") != "true"
            or os.getenv("ALPHALITMUS_ENABLE_NEXUS") != "true"):
        raise NexusComputeError("NEXUS_COMPUTE_DISABLED")
    key = os.getenv("NEXUS_API_KEY", "")
    if not key or len(key) > 512 or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise NexusComputeError("NEXUS_NOT_CONFIGURED")
    return key


def _run_id(value: object, key: str) -> str:
    result = nexus.sanitize("equity", {"run_id": value}, key).get("run_id")
    if not isinstance(result, str):
        raise NexusComputeError("NEXUS_SCHEMA_ERROR")
    return result


class _NexusComputeClient:
    """Scoped typed transport, used inside run_window_experiment's deadline/lock.

    Private transport: run_backtest/get_backtest_job are called only inside the
    validated, confirmed, enabled experiment's process lock and total deadline.
    No polling URL returned by the service is ever followed.
    """

    def __init__(self, client: httpx.AsyncClient, key: str, *, max_calls: int = 45) -> None:
        self._client = client
        self._key = key
        self._runs = 0
        self._calls = 0
        self._max_calls = max_calls

    async def _call(self, name: str, arguments: dict[str, object]) -> dict[str, Any]:
        if self._calls >= self._max_calls:
            raise NexusComputeError("NEXUS_CALL_LIMIT")
        self._calls += 1
        try:
            async with self._client.stream(
                "POST", nexus.BASE + "/tools/call",
                headers={"X-API-KEY": self._key, "Accept-Encoding": "identity"},
                json={"name": name, "arguments": arguments},
            ) as response:
                if response.status_code != 200:
                    raise NexusComputeError("NEXUS_HTTP_ERROR")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise NexusComputeError("NEXUS_SCHEMA_ERROR")
                length = response.headers.get("content-length")
                if length is not None and (not length.isdecimal() or len(length) > 10
                                           or int(length) > nexus.MAX_BYTES):
                    raise NexusComputeError("NEXUS_RESPONSE_TOO_LARGE")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > nexus.MAX_BYTES:
                        raise NexusComputeError("NEXUS_RESPONSE_TOO_LARGE")
                    body.extend(chunk)
            return nexus.unpack(json.loads(body, object_pairs_hook=nexus._unique_object))
        except httpx.TimeoutException:
            raise NexusComputeError("NEXUS_TIMEOUT") from None
        except httpx.HTTPError:
            raise NexusComputeError("NEXUS_TRANSPORT_ERROR") from None
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise NexusComputeError("NEXUS_SCHEMA_ERROR") from None

    async def run_backtest(self, n_bars: int) -> BacktestJob:
        """Submit once, with 20..500 bars, preserving the mandatory returned ID.

        Requires a prior Studio Fire Backtest. Deploy JSON is never accepted.
        Submissions are never retried, including ambiguous transport failures.
        """
        if type(n_bars) is not int or not 20 <= n_bars <= 500:
            raise NexusComputeError("NEXUS_INVALID_REQUEST")
        if self._runs >= 3:
            raise NexusComputeError("NEXUS_RUN_LIMIT")
        self._runs += 1
        data = await self._call("run_backtest", {"n_bars": n_bars})
        return self._job(data)

    def _job(self, data: dict[str, Any]) -> BacktestJob:
        identifier = _run_id(data.get("run_id"), self._key)
        if data.get("status") not in ("queued", "running", "completed"):
            raise NexusComputeError("NEXUS_UNKNOWN_JOB_STATE", run_id=identifier)
        return BacktestJob(run_id=identifier, status=data["status"])

    async def get_backtest_job(self, run_id: str) -> BacktestJob:
        """Poll only the explicit submission ID, never the service's latest job."""
        run_id = _run_id(run_id, self._key)
        data = await self._call("get_backtest_job", {"run_id": run_id})
        if _run_id(data.get("run_id"), self._key) != run_id:
            raise NexusComputeError("NEXUS_RUN_ID_MISMATCH")
        return self._job(data)


async def run_window_experiment(request: WindowExperimentRequest) -> WindowExperimentReport:
    """Run up to three sequential windows, largest baseline then reductions.

    Requires both enable switches equal to 'true', a configured key, and strict
    confirmation. Admission errors raise NexusComputeError; runtime failures
    produce partial UNPROVEN reports. Contradictory IDs take precedence as
    INCONSISTENT. External cancellation propagates and releases the local lock.
    """
    try:
        request = WindowExperimentRequest.model_validate(request)
    except ValidationError:
        raise NexusComputeError("NEXUS_INVALID_REQUEST") from None
    key = _key()
    if nexus.sanitize("signal", {"symbol": request.symbol}, key).get("symbol") != request.symbol:
        raise NexusComputeError("NEXUS_INVALID_REQUEST")
    if not _PROCESS_LOCK.acquire(blocking=False):
        raise NexusComputeError("NEXUS_COMPUTE_BUSY")
    windows = [WindowEvidence(n_bars=n) for n in reversed(request.windows)]
    index = 0
    try:
        async with asyncio.timeout(request.timeout_seconds):
            async with httpx.AsyncClient(timeout=nexus.TIMEOUT, follow_redirects=False, trust_env=False) as http:
                client = _NexusComputeClient(http, key, max_calls=request.timeout_seconds + 15)
                used_ids: set[str] = set()
                for index, window in enumerate(windows):
                    job = await client.run_backtest(window.n_bars)
                    windows[index] = window = window.model_copy(update={"run_id": job.run_id, "job_status": job.status})
                    if job.run_id in used_ids:
                        raise NexusComputeError("NEXUS_RUN_ID_MISMATCH")
                    used_ids.add(job.run_id)
                    # Always confirm via get_backtest_job, even an immediate completion.
                    while True:
                        await asyncio.sleep(_POLL_INTERVAL)
                        job = await client.get_backtest_job(job.run_id)
                        windows[index] = window = window.model_copy(update={"job_status": job.status})
                        if job.status == "completed":
                            break
                    evidence: dict[str, Any] = {}
                    errors: list[Code] = []
                    mismatch = False
                    for label in ("metrics", "equity", "trades", "signal"):
                        try:
                            raw = await client._call("get_strategy_" + label,
                                                     {"symbol": request.symbol} if label == "signal" else {})
                            # A contradictory identity must not be hidden by bad rows.
                            if label in ("equity", "trades"):
                                mismatch |= _run_id(raw.get("run_id"), key) != job.run_id
                            data = nexus.sanitize(label, raw, key)
                            if label == "metrics":
                                ret = nexus.number(data.get("total_return_pct"))
                                pf = nexus.number(data.get("profit_factor"))
                                status = data.get("status")
                                evidence[label] = MetricsEvidence(
                                    total_return_pct=ret, profit_factor=pf, max_drawdown=data.get("max_drawdown"),
                                    qualification=status, return_nonpositive=None if ret is None else ret <= 0,
                                    profit_factor_at_most_one=None if pf is None else pf <= 1,
                                    not_qualified=None if status is None else status == "NOT_QUALIFIED")
                            elif label == "signal":
                                if data.get("symbol") != request.symbol:
                                    raise NexusComputeError("NEXUS_SCHEMA_ERROR")
                                evidence[label] = SignalEvidence(trade_intent=data.get("trade_intent"),
                                                                 timestamp=nexus.number(data.get("timestamp")))
                            else:
                                identifier = _run_id(data.get("run_id"), key)
                                matched = identifier == job.run_id
                                mismatch |= not matched
                                rows = data.get("points" if label == "equity" else "trades")
                                valid = isinstance(rows, list) and all(
                                    all(field in row for field in (("t", "equity") if label == "equity"
                                                                  else ("symbol", "pnl"))) for row in rows)
                                observed_return = drawdown = None
                                if label == "equity" and matched and valid and isinstance(rows, list) and len(rows) >= 2:
                                    times = [row["t"] for row in rows]
                                    values = [float(row["equity"]) for row in rows]
                                    if all(b > a for a, b in zip(times, times[1:])) and all(v > 0 for v in values):
                                        observed_return = nexus.number((values[-1] / values[0] - 1) * 100)
                                        peak = values[0]
                                        drawdown = 0.0
                                        for value in values:
                                            peak = max(peak, value)
                                            drawdown = max(drawdown, (1 - value / peak) * 100)
                                    else:
                                        valid = False
                                evidence[label] = SeriesEvidence(
                                    binding="matched" if matched else "mismatched", run_id=identifier,
                                    row_count=len(rows) if isinstance(rows, list) else None, valid_rows=valid,
                                    observed_return_pct=observed_return, observed_max_drawdown_pct=drawdown)
                        except NexusComputeError as exc:
                            errors.append(exc.code)
                        except (ValueError, TypeError, OverflowError):
                            errors.append("NEXUS_SCHEMA_ERROR")
                        windows[index] = window.model_copy(update={**evidence, "errors": list(errors),
                            "verdict": "INCONSISTENT" if mismatch else "UNPROVEN",
                            "reason": "NEXUS_RUN_ID_MISMATCH" if mismatch else "NEXUS_METRICS_UNBOUND"})
                    if mismatch:
                        break
    except (TimeoutError, NexusComputeError) as exc:
        code: Code = "NEXUS_TIMEOUT" if isinstance(exc, TimeoutError) else exc.code
        prior = windows[index]
        windows[index] = prior.model_copy(update={"reason": code,
            "run_id": prior.run_id or (exc.run_id if isinstance(exc, NexusComputeError) else None),
            "verdict": "INCONSISTENT" if code == "NEXUS_RUN_ID_MISMATCH" else prior.verdict})
    finally:
        _PROCESS_LOCK.release()
    failing = [w.n_bars for w in windows if w.job_status == "completed" and (
        w.metrics.return_nonpositive is True or w.metrics.profit_factor_at_most_one is True
        or w.metrics.not_qualified is True)]
    return WindowExperimentReport(
        status="INCONSISTENT" if any(w.verdict == "INCONSISTENT" for w in windows) else "UNPROVEN",
        baseline_n_bars=request.windows[-1], windows=windows,
        smallest_observed_failing_n_bars=min(failing) if failing else None)
