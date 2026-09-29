/**
 * Parallel fan-out with a short TTL cache, and `as_of` resolution.
 *
 * Ten checks need seven distinct Nexus calls. Run sequentially with fail-closed
 * semantics, a single flaky call turns the whole evaluation into a refusal:
 * seven calls at 99% availability is ~93% end to end, roughly one spurious
 * refusal in fourteen. On a product whose entire claim is that its refusals
 * mean something, a spurious refusal is worse than an outage.
 *
 *   resolve as_of ◀── get_historical_coverage (cached)
 *          │
 *          ├─ allSettled ─┬─ get_strategy_signal(symbol)
 *          │              ├─ get_strategy_metrics        (cached)
 *          │              ├─ get_strategy_equity         (cached)
 *          │              ├─ get_strategy_trades         (cached)
 *          │              ├─ get_historical_funding(as_of, symbol)
 *          │              └─ get_open_interest(as_of, symbol)
 *          ▼
 *      GateData
 *
 * Metrics, equity and trades only change when a backtest runs; coverage changes
 * daily. Caching them is safe and collapses repeat fetches across a reviewer's
 * session.
 */
import type { NexusClient } from './client.js';
import {
  failed,
  type Coverage,
  type Datum,
  type Equity,
  type Funding,
  type GateData,
  type Metrics,
  type OpenInterest,
  type Signal,
  type Trades,
} from '../types.js';

export interface CacheEntry {
  at: number;
  value: Datum<unknown>;
}

export class TtlCache {
  private readonly map = new Map<string, CacheEntry>();
  constructor(
    private readonly ttlMs: number,
    private readonly clock: () => number = Date.now,
  ) {}

  get<T>(key: string): Datum<T> | undefined {
    const hit = this.map.get(key);
    if (!hit) return undefined;
    if (this.clock() - hit.at > this.ttlMs) {
      this.map.delete(key);
      return undefined;
    }
    return hit.value as Datum<T>;
  }

  set<T>(key: string, value: Datum<T>): void {
    // Never cache a failure: a transient 502 must not pin a refusal for 60s.
    if (!value.ok && value.outcome === 'failed') return;
    this.map.set(key, { at: this.clock(), value });
  }

  clear(): void {
    this.map.clear();
  }
}

async function cached<T>(
  cache: TtlCache,
  key: string,
  fn: () => Promise<Datum<T>>,
): Promise<Datum<T>> {
  const hit = cache.get<T>(key);
  if (hit) return hit;
  const value = await fn();
  cache.set(key, value);
  return value;
}

/** allSettled semantics: a thrown promise becomes a named failure, never a crash. */
async function settle<T>(p: Promise<Datum<T>>): Promise<Datum<T>> {
  try {
    return await p;
  } catch (err) {
    return failed<T>((err as Error).name || 'NexusParseError');
  }
}

/**
 * Pick the date that #3 and #4 are fetched for.
 *
 * These tools require `as_of` and serve daily snapshots. Asking for today
 * before today's snapshot is published returns nothing, DATA_GAP fails, and the
 * gate can never return EXECUTE. So ask coverage what exists rather than
 * assuming a publishing schedule — and record the answer in the receipt, so a
 * reviewer can re-fetch the same date and reproduce the observed values.
 */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Coverage field names are not pinned by catalog.json, which documents only
 * "Available historical snapshot date range". Accept the plausible spellings,
 * and if none yields a real YYYY-MM-DD, fall back to today rather than letting
 * `undefined` propagate into get_historical_funding(as_of) — that produced a
 * receipt with no as_of at all, which is worse than a wrong date because it is
 * silent.
 */
export function resolveAsOf(coverage: Datum<Coverage>, fallbackIso: string): string {
  if (!coverage.ok) return fallbackIso;
  const v = coverage.value as unknown as Record<string, unknown>;
  // The live gateway uses {first, last}. Guessing spellings was the bug;
  // these are now ordered with the observed one first.
  for (const key of ['last', 'end', 'end_date', 'latest', 'to', 'max_date']) {
    const candidate = v[key];
    if (typeof candidate === 'string' && ISO_DATE.test(candidate.slice(0, 10))) {
      return candidate.slice(0, 10);
    }
  }
  return fallbackIso;
}

/** The UTC day before an ISO date. get_open_interest serves daily snapshots. */
export function previousIso(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

export function todayIso(now: number): string {
  return new Date(now).toISOString().slice(0, 10);
}

export interface FetchAllResult {
  asOf: string;
  data: GateData;
}

export async function fetchAll(
  client: NexusClient,
  symbol: string,
  now: number,
  cache: TtlCache,
): Promise<FetchAllResult> {
  const coverage = await settle(
    cached<Coverage>(cache, 'coverage', () => client.call<Coverage>('get_historical_coverage')),
  );
  const asOf = resolveAsOf(coverage, todayIso(now));

  const prevIso = previousIso(asOf);

  const [signal, metrics, equity, trades, funding, openInterest, openInterestPrev] = await Promise.all([
    settle(client.call<Signal>('get_strategy_signal', { symbol })),
    settle(cached<Metrics>(cache, 'metrics', () => client.call<Metrics>('get_strategy_metrics'))),
    settle(cached<Equity>(cache, 'equity', () => client.call<Equity>('get_strategy_equity'))),
    settle(cached<Trades>(cache, 'trades', () => client.call<Trades>('get_strategy_trades'))),
    settle(client.call<Funding>('get_historical_funding', { as_of: asOf, symbol })),
    settle(client.call<OpenInterest>('get_open_interest', { as_of: asOf, symbol })),
    // The gateway does not return a baseline, so fetch one. Cached like the
    // rest: yesterday's snapshot never changes.
    settle(
      cached<OpenInterest>(cache, `oi:${symbol}:${prevIso}`, () =>
        client.call<OpenInterest>('get_open_interest', { as_of: prevIso, symbol }),
      ),
    ),
  ]);

  return { asOf, data: { signal, metrics, equity, trades, funding, openInterest, openInterestPrev, coverage } };
}
