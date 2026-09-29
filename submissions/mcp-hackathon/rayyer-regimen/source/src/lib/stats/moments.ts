/**
 * Sample moments.
 *
 * Every function here returns `number | null` rather than a {@link StatsResult}:
 * moments are leaf primitives called in tight loops by the rest of the package,
 * and a bare `null` keeps those call sites readable. The contract is the same
 * as everywhere else — **never `NaN`, never a throw**. `null` means "this
 * estimator is not defined for the sample you gave me", and every consumer in
 * this package handles it explicitly.
 *
 * All estimators reject non-finite input (`NaN`, `±Infinity`) by returning
 * `null`: a single bad tick must not silently poison a statistic.
 */

import { allFinite, at } from './internal';

/** Delta degrees of freedom. `1` = sample estimator (default), `0` = population. */
export interface DdofOptions {
  /**
   * Divisor correction: the estimator divides by `n - ddof`.
   *
   * Defaults to `1` (Bessel-corrected sample variance) because every downstream
   * Sharpe formula in this package is defined against the *sample* standard
   * deviation.
   */
  readonly ddof?: number;
}

/** Options for {@link kurtosis}. */
export interface KurtosisOptions {
  /**
   * When `true`, subtract 3 to return *excess* kurtosis (normal = 0).
   *
   * Defaults to **`false`**, i.e. the non-excess form where a normal
   * distribution scores 3. This default is deliberate and load-bearing: the
   * Bailey & López de Prado PSR/MinTRL/DSR formulas take γ₄ as the non-excess
   * fourth moment, and feeding them an excess value silently inflates the
   * reported confidence. Passing `{ excess: true }` is for display only.
   */
  readonly excess?: boolean;
}

/**
 * Arithmetic mean.
 *
 * @returns `null` for an empty array or any non-finite element.
 */
export function mean(xs: readonly number[]): number | null {
  if (xs.length === 0) return null;
  if (!allFinite(xs)) return null;
  let sum = 0;
  for (const x of xs) sum += x;
  const result = sum / xs.length;
  return Number.isFinite(result) ? result : null;
}

/**
 * Variance with a configurable divisor: `Σ(xᵢ − x̄)² / (n − ddof)`.
 *
 * Uses the two-pass (corrected) algorithm rather than the naive
 * `E[x²] − E[x]²` sum-of-squares shortcut, which loses catastrophic precision
 * when the mean is large relative to the spread — exactly the shape of an
 * equity curve.
 *
 * @returns `null` when `n − ddof ≤ 0`, on empty input, or on non-finite input.
 */
export function variance(xs: readonly number[], options: DdofOptions = {}): number | null {
  const ddof = options.ddof ?? 1;
  if (!Number.isFinite(ddof)) return null;
  const n = xs.length;
  const divisor = n - ddof;
  if (n === 0 || divisor <= 0) return null;
  const mu = mean(xs);
  if (mu === null) return null;
  let sumSquares = 0;
  for (const x of xs) {
    const deviation = x - mu;
    sumSquares += deviation * deviation;
  }
  const result = sumSquares / divisor;
  return Number.isFinite(result) ? result : null;
}

/**
 * Standard deviation — the square root of {@link variance} with the same `ddof`.
 *
 * @returns `null` whenever {@link variance} is `null`.
 */
export function stdDev(xs: readonly number[], options: DdofOptions = {}): number | null {
  const v = variance(xs, options);
  if (v === null || v < 0) return null;
  return Math.sqrt(v);
}

/**
 * Central moment `mₖ = (1/n) Σ(xᵢ − x̄)ᵏ`, always with the population divisor `n`.
 *
 * Private: the G1/G2 bias corrections below are defined in terms of these raw
 * moments, so exposing them would invite mixing divisor conventions.
 */
function centralMoment(xs: readonly number[], mu: number, order: number): number {
  let sum = 0;
  for (const x of xs) sum += (x - mu) ** order;
  return sum / xs.length;
}

/**
 * Sample skewness, the adjusted Fisher–Pearson standardised moment coefficient **G1**.
 *
 *     g1 = m₃ / m₂^(3/2)                  (biased, population moments)
 *     G1 = g1 · √(n(n−1)) / (n − 2)       (bias-adjusted)
 *
 * where `mₖ = (1/n) Σ(xᵢ − x̄)ᵏ`. This is the estimator Excel's `SKEW`,
 * `scipy.stats.skew(bias=False)` and SAS/SPSS report, and it is the γ₃ that the
 * Bailey & López de Prado formulas in `sharpe.ts` expect.
 *
 * Source: Joanes & Gill (1998), "Comparing measures of sample skewness and
 * kurtosis", The Statistician 47(1), estimator G1.
 *
 * @returns `null` when `n < 3` (the adjustment divides by `n − 2`) or when
 *   `m₂ = 0` (a constant series has no defined shape), or on non-finite input.
 */
export function skewness(xs: readonly number[]): number | null {
  const n = xs.length;
  if (n < 3) return null;
  if (!allFinite(xs)) return null;
  const mu = mean(xs);
  if (mu === null) return null;
  const m2 = centralMoment(xs, mu, 2);
  if (m2 <= 0) return null;
  const m3 = centralMoment(xs, mu, 3);
  const g1 = m3 / m2 ** 1.5;
  const result = (g1 * Math.sqrt(n * (n - 1))) / (n - 2);
  return Number.isFinite(result) ? result : null;
}

/**
 * Sample kurtosis, the bias-adjusted estimator **G2**.
 *
 *     g2 = m₄ / m₂² − 3                                   (biased excess)
 *     G2 = ((n + 1)·g2 + 6) · (n − 1) / ((n − 2)(n − 3))   (bias-adjusted excess)
 *
 * equivalently `G2 = [(n² − 1)·m₄/m₂² − 3(n − 1)²] / ((n − 2)(n − 3))`, which is
 * what `scipy.stats.kurtosis(bias=False)` computes.
 *
 * **Returns the NON-EXCESS form by default** (`G2 + 3`, so a normal sample sits
 * near 3). The Sharpe machinery downstream consumes γ₄ in non-excess form;
 * handing it an excess value understates the denominator of the PSR and
 * overstates confidence. Pass `{ excess: true }` only for display.
 *
 * Source: Joanes & Gill (1998), estimator G2.
 *
 * @returns `null` when `n < 4` (the adjustment divides by `n − 3`), when
 *   `m₂ = 0`, or on non-finite input.
 */
export function kurtosis(xs: readonly number[], options: KurtosisOptions = {}): number | null {
  const excess = options.excess ?? false;
  const n = xs.length;
  if (n < 4) return null;
  if (!allFinite(xs)) return null;
  const mu = mean(xs);
  if (mu === null) return null;
  const m2 = centralMoment(xs, mu, 2);
  if (m2 <= 0) return null;
  const m4 = centralMoment(xs, mu, 4);
  const biasedExcess = m4 / (m2 * m2) - 3;
  const adjustedExcess = (((n + 1) * biasedExcess + 6) * (n - 1)) / ((n - 2) * (n - 3));
  const result = excess ? adjustedExcess : adjustedExcess + 3;
  return Number.isFinite(result) ? result : null;
}

/**
 * Sum of an array, with the same finiteness contract as the estimators above.
 *
 * @returns `null` on non-finite input or a non-finite total (overflow).
 */
export function sum(xs: readonly number[]): number | null {
  if (!allFinite(xs)) return null;
  let total = 0;
  for (const x of xs) total += x;
  return Number.isFinite(total) ? total : null;
}

/**
 * Minimum and maximum in one pass.
 *
 * `Math.min(...xs)` blows the call-stack argument limit somewhere around 10⁵
 * elements, which a tick-level track record reaches easily.
 *
 * @returns `null` on empty or non-finite input.
 */
export function extent(xs: readonly number[]): { min: number; max: number } | null {
  if (xs.length === 0 || !allFinite(xs)) return null;
  let min = at(xs, 0);
  let max = min;
  for (let i = 1; i < xs.length; i += 1) {
    const x = at(xs, i);
    if (x < min) min = x;
    if (x > max) max = x;
  }
  return { min, max };
}
