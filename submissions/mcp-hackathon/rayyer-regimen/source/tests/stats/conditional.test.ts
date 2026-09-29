/**
 * Regime attribution.
 *
 * The central test is the planted-edge one: a synthetic series where one bucket
 * and only one bucket carries the performance. The engine has to find it, and
 * it has to keep reporting the thin buckets while flagging them as
 * insufficient — suppressing them is the failure mode this module exists to
 * prevent.
 */

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_MIN_SAMPLE,
  bucketize,
  compareBuckets,
  conditionalStats,
  type BucketStats,
} from '../../src/lib/stats/conditional';
import { seededNormals, unwrap } from './support';

describe('bucketize', () => {
  it('uses left-closed, right-open intervals with open outer edges', () => {
    // edges [0, 1] with labels [neg, mid, pos]:
    //   v < 0        -> neg
    //   0 <= v < 1   -> mid
    //   1 <= v       -> pos
    const value = unwrap(bucketize([-1, -0.0001, 0, 0.5, 0.9999, 1, 2], [0, 1], ['neg', 'mid', 'pos']));
    expect(value.labels).toEqual(['neg', 'neg', 'mid', 'mid', 'mid', 'pos', 'pos']);
    expect(value.counts).toEqual({ neg: 2, mid: 3, pos: 2 });
    expect(value.assigned).toBe(7);
    expect(value.unassigned).toBe(0);
  });

  it('places an exact edge value in the bucket ABOVE the edge', () => {
    const value = unwrap(bucketize([0.02], [0.01, 0.02, 0.03], ['a', 'b', 'c', 'd']));
    expect(value.labels).toEqual(['c']);
  });

  it('handles a single edge (two buckets)', () => {
    const value = unwrap(bucketize([-5, 5], [0], ['down', 'up']));
    expect(value.labels).toEqual(['down', 'up']);
  });

  it('handles zero edges (one bucket swallowing everything)', () => {
    const value = unwrap(bucketize([-5, 0, 5], [], ['all']));
    expect(value.labels).toEqual(['all', 'all', 'all']);
    expect(value.counts).toEqual({ all: 3 });
  });

  it('merges duplicate labels into a single bucket', () => {
    // Both tails map to "extreme"; the middle is its own regime.
    const value = unwrap(
      bucketize([-10, 0, 10], [-1, 1], ['extreme', 'calm', 'extreme']),
    );
    expect(value.labels).toEqual(['extreme', 'calm', 'extreme']);
    expect(value.counts.extreme).toBe(2);
  });

  it('maps non-finite values to null instead of voiding the whole analysis', () => {
    const value = unwrap(
      bucketize([1, Number.NaN, 3, Number.POSITIVE_INFINITY], [2], ['low', 'high']),
    );
    expect(value.labels).toEqual(['low', null, 'high', null]);
    expect(value.assigned).toBe(2);
    expect(value.unassigned).toBe(2);
  });

  it('returns an empty labelling for an empty value list', () => {
    const value = unwrap(bucketize([], [0], ['a', 'b']));
    expect(value.labels).toEqual([]);
    expect(value.assigned).toBe(0);
  });

  it('rejects a label count that does not match the edges', () => {
    const tooFew = bucketize([1], [0, 1], ['a', 'b']);
    expect(tooFew.ok).toBe(false);
    expect(tooFew.ok ? null : tooFew.reason).toBe('invalid_parameter');
    expect(bucketize([1], [0], ['a', 'b', 'c']).ok).toBe(false);
  });

  it('rejects non-ascending or non-finite edges', () => {
    expect(bucketize([1], [1, 0], ['a', 'b', 'c']).ok).toBe(false);
    expect(bucketize([1], [0, 0], ['a', 'b', 'c']).ok).toBe(false);
    expect(bucketize([1], [0, Number.NaN], ['a', 'b', 'c']).ok).toBe(false);
  });

  it('rejects empty label strings', () => {
    const result = bucketize([1], [0], ['', 'b']);
    expect(result.ok ? null : result.reason).toBe('invalid_parameter');
  });
});

describe('conditionalStats', () => {
  it('splits a series by label and reports per-bucket statistics', () => {
    const returns = [0.01, -0.02, 0.03, 0.04, -0.01, 0.02];
    const labels = ['a', 'a', 'a', 'b', 'b', 'b'];
    const value = unwrap(conditionalStats({ returns, labels, minSample: 3 }));
    expect(value.buckets).toHaveLength(2);
    const [a, b] = value.buckets as [BucketStats, BucketStats];
    expect(a.label).toBe('a');
    expect(a.count).toBe(3);
    expect(a.mean).toBeCloseTo((0.01 - 0.02 + 0.03) / 3, 15);
    expect(a.sumReturns).toBeCloseTo(0.02, 15);
    expect(a.wins).toBe(2);
    expect(a.winRate).toBeCloseTo(2 / 3, 15);
    expect(a.sufficient).toBe(true);
    expect(b.label).toBe('b');
    expect(b.count).toBe(3);
  });

  it('sorts buckets by label so the output order is deterministic', () => {
    const returns = [0.01, 0.02, 0.03];
    const value = unwrap(conditionalStats({ returns, labels: ['zulu', 'alpha', 'mike'], minSample: 1 }));
    expect(value.buckets.map((b) => b.label)).toEqual(['alpha', 'mike', 'zulu']);
  });

  it('FINDS A PLANTED EDGE: the bucket carrying the alpha ranks best', () => {
    // 600 periods. The regime value drives the label; the "storm" regime is
    // given a +0.6% per-period mean on top of the same 1% volatility (a true
    // per-period Sharpe of 0.6 against 0), everything else is drawn from the
    // same zero-mean distribution.
    const n = 600;
    const noise = seededNormals(n, 0, 0.01, 90_210);
    const regime = seededNormals(n, 0, 1, 555);
    const returns: number[] = [];
    const labels: string[] = [];
    for (let i = 0; i < n; i += 1) {
      const isStorm = (regime[i] ?? 0) > 0;
      labels.push(isStorm ? 'storm' : 'calm');
      returns.push((noise[i] ?? 0) + (isStorm ? 0.006 : 0));
    }

    const stats = unwrap(conditionalStats({ returns, labels, minSample: 20 }));
    const storm = stats.buckets.find((b) => b.label === 'storm');
    const calm = stats.buckets.find((b) => b.label === 'calm');
    expect(storm).toBeDefined();
    expect(calm).toBeDefined();
    expect(storm?.sufficient).toBe(true);
    expect(calm?.sufficient).toBe(true);
    expect(storm?.mean ?? 0).toBeGreaterThan(calm?.mean ?? 0);
    expect(storm?.sharpe ?? 0).toBeGreaterThan(calm?.sharpe ?? 0);
    expect(storm?.winRate ?? 0).toBeGreaterThan(calm?.winRate ?? 0);

    const comparison = unwrap(compareBuckets(stats.buckets));
    expect(comparison.best?.label).toBe('storm');
    expect(comparison.worst?.label).toBe('calm');
    // True spread is 0.6; the sampling error on each bucket's Sharpe is about
    // 1/sqrt(300) = 0.06, so 0.35 is a comfortable floor rather than a fitted one.
    expect(comparison.sharpeSpread ?? 0).toBeGreaterThan(0.35);
  });

  it('KEEPS THIN BUCKETS, flagged insufficient, instead of hiding them', () => {
    const returns = [...seededNormals(60, 0.001, 0.01, 4321), 0.5, 0.4, 0.6];
    const labels = [...new Array<string>(60).fill('normal'), 'crisis', 'crisis', 'crisis'];
    const stats = unwrap(conditionalStats({ returns, labels, minSample: 20 }));

    const crisis = stats.buckets.find((b) => b.label === 'crisis');
    expect(crisis).toBeDefined();
    expect(crisis?.count).toBe(3);
    expect(crisis?.sufficient).toBe(false);
    // Thin, but fully populated: the numbers are there to be shown next to the warning.
    expect(crisis?.mean).not.toBeNull();
    expect(crisis?.sharpe).not.toBeNull();
    expect(crisis?.winRateInterval).not.toBeNull();
    expect(crisis?.winRateInterval?.upper ?? 0).toBeGreaterThan(crisis?.winRateInterval?.lower ?? 1);

    const normal = stats.buckets.find((b) => b.label === 'normal');
    expect(normal?.sufficient).toBe(true);

    const comparison = unwrap(compareBuckets(stats.buckets));
    // Excluded from RANKING but present in the contribution table.
    expect(comparison.insufficientCount).toBe(1);
    expect(comparison.contributions.map((c) => c.label).sort()).toEqual(['crisis', 'normal']);
    expect(comparison.best?.label).toBe('normal');
  });

  it('gives a single-observation bucket a wide but defined Wilson interval and no Sharpe', () => {
    const returns = [0.01, 0.02, 0.03, -0.5];
    const labels = ['a', 'a', 'a', 'lonely'];
    const stats = unwrap(conditionalStats({ returns, labels, minSample: 2 }));
    const lonely = stats.buckets.find((b) => b.label === 'lonely');
    expect(lonely?.count).toBe(1);
    expect(lonely?.mean).toBeCloseTo(-0.5, 15);
    expect(lonely?.stdDev).toBeNull();
    expect(lonely?.sharpe).toBeNull();
    expect(lonely?.sharpeReason).toBe('insufficient_sample');
    expect(lonely?.winRate).toBe(0);
    expect(lonely?.winRateInterval?.upper ?? 0).toBeGreaterThan(0.5);
    expect(lonely?.sufficient).toBe(false);
  });

  it('reports a zero-variance bucket with a reason rather than an infinite Sharpe', () => {
    const returns = [0.01, 0.01, 0.01, 0.02, -0.03];
    const labels = ['flat', 'flat', 'flat', 'other', 'other'];
    const stats = unwrap(conditionalStats({ returns, labels, minSample: 2 }));
    const flat = stats.buckets.find((b) => b.label === 'flat');
    expect(flat?.stdDev).toBe(0);
    expect(flat?.sharpe).toBeNull();
    expect(flat?.sharpeReason).toBe('zero_variance');
  });

  it('excludes null-labelled observations and counts them', () => {
    const returns = [0.01, 0.02, 0.03, 0.04];
    const labels = ['a', null, 'a', null];
    const stats = unwrap(conditionalStats({ returns, labels, minSample: 1 }));
    expect(stats.labelled).toBe(2);
    expect(stats.unlabelled).toBe(2);
    expect(stats.buckets).toHaveLength(1);
    expect(stats.buckets[0]?.count).toBe(2);
    expect(stats.overall.count).toBe(2);
  });

  it('compounds totalReturn multiplicatively for simple returns', () => {
    const returns = [0.1, 0.1];
    const stats = unwrap(conditionalStats({ returns, labels: ['a', 'a'], minSample: 1 }));
    expect(stats.buckets[0]?.totalReturn).toBeCloseTo(0.21, 14);
    expect(stats.overall.totalReturn).toBeCloseTo(0.21, 14);
  });

  it('uses the additive identity for log returns', () => {
    const returns = [Math.log(1.1), Math.log(1.1)];
    const stats = unwrap(
      conditionalStats({ returns, labels: ['a', 'a'], minSample: 1, returnKind: 'log' }),
    );
    expect(stats.buckets[0]?.totalReturn).toBeCloseTo(0.21, 13);
  });

  it('applies a per-period risk-free rate to every bucket Sharpe', () => {
    const returns = [0.01, 0.02, 0.03, 0.04];
    const labels = ['a', 'a', 'a', 'a'];
    const withoutRf = unwrap(conditionalStats({ returns, labels, minSample: 1 }));
    const withRf = unwrap(conditionalStats({ returns, labels, minSample: 1, riskFreePerPeriod: 0.01 }));
    expect(withRf.buckets[0]?.sharpe ?? 0).toBeLessThan(withoutRf.buckets[0]?.sharpe ?? 0);
  });

  it('defaults minSample to the documented constant', () => {
    const returns = seededNormals(DEFAULT_MIN_SAMPLE - 1, 0, 0.01, 1);
    const labels = new Array<string>(returns.length).fill('a');
    const stats = unwrap(conditionalStats({ returns, labels }));
    expect(stats.minSample).toBe(DEFAULT_MIN_SAMPLE);
    expect(stats.buckets[0]?.sufficient).toBe(false);
  });

  it('fails with length_mismatch when the arrays disagree', () => {
    const result = conditionalStats({ returns: [0.1, 0.2], labels: ['a'] });
    expect(result.ok).toBe(false);
    expect(result.value).toBeNull();
    expect(result.ok ? null : result.reason).toBe('length_mismatch');
  });

  it('fails with empty_input on an empty series', () => {
    const result = conditionalStats({ returns: [], labels: [] });
    expect(result.ok ? null : result.reason).toBe('empty_input');
  });

  it('fails with non_finite_input on a bad return', () => {
    const result = conditionalStats({ returns: [0.1, Number.NaN], labels: ['a', 'a'] });
    expect(result.ok ? null : result.reason).toBe('non_finite_input');
  });

  it('rejects a negative or fractional minSample', () => {
    expect(conditionalStats({ returns: [0.1], labels: ['a'], minSample: -1 }).ok).toBe(false);
    expect(conditionalStats({ returns: [0.1], labels: ['a'], minSample: 2.5 }).ok).toBe(false);
  });

  it('rejects a confidence outside (0, 1)', () => {
    const result = conditionalStats({ returns: [0.1], labels: ['a'], confidence: 1 });
    expect(result.ok ? null : result.reason).toBe('invalid_parameter');
  });

  it('never produces NaN in any bucket field', () => {
    const returns = [0.01, 0, -0.01, 0, 0.02];
    const labels = ['a', 'a', 'b', 'b', 'c'];
    const stats = unwrap(conditionalStats({ returns, labels, minSample: 2 }));
    for (const bucket of stats.buckets) {
      for (const v of [bucket.mean, bucket.stdDev, bucket.sharpe, bucket.winRate, bucket.totalReturn]) {
        if (v !== null) expect(Number.isFinite(v)).toBe(true);
      }
      expect(Number.isFinite(bucket.sumReturns)).toBe(true);
    }
  });
});

describe('compareBuckets', () => {
  /**
   * Fixture builder. Uses an explicit `undefined` check rather than `??` so a
   * deliberate `null` override (an undefined Sharpe, say) is not silently
   * replaced by the default.
   */
  function bucket(overrides: Partial<BucketStats> & { label: string }): BucketStats {
    const pick = <K extends keyof BucketStats>(key: K, fallback: BucketStats[K]): BucketStats[K] =>
      overrides[key] === undefined ? fallback : (overrides[key] as BucketStats[K]);
    return {
      label: overrides.label,
      count: pick('count', 100),
      mean: pick('mean', 0.001),
      stdDev: pick('stdDev', 0.01),
      sharpe: pick('sharpe', 0.1),
      sharpeReason: pick('sharpeReason', null),
      wins: pick('wins', 55),
      winRate: pick('winRate', 0.55),
      winRateInterval: pick('winRateInterval', { lower: 0.45, upper: 0.65 }),
      totalReturn: pick('totalReturn', 0.1),
      sumReturns: pick('sumReturns', 0.1),
      sufficient: pick('sufficient', true),
    };
  }

  it('reports the spread between the best and worst SUFFICIENT bucket', () => {
    const stats = [
      bucket({ label: 'good', sharpe: 0.3, mean: 0.003 }),
      bucket({ label: 'bad', sharpe: -0.1, mean: -0.001 }),
      bucket({ label: 'thin', sharpe: 9, mean: 9, count: 2, sufficient: false }),
    ];
    const value = unwrap(compareBuckets(stats));
    expect(value.best?.label).toBe('good');
    expect(value.worst?.label).toBe('bad');
    expect(value.sharpeSpread).toBeCloseTo(0.4, 14);
    expect(value.meanSpread).toBeCloseTo(0.004, 14);
    expect(value.sufficientCount).toBe(2);
    expect(value.insufficientCount).toBe(1);
    expect(value.rankableCount).toBe(2);
  });

  it('excludes buckets with an undefined Sharpe from ranking', () => {
    const stats = [
      bucket({ label: 'a', sharpe: 0.2 }),
      bucket({ label: 'flat', sharpe: null, sharpeReason: 'zero_variance' }),
    ];
    const value = unwrap(compareBuckets(stats));
    expect(value.rankableCount).toBe(1);
    expect(value.sharpeSpread).toBeNull();
    expect(value.meanSpread).toBeNull();
  });

  it('returns null spreads when fewer than two buckets are rankable', () => {
    const value = unwrap(compareBuckets([bucket({ label: 'only' })]));
    expect(value.sharpeSpread).toBeNull();
    expect(value.worst).toBeNull();
  });

  it('warns when one bucket accounts for most of the total return', () => {
    const stats = [
      bucket({ label: 'hero', sumReturns: 0.9 }),
      bucket({ label: 'rest', sumReturns: 0.1 }),
    ];
    const value = unwrap(compareBuckets(stats));
    expect(value.concentrationWarning).toBe(true);
    expect(value.topContributor?.label).toBe('hero');
    expect(value.topContributor?.share).toBeCloseTo(0.9, 14);
    expect(value.totalSumReturns).toBeCloseTo(1, 14);
  });

  it('does not warn when returns are evenly spread', () => {
    const stats = [
      bucket({ label: 'a', sumReturns: 0.34 }),
      bucket({ label: 'b', sumReturns: 0.33 }),
      bucket({ label: 'c', sumReturns: 0.33 }),
    ];
    const value = unwrap(compareBuckets(stats));
    expect(value.concentrationWarning).toBe(false);
    expect(value.topContributor?.share ?? 1).toBeLessThan(0.6);
  });

  it('respects a custom concentration threshold', () => {
    const stats = [
      bucket({ label: 'a', sumReturns: 0.55 }),
      bucket({ label: 'b', sumReturns: 0.45 }),
    ];
    expect(unwrap(compareBuckets(stats)).concentrationWarning).toBe(false);
    expect(
      unwrap(compareBuckets(stats, { concentrationThreshold: 0.5 })).concentrationWarning,
    ).toBe(true);
  });

  it('never warns on a single bucket, whose share is trivially 1', () => {
    const value = unwrap(compareBuckets([bucket({ label: 'only', sumReturns: 1 })]));
    expect(value.concentrationWarning).toBe(false);
  });

  it('leaves shares undefined on a losing track record instead of flipping their sign', () => {
    const stats = [
      bucket({ label: 'a', sumReturns: -0.5 }),
      bucket({ label: 'b', sumReturns: 0.1 }),
    ];
    const value = unwrap(compareBuckets(stats));
    expect(value.totalSumReturns).toBeCloseTo(-0.4, 14);
    expect(value.topContributor).toBeNull();
    expect(value.concentrationWarning).toBe(false);
    for (const contribution of value.contributions) expect(contribution.share).toBeNull();
  });

  it('sorts contributions by size descending', () => {
    const stats = [
      bucket({ label: 'small', sumReturns: 0.1 }),
      bucket({ label: 'big', sumReturns: 0.7 }),
      bucket({ label: 'medium', sumReturns: 0.2 }),
    ];
    const value = unwrap(compareBuckets(stats));
    expect(value.contributions.map((c) => c.label)).toEqual(['big', 'medium', 'small']);
  });

  it('fails with empty_input on no buckets', () => {
    const result = compareBuckets([]);
    expect(result.ok).toBe(false);
    expect(result.ok ? null : result.reason).toBe('empty_input');
  });

  it('rejects a threshold outside (0, 1]', () => {
    const stats = [bucket({ label: 'a' })];
    expect(compareBuckets(stats, { concentrationThreshold: 0 }).ok).toBe(false);
    expect(compareBuckets(stats, { concentrationThreshold: 1.5 }).ok).toBe(false);
    expect(compareBuckets(stats, { concentrationThreshold: 1 }).ok).toBe(true);
  });
});
