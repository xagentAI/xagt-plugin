/**
 * Checks sourced from the strategy's own published record:
 * metrics, equity curve, and trade history.
 */
import type { CheckResult, GateInput, Policy, Trade } from '../../types.js';

/**
 * #2 NOT_QUALIFIED — Nexus publishes its listing gates in catalog.json:
 *   sharpe_ratio > 2.0 · trading_period_days > 30 · estimated_aum_usdt > 10000
 * The bound strategy scores sharpe 0.2989, so under a strict policy this is a
 * standing refusal. `require_qualified: false` SKIPS it and lets the other nine
 * decide — the two policies differ in exactly this one key.
 */
export function notQualified(input: GateInput, policy: Policy): CheckResult {
  if (!policy.require_qualified) {
    return {
      id: 'NOT_QUALIFIED',
      verdict: 'SKIPPED',
      observed: null,
      threshold: 'QUALIFIED_FOR_OKX_LISTING',
      unit: null,
      source: null,
      reason: 'policy.require_qualified is false',
    };
  }

  const { metrics } = input.data;
  if (!metrics.ok) {
    return {
      id: 'NOT_QUALIFIED',
      verdict: 'SKIPPED',
      observed: null,
      threshold: 'QUALIFIED_FOR_OKX_LISTING',
      unit: null,
      source: { call: 'get_strategy_metrics', outcome: metrics.outcome, ...(metrics.error ? { error: metrics.error } : {}) },
      reason: `metrics ${metrics.outcome}; DATA_GAP carries the refusal`,
    };
  }

  const m = metrics.value;
  const qualified = m.status === 'QUALIFIED_FOR_OKX_LISTING';
  return {
    id: 'NOT_QUALIFIED',
    verdict: qualified ? 'PASS' : 'FAIL',
    observed: m.status,
    threshold: 'QUALIFIED_FOR_OKX_LISTING',
    unit: null,
    source: { call: 'get_strategy_metrics', outcome: 'ok' },
    // Name which sub-gate failed. "NOT_QUALIFIED" alone tells a reviewer nothing.
    detail: {
      sharpe_ratio: { observed: m.sharpe_ratio, gate: '> 2.0', pass: m.sharpe_ratio > 2.0 },
      trading_period_days: { observed: m.trading_period_days, gate: '> 30', pass: m.trading_period_days > 30 },
      estimated_aum_usdt: { observed: m.estimated_aum_usdt, gate: '> 10000', pass: m.estimated_aum_usdt > 10000 },
    },
  };
}

/**
 * #5 DRAWDOWN_BUDGET — current drawdown from the running peak of the equity
 * series supplied. In replay mode the caller truncates the series at the
 * decision date, so this reads as of that moment rather than today.
 *
 * The series is 30–120 daily points, so the estimate is coarse. `sample_count`
 * ships in the receipt; overclaiming precision costs more than admitting it.
 */
export function drawdownBudget(input: GateInput, policy: Policy): CheckResult {
  const { equity } = input.data;
  if (!equity.ok) {
    return {
      id: 'DRAWDOWN_BUDGET',
      verdict: 'SKIPPED',
      observed: null,
      threshold: policy.max_drawdown_pct,
      unit: '%',
      source: { call: 'get_strategy_equity', outcome: equity.outcome, ...(equity.error ? { error: equity.error } : {}) },
      reason: `equity ${equity.outcome}; DATA_GAP carries the refusal`,
    };
  }

  const points = equity.value.points;
  if (points.length === 0) {
    return {
      id: 'DRAWDOWN_BUDGET',
      verdict: 'SKIPPED',
      observed: null,
      threshold: policy.max_drawdown_pct,
      unit: '%',
      source: { call: 'get_strategy_equity', outcome: 'absent' },
      reason: 'equity series is empty',
    };
  }

  let peak = -Infinity;
  let peakAt = 0;
  for (const p of points) {
    if (p.equity > peak) {
      peak = p.equity;
      peakAt = p.t;
    }
  }
  const last = points[points.length - 1]!;
  const ddPct = peak > 0 ? ((peak - last.equity) / peak) * 100 : 0;

  return {
    id: 'DRAWDOWN_BUDGET',
    verdict: ddPct > policy.max_drawdown_pct ? 'FAIL' : 'PASS',
    observed: Number(ddPct.toFixed(2)),
    threshold: policy.max_drawdown_pct,
    unit: '%',
    source: { call: 'get_strategy_equity', outcome: 'ok' },
    detail: { sample_count: points.length, peak, peak_at_ms: peakAt, current: last.equity },
  };
}

/** Trades fully closed at or before `now`, oldest first. */
function closedBy(trades: readonly Trade[], now: number): Trade[] {
  return trades.filter((t) => t.exit_ts_ms <= now).sort((a, b) => a.exit_ts_ms - b.exit_ts_ms);
}

/**
 * #7 LOSS_STREAK — trailing consecutive losers, ordered by exit time. A cool-off
 * after repeated losses. The bound strategy's observed maximum is 3, so 3 is the
 * threshold: it fires at the real extreme rather than never.
 */
export function lossStreak(input: GateInput, policy: Policy): CheckResult {
  const { trades } = input.data;
  if (!trades.ok) {
    return {
      id: 'LOSS_STREAK',
      verdict: 'SKIPPED',
      observed: null,
      threshold: policy.max_loss_streak,
      unit: 'trades',
      source: { call: 'get_strategy_trades', outcome: trades.outcome, ...(trades.error ? { error: trades.error } : {}) },
      reason: `trades ${trades.outcome}; DATA_GAP carries the refusal`,
    };
  }

  const closed = closedBy(trades.value.trades, input.now);
  let streak = 0;
  for (let i = closed.length - 1; i >= 0; i--) {
    if (closed[i]!.pnl < 0) streak++;
    else break;
  }

  return {
    id: 'LOSS_STREAK',
    verdict: streak >= policy.max_loss_streak ? 'FAIL' : 'PASS',
    observed: streak,
    threshold: policy.max_loss_streak,
    unit: 'trades',
    source: { call: 'get_strategy_trades', outcome: 'ok' },
    detail: { closed_trades_considered: closed.length },
  };
}

/**
 * #6 CORRELATED_CLUSTER — the check that exists because of real evidence.
 *
 * In run bt-7a0daf243c06 the strategy opened ETH, BTC and SOL long at 3x on the
 * same bar (entry_bar_index 50). All three hit stop_loss at -25.38%, losing
 * 5,395 combined, and that cluster IS the entire 7.62% max drawdown:
 *
 *     peak 101,538.70 ──▶ trough 93,799.53   = -7.62%
 *
 * A single-symbol cap would have passed all three, because no single position
 * breached 25%. Three correlated 3x longs opened together are one bet placed
 * three times, and that is what this refuses.
 *
 * FAIL when the concurrent same-direction position count, INCLUDING the
 * proposal, reaches `max_cluster_size`. The single-symbol exposure cap is
 * retained as a cheaper sub-condition.
 */
export function correlatedCluster(input: GateInput, policy: Policy): CheckResult {
  const { trades } = input.data;
  const { proposal } = input;

  // Sub-condition first: it needs no market data and can fail on its own.
  const symbolPct = input.accountEquity > 0 ? (proposal.notional / input.accountEquity) * 100 : 0;
  if (symbolPct > policy.max_symbol_pct) {
    return {
      id: 'CORRELATED_CLUSTER',
      verdict: 'FAIL',
      observed: Number(symbolPct.toFixed(2)),
      threshold: policy.max_symbol_pct,
      unit: '%',
      source: null,
      reason: 'single-symbol exposure cap breached',
    };
  }

  if (!trades.ok) {
    return {
      id: 'CORRELATED_CLUSTER',
      verdict: 'SKIPPED',
      observed: null,
      threshold: policy.max_cluster_size,
      unit: 'positions',
      source: { call: 'get_strategy_trades', outcome: trades.outcome, ...(trades.error ? { error: trades.error } : {}) },
      reason: `trades ${trades.outcome}; DATA_GAP carries the refusal`,
    };
  }

  const wantDirection = proposal.side === 'BUY' ? 1 : -1;
  const concurrent = trades.value.trades.filter(
    (t) =>
      t.symbol !== proposal.symbol && // same symbol is the sub-condition's job
      t.direction === wantDirection &&
      t.entry_ts_ms <= input.now &&
      t.exit_ts_ms > input.now,
  );

  const clusterSize = concurrent.length + 1; // +1 for the proposal itself
  return {
    id: 'CORRELATED_CLUSTER',
    verdict: clusterSize >= policy.max_cluster_size ? 'FAIL' : 'PASS',
    observed: clusterSize,
    threshold: policy.max_cluster_size,
    unit: 'positions',
    source: { call: 'get_strategy_trades', outcome: 'ok' },
    detail: {
      direction: wantDirection,
      concurrent_symbols: concurrent.map((t) => t.symbol),
      symbol_exposure_pct: Number(symbolPct.toFixed(2)),
    },
  };
}
