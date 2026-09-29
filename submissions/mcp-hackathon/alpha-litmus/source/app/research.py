"""Deterministic daily, long/flat EMA replay. Signals at close, fills next open."""

import hashlib
import json
import math
import re
import statistics
from datetime import datetime, timezone
from typing import Any, Literal, NotRequired, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DAY_MS = 86_400_000
MAX_TIMESTAMP = 253_402_214_400_000
MAX_RATIO = 1e12


class Feature(TypedDict):
    long: bool
    vol: float | None
    fast: NotRequired[float]
    slow: NotRequired[float]


def bounded_ratio(numerator: float, denominator: float) -> float | None:
    """Undefined or extreme ratios are not meaningful evidence."""
    if not denominator:
        return None
    result = numerator / denominator
    return round(result, 4) if math.isfinite(result) and abs(result) <= MAX_RATIO else None


class Candle(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", allow_inf_nan=False, validate_assignment=True, revalidate_instances="always"
    )
    t: int = Field(ge=0, le=MAX_TIMESTAMP, description="UTC opening timestamp in milliseconds")
    o: float = Field(ge=1e-9, le=1e12)
    h: float = Field(ge=1e-9, le=1e12)
    l: float = Field(ge=1e-9, le=1e12)  # noqa: E741 - Documented OHLC wire field.
    c: float = Field(ge=1e-9, le=1e12)
    v: float = Field(ge=0, le=1e18)

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if self.h < max(self.o, self.c, self.l) or self.l > min(self.o, self.c, self.h):
            raise ValueError("OHLC range is inconsistent")
        return self


class ResearchRequest(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", allow_inf_nan=False, validate_assignment=True, revalidate_instances="always"
    )
    candles: list[Candle] = Field(min_length=250, max_length=3000)
    symbol: str = Field(default="BTC/USDT", pattern=r"^[A-Z0-9]{2,12}/[A-Z0-9]{2,12}$")
    source: str = Field(default="user-supplied", min_length=1, max_length=160)
    data_kind: Literal["synthetic", "historical"]
    fee_bps: float = Field(default=10, ge=0, le=200)
    slippage_bps: float = Field(default=5, ge=0, le=200)

    @field_validator("source")
    @classmethod
    def safe_source(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Source must be nonblank printable provenance")
        if re.search(
            r"(?i)(api[ _-]?key|secret|password|passwd|bearer\s|token\s*[:=]|authorization|-----BEGIN|https?://[^\s/]+@|[?&][^\s=]+=|\b(?:sk|ghp|github_pat)[_-][a-z0-9_-]+|\beyJ[a-z0-9_-]+\.)",
            value,
        ):
            raise ValueError("Source must not contain credentials or secret-like content")
        return value

    @model_validator(mode="after")
    def daily_closed_series(self) -> Self:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for i, bar in enumerate(self.candles):
            if bar.t % DAY_MS:
                raise ValueError("Daily candles must open at UTC midnight")
            if bar.t + 86_400_000 > now_ms:
                raise ValueError("Only fully closed historical daily candles are accepted")
            if i and bar.t - self.candles[i - 1].t != 86_400_000:
                raise ValueError("Candles must be unique, ascending, gap-free daily bars")
        return self


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def features(candles: list[Candle]) -> list[Feature]:
    if not candles:
        raise ValueError("At least one candle is required")
    fast = slow = candles[0].c
    log_returns: list[float] = []
    out: list[Feature] = []
    for i, bar in enumerate(candles):
        fast += 2 / 21 * (bar.c - fast)
        slow += 2 / 51 * (bar.c - slow)
        if i:
            log_returns.append(math.log(bar.c / candles[i - 1].c))
        vol = statistics.pstdev(log_returns[-20:]) if len(log_returns) >= 20 else None
        out.append({"fast": fast, "slow": slow, "vol": vol, "long": i >= 50 and fast > slow})
    return out


def replay(
    candles: list[Candle],
    feat: list[Feature],
    start: int,
    end: int,
    cost_bps: float,
    vol_limit: float | None = None,
    buy_hold: bool = False,
) -> dict[str, Any]:
    """Isolated fold starts flat. Liquidates at final close, charging both sides."""
    if not 1 <= start < end <= len(candles) or len(feat) != len(candles):
        raise ValueError("Replay requires a prior signal and a nonempty valid fold")
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 1200:
        raise ValueError("One-way costs must be finite and between 0 and 1200 bps")
    if vol_limit is not None and (not math.isfinite(vol_limit) or not 0 <= vol_limit <= MAX_RATIO):
        raise ValueError("Volatility limit must be finite and bounded")
    cash = 10_000.0
    units = 0.0
    entry_value = 0.0
    entry_t = None
    peak = cash
    max_dd = 0.0
    equity = [{"t": candles[start].t, "equity": cash}]
    trades: list[dict[str, Any]] = []
    returns: list[float] = []
    previous = cash
    blocked = 0
    exposure = 0
    cost = cost_bps / 10_000
    total_cost = 0.0
    for i in range(start, end):
        bar = candles[i]
        f = feat[i - 1]
        want_long = buy_hold or f["long"]
        if want_long and vol_limit is not None and (f["vol"] is None or f["vol"] > vol_limit):
            want_long = False
            blocked += 1
        if units and not want_long:
            gross = units * bar.o
            total_cost += gross * cost
            cash = gross * (1 - cost)
            trades.append(
                {
                    "entry_t": entry_t,
                    "exit_t": bar.t,
                    "pnl": round(cash - entry_value, 4),
                    "return_pct": round((cash / entry_value - 1) * 100, 4),
                    "exit": "signal",
                }
            )
            units = 0.0
        elif not units and want_long:
            entry_value = cash
            entry_t = bar.t
            units = cash / (bar.o * (1 + cost))
            total_cost += units * bar.o * cost
            cash = 0.0
        if units:
            exposure += 1
        if i == end - 1 and units:
            gross = units * bar.c
            total_cost += gross * cost
            cash = gross * (1 - cost)
            trades.append(
                {
                    "entry_t": entry_t,
                    "exit_t": bar.t + 86_400_000 - 1,
                    "pnl": round(cash - entry_value, 4),
                    "return_pct": round((cash / entry_value - 1) * 100, 4),
                    "exit": "fold_end",
                }
            )
            units = 0.0
        value = cash + units * bar.c
        if not math.isfinite(value) or not 1e-100 <= value <= 1e100:
            raise ValueError("Replay wealth exceeds the supported numerical range")
        returns.append(value / previous - 1)
        previous = value
        peak = max(peak, value)
        max_dd = max(max_dd, 1 - value / peak)
        equity.append({"t": bar.t + 86_400_000 - 1, "equity": round(value, 6)})
    sd = statistics.pstdev(returns) if returns else 0
    wins = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = -sum(t["pnl"] for t in trades if t["pnl"] < 0)
    metrics = {
        "return_pct": round((previous / 10_000 - 1) * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "sharpe": round(statistics.mean(returns) / sd * math.sqrt(365), 4) if sd else None,
        "trade_count": len(trades),
        "win_rate_pct": round(sum(t["pnl"] > 0 for t in trades) / len(trades) * 100, 2) if trades else None,
        "profit_factor": round(wins / losses, 4) if losses else None,
        "execution_cost_usdt": round(total_cost, 4),
        "exposure_pct": round(exposure / (end - start) * 100, 2),
        "blocked_days": blocked,
    }
    metrics["sharpe"] = bounded_ratio(statistics.mean(returns) * math.sqrt(365), sd)
    metrics["profit_factor"] = bounded_ratio(wins, losses)
    return {"metrics": metrics, "equity": equity, "trades": trades}


def research(req: ResearchRequest) -> dict[str, Any]:
    """Deprecated legacy report; WAIT is not an execution recommendation."""
    # Lists and model_copy(update=...) can bypass assignment validation.
    req = ResearchRequest.model_validate(req.model_dump())
    bars = req.candles
    feat = features(bars)
    n = len(bars)
    train_end, val_end = int(n * 0.6), int(n * 0.8)
    training_vol = sorted(f["vol"] for f in feat[50:train_end] if f["vol"] is not None)
    limit = training_vol[int((len(training_vol) - 1) * 0.8)]
    total_bps = req.fee_bps + req.slippage_bps
    folds: dict[str, Any] = {}
    for name, start, end in (("train", 51, train_end), ("validation", train_end, val_end), ("test", val_end, n)):
        folds[name] = {
            "start": bars[start].t,
            "end": bars[end - 1].t,
            "bars": end - start,
            "baseline": replay(bars, feat, start, end, total_bps),
            "guarded": replay(bars, feat, start, end, total_bps, limit),
            "buy_hold": replay(bars, feat, start, end, total_bps, buy_hold=True),
        }
    stress = []
    for bps in sorted(set([total_bps, total_bps * 2, total_bps * 3])):
        result = replay(bars, feat, val_end, n, bps, limit)
        stress.append({"one_way_cost_bps": bps, **result["metrics"]})
    base = folds["test"]["baseline"]["metrics"]
    guard = folds["test"]["guarded"]["metrics"]
    small = guard["trade_count"] < 30
    delta = round(guard["return_pct"] - base["return_pct"], 4)
    dd_delta = round(base["max_drawdown_pct"] - guard["max_drawdown_pct"], 4)
    reasons = []
    if req.data_kind == "synthetic":
        reasons.append("SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE")
    if small:
        reasons.append("INSUFFICIENT_TEST_TRADES")
    if delta <= 0:
        reasons.append("GUARD_DID_NOT_IMPROVE_TEST_RETURN")
    if stress[-1]["return_pct"] <= 0:
        reasons.append("COST_STRESS_NOT_PROFITABLE")
    if folds["validation"]["guarded"]["metrics"]["return_pct"] <= 0:
        reasons.append("VALIDATION_NOT_PROFITABLE")
    if dd_delta < 0:
        reasons.append("GUARD_WORSENED_TEST_DRAWDOWN")
    if guard["max_drawdown_pct"] > 15:
        reasons.append("TEST_DRAWDOWN_ABOVE_RESEARCH_LIMIT")
    dataset_hash = digest([b.model_dump() for b in bars])
    return {
        **_legacy_payload(req, dataset_hash, reasons, limit, folds, stress, delta, dd_delta),
        "schema_version": "AlphaLitmus.legacy.v1",
        "product": "AlphaLitmus",
        "deprecated": True,
    }


def _legacy_payload(
    req: ResearchRequest,
    dataset_hash: str,
    reasons: list[str],
    limit: float,
    folds: dict[str, Any],
    stress: list[dict[str, Any]],
    delta: float,
    dd_delta: float,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "independent_research",
        "nexus_validated": False,
        "symbol": req.symbol,
        "data_kind": req.data_kind,
        "source": req.source,
        "dataset_sha256": dataset_hash,
        "report_id": digest(
            {"data": dataset_hash, "fees": req.fee_bps, "slippage": req.slippage_bps, "engine": "ema-daily-v1"}
        ),
        "decision": "WAIT" if reasons else "PAPER_CANDIDATE",
        "reason_codes": reasons,
        "strategy": {
            "id": "ema-daily-v1",
            "timeframe": "1d",
            "rules": "Long when EMA20 > EMA50 at prior close; otherwise flat. Execute at next open. No leverage, no shorts.",
            "gate": "Flat when prior 20-day log-return volatility exceeds training-only 80th percentile.",
            "volatility_limit": limit,
            "parameters_frozen": True,
        },
        "costs": {
            "fee_bps": req.fee_bps,
            "slippage_bps": req.slippage_bps,
            "model": "Combined proportional cost charged at every entry and exit; one-way bps.",
        },
        "folds": folds,
        "stress": stress,
        "comparison": {"test_return_delta_pp": delta, "test_drawdown_reduction_pp": dd_delta},
        "no_execution": True,
        "limitations": [
            "Independent reference strategy; does not replicate or validate the Nexus-bound strategy.",
            "Historical label and source are caller-provided; hashes establish integrity, not authenticity.",
            "Test is chronologically held out by code, but repeated user selection can contaminate it.",
            "No funding, borrow, order-book depth, intraday stops or capacity simulation; unlevered spot only.",
            "Daily Sharpe uses 365-day annualization and zero risk-free rate. Daily marks can miss intraday drawdown.",
            "Small trade counts cannot establish a statistically reliable edge.",
        ],
    }
