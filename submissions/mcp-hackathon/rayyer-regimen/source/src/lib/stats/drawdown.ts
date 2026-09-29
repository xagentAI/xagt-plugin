/**
 * Drawdown statistics over an equity curve.
 *
 * Drawdowns are computed on *equity levels*, not returns, because the peak has
 * to be a running maximum of the actual account value. Every equity point must
 * be finite and strictly positive — a drawdown is a fraction of a peak, and
 * that fraction is undefined once the peak can be zero or negative.
 */

import { at } from './internal';
import { fail, ok, type StatsResult } from './result';

/** Result payload of {@link maxDrawdown}. */
export interface MaxDrawdownValue {
  /**
   * Largest peak-to-trough decline as a **positive fraction** of the peak.
   * A 20% drawdown is `0.2`, never `-0.2` and never `20`.
   */
  readonly maxDrawdown: number;
  /** Index of the peak that preceded the worst trough. */
  readonly peakIndex: number;
  /** Index of the worst trough. */
  readonly troughIndex: number;
  /**
   * First index at or after `troughIndex` where equity regained the peak value,
   * or `null` when the series ends still underwater.
   */
  readonly recoveryIndex: number | null;
  /**
   * Longest underwater stretch anywhere in the series, in **periods**, measured
   * from the peak index to the index at which that peak was regained. An
   * unrecovered final stretch is measured to the last index. A series that
   * never goes below its running peak scores `0`.
   *
   * Note this is the longest stretch in *time*, which is frequently a different
   * episode from the one that produced `maxDrawdown` (the deepest).
   */
  readonly longestDrawdownPeriods: number;
  /** Equity value at `peakIndex`, echoed for audit. */
  readonly peakEquity: number;
  /** Equity value at `troughIndex`, echoed for audit. */
  readonly troughEquity: number;
}

/**
 * Maximum drawdown and the shape of the episode that produced it.
 *
 * Single pass over a running peak: `ddᵢ = (peakᵢ − eᵢ) / peakᵢ`, tracking the
 * largest value together with the peak that preceded it.
 *
 * Convention when the curve never declines: `maxDrawdown = 0` and
 * `peakIndex = troughIndex = recoveryIndex = 0`. Nulling the indices instead
 * would push a branch onto every caller for a case whose answer is genuinely
 * "no drawdown, starting from the first point".
 *
 * @returns `empty_input` for `[]`, `non_finite_input` for NaN/±Infinity,
 *   `non_positive_equity` for any element ≤ 0.
 */
export function maxDrawdown(equity: readonly number[]): StatsResult<MaxDrawdownValue> {
  const n = equity.length;
  if (n === 0) return fail('empty_input', 'No equity points supplied.');
  for (let i = 0; i < n; i += 1) {
    const value = at(equity, i);
    if (!Number.isFinite(value)) {
      return fail('non_finite_input', 'Equity curve contains a non-finite value.');
    }
    if (value <= 0) {
      return fail('non_positive_equity', 'Equity must be strictly positive at every point.');
    }
  }

  let runningPeakIndex = 0;
  let runningPeak = at(equity, 0);

  let worstDrawdown = 0;
  let worstPeakIndex = 0;
  let worstTroughIndex = 0;

  // Longest-underwater tracking runs independently of depth tracking.
  let episodePeakIndex = 0;
  let episodeUnderwater = false;
  let longestDrawdownPeriods = 0;

  for (let i = 1; i < n; i += 1) {
    const value = at(equity, i);

    if (value >= runningPeak) {
      if (episodeUnderwater) {
        longestDrawdownPeriods = Math.max(longestDrawdownPeriods, i - episodePeakIndex);
        episodeUnderwater = false;
      }
      runningPeak = value;
      runningPeakIndex = i;
      episodePeakIndex = i;
      continue;
    }

    episodeUnderwater = true;
    const drawdown = (runningPeak - value) / runningPeak;
    if (drawdown > worstDrawdown) {
      worstDrawdown = drawdown;
      worstPeakIndex = runningPeakIndex;
      worstTroughIndex = i;
    }
  }

  if (episodeUnderwater) {
    longestDrawdownPeriods = Math.max(longestDrawdownPeriods, n - 1 - episodePeakIndex);
  }

  let recoveryIndex: number | null = null;
  if (worstDrawdown === 0) {
    recoveryIndex = 0;
  } else {
    const peakEquity = at(equity, worstPeakIndex);
    for (let i = worstTroughIndex + 1; i < n; i += 1) {
      if (at(equity, i) >= peakEquity) {
        recoveryIndex = i;
        break;
      }
    }
  }

  return ok({
    maxDrawdown: worstDrawdown,
    peakIndex: worstPeakIndex,
    troughIndex: worstTroughIndex,
    recoveryIndex,
    longestDrawdownPeriods,
    peakEquity: at(equity, worstPeakIndex),
    troughEquity: at(equity, worstTroughIndex),
  });
}

/** Result payload of {@link ulcerIndex}. */
export interface UlcerIndexValue {
  /**
   * The Ulcer Index in **percentage points**, matching Martin & McCann's
   * original definition (a series that spends its life 5% underwater scores
   * ≈ 5, not ≈ 0.05).
   */
  readonly ulcerIndex: number;
  /** The same quantity as a fraction (`ulcerIndex / 100`), for charting alongside returns. */
  readonly ulcerIndexFraction: number;
  /** Number of equity points included in the average. */
  readonly periods: number;
  /** The deepest single retracement encountered, as a positive fraction. */
  readonly maxRetracement: number;
}

/**
 * Ulcer Index — the quadratic mean of percentage drawdown across the whole
 * curve:
 *
 *     UI = √( (1/n) · Σ Dᵢ² ),   Dᵢ = 100 · (peakᵢ − eᵢ) / peakᵢ
 *
 * Squaring penalises deep drawdowns far more than shallow ones and the average
 * penalises long ones, which is why it tracks the *experience* of holding a
 * strategy better than max drawdown does — max drawdown is a single unlucky
 * afternoon, the Ulcer Index is the whole year.
 *
 * The first point is included with `D₀ = 0`, so `n` is the number of equity
 * points, not the number of returns.
 *
 * Source: Martin, P. & McCann, B. (1989), "The Investor's Guide to Fidelity
 * Funds".
 *
 * @returns the same failure reasons as {@link maxDrawdown}.
 */
export function ulcerIndex(equity: readonly number[]): StatsResult<UlcerIndexValue> {
  const n = equity.length;
  if (n === 0) return fail('empty_input', 'No equity points supplied.');
  for (let i = 0; i < n; i += 1) {
    const value = at(equity, i);
    if (!Number.isFinite(value)) {
      return fail('non_finite_input', 'Equity curve contains a non-finite value.');
    }
    if (value <= 0) {
      return fail('non_positive_equity', 'Equity must be strictly positive at every point.');
    }
  }

  let runningPeak = at(equity, 0);
  let sumSquares = 0;
  let maxRetracement = 0;
  for (let i = 0; i < n; i += 1) {
    const value = at(equity, i);
    if (value > runningPeak) runningPeak = value;
    const retracement = (runningPeak - value) / runningPeak;
    if (retracement > maxRetracement) maxRetracement = retracement;
    const percent = 100 * retracement;
    sumSquares += percent * percent;
  }

  const index = Math.sqrt(sumSquares / n);
  if (!Number.isFinite(index)) {
    return fail('undefined_denominator', 'Ulcer index evaluated to a non-finite value.');
  }

  return ok({
    ulcerIndex: index,
    ulcerIndexFraction: index / 100,
    periods: n,
    maxRetracement,
  });
}
