/**
 * The source-agnostic domain model.
 *
 * Everything downstream — the statistics, the regime attribution, the MCP tools —
 * is written against these types and never against a vendor's response shape. A data
 * source is therefore a thin adapter: it produces a `TrackRecord` and, if it can, a
 * `RegimeSeries`. That is what makes OlaXBT Nexus one source rather than the only one,
 * and it is what lets the same engine judge a track record pasted in by hand.
 */

/** A point on an equity curve. `t` is epoch milliseconds, UTC. */
export interface EquityPoint {
  readonly t: number;
  readonly equity: number;
}

export interface Trade {
  readonly symbol: string;
  readonly pnl: number;
  /** Epoch ms of the exit, when the source reports it. */
  readonly exitedAt?: number;
  readonly entryPrice?: number;
  readonly exitPrice?: number;
  readonly holdingBars?: number;
  readonly exitReason?: string;
}

/**
 * Performance figures as the SOURCE reports them.
 *
 * Kept separate from anything we compute, on purpose. Regimen recomputes every figure
 * from the raw equity curve and reports the divergence; a dashboard number and a
 * number derived from the curve disagreeing is itself a finding worth surfacing.
 */
export interface ReportedMetrics {
  readonly sharpeRatio?: number;
  readonly tradingPeriodDays?: number;
  readonly estimatedAumUsdt?: number;
  readonly profitFactor?: number;
  readonly maxDrawdown?: number;
  readonly totalReturnPct?: number;
  readonly winRatePct?: number;
  readonly tradeCount?: number;
  readonly status?: string;
}

/** Where a single number came from, so every claim can be traced back to a call. */
export interface Provenance {
  /** Source adapter id, e.g. `olaxbt-nexus`. */
  readonly source: string;
  /** The upstream operation, e.g. `get_macro`. */
  readonly operation: string;
  /** The point-in-time key the upstream was asked for, when it takes one. */
  readonly asOf?: string;
  /** When we performed the call (ISO 8601). */
  readonly fetchedAt: string;
  /** True when served from our immutable cache rather than a fresh call. */
  readonly cached: boolean;
}

export interface TrackRecord {
  readonly sourceId: string;
  /** Opaque, non-identifying label for the strategy, safe to show. */
  readonly label: string;
  readonly equity: readonly EquityPoint[];
  readonly trades: readonly Trade[];
  readonly reported?: ReportedMetrics;
  readonly provenance: readonly Provenance[];
}

/** A named market condition observed at a single UTC date. */
export interface RegimeObservation {
  /** UTC calendar date, `YYYY-MM-DD`. */
  readonly date: string;
  /**
   * Factor values at that date. `null` means the source had no value — which is
   * different from zero and must never be coerced into one.
   */
  readonly factors: Readonly<Record<string, number | string | null>>;
  readonly provenance: readonly Provenance[];
}

export interface RegimeSeries {
  readonly sourceId: string;
  readonly observations: readonly RegimeObservation[];
  /** Factors this series actually carries, in display order. */
  readonly factorKeys: readonly string[];
}

/** The live trading intent a source publishes, if it publishes one. */
export interface LiveSignal {
  readonly symbol: string;
  readonly intent: 'BUY' | 'SELL' | 'HOLD' | 'UNKNOWN';
  readonly rationale?: string;
  readonly observedAt: number;
  readonly provenance: Provenance;
}

export interface SourceCredentials {
  /** Vendor API key supplied by the caller. Never logged, never stored. */
  readonly apiKey?: string;
}

/**
 * A data source.
 *
 * `capabilities` is deliberately explicit: the engine asks what a source can do
 * rather than probing and catching, so an unsupported feature is a clear refusal
 * instead of a mystery failure halfway through an analysis.
 */
export interface SourceAdapter {
  readonly id: string;
  readonly displayName: string;
  readonly capabilities: {
    readonly trackRecord: boolean;
    readonly regimes: boolean;
    readonly liveSignal: boolean;
    /** Can re-run the strategy over a different evaluation window. */
    readonly reevaluate: boolean;
  };

  fetchTrackRecord(credentials: SourceCredentials): Promise<TrackRecord>;
  fetchRegimes?(dates: readonly string[], credentials: SourceCredentials): Promise<RegimeSeries>;
  fetchLiveSignal?(symbol: string, credentials: SourceCredentials): Promise<LiveSignal>;
}
