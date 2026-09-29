/**
 * Public surface and package-wide invariants.
 *
 * The two contracts stated in `index.ts` are enforced here as a sweep rather
 * than one assertion at a time: nothing throws on user-shaped data, and no
 * public function returns NaN or Infinity anywhere in its payload.
 */

import { describe, expect, it } from 'vitest';

import * as stats from '../../src/lib/stats';
import { fail, isOk, ok, valueOrNull, type StatsResult } from '../../src/lib/stats/result';
import { nonFinitePaths, seededNormals, unwrap } from './support';

/** Inputs that a real upload has produced at some point. */
const HOSTILE_RETURN_SERIES: ReadonlyArray<readonly number[]> = [
  [],
  [0.01],
  [0, 0],
  [0.01, 0.01, 0.01, 0.01, 0.01],
  [-1, -1, -1],
  [Number.NaN],
  [0.01, Number.NaN, 0.02],
  [Number.POSITIVE_INFINITY, 1],
  [Number.NEGATIVE_INFINITY],
  [1e-300, -1e-300],
  [1e300, -1e300],
  [0.5, -0.5, 0.5, -0.5],
  seededNormals(50, 0, 0.01, 1),
  seededNormals(3, 0.5, 2, 2),
];

const HOSTILE_EQUITY_CURVES: ReadonlyArray<readonly number[]> = [
  [],
  [100],
  [0],
  [-100, 50],
  [100, 0, 50],
  [100, Number.NaN],
  [100, Number.POSITIVE_INFINITY],
  [1e-300, 1e300],
  [100, 100, 100],
  [100, 1],
];

describe('barrel exports', () => {
  const expected = [
    // result envelope
    'fail',
    'isOk',
    'ok',
    'valueOrNull',
    // numeric
    'erf',
    'erfc',
    'mulberry32',
    'normalCdf',
    'normalInv',
    'normalPdf',
    // moments
    'extent',
    'kurtosis',
    'mean',
    'skewness',
    'stdDev',
    'sum',
    'variance',
    // returns
    'IRREGULAR_SPACING_FRACTION',
    'MS_PER_YEAR',
    'SPACING_DEVIATION_TOLERANCE',
    'inferPeriodsPerYear',
    'toReturns',
    'totalReturn',
    // sharpe
    'EULER_MASCHERONI',
    'annualise',
    'deflatedSharpeRatio',
    'expectedMaximumSharpe',
    'minimumTrackRecordLength',
    'probabilisticSharpeRatio',
    'sharpeRatio',
    // bootstrap
    'bootstrapCI',
    'optimalBlockLength',
    'stationaryBootstrap',
    // drawdown
    'maxDrawdown',
    'ulcerIndex',
    // trades
    'tradeStats',
    'wilsonInterval',
    // conditional
    'DEFAULT_MIN_SAMPLE',
    'bucketize',
    'compareBuckets',
    'conditionalStats',
  ] as const;

  it.each(expected)('re-exports %s', (name) => {
    expect(stats).toHaveProperty(name);
  });

  it('exports nothing beyond the documented surface', () => {
    expect(Object.keys(stats).sort()).toEqual([...expected].sort());
  });

  it('uses named exports only (no default export)', () => {
    expect(Object.keys(stats)).not.toContain('default');
  });

  it('does not leak the internal helpers module', () => {
    expect(stats).not.toHaveProperty('at');
    expect(stats).not.toHaveProperty('quantileType7');
  });
});

describe('result helpers', () => {
  it('ok() wraps a value on the success branch', () => {
    const result = ok(42);
    expect(result.ok).toBe(true);
    expect(result.value).toBe(42);
    expect(isOk(result)).toBe(true);
    expect(valueOrNull(result)).toBe(42);
  });

  it('fail() pins value to null and carries a reason and a message', () => {
    const result: StatsResult<number> = fail('insufficient_sample', 'too short');
    expect(result.ok).toBe(false);
    expect(result.value).toBeNull();
    expect(isOk(result)).toBe(false);
    expect(valueOrNull(result)).toBeNull();
    expect(result.ok ? null : result.reason).toBe('insufficient_sample');
    expect(result.ok ? null : result.message).toBe('too short');
  });
});

describe('package invariant: nothing throws on user-shaped data', () => {
  it('survives hostile return series', () => {
    for (const returns of HOSTILE_RETURN_SERIES) {
      expect(() => {
        stats.sharpeRatio(returns);
        stats.mean(returns);
        stats.variance(returns);
        stats.stdDev(returns);
        stats.skewness(returns);
        stats.kurtosis(returns);
        stats.sum(returns);
        stats.extent(returns);
        stats.totalReturn(returns);
        stats.tradeStats(returns);
        stats.optimalBlockLength(returns);
        stats.stationaryBootstrap(returns, { blockMeanLength: 3, resamples: 5, seed: 1 });
        stats.bootstrapCI(returns, (s) => stats.mean(s), { seed: 1, resamples: 20 });
        stats.conditionalStats({
          returns,
          labels: returns.map(() => 'a'),
          minSample: 2,
        });
      }).not.toThrow();
    }
  });

  it('survives hostile equity curves', () => {
    for (const equity of HOSTILE_EQUITY_CURVES) {
      expect(() => {
        stats.maxDrawdown(equity);
        stats.ulcerIndex(equity);
        stats.toReturns(
          equity.map((e, i) => ({ t: i, equity: e })),
          { kind: 'simple' },
        );
        stats.toReturns(
          equity.map((e, i) => ({ t: i, equity: e })),
          { kind: 'log' },
        );
        stats.inferPeriodsPerYear(equity);
      }).not.toThrow();
    }
  });

  it('survives hostile Sharpe arguments', () => {
    const sharpes = [0, 0.1, -0.1, 1e6, -1e6, Number.NaN, Number.POSITIVE_INFINITY];
    const ns = [0, 1, 2, 1e9, Number.NaN];
    expect(() => {
      for (const sharpe of sharpes) {
        for (const n of ns) {
          stats.probabilisticSharpeRatio({ sharpe, n, skewness: -20, kurtosis: 100 });
          stats.minimumTrackRecordLength({ sharpe, skewness: 3, kurtosis: 0, confidence: 0.5 });
          stats.deflatedSharpeRatio({
            sharpe,
            n,
            skewness: 0,
            kurtosis: 3,
            trialSharpes: [0.1, 0.2, Number.NaN],
          });
          stats.annualise(sharpe, n);
        }
      }
    }).not.toThrow();
  });

  it('survives hostile bucketize and wilson arguments', () => {
    expect(() => {
      stats.bucketize([1, Number.NaN], [], []);
      stats.bucketize([1], [Number.NaN], ['a', 'b']);
      stats.bucketize([], [0], ['a', 'b']);
      stats.wilsonInterval(-1, 0, 0);
      stats.wilsonInterval(Number.NaN, Number.NaN, Number.NaN);
      stats.compareBuckets([]);
    }).not.toThrow();
  });
});

describe('package invariant: no public function returns NaN or Infinity', () => {
  function assertClean(result: StatsResult<unknown>, label: string): void {
    if (!result.ok) {
      expect(result.value).toBeNull();
      expect(typeof result.reason).toBe('string');
      expect(result.message.length).toBeGreaterThan(0);
      return;
    }
    const violations = nonFinitePaths(result.value);
    expect(violations, `${label}: ${violations.join(', ')}`).toEqual([]);
  }

  it('holds for every Sharpe-family result over hostile inputs', () => {
    const sharpes = [0, 0.05, -0.05, 2, -2, 50];
    const moments: ReadonlyArray<readonly [number, number]> = [
      [0, 3],
      [-5, 40],
      [5, 1],
      [0, 0],
      [-0.2, 4.4],
    ];
    for (const sharpe of sharpes) {
      for (const [skew, kurt] of moments) {
        for (const n of [2, 10, 1e6]) {
          assertClean(
            stats.probabilisticSharpeRatio({ sharpe, n, skewness: skew, kurtosis: kurt }),
            `psr(${sharpe},${n},${skew},${kurt})`,
          );
          assertClean(
            stats.minimumTrackRecordLength({ sharpe, skewness: skew, kurtosis: kurt }),
            `mintrl(${sharpe},${skew},${kurt})`,
          );
          assertClean(
            stats.deflatedSharpeRatio({
              sharpe,
              n,
              skewness: skew,
              kurtosis: kurt,
              trialSharpes: [0, 0.1, 0.2, -0.05],
            }),
            `dsr(${sharpe},${n},${skew},${kurt})`,
          );
        }
      }
    }
  });

  it('holds for every return-series result over hostile inputs', () => {
    for (const returns of HOSTILE_RETURN_SERIES) {
      assertClean(stats.sharpeRatio(returns), 'sharpeRatio');
      assertClean(stats.tradeStats(returns), 'tradeStats');
      assertClean(
        stats.bootstrapCI(returns, (s) => stats.mean(s), { seed: 1, resamples: 30 }),
        'bootstrapCI',
      );
      assertClean(
        stats.conditionalStats({ returns, labels: returns.map(() => 'a'), minSample: 2 }),
        'conditionalStats',
      );
      for (const value of [
        stats.mean(returns),
        stats.variance(returns),
        stats.stdDev(returns),
        stats.skewness(returns),
        stats.kurtosis(returns),
        stats.sum(returns),
        stats.totalReturn(returns),
      ]) {
        if (value !== null) expect(Number.isFinite(value)).toBe(true);
      }
    }
  });

  it('holds for every equity-curve result over hostile inputs', () => {
    for (const equity of HOSTILE_EQUITY_CURVES) {
      assertClean(stats.maxDrawdown(equity), 'maxDrawdown');
      assertClean(stats.ulcerIndex(equity), 'ulcerIndex');
      const series = stats.toReturns(
        equity.map((e, i) => ({ t: i, equity: e })),
        { kind: 'simple' },
      );
      expect(nonFinitePaths(series.returns)).toEqual([]);
      expect(nonFinitePaths(series.timestamps)).toEqual([]);
    }
  });

  it('holds for every Wilson interval over the full count grid', () => {
    for (let n = 1; n <= 25; n += 1) {
      for (let k = 0; k <= n; k += 1) {
        for (const confidence of [0.5, 0.9, 0.95, 0.99, 0.999]) {
          assertClean(stats.wilsonInterval(k, n, confidence), `wilson(${k},${n},${confidence})`);
        }
      }
    }
  });
});

describe('end-to-end: an equity curve all the way to a verdict', () => {
  it('runs the full pipeline and produces a coherent audit trail', () => {
    const DAY = 24 * 60 * 60 * 1000;
    // Per-period Sharpe of 0.0015/0.009 = 0.167 over 600 periods, i.e. z ~ 4.
    const returns = seededNormals(600, 0.0015, 0.009, 2_024_314);
    let level = 100;
    const points = [{ t: 0, equity: level }];
    for (let i = 0; i < returns.length; i += 1) {
      level *= 1 + (returns[i] ?? 0);
      points.push({ t: (i + 1) * DAY, equity: level });
    }

    const series = stats.toReturns(points, { kind: 'simple' });
    expect(series.returns).toHaveLength(600);
    expect(series.dropped).toHaveLength(0);

    const inference = stats.inferPeriodsPerYear(series.timestamps);
    expect(inference.periodsPerYear).toBeCloseTo(365.2425, 6);
    expect(inference.irregular).toBe(false);

    const sharpe = unwrap(stats.sharpeRatio(series.returns));
    expect(sharpe.perPeriod).toBe(true);

    const annual = unwrap(stats.annualise(sharpe.sharpe, inference.periodsPerYear ?? 1));
    expect(annual.annualisedSharpe).toBeCloseTo(
      sharpe.sharpe * Math.sqrt(inference.periodsPerYear ?? 1),
      12,
    );

    const g3 = stats.skewness(series.returns) ?? 0;
    const g4 = stats.kurtosis(series.returns) ?? 3;
    const psr = unwrap(
      stats.probabilisticSharpeRatio({ sharpe: sharpe.sharpe, n: series.returns.length, skewness: g3, kurtosis: g4 }),
    );
    expect(psr.psr).toBeGreaterThan(0.9);

    const trl = unwrap(
      stats.minimumTrackRecordLength({ sharpe: sharpe.sharpe, skewness: g3, kurtosis: g4 }),
    );
    // We already have 600 periods and PSR is above 95%, so minTRL must be under 600.
    expect(trl.periodsRequired).toBeLessThan(600);

    const dd = unwrap(stats.maxDrawdown(points.map((p) => p.equity)));
    expect(dd.maxDrawdown).toBeGreaterThan(0);
    expect(dd.maxDrawdown).toBeLessThan(1);
    expect(dd.troughIndex).toBeGreaterThan(dd.peakIndex);

    const ci = unwrap(
      stats.bootstrapCI(series.returns, (s) => stats.mean(s), { seed: 555, resamples: 400 }),
    );
    expect(ci.lower).toBeLessThan(ci.upper);

    const regime = seededNormals(600, 0, 1, 777);
    const labelling = unwrap(stats.bucketize(regime, [-0.5, 0.5], ['low', 'mid', 'high']));
    const conditional = unwrap(
      stats.conditionalStats({ returns: series.returns, labels: labelling.labels, minSample: 30 }),
    );
    expect(conditional.buckets).toHaveLength(3);
    expect(conditional.labelled).toBe(600);

    const comparison = unwrap(stats.compareBuckets(conditional.buckets));
    expect(comparison.sufficientCount).toBe(3);
    expect(comparison.contributions).toHaveLength(3);
  });
});
