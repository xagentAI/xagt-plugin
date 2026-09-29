/**
 * Sample moments.
 *
 * The skewness and kurtosis cases carry their full hand derivation in the
 * comments: G1/G2 have at least three competing conventions in circulation and
 * a reviewer needs to be able to check which one we implemented without
 * running anything.
 */

import { describe, expect, it } from 'vitest';

import { extent, kurtosis, mean, skewness, stdDev, sum, variance } from '../../src/lib/stats/moments';

/**
 * Worked example used throughout this file.
 *
 *   xs   = [2, 4, 4, 4, 5, 5, 7, 9]      n = 8
 *   mean = 40 / 8 = 5
 *   deviations        = [-3, -1, -1, -1, 0, 0, 2, 4]
 *   sum of squares    = 9 + 1 + 1 + 1 + 0 + 0 + 4 + 16  = 32
 *   m2 (population)   = 32 / 8 = 4          -> population sd = 2
 *   sample variance   = 32 / 7 = 4.571428571428571
 *   sample sd         = sqrt(32/7)         = 2.138089935299395
 */
const XS = [2, 4, 4, 4, 5, 5, 7, 9] as const;

describe('mean', () => {
  it('computes the arithmetic mean', () => {
    expect(mean([...XS])).toBe(5);
    expect(mean([1, 2, 3, 4])).toBe(2.5);
    expect(mean([-1, 1])).toBe(0);
  });

  it('handles a single element', () => {
    expect(mean([42])).toBe(42);
  });

  it('returns null for an empty array', () => {
    expect(mean([])).toBeNull();
  });

  it('returns null, not NaN, when any element is non-finite', () => {
    expect(mean([1, Number.NaN, 3])).toBeNull();
    expect(mean([1, Number.POSITIVE_INFINITY])).toBeNull();
    expect(mean([Number.NEGATIVE_INFINITY, 0])).toBeNull();
  });

  it('stays accurate when the mean dwarfs the spread', () => {
    // A naive E[x^2] - E[x]^2 formulation loses all precision here; the mean
    // itself is fine, but this is the series the variance test below leans on.
    const xs = [1e9 + 4, 1e9 + 7, 1e9 + 13, 1e9 + 16];
    expect(mean(xs)).toBe(1e9 + 10);
  });
});

describe('variance / stdDev', () => {
  it('defaults to the sample estimator (ddof = 1)', () => {
    expect(variance([...XS])).toBeCloseTo(4.571428571428571, 15);
    expect(stdDev([...XS])).toBeCloseTo(2.138089935299395, 15);
  });

  it('supports the population estimator (ddof = 0)', () => {
    expect(variance([...XS], { ddof: 0 })).toBe(4);
    expect(stdDev([...XS], { ddof: 0 })).toBe(2);
  });

  it('returns null when n - ddof <= 0', () => {
    expect(variance([5])).toBeNull();
    expect(stdDev([5])).toBeNull();
    expect(variance([1, 2], { ddof: 2 })).toBeNull();
    expect(variance([1, 2, 3], { ddof: 5 })).toBeNull();
  });

  it('returns null for empty input at any ddof', () => {
    expect(variance([])).toBeNull();
    expect(variance([], { ddof: 0 })).toBeNull();
    expect(stdDev([])).toBeNull();
  });

  it('returns exactly zero for a constant series', () => {
    expect(variance([3, 3, 3, 3])).toBe(0);
    expect(stdDev([3, 3, 3, 3])).toBe(0);
  });

  it('returns null on non-finite input', () => {
    expect(variance([1, 2, Number.NaN])).toBeNull();
    expect(stdDev([1, Number.POSITIVE_INFINITY, 3])).toBeNull();
  });

  it('returns null for a non-finite ddof rather than producing NaN', () => {
    expect(variance([...XS], { ddof: Number.NaN })).toBeNull();
  });

  it('uses the two-pass algorithm, so a large offset does not destroy precision', () => {
    // var([4,7,13,16]) = 30. Shifted by 1e9 the naive sum-of-squares form
    // returns something like 0 or a negative number in float64.
    const base = [4, 7, 13, 16];
    const shifted = base.map((x) => x + 1e9);
    expect(variance(base)).toBeCloseTo(30, 12);
    expect(variance(shifted)).toBeCloseTo(30, 6);
  });
});

describe('skewness (adjusted Fisher-Pearson G1)', () => {
  it('matches the hand derivation for the worked example', () => {
    // m3 = ((-3)^3 + (-1)^3 * 3 + 0 + 0 + 2^3 + 4^3) / 8
    //    = (-27 - 3 + 8 + 64) / 8 = 42 / 8 = 5.25
    // g1 = m3 / m2^1.5 = 5.25 / 4^1.5 = 5.25 / 8 = 0.65625
    // G1 = g1 * sqrt(n(n-1)) / (n-2)
    //    = 0.65625 * sqrt(56) / 6
    //    = 0.65625 * 7.483314773547883 / 6
    //    = 0.8184875533567996
    expect(skewness([...XS])).toBeCloseTo(0.8184875533567996, 14);
  });

  it('matches a second reference case with an extreme outlier', () => {
    // scipy.stats.skew([1,2,3,4,100], bias=False) = 2.232395911636458
    expect(skewness([1, 2, 3, 4, 100])).toBeCloseTo(2.232395911636458, 13);
  });

  it('is exactly zero for a symmetric sample', () => {
    expect(skewness([-2, -1, 0, 1, 2])).toBe(0);
    expect(skewness([1, 2, 3, 4, 5])).toBe(0);
  });

  it('flips sign when the sample is mirrored', () => {
    const forward = skewness([...XS]);
    const mirrored = skewness(XS.map((x) => -x));
    expect(forward).not.toBeNull();
    expect(mirrored).not.toBeNull();
    expect(mirrored ?? 0).toBeCloseTo(-(forward ?? 0), 14);
  });

  it('is scale and location invariant', () => {
    const base = skewness([...XS]) ?? 0;
    expect(skewness(XS.map((x) => x * 7 + 100)) ?? 0).toBeCloseTo(base, 12);
  });

  it('returns null below n = 3, because the (n-2) adjustment is undefined', () => {
    expect(skewness([])).toBeNull();
    expect(skewness([1])).toBeNull();
    expect(skewness([1, 2])).toBeNull();
    expect(skewness([1, 2, 3])).not.toBeNull();
  });

  it('returns null, not NaN, for a constant series (m2 = 0)', () => {
    expect(skewness([4, 4, 4, 4, 4])).toBeNull();
  });

  it('returns null on non-finite input', () => {
    expect(skewness([1, 2, Number.NaN, 4])).toBeNull();
  });
});

describe('kurtosis (adjusted G2)', () => {
  it('matches the hand derivation and returns the NON-EXCESS form by default', () => {
    // m4 = (3^4 + 1 + 1 + 1 + 0 + 0 + 2^4 + 4^4) / 8
    //    = (81 + 3 + 16 + 256) / 8 = 356 / 8 = 44.5
    // g2 (biased excess) = m4/m2^2 - 3 = 44.5/16 - 3 = 2.78125 - 3 = -0.21875
    // G2 (adjusted excess) = ((n+1)*g2 + 6) * (n-1) / ((n-2)(n-3))
    //                      = ((9)(-0.21875) + 6) * 7 / (6 * 5)
    //                      = (-1.96875 + 6) * 7 / 30
    //                      = 4.03125 * 7 / 30 = 0.940625
    // Non-excess = 0.940625 + 3 = 3.940625
    expect(kurtosis([...XS])).toBeCloseTo(3.940625, 13);
    expect(kurtosis([...XS], { excess: true })).toBeCloseTo(0.940625, 13);
  });

  it('differs from the default by exactly 3', () => {
    const nonExcess = kurtosis([...XS]) ?? 0;
    const excess = kurtosis([...XS], { excess: true }) ?? 0;
    expect(nonExcess - excess).toBeCloseTo(3, 14);
  });

  it('matches a second reference case with an extreme outlier', () => {
    // scipy.stats.kurtosis([1,2,3,4,100], bias=False) = 4.986865957200654 (excess)
    expect(kurtosis([1, 2, 3, 4, 100], { excess: true })).toBeCloseTo(4.986865957200654, 12);
    expect(kurtosis([1, 2, 3, 4, 100])).toBeCloseTo(7.986865957200654, 12);
  });

  it('is scale and location invariant', () => {
    const base = kurtosis([...XS]) ?? 0;
    expect(kurtosis(XS.map((x) => x * -3 + 50)) ?? 0).toBeCloseTo(base, 12);
  });

  it('returns null below n = 4, because the (n-3) adjustment is undefined', () => {
    expect(kurtosis([])).toBeNull();
    expect(kurtosis([1])).toBeNull();
    expect(kurtosis([1, 2])).toBeNull();
    expect(kurtosis([1, 2, 3])).toBeNull();
    expect(kurtosis([1, 2, 3, 4])).not.toBeNull();
  });

  it('returns null, not NaN, for a constant series (m2 = 0)', () => {
    expect(kurtosis([7, 7, 7, 7, 7])).toBeNull();
  });

  it('returns null on non-finite input', () => {
    expect(kurtosis([1, 2, 3, Number.POSITIVE_INFINITY])).toBeNull();
  });

  it('sits near 3 (non-excess) for a large normal-ish sample', () => {
    // Sanity anchor for the default convention: normal kurtosis is 3, not 0.
    const xs: number[] = [];
    for (let i = 1; i <= 4001; i += 1) xs.push(Math.cos(i) + Math.cos(i * 1.7) + Math.cos(i * 2.9));
    const k = kurtosis(xs) ?? 0;
    expect(k).toBeGreaterThan(2);
    expect(k).toBeLessThan(4);
  });
});

describe('sum', () => {
  it('adds up the series', () => {
    expect(sum([...XS])).toBe(40);
    expect(sum([])).toBe(0);
  });

  it('returns null on non-finite input', () => {
    expect(sum([1, Number.NaN])).toBeNull();
  });
});

describe('extent', () => {
  it('returns the minimum and maximum', () => {
    expect(extent([...XS])).toEqual({ min: 2, max: 9 });
    expect(extent([5])).toEqual({ min: 5, max: 5 });
  });

  it('returns null on empty or non-finite input', () => {
    expect(extent([])).toBeNull();
    expect(extent([1, Number.NaN])).toBeNull();
  });

  it('handles arrays far beyond the spread-argument limit', () => {
    const xs = Array.from({ length: 300_000 }, (_, i) => (i * 37) % 1009);
    const result = extent(xs);
    expect(result).not.toBeNull();
    expect(result?.min).toBe(0);
    expect(result?.max).toBe(1008);
  });
});
