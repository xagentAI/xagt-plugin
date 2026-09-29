/**
 * Shared private helpers for the statistics core.
 *
 * Nothing here is re-exported from `index.ts`: these exist so the public modules
 * can stay readable under `noUncheckedIndexedAccess` without sprinkling
 * non-null assertions through every numeric loop.
 */

/**
 * In-bounds indexed read.
 *
 * `noUncheckedIndexedAccess` types every `xs[i]` as `number | undefined`. Every
 * call site in this package indexes inside a length-checked loop, so the
 * fallback is unreachable; it returns NaN rather than 0 so that a future
 * out-of-bounds read poisons the computation visibly instead of silently
 * biasing a statistic toward zero.
 */
export function at(xs: readonly number[], index: number): number {
  const value = xs[index];
  return value === undefined ? Number.NaN : value;
}

/** True when every element is a finite number (no NaN, no ±Infinity). */
export function allFinite(xs: readonly number[]): boolean {
  for (const x of xs) {
    if (!Number.isFinite(x)) return false;
  }
  return true;
}

/** Index of the first non-finite element, or -1 when all are finite. */
export function firstNonFiniteIndex(xs: readonly number[]): number {
  for (let i = 0; i < xs.length; i += 1) {
    if (!Number.isFinite(at(xs, i))) return i;
  }
  return -1;
}

/** Ascending numeric copy. Never mutates the input. */
export function sortedAscending(xs: readonly number[]): number[] {
  return [...xs].sort((a, b) => a - b);
}

/**
 * Quantile of an already-ascending array using the R type-7 / NumPy `linear`
 * convention: h = (n - 1) * q, interpolating linearly between the bracketing
 * order statistics. Chosen because it is the default in R, NumPy and pandas,
 * so bootstrap percentile bounds reconcile with those tools.
 *
 * Source: Hyndman & Fan (1996), "Sample Quantiles in Statistical Packages",
 * definition 7.
 */
export function quantileType7(sortedAsc: readonly number[], q: number): number {
  const n = sortedAsc.length;
  if (n === 0) return Number.NaN;
  if (n === 1) return at(sortedAsc, 0);
  const h = (n - 1) * q;
  const lower = Math.floor(h);
  const upper = Math.min(lower + 1, n - 1);
  const frac = h - lower;
  const a = at(sortedAsc, lower);
  const b = at(sortedAsc, upper);
  return a + frac * (b - a);
}

/** Median via {@link quantileType7}; input need not be sorted. */
export function median(xs: readonly number[]): number {
  return quantileType7(sortedAscending(xs), 0.5);
}
