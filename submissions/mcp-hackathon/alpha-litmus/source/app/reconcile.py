"""Conditional arithmetic checks, not an attestation of strategy profitability."""
import time
from typing import Any

from app.nexus import SURFACES, number, sanitize


def reconcile(evidence: dict[str, Any], symbol: str, now: float | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    unavailable: list[str] = []
    surfaces: dict[str, dict[str, Any]] = {}
    limitations = [
        "Trades are recent fills, not an attested complete history; equal counts do not prove completeness.",
        "Metrics and signal have no documented run binding; full metrics-to-run reconciliation is unavailable.",
        "Equity comparisons assume the same window and no external cash flows; sampling can hide drawdown.",
        "Fees, slippage, position closure, Sharpe methodology and out-of-sample performance are not attested.",
        "MATCH denotes only the stated check, not verified profit evidence or an execution recommendation.",
    ]

    def add(code: str, status: str, claimed: object, recomputed: object,
            tolerance: float | None, path: str, explanation: str) -> None:
        results.append({"code": code, "status": status, "claimed": claimed,
                        "recomputed": recomputed, "tolerance": tolerance,
                        "evidence_path": path, "explanation": explanation})

    def descriptive(code: str, claimed: float | None, computed: float | None,
                    tolerance: float, path: str, limitation: str) -> None:
        if claimed is None or computed is None:
            observation = "Arithmetic comparison unavailable."
        elif abs(claimed - computed) <= tolerance:
            observation = "Arithmetic agreement within tolerance, not a verified match."
        else:
            observation = "Arithmetic discrepancy exceeds tolerance, not a bound contradiction."
        add(code, "INSUFFICIENT_EVIDENCE", claimed, computed, tolerance, path,
            observation + " " + limitation)

    for label in SURFACES:
        surface = evidence.get(label)
        data: dict[str, Any] = {}
        if isinstance(surface, dict) and surface.get("status") == "received":
            try:
                data = sanitize(label, surface.get("data"))
            except (ValueError, TypeError, RecursionError):
                pass
        surfaces[label] = data
        if not data:
            unavailable.append(label)
            add(label.upper() + "_AVAILABLE", "UNAVAILABLE", None, None, None,
                label, "Evidence surface is missing or unusable.")

    signal, metrics, equity, trades = (surfaces[label] for label in SURFACES)
    requested = sanitize("signal", {"symbol": symbol}).get("symbol")
    actual = signal.get("symbol")
    add("SIGNAL_SYMBOL", "INSUFFICIENT_EVIDENCE" if actual is None or requested is None else
        "MATCH" if actual == requested else "MISMATCH", requested, actual, None,
        "signal.data.symbol", "Exact instrument equality; no symbol normalization.")
    intent = signal.get("trade_intent")
    add("SIGNAL_INTENT", "MATCH" if intent is not None else "INSUFFICIENT_EVIDENCE",
        intent, intent, None, "signal.data.trade_intent", "Documented BUY, SELL or HOLD intent required.")
    timestamp = number(signal.get("timestamp"))
    clock = number(time.time() if now is None else now)
    age = number(clock - timestamp) if clock is not None and timestamp is not None else None
    summary["signal_age_seconds"] = age
    add("SIGNAL_FRESH", "INSUFFICIENT_EVIDENCE" if age is None else
        "MATCH" if 0 <= age <= 900 else "MISMATCH", timestamp, age, 900,
        "signal.data.timestamp", "Source timestamp is Unix seconds; age must be between 0 and 900 seconds inclusive.")
    run_a, run_b = equity.get("run_id"), trades.get("run_id")
    run_match = run_a is not None and run_b is not None and run_a == run_b
    add("RUN_CONSISTENCY", "INSUFFICIENT_EVIDENCE" if run_a is None or run_b is None else
        "MATCH" if run_match else "MISMATCH", run_a, run_b, None,
        "equity.data.run_id;trades.data.run_id", "Equity and trades must identify the same run.")
    add("METRICS_SIGNAL_RUN_BINDING", "INSUFFICIENT_EVIDENCE", None, None, None,
        "metrics.data;signal.data", "No documented metrics/signal run identifiers; full reconciliation cannot succeed.")

    rows = trades.get("trades")
    valid_rows = isinstance(rows, list) and all("symbol" in row and "pnl" in row for row in rows)
    symbols_match = valid_rows and isinstance(rows, list) and requested is not None and all(row["symbol"] == requested for row in rows)
    add("TRADE_SYMBOLS", "INSUFFICIENT_EVIDENCE" if not valid_rows or not rows or requested is None else
        "MATCH" if symbols_match else "MISMATCH", requested, None, None,
        "trades.data.trades[].symbol", "Every returned fill must match the requested instrument exactly.")
    count = len(rows) if isinstance(rows, list) else None
    claimed_count = metrics.get("trade_count")
    summary["recent_trade_count"] = count
    descriptive("TRADE_COUNT", claimed_count, count, 0,
        "metrics.data.trade_count;trades.data.trades",
        "Conditional count comparison only: metrics have no run binding; recent fills may omit history and equal counts do not attest completeness.")
    pnl_total: float | None = None
    pf: float | None = None
    win_rate: float | None = None
    if valid_rows and isinstance(rows, list):
        pnls = [float(row["pnl"]) for row in rows]
        wins = sum(pnl > 0 for pnl in pnls)
        losses = sum(pnl < 0 for pnl in pnls)
        gross_profit = number(sum(pnl for pnl in pnls if pnl > 0))
        gross_loss = number(-sum(pnl for pnl in pnls if pnl < 0))
        pnl_total = number(sum(pnls))
        pf = number(gross_profit / gross_loss) if gross_profit is not None and gross_loss else None
        win_rate = 100 * wins / len(pnls) if pnls else None
        summary.update({"recent_wins": wins, "recent_losses": losses,
                        "recent_breakeven": len(pnls) - wins - losses,
                        "recent_gross_profit": gross_profit, "recent_gross_loss": gross_loss,
                        "recent_pnl": pnl_total, "recent_profit_factor": pf,
                        "recent_win_rate_pct": win_rate})

    for field, computed in (("win_rate_pct", win_rate), ("profit_factor", pf)):
        claimed = number(metrics.get(field))
        descriptive(field.upper(), claimed, computed, 0.01,
            "metrics.data." + field + ";trades.data.trades[].pnl",
            "Metrics have no run binding and recent fills do not attest a complete comparable closed-trade window; zero gross loss leaves profit factor undefined.")

    points = equity.get("points")
    valid_points = isinstance(points, list) and len(points) >= 2 and all(
        "t" in point and "equity" in point and point["equity"] > 0 for point in points)
    if valid_points and isinstance(points, list):
        valid_points = all(a["t"] < b["t"] for a, b in zip(points, points[1:]))
    add("EQUITY_INTEGRITY", "MATCH" if valid_points else "INSUFFICIENT_EVIDENCE", None, None, None,
        "equity.data.points", "At least two positive equity points with strictly increasing timestamps are required.")
    change: float | None = None
    return_pct: float | None = None
    drawdown: float | None = None
    if valid_points and isinstance(points, list):
        values = [float(point["equity"]) for point in points]
        change = number(values[-1] - values[0])
        return_pct = number((values[-1] / values[0] - 1) * 100)
        peak = values[0]
        drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            drawdown = max(drawdown, (1 - value / peak) * 100)
        summary.update({"equity_point_count": len(values), "equity_change": change,
                        "equity_return_pct": return_pct, "sampled_max_drawdown_pct": drawdown})
    dd = metrics.get("max_drawdown")
    claimed_dd = float(dd[:-1]) if isinstance(dd, str) else None
    for code, claimed, computed, path in (
        ("TOTAL_RETURN_PCT", number(metrics.get("total_return_pct")), return_pct, "metrics.data.total_return_pct;equity.data.points"),
        ("MAX_DRAWDOWN", claimed_dd, drawdown, "metrics.data.max_drawdown;equity.data.points"),
        ("PNL_EQUITY_CHANGE", pnl_total, change, "trades.data.trades[].pnl;equity.data.points"),
    ):
        descriptive(code, claimed, computed, 0.01, path,
            "Aligned windows, complete samples and absence of cash flows are unverified even with equal run IDs; metrics have no run binding.")
    return {"results": results, "summary": summary,
            "inconsistent": any(result["status"] == "MISMATCH" for result in results),
            "limitations": limitations, "unavailable": unavailable}
