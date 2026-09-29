/**
 * Turning a raw equity curve into a clean return series, and working out how
 * often that series is sampled.
 *
 * This is the module that touches the messiest data in the product. Real
 * uploaded track records arrive out of order, with duplicate timestamps from a
 * retried write, with a zero equity row from a broker outage, and at irregular
 * spacing. None of that is an exception — it is the normal case — so nothing
 * here throws. Rows that cannot be used are dropped and *reported*, so the UI
 * can tell the user exactly what was ignored.
 */

import { at, median } from './internal';

/** A single point on an equity curve. */
export interface EquityPoint {
  /** Timestamp in epoch milliseconds. */
  readonly t: number;
  /** Account equity at `t`. Must be finite and strictly positive. */
  readonly equity: number;
}

/** Why a raw point (or a derived return) was excluded. */
export type DropReasonCode =
  /** `t` was `NaN` or `±Infinity`. */
  | 'non_finite_timestamp'
  /** `equity` was `NaN` or `±Infinity`. */
  | 'non_finite_equity'
  /** `equity` was zero or negative, so a ratio to it is undefined. */
  | 'non_positive_equity'
  /** An earlier point shared this timestamp; the last one in input order wins. */
  | 'duplicate_timestamp'
  /** The period return itself overflowed to a non-finite value. */
  | 'non_finite_return';

/** A dropped row, with enough context to show the user which one it was. */
export interface DropReason {
  /** Index in the ORIGINAL input array, so the UI can highlight the offending row. */
  readonly index: number;
  /** The timestamp as supplied (may itself be non-finite). */
  readonly t: number;
  readonly code: DropReasonCode;
  readonly message: string;
}

/** Simple (arithmetic) or logarithmic period returns. */
export type ReturnKind = 'simple' | 'log';

/** Options for {@link toReturns}. */
export interface ToReturnsOptions {
  /**
   * `'simple'` → `eᵢ₊₁/eᵢ − 1`; `'log'` → `ln(eᵢ₊₁/eᵢ)`.
   *
   * Simple returns compound multiplicatively and are what the drawdown and
   * regime-attribution code assumes; log returns are additive and are the right
   * input when you intend to sum across periods.
   */
  readonly kind: ReturnKind;
}

/** A cleaned return series plus the audit trail of what was discarded. */
export interface ReturnSeries {
  readonly kind: ReturnKind;
  readonly returns: number[];
  /**
   * `timestamps[i]` is the timestamp at the **END** of the period that produced
   * `returns[i]` — i.e. the `t` of the *later* of the two equity points.
   *
   * This convention is load-bearing. The regime-attribution engine joins a
   * return to the market state that was observable when the period closed; if
   * these were the opening timestamps, every return would be attributed to the
   * regime one period early and the whole conditional analysis would be
   * shifted. `timestamps.length === returns.length` always.
   */
  readonly timestamps: number[];
  readonly dropped: DropReason[];
  /** Count of usable equity points after cleaning (always `returns.length + 1`, or 0). */
  readonly usablePoints: number;
}

/**
 * Convert an equity curve to a period return series.
 *
 * Pipeline, in order:
 *  1. reject points with non-finite `t`, non-finite `equity`, or `equity ≤ 0`;
 *  2. sort by `t` ascending, stably (ties keep input order);
 *  3. collapse exact duplicate timestamps, **keeping the last one in input
 *     order** — a duplicate is almost always a corrected re-write of the same
 *     bar, and the correction is the one that arrived last;
 *  4. difference adjacent points into returns;
 *  5. drop any return that is still non-finite (only reachable via float
 *     overflow on an absurd equity ratio).
 *
 * Never throws. An empty or entirely invalid input yields an empty series with
 * every rejection listed in `dropped`.
 */
export function toReturns(
  points: readonly EquityPoint[],
  options: ToReturnsOptions,
): ReturnSeries {
  const kind = options.kind;
  const dropped: DropReason[] = [];
  const kept: Array<{ t: number; equity: number; index: number }> = [];

  for (let i = 0; i < points.length; i += 1) {
    const point = points[i];
    if (point === undefined) continue;
    if (!Number.isFinite(point.t)) {
      dropped.push({
        index: i,
        t: point.t,
        code: 'non_finite_timestamp',
        message: 'Timestamp is not a finite epoch-millisecond value.',
      });
      continue;
    }
    if (!Number.isFinite(point.equity)) {
      dropped.push({
        index: i,
        t: point.t,
        code: 'non_finite_equity',
        message: 'Equity is not a finite number.',
      });
      continue;
    }
    if (point.equity <= 0) {
      dropped.push({
        index: i,
        t: point.t,
        code: 'non_positive_equity',
        message: 'Equity must be strictly positive; a return relative to zero or negative equity is undefined.',
      });
      continue;
    }
    kept.push({ t: point.t, equity: point.equity, index: i });
  }

  // Decorate-sort-undecorate on (t, original index). Array#sort has been
  // required to be stable since ES2019, but tie-breaking explicitly makes the
  // "last duplicate wins" rule below independent of that guarantee.
  kept.sort((a, b) => (a.t === b.t ? a.index - b.index : a.t - b.t));

  const deduped: Array<{ t: number; equity: number; index: number }> = [];
  for (const entry of kept) {
    const previous = deduped[deduped.length - 1];
    if (previous !== undefined && previous.t === entry.t) {
      dropped.push({
        index: previous.index,
        t: previous.t,
        code: 'duplicate_timestamp',
        message: 'Duplicate timestamp superseded by a later row with the same timestamp.',
      });
      deduped[deduped.length - 1] = entry;
      continue;
    }
    deduped.push(entry);
  }

  const returns: number[] = [];
  const timestamps: number[] = [];
  for (let i = 1; i < deduped.length; i += 1) {
    const previous = deduped[i - 1];
    const current = deduped[i];
    if (previous === undefined || current === undefined) continue;
    const ratio = current.equity / previous.equity;
    const value = kind === 'log' ? Math.log(ratio) : ratio - 1;
    if (!Number.isFinite(value)) {
      dropped.push({
        index: current.index,
        t: current.t,
        code: 'non_finite_return',
        message: 'Period return overflowed to a non-finite value.',
      });
      continue;
    }
    returns.push(value);
    // END-of-period timestamp: see the ReturnSeries.timestamps doc comment.
    timestamps.push(current.t);
  }

  return { kind, returns, timestamps, dropped, usablePoints: deduped.length };
}

/**
 * Milliseconds in a mean Gregorian year (365.2425 days).
 *
 * Used instead of 365 or 365.25 so that a daily series annualises to 365.2425
 * rather than drifting by a quarter-day a year. Note this is a *calendar*
 * conversion: a series of daily bars that only exist on trading days has a
 * median spacing of one day and therefore annualises at ~365, not 252. That is
 * the honest answer for a calendar-time Sharpe; if you want the trading-day
 * convention, supply the periods per year yourself.
 */
export const MS_PER_YEAR = 365.2425 * 24 * 60 * 60 * 1000;

/**
 * Fraction of spacings that may deviate from the median by more than
 * {@link SPACING_DEVIATION_TOLERANCE} before the series is called irregular.
 *
 * Calibrated so that daily bars with weekend gaps stay "regular": a five-day
 * trading week contributes four 1-day gaps and one 3-day gap, i.e. exactly 20%
 * deviating, which sits under the 25% threshold. A genuinely event-driven
 * series (per-trade timestamps) blows straight past it.
 */
export const IRREGULAR_SPACING_FRACTION = 0.25;

/** A spacing counts as deviating when |spacing − median| > 50% of the median. */
export const SPACING_DEVIATION_TOLERANCE = 0.5;

/** Result of {@link inferPeriodsPerYear}. */
export interface PeriodInference {
  /**
   * Annualisation factor: `MS_PER_YEAR / medianSpacingMs`.
   *
   * `null` when it cannot be derived (fewer than two timestamps, or a
   * non-positive median spacing). **Never defaulted to 252 or 365** — silently
   * guessing the sampling frequency is how an hourly series gets reported with
   * a daily Sharpe.
   */
  readonly periodsPerYear: number | null;
  /** Median gap between consecutive timestamps, in milliseconds. `null` when undefined. */
  readonly medianSpacingMs: number | null;
  /**
   * `true` when more than {@link IRREGULAR_SPACING_FRACTION} of the gaps deviate
   * from the median by more than {@link SPACING_DEVIATION_TOLERANCE} of it.
   * When set, `periodsPerYear` is still returned but should be presented as an
   * approximation.
   */
  readonly irregular: boolean;
  /** Number of gaps examined (`timestamps.length − 1`, after invalid gaps are skipped). */
  readonly spacingCount: number;
  /** Observed fraction of deviating gaps, for display alongside the flag. */
  readonly deviatingFraction: number;
}

/**
 * Infer the annualisation factor from the **median** spacing of timestamps.
 *
 * The median rather than the mean, because a single multi-month gap (a strategy
 * that was switched off over the summer) would drag a mean spacing far away
 * from the sampling frequency, while the median simply ignores it.
 *
 * Timestamps must be ascending; non-positive gaps are skipped rather than
 * treated as zero-length periods. Never throws.
 */
export function inferPeriodsPerYear(timestamps: readonly number[]): PeriodInference {
  const empty: PeriodInference = {
    periodsPerYear: null,
    medianSpacingMs: null,
    irregular: false,
    spacingCount: 0,
    deviatingFraction: 0,
  };
  if (timestamps.length < 2) return empty;

  const spacings: number[] = [];
  for (let i = 1; i < timestamps.length; i += 1) {
    const gap = at(timestamps, i) - at(timestamps, i - 1);
    if (Number.isFinite(gap) && gap > 0) spacings.push(gap);
  }
  if (spacings.length === 0) return empty;

  const medianSpacingMs = median(spacings);
  if (!Number.isFinite(medianSpacingMs) || medianSpacingMs <= 0) {
    return { ...empty, spacingCount: spacings.length };
  }

  let deviating = 0;
  for (const gap of spacings) {
    if (Math.abs(gap - medianSpacingMs) > SPACING_DEVIATION_TOLERANCE * medianSpacingMs) {
      deviating += 1;
    }
  }
  const deviatingFraction = deviating / spacings.length;
  const periodsPerYear = MS_PER_YEAR / medianSpacingMs;

  return {
    periodsPerYear: Number.isFinite(periodsPerYear) && periodsPerYear > 0 ? periodsPerYear : null,
    medianSpacingMs,
    irregular: deviatingFraction > IRREGULAR_SPACING_FRACTION,
    spacingCount: spacings.length,
    deviatingFraction,
  };
}

/**
 * Compound a simple-return series into a cumulative total return: `Π(1 + rᵢ) − 1`.
 *
 * For `kind: 'log'` the additive identity applies instead: `exp(Σrᵢ) − 1`.
 *
 * @returns `null` on non-finite input or a non-finite product, and `0` for an
 *   empty series (no periods traded means no return).
 */
export function totalReturn(returns: readonly number[], kind: ReturnKind = 'simple'): number | null {
  if (returns.length === 0) return 0;
  if (kind === 'log') {
    let total = 0;
    for (const r of returns) {
      if (!Number.isFinite(r)) return null;
      total += r;
    }
    const result = Math.exp(total) - 1;
    return Number.isFinite(result) ? result : null;
  }
  let growth = 1;
  for (const r of returns) {
    if (!Number.isFinite(r)) return null;
    growth *= 1 + r;
  }
  const result = growth - 1;
  return Number.isFinite(result) ? result : null;
}
