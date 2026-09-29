import { describe, expect, it } from 'vitest';
import { isoDate, maxDrawdownPct, replay, type ReplayInputs } from '../src/chart/replay.js';
import { renderSvg, renderTable } from '../src/chart/render.js';
import { mergePolicy } from '../src/policy/index.js';
import { absent, present, type Equity, type Trade, type Trades } from '../src/types.js';
import { BASE_POLICY, COVERAGE, METRICS, TRADES_CLUSTER } from './helpers.js';

const DAY = 86_400_000;
const START = Date.UTC(2026, 5, 19); // 2026-06-19, the bar-50 entry date

/** Calm, always-available market data so only the check under test can fail. */
function openMarket(trades: Trade[]): ReplayInputs['market'] {
  const m: ReplayInputs['market'] = new Map();
  for (const t of trades) {
    m.set(`${t.symbol}|${isoDate(t.entry_ts_ms)}`, {
      funding: present({ symbol: t.symbol, as_of_date: isoDate(t.entry_ts_ms), last_funding_rate: 0.0001 }),
      openInterest: present({
        symbol: t.symbol,
        as_of_date: isoDate(t.entry_ts_ms),
        open_interest: 1_000_000,
        open_interest_prev: 980_000,
      }),
    });
  }
  return m;
}

function equityFor(trades: Trade[], startingEquity = 100_000): Equity {
  let e = startingEquity;
  return {
    run_id: 'bt-test',
    points: [
      { t: trades[0]!.entry_ts_ms - DAY, equity: e },
      ...trades.map((t) => ({ t: t.exit_ts_ms, equity: (e += t.pnl) })),
    ],
  };
}

function run(trades: Trades, overrides: Partial<ReplayInputs> = {}) {
  return replay({
    trades,
    equity: equityFor(trades.trades),
    policy: mergePolicy(BASE_POLICY, 'permissive'),
    startingEquity: 100_000,
    market: openMarket(trades.trades),
    staticData: { metrics: present(METRICS), coverage: present(COVERAGE) },
    ...overrides,
  });
}

const trade = (o: Partial<Trade> & { symbol: string; entry_ts_ms: number; exit_ts_ms: number; pnl: number }): Trade => ({
  run_id: 'bt-test',
  direction: 1,
  entry_price: 100,
  exit_price: 110,
  size: 10,
  leverage: 1,
  pnl_pct: 10,
  exit_reason: 'take_profit',
  holding_bars: 2,
  commission: 1,
  entry_bar_index: 0,
  exit_bar_index: 2,
  ...o,
});

describe('point-in-time discipline', () => {
  it('judges each trade at its own entry date, not today', () => {
    const trades: Trades = {
      run_id: 'bt-test',
      trades: [
        trade({ symbol: 'BTC/USDT', entry_ts_ms: START, exit_ts_ms: START + DAY, pnl: 100 }),
        trade({ symbol: 'ETH/USDT', entry_ts_ms: START + 10 * DAY, exit_ts_ms: START + 11 * DAY, pnl: 50 }),
      ],
    };
    const r = run(trades);
    expect(r.decisions.map((d) => d.as_of)).toEqual(['2026-06-19', '2026-06-29']);
  });

  it('does not let SIGNAL_STALE fire from harness drift', () => {
    // A fixed signal timestamp across a 90-day replay would fail every decision
    // after the first. The signal is synthesized at each entry instead.
    const trades: Trades = {
      run_id: 'bt-test',
      trades: Array.from({ length: 6 }, (_, i) =>
        trade({
          symbol: `S${i}/USDT`,
          entry_ts_ms: START + i * 10 * DAY,
          exit_ts_ms: START + i * 10 * DAY + DAY,
          pnl: 10,
        }),
      ),
    };
    const r = run(trades);
    expect(r.decisions.every((d) => !d.failed.includes('SIGNAL_STALE'))).toBe(true);
  });

  it('never shows the gate an equity point from the future', () => {
    const trades: Trades = {
      run_id: 'bt-test',
      trades: [
        trade({ symbol: 'BTC/USDT', entry_ts_ms: START, exit_ts_ms: START + DAY, pnl: -9_000 }),
        trade({ symbol: 'ETH/USDT', entry_ts_ms: START + 2 * DAY, exit_ts_ms: START + 3 * DAY, pnl: 50 }),
      ],
    };
    const r = run(trades);
    // The first decision cannot know about the -9,000 that follows it, so
    // DRAWDOWN_BUDGET must not fail on trade 1.
    expect(r.decisions[0]!.failed).not.toContain('DRAWDOWN_BUDGET');
    // The second one can: the loss is now in the past.
    expect(r.decisions[1]!.failed).toContain('DRAWDOWN_BUDGET');
  });
});

describe('the bar-50 cluster, replayed', () => {
  it('refuses the correlated entries', () => {
    const r = run(TRADES_CLUSTER);
    const refused = r.decisions.filter((d) => d.failed.includes('CORRELATED_CLUSTER'));
    expect(refused.length).toBeGreaterThanOrEqual(2);
    expect(r.summary.refused).toBeGreaterThanOrEqual(2);
  });

  it('refused trades contribute nothing to the with-gate curve', () => {
    const r = run(TRADES_CLUSTER);
    const takenPnl = r.decisions.filter((d) => d.verdict === 'EXECUTE').reduce((s, d) => s + d.pnl, 0);
    expect(r.summary.pnlWithGate).toBeCloseTo(takenPnl, 2);
    expect(r.decisions.every((d) => (d.verdict === 'EXECUTE' ? d.realizedPnl === d.pnl : d.realizedPnl === 0))).toBe(true);
  });

  it('the without-gate curve takes every trade regardless of verdict', () => {
    const r = run(TRADES_CLUSTER);
    const all = TRADES_CLUSTER.trades.reduce((s, t) => s + t.pnl, 0);
    expect(r.summary.pnlWithoutGate).toBeCloseTo(all, 2);
  });
});

describe('missing market data fails closed', () => {
  it('refuses every decision when funding and OI were never recorded', () => {
    const r = run(TRADES_CLUSTER, { market: new Map() });
    expect(r.summary.refused).toBe(TRADES_CLUSTER.trades.length);
    expect(r.decisions.every((d) => d.failed.includes('DATA_GAP'))).toBe(true);
  });

  it('refuses when metrics are unavailable under a strict policy', () => {
    const r = run(TRADES_CLUSTER, {
      policy: mergePolicy(BASE_POLICY, 'strict'),
      staticData: { metrics: absent(), coverage: present(COVERAGE) },
    });
    expect(r.decisions.every((d) => d.failed.includes('DATA_GAP'))).toBe(true);
  });
});

describe('maxDrawdownPct', () => {
  it('measures peak to trough, not first to last', () => {
    expect(maxDrawdownPct([{ equity: 100 }, { equity: 120 }, { equity: 90 }, { equity: 110 }])).toBe(25);
  });
  it('is zero for a monotonically rising curve', () => {
    expect(maxDrawdownPct([{ equity: 100 }, { equity: 110 }])).toBe(0);
  });
  it('handles a single point', () => {
    expect(maxDrawdownPct([{ equity: 100 }])).toBe(0);
  });
});

describe('rendering', () => {
  it('emits standalone SVG with no external references', () => {
    const svg = renderSvg(run(TRADES_CLUSTER));
    expect(svg.startsWith('<svg')).toBe(true);
    expect(svg).not.toMatch(/https?:\/\/(?!www\.w3\.org)/);
    expect(svg).not.toContain('<script');
  });

  it('labels both curves and the drawdown delta', () => {
    const svg = renderSvg(run(TRADES_CLUSTER));
    expect(svg).toContain('without gate');
    expect(svg).toContain('with gate');
    expect(svg).toContain('max drawdown');
  });

  it('escapes a hostile title rather than injecting markup', () => {
    const svg = renderSvg(run(TRADES_CLUSTER), { title: '<script>x</script>' });
    expect(svg).not.toContain('<script>x');
    expect(svg).toContain('&lt;script&gt;');
  });

  it('tabulates every decision with its failed checks', () => {
    const txt = renderTable(run(TRADES_CLUSTER));
    expect(txt).toContain('ETH/USDT');
    expect(txt).toContain('CORRELATED_CLUSTER');
    expect(txt.split('\n').filter((l) => l.includes('USDT'))).toHaveLength(3);
  });
});
