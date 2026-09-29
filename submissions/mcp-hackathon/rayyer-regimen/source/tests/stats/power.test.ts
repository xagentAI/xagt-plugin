/**
 * Statistical power and size — the negative control.
 *
 * A significance test that always says "significant" passes every
 * known-answer test in this repository. The only thing that catches it is
 * running it against data with a KNOWN answer in both directions:
 *
 *   - a seeded series with a genuinely positive mean must come back with a high
 *     PSR (power: we detect the edge that is there), and
 *   - a seeded series with a mean of EXACTLY ZERO must mostly come back
 *     inconclusive (size: we do not manufacture an edge that is not there).
 *
 * Both are run across 20 independent seeds so the result is a property of the
 * estimator rather than of one lucky draw. Everything is seeded, so the numbers
 * are identical on every machine and every run.
 */

import { describe, expect, it } from 'vitest';

import { kurtosis, mean, skewness, stdDev } from '../../src/lib/stats/moments';
import { probabilisticSharpeRatio, sharpeRatio } from '../../src/lib/stats/sharpe';
import { seededNormals, unwrap } from './support';

const SEEDS = Array.from({ length: 20 }, (_, i) => 1_000 + i * 7919);
const N = 750;
const SD = 0.01;

/** Per-period PSR against a zero benchmark for one seeded return series. */
function psrOf(returns: number[]): number {
  const sharpe = unwrap(sharpeRatio(returns)).sharpe;
  const g3 = skewness(returns);
  const g4 = kurtosis(returns); // NON-excess, as PSR requires
  expect(g3).not.toBeNull();
  expect(g4).not.toBeNull();
  return unwrap(
    probabilisticSharpeRatio({
      sharpe,
      n: returns.length,
      skewness: g3 ?? 0,
      kurtosis: g4 ?? 3,
    }),
  ).psr;
}

describe('seeded normal generator (fixture sanity check)', () => {
  it('reproduces the requested mean and standard deviation', () => {
    const xs = seededNormals(50_000, 0.002, 0.01, 4242);
    expect(mean(xs) ?? 0).toBeCloseTo(0.002, 4);
    expect(stdDev(xs) ?? 0).toBeCloseTo(0.01, 4);
  });

  it('produces an approximately normal shape (skew ~0, non-excess kurtosis ~3)', () => {
    const xs = seededNormals(50_000, 0, 1, 4243);
    expect(Math.abs(skewness(xs) ?? 1)).toBeLessThan(0.05);
    expect(kurtosis(xs) ?? 0).toBeGreaterThan(2.9);
    expect(kurtosis(xs) ?? 0).toBeLessThan(3.1);
  });

  it('is deterministic', () => {
    expect(seededNormals(100, 0.001, 0.01, 7)).toEqual(seededNormals(100, 0.001, 0.01, 7));
    expect(seededNormals(100, 0.001, 0.01, 7)).not.toEqual(seededNormals(100, 0.001, 0.01, 8));
  });
});

describe('POWER: PSR detects a known positive mean', () => {
  // mean 0.002 with sd 0.01 is a per-period Sharpe of 0.2. Over 750 periods
  // that is z = 0.2 * sqrt(749) ~ 5.47, i.e. a PSR indistinguishable from 1.
  const psrs = SEEDS.map((seed) => psrOf(seededNormals(N, 0.002, SD, seed)));

  it('reports PSR > 0.999 on every one of the 20 seeds', () => {
    for (const psr of psrs) expect(psr).toBeGreaterThan(0.999);
  });

  it('clears the 95% significance bar on every seed', () => {
    expect(psrs.filter((p) => p > 0.95)).toHaveLength(SEEDS.length);
  });
});

describe('NEGATIVE CONTROL: PSR does NOT manufacture an edge from a zero-mean series', () => {
  // The true Sharpe is exactly 0. A correctly calibrated PSR against a zero
  // benchmark is then approximately Uniform(0, 1), so about 1 seed in 20 should
  // clear 0.95 by chance. Anything close to 20/20 means the estimator is broken
  // (or the higher moments are being fed in the wrong convention).
  const psrs = SEEDS.map((seed) => psrOf(seededNormals(N, 0, SD, seed + 500_000)));
  const significant = psrs.filter((p) => p > 0.95).length;

  it('flags at most a handful of the 20 zero-mean seeds as significant', () => {
    expect(significant).toBeLessThanOrEqual(4);
  });

  it('does not flag a majority of the zero-mean seeds', () => {
    expect(significant).toBeLessThan(SEEDS.length / 2);
  });

  it('is calibrated: the median PSR across zero-mean seeds sits near 0.5', () => {
    const sorted = [...psrs].sort((a, b) => a - b);
    const median = ((sorted[9] ?? 0) + (sorted[10] ?? 0)) / 2;
    expect(median).toBeGreaterThan(0.2);
    expect(median).toBeLessThan(0.8);
  });

  it('spans the unit interval rather than clustering at one end', () => {
    expect(Math.min(...psrs)).toBeLessThan(0.35);
    expect(Math.max(...psrs)).toBeGreaterThan(0.65);
  });
});

describe('POWER vs SIZE separation', () => {
  it('ranks every positive-mean seed above the median zero-mean seed', () => {
    const positive = SEEDS.map((seed) => psrOf(seededNormals(N, 0.002, SD, seed)));
    const nulls = SEEDS.map((seed) => psrOf(seededNormals(N, 0, SD, seed + 500_000)));
    const nullsSorted = [...nulls].sort((a, b) => a - b);
    const nullMedian = ((nullsSorted[9] ?? 0) + (nullsSorted[10] ?? 0)) / 2;
    for (const psr of positive) expect(psr).toBeGreaterThan(nullMedian);
  });

  it('loses power on a short sample, as it must', () => {
    // Same effect size, 30 periods instead of 750: z ~ 0.2*sqrt(29) = 1.08,
    // which is not significant. A PSR that stayed near 1 here would be ignoring n.
    const short = psrOf(seededNormals(30, 0.002, SD, 31_337));
    const long = psrOf(seededNormals(750, 0.002, SD, 31_337));
    expect(short).toBeLessThan(long);
    expect(short).toBeLessThan(0.999);
  });

  it('reports a negative-mean series as decidedly insignificant', () => {
    for (const seed of SEEDS.slice(0, 5)) {
      expect(psrOf(seededNormals(N, -0.002, SD, seed))).toBeLessThan(0.01);
    }
  });
});
