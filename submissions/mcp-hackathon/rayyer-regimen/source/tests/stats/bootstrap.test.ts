/**
 * Stationary bootstrap and percentile confidence intervals.
 *
 * Reproducibility is the headline property here, so it is asserted from both
 * directions: same seed must be bit-for-bit identical, different seed must
 * actually differ. A bootstrap that quietly ignores its seed would pass only
 * the first half.
 */

import { describe, expect, it } from 'vitest';

import { bootstrapCI, optimalBlockLength, stationaryBootstrap } from '../../src/lib/stats/bootstrap';
import { mean, stdDev } from '../../src/lib/stats/moments';
import { seededNormals, unwrap } from './support';

const SERIES = seededNormals(200, 0.001, 0.01, 20_240_101);

describe('stationaryBootstrap', () => {
  it('produces the requested number of resamples, each the length of the series', () => {
    const value = unwrap(
      stationaryBootstrap(SERIES, { blockMeanLength: 10, resamples: 25, seed: 7 }),
    );
    expect(value.indices).toHaveLength(25);
    for (const row of value.indices) expect(row).toHaveLength(SERIES.length);
  });

  it('only emits in-range integer indices', () => {
    const value = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 8, resamples: 40, seed: 3 }));
    for (const row of value.indices) {
      for (const index of row) {
        expect(Number.isInteger(index)).toBe(true);
        expect(index).toBeGreaterThanOrEqual(0);
        expect(index).toBeLessThan(SERIES.length);
      }
    }
  });

  it('echoes its settings, including the derived restart probability', () => {
    const value = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 4, resamples: 2, seed: 11 }));
    expect(value.n).toBe(SERIES.length);
    expect(value.blockMeanLength).toBe(4);
    expect(value.seed).toBe(11);
    expect(value.restartProbability).toBe(0.25);
  });

  it('is bit-for-bit identical for the same seed', () => {
    const a = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 6, resamples: 30, seed: 4242 }));
    const b = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 6, resamples: 30, seed: 4242 }));
    expect(a.indices).toEqual(b.indices);
  });

  it('differs for a different seed', () => {
    const a = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 6, resamples: 30, seed: 1 }));
    const b = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 6, resamples: 30, seed: 2 }));
    expect(a.indices).not.toEqual(b.indices);
  });

  it('wraps around circularly instead of truncating blocks at the end', () => {
    // With an enormous mean block length the restart probability is ~0, so each
    // resample must be one contiguous circular block: indices[t] = (start + t) mod n.
    const n = SERIES.length;
    const value = unwrap(
      stationaryBootstrap(SERIES, { blockMeanLength: 1e9, resamples: 5, seed: 99 }),
    );
    for (const row of value.indices) {
      const start = row[0] ?? 0;
      for (let t = 0; t < n; t += 1) {
        expect(row[t]).toBe((start + t) % n);
      }
    }
    // At least one resample must actually have started away from 0 and hence
    // run off the end of the series, or the wrap-around was never exercised.
    const someRowWrapped = value.indices.some((row) => (row[0] ?? 0) > 0);
    expect(someRowWrapped).toBe(true);
  });

  it('degenerates to the IID bootstrap at blockMeanLength = 1', () => {
    // p = 1 means every step starts a new block, so the probability that index
    // t continues index t-1 is 1/n rather than ~1.
    const n = SERIES.length;
    const value = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 1, resamples: 50, seed: 5 }));
    let continuations = 0;
    let steps = 0;
    for (const row of value.indices) {
      for (let t = 1; t < row.length; t += 1) {
        steps += 1;
        if (row[t] === (((row[t - 1] ?? 0) + 1) % n)) continuations += 1;
      }
    }
    expect(continuations / steps).toBeLessThan(0.05);
  });

  it('preserves short-range dependence at a large mean block length', () => {
    const n = SERIES.length;
    const value = unwrap(stationaryBootstrap(SERIES, { blockMeanLength: 20, resamples: 50, seed: 5 }));
    let continuations = 0;
    let steps = 0;
    for (const row of value.indices) {
      for (let t = 1; t < row.length; t += 1) {
        steps += 1;
        if (row[t] === (((row[t - 1] ?? 0) + 1) % n)) continuations += 1;
      }
    }
    // Expected continuation rate is 1 - p + p/n = 0.95 + 0.00025.
    expect(continuations / steps).toBeGreaterThan(0.9);
    expect(continuations / steps).toBeLessThan(0.99);
  });

  it('rejects degenerate inputs with typed reasons rather than throwing', () => {
    const cases: Array<[readonly number[], number, number, number, string]> = [
      [[], 4, 10, 1, 'empty_input'],
      [[0.1], 4, 10, 1, 'insufficient_sample'],
      [SERIES, 0.5, 10, 1, 'invalid_parameter'],
      [SERIES, Number.NaN, 10, 1, 'invalid_parameter'],
      [SERIES, 4, 0, 1, 'invalid_parameter'],
      [SERIES, 4, 2.5, 1, 'invalid_parameter'],
      [SERIES, 4, 10, Number.NaN, 'invalid_parameter'],
    ];
    for (const [series, blockMeanLength, resamples, seed, reason] of cases) {
      const result = stationaryBootstrap(series, { blockMeanLength, resamples, seed });
      expect(result.ok).toBe(false);
      expect(result.value).toBeNull();
      expect(result.ok ? null : result.reason).toBe(reason);
    }
  });

  it('never mutates the input series', () => {
    const input = [...SERIES];
    stationaryBootstrap(input, { blockMeanLength: 5, resamples: 10, seed: 1 });
    expect(input).toEqual(SERIES);
  });
});

describe('optimalBlockLength', () => {
  it('follows the documented n^(1/3) heuristic', () => {
    expect(optimalBlockLength(new Array<number>(1000).fill(0))).toBe(10);
    expect(optimalBlockLength(new Array<number>(8).fill(0))).toBe(2);
    expect(optimalBlockLength(new Array<number>(27).fill(0))).toBe(3);
  });

  it('clamps to at least 1 and at most n', () => {
    expect(optimalBlockLength([1])).toBe(1);
    expect(optimalBlockLength([1, 2])).toBe(1);
  });

  it('returns null for an empty series', () => {
    expect(optimalBlockLength([])).toBeNull();
  });
});

describe('bootstrapCI', () => {
  const statistic = (sample: number[]): number | null => mean(sample);

  it('brackets the point estimate and reports its provenance', () => {
    const ci = unwrap(bootstrapCI(SERIES, statistic, { seed: 2024, resamples: 500 }));
    expect(ci.method).toBe('percentile');
    expect(ci.level).toBe(0.95);
    expect(ci.resamples).toBe(500);
    expect(ci.seed).toBe(2024);
    expect(ci.usableResamples).toBe(500);
    expect(ci.pointEstimate).toBeCloseTo(mean(SERIES) ?? 0, 15);
    expect(ci.lower).toBeLessThan(ci.upper);
    expect(ci.lower).toBeLessThanOrEqual(ci.pointEstimate);
    expect(ci.upper).toBeGreaterThanOrEqual(ci.pointEstimate);
  });

  it('is bit-for-bit reproducible for the same seed', () => {
    const a = unwrap(bootstrapCI(SERIES, statistic, { seed: 777, resamples: 300 }));
    const b = unwrap(bootstrapCI(SERIES, statistic, { seed: 777, resamples: 300 }));
    expect(a).toEqual(b);
    expect(a.lower).toBe(b.lower);
    expect(a.upper).toBe(b.upper);
  });

  it('produces different bounds for a different seed', () => {
    const a = unwrap(bootstrapCI(SERIES, statistic, { seed: 1, resamples: 300 }));
    const b = unwrap(bootstrapCI(SERIES, statistic, { seed: 2, resamples: 300 }));
    expect(a.lower).not.toBe(b.lower);
    expect(a.upper).not.toBe(b.upper);
    // but the point estimate is seed-independent by construction
    expect(a.pointEstimate).toBe(b.pointEstimate);
  });

  it('widens as the coverage level rises', () => {
    const narrow = unwrap(bootstrapCI(SERIES, statistic, { seed: 5, resamples: 800, level: 0.5 }));
    const wide = unwrap(bootstrapCI(SERIES, statistic, { seed: 5, resamples: 800, level: 0.99 }));
    expect(wide.upper - wide.lower).toBeGreaterThan(narrow.upper - narrow.lower);
  });

  it('roughly matches the analytic standard error for the mean of an IID series', () => {
    // Sanity anchor rather than a coverage proof: with blockMeanLength = 1 the
    // resampling is IID, so the 95% percentile interval half-width should sit
    // near 1.96 * sd / sqrt(n).
    const n = SERIES.length;
    const analyticHalfWidth = (1.959963984540054 * (stdDev(SERIES) ?? 0)) / Math.sqrt(n);
    const ci = unwrap(
      bootstrapCI(SERIES, statistic, { seed: 31337, resamples: 2000, blockMeanLength: 1 }),
    );
    const bootstrapHalfWidth = (ci.upper - ci.lower) / 2;
    expect(bootstrapHalfWidth).toBeGreaterThan(analyticHalfWidth * 0.75);
    expect(bootstrapHalfWidth).toBeLessThan(analyticHalfWidth * 1.25);
  });

  it('defaults the block length to the n^(1/3) heuristic', () => {
    const ci = unwrap(bootstrapCI(SERIES, statistic, { seed: 9, resamples: 100 }));
    expect(ci.blockMeanLength).toBe(optimalBlockLength(SERIES));
  });

  it('works on a statistic that is not the mean', () => {
    const ci = unwrap(
      bootstrapCI(SERIES, (sample) => stdDev(sample), { seed: 12, resamples: 400 }),
    );
    expect(ci.pointEstimate).toBeCloseTo(stdDev(SERIES) ?? 0, 15);
    expect(ci.lower).toBeGreaterThan(0);
  });

  it('drops replicates where the statistic is undefined, and reports how many survived', () => {
    // Undefined on every other call: the interval should still be built from
    // the survivors rather than poisoned with nulls.
    let calls = 0;
    const flaky = (sample: number[]): number | null => {
      calls += 1;
      return calls % 2 === 0 ? null : mean(sample);
    };
    const ci = unwrap(bootstrapCI(SERIES, flaky, { seed: 4, resamples: 200 }));
    expect(ci.usableResamples).toBeGreaterThan(50);
    expect(ci.usableResamples).toBeLessThan(200);
  });

  it('fails with undefined_statistic when the statistic is undefined on the original series', () => {
    const result = bootstrapCI(SERIES, () => null, { seed: 1, resamples: 10 });
    expect(result.ok).toBe(false);
    expect(result.ok ? null : result.reason).toBe('undefined_statistic');
  });

  it('fails with undefined_statistic when the statistic returns a non-finite number', () => {
    const result = bootstrapCI(SERIES, () => Number.POSITIVE_INFINITY, { seed: 1, resamples: 10 });
    expect(result.ok ? null : result.reason).toBe('undefined_statistic');
  });

  it('rejects a level outside (0, 1)', () => {
    for (const level of [0, 1, -0.5, 2, Number.NaN]) {
      const result = bootstrapCI(SERIES, statistic, { seed: 1, resamples: 10, level });
      expect(result.ok).toBe(false);
      expect(result.ok ? null : result.reason).toBe('invalid_parameter');
    }
  });

  it('propagates the underlying bootstrap failure for degenerate series', () => {
    expect(bootstrapCI([], statistic, { seed: 1 }).ok).toBe(false);
    const single = bootstrapCI([0.01], statistic, { seed: 1 });
    expect(single.ok ? null : single.reason).toBe('insufficient_sample');
  });

  it('collapses to a point interval for a constant series', () => {
    const constant = new Array<number>(50).fill(0.02);
    const ci = unwrap(bootstrapCI(constant, statistic, { seed: 8, resamples: 200 }));
    expect(ci.lower).toBeCloseTo(0.02, 15);
    expect(ci.upper).toBeCloseTo(0.02, 15);
  });

  it('never returns NaN or Infinity', () => {
    const ci = unwrap(bootstrapCI(SERIES, statistic, { seed: 6, resamples: 250 }));
    for (const v of [ci.pointEstimate, ci.lower, ci.upper, ci.level, ci.blockMeanLength]) {
      expect(Number.isFinite(v)).toBe(true);
    }
  });
});
