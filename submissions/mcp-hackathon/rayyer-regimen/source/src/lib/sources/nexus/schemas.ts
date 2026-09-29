import { z } from 'zod';

/**
 * Response shapes for the OlaXBT Nexus MCP gateway.
 *
 * Every object schema here is LOOSE on purpose. These describe a third-party service
 * we do not control: a vendor adding a field must not break an analysis, while a
 * vendor removing a field we depend on must fail loudly and name the field. So the
 * required set is exactly what the engine reads, and everything else passes through.
 *
 * Numbers are coerced from strings where the published examples are inconsistent
 * about it (`max_drawdown` is documented as `"3.85%"`, for instance), and the parsing
 * is explicit rather than a blanket `z.coerce` so a genuinely unparseable value
 * surfaces as `null` instead of `NaN`.
 *
 * Tool inventory and example payloads: https://nexus.olaxbt.xyz/api/mcp/docs/catalog.json
 */

/** Accepts a number, a numeric string, or a percent string such as `"3.85%"`. */
const loose_number = z
  .union([z.number(), z.string()])
  .nullish()
  .transform((value) => {
    if (value === null || value === undefined) return null;
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    const cleaned = value.trim().replace(/%$/, '');
    if (cleaned === '') return null;
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  });

/** True when the documented value is a percentage string like `"3.85%"`. */
export function isPercentString(value: unknown): boolean {
  return typeof value === 'string' && /%\s*$/.test(value);
}

export const strategySignalSchema = z.looseObject({
  symbol: z.string(),
  trade_intent: z.string(),
  reasoning_log: z.string().nullish(),
  confidence: loose_number,
  timestamp: loose_number,
});

export const strategyMetricsSchema = z.looseObject({
  sharpe_ratio: loose_number,
  trading_period_days: loose_number,
  estimated_aum_usdt: loose_number,
  profit_factor: loose_number,
  max_drawdown: z.union([z.number(), z.string()]).nullish(),
  total_return_pct: loose_number,
  win_rate_pct: loose_number,
  trade_count: loose_number,
  status: z.string().nullish(),
});

export const equityPointSchema = z.looseObject({
  t: loose_number,
  equity: loose_number,
});

export const strategyEquitySchema = z.looseObject({
  run_id: z.string().nullish(),
  points: z.array(equityPointSchema),
});

export const tradeSchema = z.looseObject({
  symbol: z.string().nullish(),
  pnl: loose_number,
  entry_price: loose_number,
  exit_price: loose_number,
  holding_bars: loose_number,
  exit_reason: z.string().nullish(),
  exit_time: loose_number,
  timestamp: loose_number,
});

export const strategyTradesSchema = z.looseObject({
  run_id: z.string().nullish(),
  trades: z.array(tradeSchema),
});

export const backtestStartSchema = z.looseObject({
  run_id: z.string(),
  status: z.string().nullish(),
});

export const backtestJobSchema = z.looseObject({
  run_id: z.string().nullish(),
  status: z.string(),
  step: loose_number,
  total_steps: loose_number,
  trade_count: loose_number,
  equity: loose_number,
});

export const macroSchema = z.looseObject({
  as_of_date: z.string().nullish(),
  macro: z.looseObject({}).nullish(),
});

export const fundingSchema = z.looseObject({
  symbol: z.string().nullish(),
  as_of_date: z.string().nullish(),
  last_funding_rate: loose_number,
});

export const openInterestSchema = z.looseObject({
  symbol: z.string().nullish(),
  as_of_date: z.string().nullish(),
  open_interest_usd: loose_number,
  long_short_ratio: loose_number,
});

export const vcpSchema = z.looseObject({
  symbol: z.string().nullish(),
  as_of_date: z.string().nullish(),
  passed: z.array(z.string()).nullish(),
  failed: z.array(z.string()).nullish(),
});

export const fearGreedSchema = z.looseObject({
  as_of_date: z.string().nullish(),
  fear_greed: loose_number,
  fear_greed_label: z.string().nullish(),
});

export const ohlcvSchema = z.looseObject({
  symbol: z.string().nullish(),
  as_of_date: z.string().nullish(),
  last_close: loose_number,
  last_funding_rate: loose_number,
  indicators: z.looseObject({}).nullish(),
  candles: z.array(z.looseObject({})).nullish(),
  candle_count: loose_number,
});

export const coverageSchema = z.looseObject({
  min_date: z.string(),
  max_date: z.string(),
});

export type StrategySignal = z.infer<typeof strategySignalSchema>;
export type StrategyMetrics = z.infer<typeof strategyMetricsSchema>;
export type StrategyEquity = z.infer<typeof strategyEquitySchema>;
export type StrategyTrades = z.infer<typeof strategyTradesSchema>;
export type BacktestJob = z.infer<typeof backtestJobSchema>;
export type Coverage = z.infer<typeof coverageSchema>;
