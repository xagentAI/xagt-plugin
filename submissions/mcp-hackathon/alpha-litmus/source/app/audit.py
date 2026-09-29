"""Fail-closed evidence assessment. No arbitrary trust score or sizing advice."""

import math
from datetime import datetime, timezone
from typing import Any


def number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(str(value).removesuffix("%"))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def audit(evidence: dict[str, Any], symbol: str, now: float | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    reasons: list[str] = []
    checks: list[dict[str, str]] = []

    def check(code: str, ok: bool, detail: str) -> None:
        checks.append({"code": code, "status": "PASS" if ok else "UNVERIFIED", "detail": detail})
        if not ok:
            reasons.append(code)

    surfaces: dict[str, dict[str, Any]] = {}
    for key in ("signal", "metrics", "equity", "trades"):
        envelope = evidence.get(key)
        received = isinstance(envelope, dict) and envelope.get("status") == "received"
        data = envelope.get("data") if isinstance(envelope, dict) else None
        check(key.upper() + "_AVAILABLE", received, "Nexus evidence surface received; does not prove freshness.")
        surfaces[key] = data if received and isinstance(data, dict) else {}
    signal, metrics, equity, trades = (surfaces[key] for key in ("signal", "metrics", "equity", "trades"))
    timestamp = number(signal.get("timestamp"))
    if timestamp and timestamp > 1e12:
        timestamp /= 1000
    age = now - timestamp if timestamp else None
    check(
        "SIGNAL_FRESH",
        age is not None and 0 <= age <= 900,
        "Maximum source-signal age 900 seconds; fetch time is not source time.",
    )
    check(
        "SIGNAL_SCHEMA",
        signal.get("symbol") == symbol and signal.get("trade_intent") in ("BUY", "SELL", "HOLD"),
        "Symbol and intent must match the requested instrument.",
    )
    count = number(metrics.get("trade_count"))
    check(
        "TRADE_SAMPLE",
        count is not None and count >= 30,
        "At least 30 reported trades is a screening floor, not proof of significance.",
    )
    dd = number(metrics.get("max_drawdown"))
    check(
        "DRAWDOWN_SCREEN",
        dd is not None and 0 <= dd <= 15,
        "Reported drawdown must be between 0 and 15 percentage points.",
    )
    run_a, run_b = equity.get("run_id"), trades.get("run_id")
    check("RUN_CONSISTENCY", bool(run_a) and run_a == run_b, "Equity and trades must identify the same run.")
    points = equity.get("points", [])
    valid_points = isinstance(points, list) and len(points) >= 2
    previous_t: float | None = None
    for point in points if isinstance(points, list) else []:
        value = number(point.get("equity")) if isinstance(point, dict) else None
        timestamp_value = number(point.get("t")) if isinstance(point, dict) else None
        if (
            value is None
            or not 0 < value <= 1e18
            or timestamp_value is None
            or not 0 <= timestamp_value <= 253402300799999
            or (previous_t is not None and timestamp_value <= previous_t)
        ):
            valid_points = False
            break
        previous_t = timestamp_value
    check("EQUITY_INTEGRITY", valid_points, "Positive equity and strictly ascending timestamps required.")
    check(
        "TRADES_PRESENT",
        isinstance(trades.get("trades"), list) and bool(trades["trades"]),
        "At least one trade record must be available; recent records may not be full history.",
    )
    # The official published examples do not attest these facts. Never infer them.
    check("COST_ACCOUNTING_ATTESTED", False, "Nexus summary alone does not establish the fee/slippage model.")
    check("OUT_OF_SAMPLE_ATTESTED", False, "Nexus summary alone does not establish a frozen out-of-sample evaluation.")
    check(
        "METRICS_SIGNAL_RUN_BINDING",
        False,
        "Documented metrics and signal examples do not bind all surfaces to one run.",
    )
    return {
        "mode": "nexus_live",
        "symbol": symbol,
        "decision": "WAIT",
        "no_execution": True,
        "signal_age_seconds": round(age, 1) if age is not None else None,
        "checks": checks,
        "reason_codes": reasons,
        "evidence": evidence,
        "limitations": [
            "WAIT is an evidence gap, not a prediction that the strategy will lose.",
            "No supplied summary is independently validated profit evidence.",
            "Reference-strategy research is separate from the Nexus-bound strategy.",
        ],
    }
