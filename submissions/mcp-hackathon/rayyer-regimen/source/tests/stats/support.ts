/**
 * Shared deterministic fixtures for the statistics suite.
 *
 * Not a test file. Everything here is seeded: the suite must produce identical
 * numbers on every machine and every run, so there is no `Math.random`, no
 * `Date.now`, and no dependence on locale or timezone anywhere in these tests.
 */

import { mulberry32, normalInv } from '../../src/lib/stats/numeric';
import { isOk, type StatsResult } from '../../src/lib/stats/result';

/**
 * Draw `n` normal variates by inverse transform from the seeded uniform stream.
 *
 * Inverse transform rather than Box–Muller so that the mapping from the uniform
 * stream to the normal sample is one-to-one and order-preserving: changing `n`
 * extends the sample rather than reshuffling it, which makes a failing test
 * reproducible by shrinking `n`.
 *
 * `mulberry32` can in principle return exactly 0 (probability 2⁻³²), which
 * would map to −Infinity, so draws are clamped into [2⁻⁵³, 1 − 2⁻⁵³].
 */
export function seededNormals(n: number, mean: number, sd: number, seed: number): number[] {
  const rng = mulberry32(seed);
  const out: number[] = [];
  const epsilon = Number.EPSILON / 2;
  for (let i = 0; i < n; i += 1) {
    const u = Math.min(Math.max(rng(), epsilon), 1 - epsilon);
    out.push(mean + sd * normalInv(u));
  }
  return out;
}

/** Seeded uniforms in [0, 1). */
export function seededUniforms(n: number, seed: number): number[] {
  const rng = mulberry32(seed);
  const out: number[] = [];
  for (let i = 0; i < n; i += 1) out.push(rng());
  return out;
}

/** Compound simple returns into an equity curve starting at `start`. */
export function equityFromReturns(returns: readonly number[], start = 100): number[] {
  const equity = [start];
  let level = start;
  for (const r of returns) {
    level *= 1 + r;
    equity.push(level);
  }
  return equity;
}

/** Epoch-ms timestamps on a fixed grid. Timezone-independent by construction. */
export function timestampsEvery(n: number, spacingMs: number, startMs = 0): number[] {
  const out: number[] = [];
  for (let i = 0; i < n; i += 1) out.push(startMs + i * spacingMs);
  return out;
}

/** One day in milliseconds. */
export const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Unwrap a successful result or fail loudly with the reason.
 *
 * Keeps the assertion noise out of the tests themselves while still making a
 * surprise failure readable in the reporter output.
 */
export function unwrap<T>(result: StatsResult<T>): T {
  if (!isOk(result)) {
    throw new Error(`expected ok result, got reason="${result.reason}" message="${result.message}"`);
  }
  return result.value;
}

/**
 * Walk a value and return every finite-number violation it contains.
 *
 * Used by the package-wide invariant sweep: no public function may return `NaN`
 * or `±Infinity` anywhere in its payload.
 */
export function nonFinitePaths(value: unknown, path = '$'): string[] {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? [] : [`${path} = ${String(value)}`];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item, i) => nonFinitePaths(item, `${path}[${i}]`));
  }
  if (value !== null && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) => nonFinitePaths(item, `${path}.${key}`));
  }
  return [];
}
