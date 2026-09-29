import { RegimenError } from '@/lib/errors';
import type {
  EquityPoint,
  LiveSignal,
  Provenance,
  RegimeObservation,
  RegimeSeries,
  ReportedMetrics,
  SourceAdapter,
  SourceCredentials,
  Trade,
  TrackRecord,
} from '@/lib/sources/types';
import { NEXUS_SOURCE_ID, NexusClient } from './client';
import {
  coverageSchema,
  fearGreedSchema,
  fundingSchema,
  macroSchema,
  openInterestSchema,
  strategyEquitySchema,
  strategyMetricsSchema,
  strategySignalSchema,
  strategyTradesSchema,
  vcpSchema,
} from './schemas';

/**
 * Adapter mapping the OlaXBT Nexus gateway onto Regimen's domain model.
 *
 * The mapping is where vendor quirks are absorbed so the engine never sees them:
 * `max_drawdown` arrives as the string `"3.85%"`, equity timestamps arrive in
 * milliseconds while `as_of` keys are UTC calendar dates, and a trade may or may not
 * carry an exit time. Anything genuinely absent stays `null` rather than being
 * defaulted to zero — a missing funding rate and a funding rate of zero are different
 * facts, and conflating them would quietly corrupt a regime bucket.
 */

/** How many point-in-time reads to have in flight; the client's token bucket paces the rest. */
const REGIME_CONCURRENCY = 6;

/** Factors pulled per date, in the order they are displayed. */
export const REGIME_FACTOR_KEYS = [
  'vix',
  'us10y',
  'fedFunds',
  'fundingRate',
  'openInterestUsd',
  'longShortRatio',
  'fearGreed',
  'trendTemplatePassed',
] as const;

export interface NexusAdapterOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly symbol?: string;
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value.trim().replace(/%$/, ''));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Normalise an upstream timestamp to epoch milliseconds.
 * Nexus mixes second- and millisecond-precision epochs across tools, so the magnitude
 * decides: anything below ~Nov 2286 in ms is treated as seconds.
 */
export function normaliseEpoch(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) return null;
  return value < 1e11 ? Math.round(value * 1000) : Math.round(value);
}

export function utcDate(epochMs: number): string {
  return new Date(epochMs).toISOString().slice(0, 10);
}

function mapIntent(raw: string): LiveSignal['intent'] {
  const upper = raw.trim().toUpperCase();
  return upper === 'BUY' || upper === 'SELL' || upper === 'HOLD' ? upper : 'UNKNOWN';
}

/** Run `task` over `items` with bounded concurrency, preserving input order. */
async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  task: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      results[index] = await task(items[index] as T, index);
    }
  });
  await Promise.all(workers);
  return results;
}

export class NexusAdapter implements SourceAdapter {
  readonly id = NEXUS_SOURCE_ID;
  readonly displayName = 'OlaXBT Nexus';
  readonly capabilities = {
    trackRecord: true,
    regimes: true,
    liveSignal: true,
    reevaluate: true,
  } as const;

  private readonly options: NexusAdapterOptions;

  constructor(options: NexusAdapterOptions = {}) {
    this.options = options;
  }

  private client(credentials: SourceCredentials): NexusClient {
    return new NexusClient({
      apiKey: credentials.apiKey ?? '',
      ...(this.options.baseUrl ? { baseUrl: this.options.baseUrl } : {}),
      ...(this.options.fetchImpl ? { fetchImpl: this.options.fetchImpl } : {}),
    });
  }

  /**
   * The strategy's published track record.
   *
   * Equity and trades are fetched together because the analysis needs both, and
   * metrics are fetched so Regimen can contrast what Nexus reports against what the
   * equity curve actually implies.
   */
  async fetchTrackRecord(credentials: SourceCredentials): Promise<TrackRecord> {
    const client = this.client(credentials);
    const provenance: Provenance[] = [];

    const [equityResult, tradesResult, metricsResult] = await Promise.all([
      client.call('get_strategy_equity', {}, strategyEquitySchema),
      client.call('get_strategy_trades', {}, strategyTradesSchema).catch((error: unknown) => {
        // A strategy with no filled trades is a valid state, not a failure: the
        // equity curve alone still supports the significance analysis.
        if (error instanceof RegimenError && error.code === 'upstream_not_published') return null;
        throw error;
      }),
      client.call('get_strategy_metrics', {}, strategyMetricsSchema).catch((error: unknown) => {
        if (error instanceof RegimenError && error.code === 'upstream_not_published') return null;
        throw error;
      }),
    ]);

    provenance.push(equityResult.provenance);
    if (tradesResult) provenance.push(tradesResult.provenance);
    if (metricsResult) provenance.push(metricsResult.provenance);

    const equity: EquityPoint[] = [];
    for (const point of equityResult.value.points) {
      const t = normaliseEpoch(point.t);
      const value = point.equity;
      if (t === null || value === null) continue;
      equity.push({ t, equity: value });
    }

    if (equity.length === 0) {
      throw new RegimenError('insufficient_sample', 'Nexus returned an empty equity curve for this strategy.', {
        details: { pointsReturned: equityResult.value.points.length },
        remedy: 'Run a Fire Backtest in Nexus Studio so the strategy publishes an equity curve, then retry.',
      });
    }

    const trades: Trade[] = [];
    for (const raw of tradesResult?.value.trades ?? []) {
      const pnl = raw.pnl;
      if (pnl === null) continue;
      const exitedAt = normaliseEpoch(raw.exit_time ?? raw.timestamp ?? null);
      trades.push({
        symbol: raw.symbol ?? this.options.symbol ?? 'UNKNOWN',
        pnl,
        ...(exitedAt !== null ? { exitedAt } : {}),
        ...(raw.entry_price !== null ? { entryPrice: raw.entry_price } : {}),
        ...(raw.exit_price !== null ? { exitPrice: raw.exit_price } : {}),
        ...(raw.holding_bars !== null ? { holdingBars: raw.holding_bars } : {}),
        ...(raw.exit_reason ? { exitReason: raw.exit_reason } : {}),
      });
    }

    const reported: ReportedMetrics | undefined = metricsResult
      ? {
          ...(metricsResult.value.sharpe_ratio !== null ? { sharpeRatio: metricsResult.value.sharpe_ratio } : {}),
          ...(metricsResult.value.trading_period_days !== null
            ? { tradingPeriodDays: metricsResult.value.trading_period_days }
            : {}),
          ...(metricsResult.value.estimated_aum_usdt !== null
            ? { estimatedAumUsdt: metricsResult.value.estimated_aum_usdt }
            : {}),
          ...(metricsResult.value.profit_factor !== null ? { profitFactor: metricsResult.value.profit_factor } : {}),
          ...(toFiniteNumber(metricsResult.value.max_drawdown) !== null
            ? // Reported as a percentage string; normalised to a fraction here.
              { maxDrawdown: (toFiniteNumber(metricsResult.value.max_drawdown) as number) / 100 }
            : {}),
          ...(metricsResult.value.total_return_pct !== null
            ? { totalReturnPct: metricsResult.value.total_return_pct }
            : {}),
          ...(metricsResult.value.win_rate_pct !== null ? { winRatePct: metricsResult.value.win_rate_pct } : {}),
          ...(metricsResult.value.trade_count !== null ? { tradeCount: metricsResult.value.trade_count } : {}),
          ...(metricsResult.value.status ? { status: metricsResult.value.status } : {}),
        }
      : undefined;

    return {
      sourceId: this.id,
      label: equityResult.value.run_id ?? 'nexus-strategy',
      equity,
      trades,
      ...(reported ? { reported } : {}),
      provenance,
    };
  }

  /** The dates Nexus can answer point-in-time questions about. */
  async fetchCoverage(credentials: SourceCredentials): Promise<{ minDate: string; maxDate: string }> {
    const client = this.client(credentials);
    const { value } = await client.call('get_historical_coverage', {}, coverageSchema);
    return { minDate: value.min_date, maxDate: value.max_date };
  }

  /**
   * Market conditions on each requested date.
   *
   * Every factor is read with an explicit `as_of`, so this is point-in-time data and
   * carries no lookahead: the analysis only ever sees what was knowable on the day.
   * A factor that fails to load is recorded as `null` with the failure noted, rather
   * than aborting the whole map — one missing VIX print should not destroy a
   * hundred-day attribution.
   */
  async fetchRegimes(dates: readonly string[], credentials: SourceCredentials): Promise<RegimeSeries> {
    const client = this.client(credentials);
    const symbol = this.options.symbol ?? 'BTC/USDT';

    const observations = await mapWithConcurrency(dates, REGIME_CONCURRENCY, async (date) => {
      const factors: Record<string, number | string | null> = Object.fromEntries(
        REGIME_FACTOR_KEYS.map((key) => [key, null]),
      );
      const provenance: Provenance[] = [];

      const settled = await Promise.allSettled([
        client.call('get_macro', { as_of: date }, macroSchema),
        client.call('get_historical_funding', { as_of: date, symbol }, fundingSchema),
        client.call('get_open_interest', { as_of: date, symbol }, openInterestSchema),
        client.call('get_fear_greed', { as_of: date }, fearGreedSchema),
        client.call('get_vcp', { as_of: date, symbol }, vcpSchema),
      ]);

      const [macro, funding, openInterest, fearGreed, vcp] = settled;

      if (macro.status === 'fulfilled') {
        const bag = (macro.value.value.macro ?? {}) as Record<string, unknown>;
        factors['vix'] = toFiniteNumber(bag['vix']);
        factors['us10y'] = toFiniteNumber(bag['us_10y_yield_pct']);
        factors['fedFunds'] = toFiniteNumber(bag['effective_fed_funds_pct']);
        provenance.push(macro.value.provenance);
      }
      if (funding.status === 'fulfilled') {
        factors['fundingRate'] = funding.value.value.last_funding_rate;
        provenance.push(funding.value.provenance);
      }
      if (openInterest.status === 'fulfilled') {
        factors['openInterestUsd'] = openInterest.value.value.open_interest_usd;
        factors['longShortRatio'] = openInterest.value.value.long_short_ratio;
        provenance.push(openInterest.value.provenance);
      }
      if (fearGreed.status === 'fulfilled') {
        factors['fearGreed'] = fearGreed.value.value.fear_greed;
        provenance.push(fearGreed.value.provenance);
      }
      if (vcp.status === 'fulfilled') {
        const passed = vcp.value.value.passed?.length ?? null;
        factors['trendTemplatePassed'] = passed;
        provenance.push(vcp.value.provenance);
      }

      return { date, factors, provenance } satisfies RegimeObservation;
    });

    return {
      sourceId: this.id,
      observations,
      factorKeys: [...REGIME_FACTOR_KEYS],
    };
  }

  async fetchLiveSignal(symbol: string, credentials: SourceCredentials): Promise<LiveSignal> {
    const client = this.client(credentials);
    const { value, provenance } = await client.call('get_strategy_signal', { symbol }, strategySignalSchema);
    const observedAt = normaliseEpoch(value.timestamp) ?? Date.now();
    return {
      symbol: value.symbol,
      intent: mapIntent(value.trade_intent),
      ...(value.reasoning_log ? { rationale: value.reasoning_log } : {}),
      observedAt,
      provenance,
    };
  }
}
