/**
 * The generator is the measuring instrument. If it is wrong, every number on the
 * scorecard is wrong in a way that looks fine.
 *
 * So these tests check the instrument, not the engine: that a seed reproduces a
 * case exactly, that the series really hit the mean and volatility they claim,
 * that the three distributions genuinely differ in shape rather than in name,
 * that `provableAtThisLength` is the engine's own MinTRL arithmetic rather than a
 * lookalike, and that the degenerate traps are actually degenerate.
 */

import { describe, expect, it } from 'vitest';

import {
  PROVABILITY_CONFIDENCE,
  STANDARDISED_MOMENTS,
  STARTING_EQUITY,
  generateCase,
  generateDegenerateCase,
  type CaseSpec,
  type DegenerateKind,
  type SyntheticDistribution,
} from '../../src/lib/eval/synthetic';
import { kurtosis, mean, skewness, stdDev } from '../../src/lib/stats/moments';
import { minimumTrackRecordLength } from '../../src/lib/stats/sharpe';
import { toReturns } from '../../src/lib/stats/returns';

/** A long sample: enough for the sample moments to pin the population ones down. */
const MOMENT_SAMPLE_PERIODS = 20_000;

function spec(overrides: Partial<CaseSpec> & Pick<CaseSpec, 'id'>): CaseSpec {
  return {
    periods: 250,
    trueSharpePerPeriod: 0,
    volatilityPerPeriod: 0.01,
    distribution: 'normal',
    seed: 1234,
    ...overrides,
  };
}

function returnsOf(equity: readonly { t: number; equity: number }[]): number[] {
  return toReturns(equity, { kind: 'simple' }).returns;
}

describe('generateCase determinism', () => {
  it('reproduces the same track record for the same seed', () => {
    const first = generateCase(spec({ id: 'det/a', seed: 424_242, distribution: 'skewed', periods: 120 }));
    const second = generateCase(spec({ id: 'det/a', seed: 424_242, distribution: 'skewed', periods: 120 }));

    expect(second.record.equity).toEqual(first.record.equity);
    expect(second.truth).toEqual(first.truth);
  });

  it('produces a different track record for a different seed', () => {
    const first = generateCase(spec({ id: 'det/a', seed: 424_242, periods: 120 }));
    const second = generateCase(spec({ id: 'det/a', seed: 424_243, periods: 120 }));

    expect(second.record.equity).not.toEqual(first.record.equity);
    // The ground truth is a property of the specification, not of the draw, so it
    // must NOT move when the seed does.
    expect(second.truth).toEqual(first.truth);
  });

  it('reproduces the regime series for the same seed and diverges for another', () => {
    const base = spec({
      id: 'det/regime',
      seed: 55_555,
      periods: 180,
      regimeEffect: { factor: 'vix', activeBucketSharpe: 0.3, inactiveBucketSharpe: 0 },
    });
    const first = generateCase(base);
    const second = generateCase(base);
    const different = generateCase({ ...base, seed: 55_556 });

    expect(second.regimes).toEqual(first.regimes);
    expect(different.regimes).not.toEqual(first.regimes);
  });

  it('starts every curve at a round 10,000 and keeps equity strictly positive', () => {
    for (const distribution of ['normal', 'skewed', 'fat_tailed'] as const) {
      const generated = generateCase(
        spec({ id: `positive/${distribution}`, distribution, periods: 2_000, volatilityPerPeriod: 0.02, seed: 98_765 }),
      );
      expect(generated.record.equity[0]?.equity).toBe(STARTING_EQUITY);
      expect(generated.record.equity).toHaveLength(2_001);
      expect(generated.record.equity.every((point) => point.equity > 0)).toBe(true);
    }
  });

  it('spaces equity points one calendar day apart', () => {
    const generated = generateCase(spec({ id: 'spacing', periods: 30 }));
    const stamps = generated.record.equity.map((point) => point.t);
    for (let i = 1; i < stamps.length; i += 1) {
      expect((stamps[i] as number) - (stamps[i - 1] as number)).toBe(86_400_000);
    }
  });
});

describe('generated series hit their target mean and volatility', () => {
  const trueSharpe = 0.2;
  const volatility = 0.01;

  for (const distribution of ['normal', 'skewed', 'fat_tailed'] as const) {
    it(`${distribution}: realised mean and standard deviation match the target`, () => {
      const generated = generateCase(
        spec({
          id: `moments/${distribution}`,
          distribution,
          periods: MOMENT_SAMPLE_PERIODS,
          trueSharpePerPeriod: trueSharpe,
          volatilityPerPeriod: volatility,
          seed: 20_250_101,
        }),
      );
      const returns = returnsOf(generated.record.equity);
      const sampleMean = mean(returns);
      const sampleSd = stdDev(returns, { ddof: 1 });

      expect(sampleMean).not.toBeNull();
      expect(sampleSd).not.toBeNull();

      // Six standard errors of the mean. Wide enough that a correct generator
      // never trips it, narrow enough that a drift bug always does.
      const standardError = volatility / Math.sqrt(MOMENT_SAMPLE_PERIODS);
      expect(Math.abs((sampleMean as number) - trueSharpe * volatility)).toBeLessThan(6 * standardError);
      expect(Math.abs((sampleSd as number) / volatility - 1)).toBeLessThan(0.05);
    });
  }

  it("sample-matched generation pins the realised moments exactly", () => {
    const generated = generateCase(
      spec({
        id: 'moments/sample-matched',
        distribution: 'fat_tailed',
        periods: 500,
        trueSharpePerPeriod: 0.25,
        volatilityPerPeriod: 0.01,
        seed: 31_337,
      }),
      { momentMatching: 'sample' },
    );
    const returns = returnsOf(generated.record.equity);
    expect(mean(returns) as number).toBeCloseTo(0.0025, 12);
    expect(stdDev(returns, { ddof: 1 }) as number).toBeCloseTo(0.01, 12);
  });
});

describe('the distribution axis is real, not decorative', () => {
  function shapeMoments(distribution: SyntheticDistribution): { skew: number; excessKurtosis: number } {
    const generated = generateCase(
      spec({
        id: `shape/${distribution}`,
        distribution,
        periods: MOMENT_SAMPLE_PERIODS,
        trueSharpePerPeriod: 0,
        volatilityPerPeriod: 0.01,
        seed: 777_001,
      }),
    );
    const returns = returnsOf(generated.record.equity);
    return {
      skew: skewness(returns) as number,
      excessKurtosis: kurtosis(returns, { excess: true }) as number,
    };
  }

  it('normal is close to symmetric and mesokurtic', () => {
    const moments = shapeMoments('normal');
    expect(Math.abs(moments.skew)).toBeLessThan(0.15);
    expect(Math.abs(moments.excessKurtosis)).toBeLessThan(0.5);
  });

  it('skewed produces materially negative skewness', () => {
    const moments = shapeMoments('skewed');
    expect(moments.skew).toBeLessThan(-1.2);
  });

  it('fat_tailed produces materially positive excess kurtosis', () => {
    const moments = shapeMoments('fat_tailed');
    expect(moments.excessKurtosis).toBeGreaterThan(2);
    expect(Math.abs(moments.skew)).toBeLessThan(0.75);
  });

  it('the published population moments match the closed-form mixture and Student-t values', () => {
    // Two-component mixture: 0.9·N(0.25, 0.6²) + 0.1·N(-2.25, 1.4²).
    expect(STANDARDISED_MOMENTS.skewed.skewness).toBeCloseTo(-1.9578, 3);
    expect(STANDARDISED_MOMENTS.skewed.kurtosis).toBeCloseTo(8.6565, 3);
    // Student-t kurtosis 3 + 6/(v - 4) at v = 5.
    expect(STANDARDISED_MOMENTS.fat_tailed.kurtosis).toBeCloseTo(9, 12);
    expect(STANDARDISED_MOMENTS.normal.kurtosis).toBe(3);
    // Every shape standardises to the same first two moments, so only the shape varies.
    for (const distribution of ['normal', 'skewed', 'fat_tailed'] as const) {
      expect(STANDARDISED_MOMENTS[distribution].mean).toBe(0);
      expect(STANDARDISED_MOMENTS[distribution].sd).toBe(1);
    }
  });
});

describe('provableAtThisLength', () => {
  const lengths = [20, 25, 45, 60, 120, 250, 400];
  const sharpes = [0.08, 0.1, 0.15, 0.25, 0.4];

  for (const distribution of ['normal', 'skewed', 'fat_tailed'] as const) {
    it(`${distribution}: agrees with a direct minimumTrackRecordLength call`, () => {
      const moments = STANDARDISED_MOMENTS[distribution];
      for (const trueSharpePerPeriod of sharpes) {
        const direct = minimumTrackRecordLength({
          sharpe: trueSharpePerPeriod,
          skewness: moments.skewness,
          kurtosis: moments.kurtosis,
          benchmarkSharpe: 0,
          confidence: PROVABILITY_CONFIDENCE,
        });
        expect(direct.ok).toBe(true);
        if (!direct.ok) return;

        for (const periods of lengths) {
          const generated = generateCase(
            spec({
              id: `provable/${distribution}/${trueSharpePerPeriod}/${periods}`,
              distribution,
              periods,
              trueSharpePerPeriod,
              seed: 606_060,
            }),
          );
          expect(generated.truth.periodsRequired).toBe(direct.value.periodsRequired);
          expect(generated.truth.minimumTrackRecordLength).toBeCloseTo(
            direct.value.minimumTrackRecordLength,
            12,
          );
          expect(generated.truth.provableAtThisLength).toBe(periods >= direct.value.periodsRequired);
        }
      }
    });
  }

  it('is false, with no MinTRL, when there is genuinely no edge', () => {
    const generated = generateCase(spec({ id: 'provable/no-edge', periods: 5_000, trueSharpePerPeriod: 0 }));
    expect(generated.truth.hasEdge).toBe(false);
    expect(generated.truth.provableAtThisLength).toBe(false);
    expect(generated.truth.minimumTrackRecordLength).toBeNull();
    expect(generated.truth.periodsRequired).toBeNull();
  });

  it('reports the blended population Sharpe for a planted regime effect', () => {
    const generated = generateCase(
      spec({
        id: 'provable/regime',
        periods: 180,
        regimeEffect: { factor: 'vix', activeBucketSharpe: 0.35, inactiveBucketSharpe: 0 },
        seed: 8_080,
      }),
    );
    // (0.5·0.35 + 0.5·0) / sqrt(1 + 0.25·0.35²) = 0.175 / 1.015197…
    expect(generated.truth.trueSharpePerPeriod).toBeCloseTo(0.175 / Math.sqrt(1 + 0.25 * 0.35 * 0.35), 12);
    expect(generated.truth.hasEdge).toBe(true);
    expect(generated.truth.plantedRegimeEffect).toBe(true);
  });

  it('does not call an equal-bucket regime case a planted effect', () => {
    const generated = generateCase(
      spec({
        id: 'provable/regime-null',
        periods: 180,
        regimeEffect: { factor: 'vix', activeBucketSharpe: 0.1, inactiveBucketSharpe: 0.1 },
        seed: 8_081,
      }),
    );
    expect(generated.truth.plantedRegimeEffect).toBe(false);
    expect(generated.truth.trueSharpePerPeriod).toBeCloseTo(0.1, 12);
  });
});

describe('regime series', () => {
  it('emits one observation per return period, aligned to the period END date', () => {
    const generated = generateCase(
      spec({
        id: 'regime/alignment',
        periods: 90,
        regimeEffect: { factor: 'vix', activeBucketSharpe: 0.3, inactiveBucketSharpe: 0 },
        seed: 4_040,
      }),
    );
    const series = generated.regimes;
    expect(series).toBeDefined();
    if (series === undefined) return;

    expect(series.factorKeys).toEqual(['vix']);
    expect(series.observations).toHaveLength(90);

    const closes = toReturns(generated.record.equity, { kind: 'simple' }).timestamps;
    expect(closes).toHaveLength(90);
    series.observations.forEach((observation, index) => {
      expect(observation.date).toBe(new Date(closes[index] as number).toISOString().slice(0, 10));
      expect(typeof observation.factors['vix']).toBe('number');
    });
  });

  it('spreads factor values across the published VIX buckets', () => {
    const generated = generateCase(
      spec({
        id: 'regime/buckets',
        periods: 400,
        regimeEffect: { factor: 'vix', activeBucketSharpe: 0.3, inactiveBucketSharpe: 0 },
        seed: 4_041,
      }),
    );
    const values = (generated.regimes?.observations ?? []).map((observation) => observation.factors['vix'] as number);
    const counts = [
      values.filter((v) => v < 15).length,
      values.filter((v) => v >= 15 && v < 20).length,
      values.filter((v) => v >= 20 && v < 30).length,
      values.filter((v) => v >= 30).length,
    ];
    // All four published buckets must clear the regime engine's 15-observation
    // minimum, otherwise the permutation test has nothing to compare.
    for (const count of counts) expect(count).toBeGreaterThanOrEqual(15);
  });
});

describe('degenerate traps really are degenerate', () => {
  it('constant equity yields zero variance', () => {
    const generated = generateDegenerateCase('trap/constant', 'constant_equity', 1);
    const returns = returnsOf(generated.record.equity);
    expect(returns.length).toBeGreaterThan(0);
    expect(returns.every((value) => value === 0)).toBe(true);
    expect(stdDev(returns, { ddof: 1 })).toBe(0);
    expect(generated.truth.degenerate).toBe('constant_equity');
  });

  it('the three-point trap yields two returns', () => {
    const generated = generateDegenerateCase('trap/three', 'too_few_points', 2);
    expect(generated.record.equity).toHaveLength(3);
    expect(returnsOf(generated.record.equity)).toHaveLength(2);
  });

  it('the duplicate-timestamp trap collapses to far fewer usable returns than rows', () => {
    const generated = generateDegenerateCase('trap/dupes', 'duplicate_timestamps', 3);
    const stamps = generated.record.equity.map((point) => point.t);
    const distinct = new Set(stamps);
    expect(distinct.size).toBeLessThan(stamps.length);

    const series = toReturns(generated.record.equity, { kind: 'simple' });
    expect(series.dropped.some((drop) => drop.code === 'duplicate_timestamp')).toBe(true);
    // Below the engine's 20-usable-return floor, so the only honest answer is a refusal.
    expect(series.returns.length).toBeLessThan(20);
  });

  it('the unsorted trap arrives out of chronological order', () => {
    const generated = generateDegenerateCase('trap/unsorted', 'unsorted_timestamps', 4);
    const stamps = generated.record.equity.map((point) => point.t);
    const ascending = stamps.every((value, index) => index === 0 || value > (stamps[index - 1] as number));
    expect(ascending).toBe(false);
    expect(new Set(stamps).size).toBe(stamps.length);
    expect(toReturns(generated.record.equity, { kind: 'simple' }).returns.length).toBeLessThan(20);
  });

  it('keeps every trap positive, edgeless and unprovable', () => {
    const kinds: DegenerateKind[] = [
      'constant_equity',
      'too_few_points',
      'duplicate_timestamps',
      'unsorted_timestamps',
    ];
    for (const kind of kinds) {
      const generated = generateDegenerateCase(`trap/${kind}`, kind, 9);
      expect(generated.record.equity.every((point) => point.equity > 0)).toBe(true);
      expect(generated.truth.hasEdge).toBe(false);
      expect(generated.truth.provableAtThisLength).toBe(false);
      expect(generated.truth.degenerate).toBe(kind);
    }
  });

  it('is deterministic for a fixed seed', () => {
    const first = generateDegenerateCase('trap/dupes', 'duplicate_timestamps', 77);
    const second = generateDegenerateCase('trap/dupes', 'duplicate_timestamps', 77);
    const other = generateDegenerateCase('trap/dupes', 'duplicate_timestamps', 78);
    expect(second.record.equity).toEqual(first.record.equity);
    expect(other.record.equity).not.toEqual(first.record.equity);
  });
});
