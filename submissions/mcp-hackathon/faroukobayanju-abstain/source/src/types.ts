/**
 * Core types for the Abstain gate.
 *
 *   signal ──▶ [ 10 pure checks ] ──▶ verdict ──▶ receipt
 *                     │
 *                     ├─ any FAIL        ⇒ ABSTAIN
 *                     ├─ trade_intent    ⇒ NO_TRADE (short-circuits before gating)
 *                     │  == "HOLD"
 *                     └─ all PASS/SKIPPED ⇒ EXECUTE
 *
 * Every check is a pure function of (input, policy). No I/O, no clock, no
 * randomness — `now` and `asOf` are injected so a decision is replayable.
 */

export type Verdict = 'EXECUTE' | 'ABSTAIN' | 'NO_TRADE';

export type CheckVerdict = 'PASS' | 'FAIL' | 'SKIPPED';

export const CHECK_IDS = [
  'SIGNAL_STALE',
  'SIGNAL_SUPPORT',
  'NOT_QUALIFIED',
  'FUNDING_REGIME',
  'OI_SHOCK',
  'DRAWDOWN_BUDGET',
  'CORRELATED_CLUSTER',
  'LOSS_STREAK',
  'DATA_GAP',
  'SIZE_BOUND',
  'DUPLICATE',
] as const;

export type CheckId = (typeof CHECK_IDS)[number];

/**
 * Why a datum is not usable. `absent` and `failed` are deliberately distinct:
 * "Nexus has no OI snapshot for this date" and "the OI call timed out" are
 * different facts, and a receipt that blurs them is less honest than one that
 * does not. Both still fail closed via DATA_GAP.
 */
export type SourceOutcome = 'ok' | 'absent' | 'failed';

export interface SourceRef {
  call: string;
  outcome: SourceOutcome;
  /** Error class name when outcome === 'failed'. */
  error?: string;
}

export interface CheckResult {
  id: CheckId;
  verdict: CheckVerdict;
  observed: number | string | null;
  threshold: number | string | null;
  unit: string | null;
  source: SourceRef | null;
  /** Present when verdict is SKIPPED, or when FAIL needs more than numbers. */
  reason?: string;
  /** Extra evidence a reviewer needs to trust the number (e.g. equity sample size). */
  detail?: Record<string, unknown>;
}

/** A datum that was fetched successfully, or an explanation of why it was not. */
export type Datum<T> =
  | { ok: true; value: T }
  | { ok: false; outcome: 'absent' | 'failed'; error?: string };

export const absent = <T>(): Datum<T> => ({ ok: false, outcome: 'absent' });
export const failed = <T>(error: string): Datum<T> => ({ ok: false, outcome: 'failed', error });
export const present = <T>(value: T): Datum<T> => ({ ok: true, value });

// ---------------------------------------------------------------------------
// Nexus payload shapes (post-envelope-unwrap; see src/nexus/client.ts)
// ---------------------------------------------------------------------------

export type TradeIntent = 'BUY' | 'SELL' | 'HOLD';

export interface Signal {
  symbol: string;
  trade_intent: TradeIntent;
  reasoning_log: string;
  /** Unix SECONDS, not milliseconds. */
  timestamp: number;
  /** Undocumented in catalog.json but present in live responses. */
  confidence?: number;
}

export interface Metrics {
  sharpe_ratio: number;
  trading_period_days: number;
  estimated_aum_usdt: number;
  profit_factor: number;
  /** Percent STRING, e.g. "7.62%". Other percentages on this object are numbers. */
  max_drawdown: string;
  total_return_pct: number;
  win_rate_pct: number;
  trade_count: number;
  status: 'QUALIFIED_FOR_OKX_LISTING' | 'NOT_QUALIFIED';
}

export interface EquityPoint {
  /** Milliseconds epoch. */
  t: number;
  equity: number;
}

export interface Equity {
  run_id: string;
  points: EquityPoint[];
}

export interface Trade {
  run_id: string;
  symbol: string;
  /** 1 = long, -1 = short. */
  direction: number;
  entry_price: number;
  exit_price: number;
  size: number;
  leverage: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  holding_bars: number;
  commission: number;
  entry_bar_index: number;
  exit_bar_index: number;
  entry_ts_ms: number;
  exit_ts_ms: number;
}

export interface Trades {
  run_id: string;
  trades: Trade[];
}

export interface Funding {
  symbol: string;
  as_of_date: string;
  last_funding_rate: number;
}

export interface OpenInterest {
  symbol: string;
  as_of_date: string;
  open_interest: number;
  /** Previous snapshot's open interest, when the gateway supplies it. */
  open_interest_prev?: number;
  long_short_ratio?: number;
}

/**
 * catalog.json documents only "Available historical snapshot date range" and
 * does not pin the field names, so every field is optional and resolveAsOf()
 * probes the plausible spellings.
 */
export interface Coverage {
  /** Observed live shape: {first, last}. */
  first?: string;
  last?: string;
  start?: string;
  end?: string;
  end_date?: string;
  latest?: string;
  to?: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Gate input
// ---------------------------------------------------------------------------

export interface Proposal {
  symbol: string;
  side: 'BUY' | 'SELL';
  /** Quote-currency notional of the proposed position. */
  notional: number;
  signalId: string;
}

export interface GateData {
  signal: Datum<Signal>;
  metrics: Datum<Metrics>;
  equity: Datum<Equity>;
  trades: Datum<Trades>;
  funding: Datum<Funding>;
  openInterest: Datum<OpenInterest>;
  /** Previous UTC day, so OI_SHOCK can diff without a gateway-supplied baseline. */
  openInterestPrev: Datum<OpenInterest>;
  coverage: Datum<Coverage>;
}

export interface GateInput {
  /** Resolved UTC date (YYYY-MM-DD) that #3/#4 were fetched for. Recorded in the receipt. */
  asOf: string;
  /** Milliseconds epoch. Injected so SIGNAL_STALE is deterministic under test. */
  now: number;
  proposal: Proposal;
  data: GateData;
  /** Signal ids already committed to the receipt chain. */
  seenSignalIds: ReadonlySet<string>;
  /** Total account equity, for the single-symbol sub-condition of CORRELATED_CLUSTER. */
  accountEquity: number;
}

export interface Policy {
  max_signal_age_s: number;
  require_qualified: boolean;
  /** Refuse when the strategy signal does not back the proposed side. */
  require_signal_support: boolean;
  /** Refuse when any required datum is missing or the window is uncovered. */
  require_data_complete: boolean;
  max_funding_rate: number;
  max_oi_delta_pct: number;
  max_drawdown_pct: number;
  max_cluster_size: number;
  max_symbol_pct: number;
  max_loss_streak: number;
  min_notional: number;
  max_notional: number;
}

export interface GateOutcome {
  verdict: Verdict;
  checks: CheckResult[];
  asOf: string;
  reason?: string;
}
