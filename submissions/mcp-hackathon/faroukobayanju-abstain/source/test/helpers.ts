import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  absent,
  failed,
  present,
  type Coverage,
  type Equity,
  type Funding,
  type GateData,
  type GateInput,
  type Metrics,
  type OpenInterest,
  type Policy,
  type Signal,
  type Trades,
} from '../src/types.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixture = <T>(name: string): T =>
  JSON.parse(readFileSync(join(here, '..', 'fixtures', name), 'utf8')) as T;

export const METRICS = fixture<Metrics>('metrics.json');
export const SIGNAL_HOLD = fixture<Signal>('signal-hold.json');
export const TRADES_CLUSTER = fixture<Trades>('trades-cluster.json');
export const EQUITY_DRAWDOWN = fixture<Equity>('equity-drawdown.json');
export const COVERAGE = fixture<Coverage>('coverage.json');
export { BASE_POLICY } from '../src/policy/base.js';

/** The bar-50 cluster all entered at this instant. */
export const BAR_50_MS = 1781827200000;
/** After every cluster trade has closed. */
export const AFTER_CLUSTER_MS = 1782400000000;

export const buyingSignal = (timestampS: number): Signal => ({
  symbol: 'BTC/USDT',
  trade_intent: 'BUY',
  reasoning_log: 'test',
  timestamp: timestampS,
  confidence: 0.61,
});

export const goodFunding: Funding = {
  symbol: 'BTC/USDT',
  as_of_date: '2026-09-17',
  last_funding_rate: 0.0001,
};

export const hostileFunding: Funding = {
  symbol: 'BTC/USDT',
  as_of_date: '2026-09-17',
  last_funding_rate: 0.0019,
};

export const calmOi: OpenInterest = {
  symbol: 'BTC/USDT',
  as_of_date: '2026-09-17',
  open_interest: 1_000_000,
  open_interest_prev: 970_000,
};

export const shockedOi: OpenInterest = {
  symbol: 'BTC/USDT',
  as_of_date: '2026-09-17',
  open_interest: 1_000_000,
  open_interest_prev: 800_000,
};

/** An equity series with no meaningful drawdown. */
export const FLAT_EQUITY: Equity = {
  run_id: 'bt-flat',
  points: [
    { t: 1781827200000, equity: 100_000 },
    { t: 1781913600000, equity: 100_500 },
    { t: 1782000000000, equity: 100_400 },
  ],
};

/** A single closed winner, so LOSS_STREAK has something benign to read. */
export const TRADES_WINNER: Trades = {
  run_id: 'bt-win',
  trades: [
    {
      run_id: 'bt-win',
      symbol: 'ETH/USDT',
      direction: 1,
      entry_price: 1000,
      exit_price: 1100,
      size: 1,
      leverage: 1,
      pnl: 100,
      pnl_pct: 10,
      exit_reason: 'take_profit',
      holding_bars: 3,
      commission: 1,
      entry_bar_index: 1,
      exit_bar_index: 4,
      entry_ts_ms: 1781000000000,
      exit_ts_ms: 1781200000000,
    },
  ],
};

export interface Overrides {
  now?: number;
  asOf?: string;
  side?: 'BUY' | 'SELL';
  notional?: number;
  signalId?: string;
  seen?: string[];
  accountEquity?: number;
  data?: Partial<GateData>;
}

/** A fully-passing baseline. Every test perturbs exactly one thing. */
export function makeInput(o: Overrides = {}): GateInput {
  const now = o.now ?? 1789682946000 + 60_000;
  const data: GateData = {
    signal: present(buyingSignal(1789682946)),
    metrics: present({ ...METRICS, status: 'QUALIFIED_FOR_OKX_LISTING' }),
    equity: present(FLAT_EQUITY),
    trades: present(TRADES_WINNER),
    funding: present(goodFunding),
    openInterest: present(calmOi),
    // A real baseline one day back, so OI_SHOCK genuinely PASSes here
    // rather than skipping for want of something to diff against.
    openInterestPrev: present({ ...calmOi, as_of_date: '2026-09-16', open_interest: calmOi.open_interest }),
    coverage: present(COVERAGE),
    ...o.data,
  };
  return {
    asOf: o.asOf ?? '2026-09-17',
    now,
    proposal: {
      symbol: 'BTC/USDT',
      side: o.side ?? 'BUY',
      notional: o.notional ?? 15_000,
      signalId: o.signalId ?? 'sig_test_1',
    },
    data,
    seenSignalIds: new Set(o.seen ?? []),
    accountEquity: o.accountEquity ?? 100_000,
  };
}

export { absent, failed, present };
