/**
 * Named error classes for every documented Nexus failure.
 *
 * catalog.json publishes these codes:
 *   401  missing, unknown, or revoked X-API-KEY
 *   400  bad arguments (e.g. missing `symbol`)
 *   404  unknown tool OR metrics/signal not published yet   ← two facts, one code
 *   429  too many concurrent backtests
 *   502  gateway cannot reach the strategy engine
 *
 * No catch-all anywhere. Every branch names a class, and the class name lands
 * in the receipt so `NexusTimeoutError` and `NexusAuthError` stay distinguishable
 * in the evidence chain.
 */
export class NexusError extends Error {
  constructor(
    message: string,
    readonly tool: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = new.target.name;
  }
}

/** 401 — key missing, unknown, or revoked. Never retried; retrying a bad key is noise. */
export class NexusAuthError extends NexusError {}

/** 400 — malformed arguments, e.g. get_strategy_signal without `symbol`. Never retried. */
export class NexusBadRequestError extends NexusError {}

/** 404 on a tool we know exists: the strategy has not published this datum yet. */
export class NexusNotPublishedError extends NexusError {}

/** 404 on a tool the gateway does not know. A bug in our call, not a data gap. */
export class NexusUnknownToolError extends NexusError {}

/** 429 — concurrent backtest limit. Retried once after a backoff. */
export class NexusRateLimitError extends NexusError {}

/** 5xx — gateway cannot reach the strategy engine. Retried once. */
export class NexusUpstreamError extends NexusError {}

/** Network timeout or abort. Retried twice with backoff. */
export class NexusTimeoutError extends NexusError {}

/** Body was not JSON, or the envelope was malformed. Never retried. */
export class NexusParseError extends NexusError {}

/** Retry budget per error class. Anything absent from this map is not retried. */
export const RETRIES: Record<string, number> = {
  NexusTimeoutError: 2,
  NexusRateLimitError: 1,
  NexusUpstreamError: 1,
};

/**
 * A 404 means "not published yet" only for tools the gateway actually serves.
 * Checked against the live /tools listing so a typo in a tool name surfaces as
 * a bug (NexusUnknownToolError) rather than hiding as a data gap.
 */
export const KNOWN_TOOLS = new Set([
  'get_strategy_signal',
  'get_strategy_metrics',
  'get_strategy_equity',
  'get_strategy_trades',
  'run_backtest',
  'get_backtest_job',
  'get_historical_ohlcv',
  'get_historical_funding',
  'get_open_interest',
  'get_vcp',
  'get_macro',
  'get_market_snapshot',
  'get_historical_coverage',
  'get_etf_flow',
  'get_oi_ranking',
  'get_fear_greed',
  'get_news',
  'get_sentiment',
]);

/**
 * Map an HTTP status to its error class.
 *
 *   404 ──┬─ tool is known   ──▶ NexusNotPublishedError  (a data ABSENCE)
 *         └─ tool is unknown ──▶ NexusUnknownToolError   (a call FAILURE)
 */
export function classify(status: number, tool: string, detail: string): NexusError {
  switch (status) {
    case 401:
      return new NexusAuthError(`unauthorized calling ${tool}: ${detail}`, tool, status);
    case 400:
      return new NexusBadRequestError(`bad arguments for ${tool}: ${detail}`, tool, status);
    case 404:
      return KNOWN_TOOLS.has(tool)
        ? new NexusNotPublishedError(`${tool} has no published data yet`, tool, status)
        : new NexusUnknownToolError(`gateway does not serve tool ${tool}`, tool, status);
    case 429:
      return new NexusRateLimitError(`rate limited calling ${tool}`, tool, status);
    default:
      if (status >= 500) {
        return new NexusUpstreamError(`gateway error ${status} calling ${tool}: ${detail}`, tool, status);
      }
      return new NexusParseError(`unexpected status ${status} calling ${tool}: ${detail}`, tool, status);
  }
}
