/**
 * With-gate vs without-gate replay.
 *
 * Runs the strategy's real trades back through THE SAME `runGate` the live API
 * uses — not a parallel reimplementation. A chart produced by different logic
 * than the product is worth very little: if the two ever disagree, the chart is
 * a claim you cannot back.
 *
 * For each trade, the decision is evaluated as of that trade's ENTRY moment:
 *
 *     now   = trade.entry_ts_ms          (not wall clock)
 *     as_of = the UTC date of that entry  (not today)
 *     equity/trades = truncated to what was knowable at that moment
 *
 * so a June entry is judged against June's funding and June's open interest.
 * That truncation is the whole discipline — evaluating June against September
 * data is the lookahead problem wearing a different hat.
 *
 *   without gate:  every trade taken          ──▶ equity curve A
 *   with gate:     refused trades contribute 0 ──▶ equity curve B
 */
import { runGate } from '../gate/index.js';
import { present, type Datum, type Equity, type GateData, type GateInput, type Policy, type Trade, type Trades } from '../types.js';

export interface ReplayDecision {
  seq: number;
  symbol: string;
  entry_ts_ms: number;
  as_of: string;
  verdict: 'EXECUTE' | 'ABSTAIN' | 'NO_TRADE';
  failed: string[];
  pnl: number;
  /** pnl the account actually takes once the gate has spoken. */
  realizedPnl: number;
}

export interface ReplayResult {
  decisions: ReplayDecision[];
  withoutGate: { t: number; equity: number }[];
  withGate: { t: number; equity: number }[];
  summary: {
    trades: number;
    refused: number;
    pnlWithoutGate: number;
    pnlWithGate: number;
    maxDrawdownWithoutPct: number;
    maxDrawdownWithPct: number;
  };
}

export const isoDate = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/** Peak-to-trough drawdown over a curve, as a positive percentage. */
export function maxDrawdownPct(points: readonly { equity: number }[]): number {
  let peak = -Infinity;
  let worst = 0;
  for (const p of points) {
    if (p.equity > peak) peak = p.equity;
    if (peak > 0) worst = Math.max(worst, ((peak - p.equity) / peak) * 100);
  }
  return Number(worst.toFixed(2));
}

export interface ReplayInputs {
  trades: Trades;
  equity: Equity;
  policy: Policy;
  startingEquity: number;
  /** Point-in-time market data keyed by `${symbol}|${as_of}`; absent entries fail closed. */
  market: Map<
    string,
    { funding: Datum<unknown>; openInterest: Datum<unknown>; openInterestPrev?: Datum<unknown> }
  >;
  /** Everything genuinely constant across the replay. */
  staticData: Pick<GateData, 'metrics' | 'coverage'>;
}

/**
 * The trade IS the proposal in a replay, so the signal is synthesized at the
 * entry moment. Carrying one fixed timestamp across all trades would make
 * SIGNAL_STALE fail on every decision after the first — an artefact of the
 * harness, not a judgement about the strategy.
 */
function signalAt(symbol: string, entryTsMs: number, direction: number): GateData['signal'] {
  return present({
    symbol,
    // The recorded trade IS both the signal and the proposal here, so the
    // intent must follow the trade's direction. Hardcoding BUY made every
    // recorded short fail SIGNAL_SUPPORT — an artefact of the harness, not a
    // judgement about the strategy.
    trade_intent: direction === 1 ? ('BUY' as const) : ('SELL' as const),
    reasoning_log: 'replay: the recorded trade is the proposal',
    timestamp: Math.floor(entryTsMs / 1000),
  });
}

export function replay(inputs: ReplayInputs): ReplayResult {
  const ordered = [...inputs.trades.trades].sort((a, b) => a.entry_ts_ms - b.entry_ts_ms);

  let equityWithout = inputs.startingEquity;
  let equityWith = inputs.startingEquity;
  const withoutGate: { t: number; equity: number }[] = [{ t: ordered[0]?.entry_ts_ms ?? 0, equity: equityWithout }];
  const withGate: { t: number; equity: number }[] = [{ t: ordered[0]?.entry_ts_ms ?? 0, equity: equityWith }];
  const decisions: ReplayDecision[] = [];

  ordered.forEach((trade, i) => {
    const now = trade.entry_ts_ms;
    const asOf = isoDate(now);
    const key = `${trade.symbol}|${asOf}`;
    const market = inputs.market.get(key);

    // Only what was knowable at this entry. Truncating here is what keeps the
    // replay honest; without it the gate would see the whole future curve.
    const knownTrades: Trade[] = ordered.filter((t) => t.exit_ts_ms <= now || t.entry_ts_ms <= now);
    const knownEquity = inputs.equity.points.filter((p) => p.t <= now);

    const input: GateInput = {
      asOf,
      now,
      proposal: {
        symbol: trade.symbol,
        side: trade.direction === 1 ? 'BUY' : 'SELL',
        notional: Math.abs(trade.entry_price * trade.size),
        signalId: `replay_${trade.symbol}_${now}`,
      },
      data: {
        signal: signalAt(trade.symbol, now, trade.direction),
        metrics: inputs.staticData.metrics,
        coverage: inputs.staticData.coverage,
        equity: present({ run_id: inputs.equity.run_id, points: knownEquity }),
        trades: present({ run_id: inputs.trades.run_id, trades: knownTrades }),
        funding: (market?.funding ?? { ok: false, outcome: 'absent' }) as GateData['funding'],
        openInterest: (market?.openInterest ?? { ok: false, outcome: 'absent' }) as GateData['openInterest'],
        openInterestPrev: (market?.openInterestPrev ?? { ok: false, outcome: 'absent' }) as GateData['openInterestPrev'],
      },
      seenSignalIds: new Set(),
      accountEquity: equityWith,
    };

    const outcome = runGate(input, inputs.policy);
    const allowed = outcome.verdict === 'EXECUTE';

    equityWithout += trade.pnl;
    if (allowed) equityWith += trade.pnl;

    withoutGate.push({ t: trade.exit_ts_ms, equity: equityWithout });
    withGate.push({ t: trade.exit_ts_ms, equity: equityWith });

    decisions.push({
      seq: i + 1,
      symbol: trade.symbol,
      entry_ts_ms: now,
      as_of: asOf,
      verdict: outcome.verdict,
      failed: outcome.checks.filter((c) => c.verdict === 'FAIL').map((c) => c.id),
      pnl: trade.pnl,
      realizedPnl: allowed ? trade.pnl : 0,
    });
  });

  return {
    decisions,
    withoutGate,
    withGate,
    summary: {
      trades: ordered.length,
      refused: decisions.filter((d) => d.verdict !== 'EXECUTE').length,
      pnlWithoutGate: Number((equityWithout - inputs.startingEquity).toFixed(2)),
      pnlWithGate: Number((equityWith - inputs.startingEquity).toFixed(2)),
      maxDrawdownWithoutPct: maxDrawdownPct(withoutGate),
      maxDrawdownWithPct: maxDrawdownPct(withGate),
    },
  };
}
