/**
 * Sharpe ratio and the Bailey / López de Prado significance family.
 *
 * Every known-answer case below carries its arithmetic in the comment so a
 * reviewer can verify the formula without running anything. The final values
 * were cross-checked against an independent scipy implementation of the same
 * published equations.
 */

import { describe, expect, it } from 'vitest';

import {
  EULER_MASCHERONI,
  annualise,
  deflatedSharpeRatio,
  expectedMaximumSharpe,
  minimumTrackRecordLength,
  probabilisticSharpeRatio,
  sharpeRatio,
} from '../../src/lib/stats/sharpe';
import { normalInv } from '../../src/lib/stats/numeric';
import { unwrap } from './support';

describe('sharpeRatio', () => {
  it('computes (mean - rf) / sample stdDev', () => {
    // xs = [1, 2, 3, 4, 5]: mean 3, sample sd = sqrt(10/4) = sqrt(2.5)
    // SR = 3 / 1.5811388300841898 = 1.8973665961010275
    const value = unwrap(sharpeRatio([1, 2, 3, 4, 5]));
    expect(value.sharpe).toBeCloseTo(1.8973665961010275, 13);
    expect(value.perPeriod).toBe(true);
  });

  it('subtracts a per-period risk-free rate', () => {
    // mean 3, rf 0.5 -> (3 - 0.5) / sqrt(2.5) = 1.5811388300841898
    const value = unwrap(sharpeRatio([1, 2, 3, 4, 5], { riskFreePerPeriod: 0.5 }));
    expect(value.sharpe).toBeCloseTo(1.5811388300841898, 13);
    expect(value.inputs.riskFreePerPeriod).toBe(0.5);
  });

  it('echoes the inputs it used, for the audit trail', () => {
    const value = unwrap(sharpeRatio([0.01, -0.02, 0.03, 0.005]));
    expect(value.inputs.n).toBe(4);
    expect(value.inputs.meanReturn).toBeCloseTo(0.00625, 15);
    expect(value.inputs.stdDev).toBeGreaterThan(0);
  });

  it('uses the SAMPLE standard deviation (ddof = 1), not the population one', () => {
    // Population sd of [1,2,3,4,5] is sqrt(2) = 1.4142..., sample is sqrt(2.5).
    // The two give 2.1213 and 1.8974; the PSR formulas assume the latter.
    const value = unwrap(sharpeRatio([1, 2, 3, 4, 5]));
    expect(value.sharpe).toBeLessThan(2);
  });

  it('fails with zero_variance on a constant series instead of returning Infinity', () => {
    const result = sharpeRatio([0.01, 0.01, 0.01, 0.01]);
    expect(result.ok).toBe(false);
    expect(result.ok ? null : result.reason).toBe('zero_variance');
    expect(result.value).toBeNull();
  });

  it('fails with empty_input on an empty series', () => {
    const result = sharpeRatio([]);
    expect(result.ok ? null : result.reason).toBe('empty_input');
  });

  it('fails with insufficient_sample on a single return', () => {
    const result = sharpeRatio([0.05]);
    expect(result.ok ? null : result.reason).toBe('insufficient_sample');
  });

  it('fails with non_finite_input when the series contains NaN or Infinity', () => {
    const withNan = sharpeRatio([0.01, Number.NaN, 0.02]);
    expect(withNan.ok ? null : withNan.reason).toBe('non_finite_input');
    const withInfinity = sharpeRatio([0.01, Number.POSITIVE_INFINITY]);
    expect(withInfinity.ok ? null : withInfinity.reason).toBe('non_finite_input');
  });

  it('fails with invalid_parameter for a non-finite risk-free rate', () => {
    const result = sharpeRatio([1, 2, 3], { riskFreePerPeriod: Number.NaN });
    expect(result.ok ? null : result.reason).toBe('invalid_parameter');
  });

  it('is negative for a losing strategy', () => {
    const value = unwrap(sharpeRatio([-0.01, -0.02, -0.005, -0.03]));
    expect(value.sharpe).toBeLessThan(0);
  });
});

describe('annualise', () => {
  it('scales by the square root of time', () => {
    const value = unwrap(annualise(0.1, 252));
    expect(value.annualisedSharpe).toBeCloseTo(0.1 * Math.sqrt(252), 14);
    expect(value.perPeriodSharpe).toBe(0.1);
    expect(value.periodsPerYear).toBe(252);
  });

  it('is the identity at one period per year', () => {
    expect(unwrap(annualise(1.3, 1)).annualisedSharpe).toBeCloseTo(1.3, 15);
  });

  it('preserves sign', () => {
    expect(unwrap(annualise(-0.2, 52)).annualisedSharpe).toBeLessThan(0);
  });

  it('rejects a non-positive or non-finite periodsPerYear', () => {
    const atZero = annualise(0.1, 0);
    expect(atZero.ok ? null : atZero.reason).toBe('invalid_parameter');
    expect(annualise(0.1, -5).ok).toBe(false);
    expect(annualise(0.1, Number.POSITIVE_INFINITY).ok).toBe(false);
  });

  it('rejects a non-finite Sharpe ratio', () => {
    const result = annualise(Number.NaN, 252);
    expect(result.ok ? null : result.reason).toBe('non_finite_input');
  });
});

describe('probabilisticSharpeRatio', () => {
  it('matches the hand-derived known answer', () => {
    // SR_hat = 0.1, n = 100, gamma3 = -0.5, gamma4 = 4.0 (NON-excess), SR* = 0
    //
    //   radicand = 1 - gamma3*SR + ((gamma4 - 1)/4)*SR^2
    //            = 1 - (-0.5)(0.1) + ((4.0 - 1)/4)(0.01)
    //            = 1 + 0.05 + 0.75*0.01
    //            = 1.0575
    //   sqrt(n - 1) = sqrt(99) = 9.9498743710662
    //   sqrt(radicand) = 1.0283481897...
    //   z = (0.1 - 0) * 9.9498743710662 / 1.0283481897 = 0.9675588936937933
    //   PSR = Phi(z) = 0.8333676424821833
    const value = unwrap(
      probabilisticSharpeRatio({ sharpe: 0.1, n: 100, skewness: -0.5, kurtosis: 4.0 }),
    );
    expect(value.radicand).toBeCloseTo(1.0575, 15);
    expect(value.zScore).toBeCloseTo(0.9675588936937933, 13);
    expect(value.psr).toBeCloseTo(0.8333676424821833, 13);
  });

  it('matches a second known answer at exactly normal higher moments', () => {
    // SR_hat = 0.05, n = 250, gamma3 = 0, gamma4 = 3 (normal)
    //   radicand = 1 - 0 + ((3-1)/4)(0.0025) = 1 + 0.5*0.0025 = 1.00125
    //   z = 0.05 * sqrt(249) / sqrt(1.00125) = 0.7884940370363923
    //   PSR = 0.784796107435966
    const value = unwrap(probabilisticSharpeRatio({ sharpe: 0.05, n: 250, skewness: 0, kurtosis: 3 }));
    expect(value.radicand).toBeCloseTo(1.00125, 15);
    expect(value.zScore).toBeCloseTo(0.7884940370363923, 13);
    expect(value.psr).toBeCloseTo(0.784796107435966, 13);
  });

  it('matches a known answer against a non-zero benchmark', () => {
    // SR_hat = 0.2, n = 36, gamma3 = -1.2, gamma4 = 8.0, SR* = 0.05
    //   radicand = 1 - (-1.2)(0.2) + ((8-1)/4)(0.04) = 1 + 0.24 + 1.75*0.04 = 1.31
    //   z = (0.2 - 0.05)*sqrt(35)/sqrt(1.31) = 0.7753354359036734
    //   PSR = 0.7809292623204689
    const value = unwrap(
      probabilisticSharpeRatio({
        sharpe: 0.2,
        n: 36,
        skewness: -1.2,
        kurtosis: 8.0,
        benchmarkSharpe: 0.05,
      }),
    );
    expect(value.radicand).toBeCloseTo(1.31, 14);
    expect(value.zScore).toBeCloseTo(0.7753354359036734, 13);
    expect(value.psr).toBeCloseTo(0.7809292623204689, 13);
  });

  it('is exactly 0.5 when the observed Sharpe equals the benchmark', () => {
    const value = unwrap(
      probabilisticSharpeRatio({
        sharpe: 0.3,
        n: 500,
        skewness: -0.4,
        kurtosis: 5,
        benchmarkSharpe: 0.3,
      }),
    );
    expect(value.zScore).toBe(0);
    expect(value.psr).toBe(0.5);
  });

  it('penalises negative skew: more left tail lowers PSR at the same Sharpe', () => {
    const symmetric = unwrap(probabilisticSharpeRatio({ sharpe: 0.15, n: 300, skewness: 0, kurtosis: 3 }));
    const negSkew = unwrap(probabilisticSharpeRatio({ sharpe: 0.15, n: 300, skewness: -1.5, kurtosis: 3 }));
    expect(negSkew.psr).toBeLessThan(symmetric.psr);
    expect(negSkew.radicand).toBeGreaterThan(symmetric.radicand);
  });

  it('penalises fat tails: higher kurtosis lowers PSR at the same Sharpe', () => {
    const normal = unwrap(probabilisticSharpeRatio({ sharpe: 0.15, n: 300, skewness: 0, kurtosis: 3 }));
    const fat = unwrap(probabilisticSharpeRatio({ sharpe: 0.15, n: 300, skewness: 0, kurtosis: 12 }));
    expect(fat.psr).toBeLessThan(normal.psr);
  });

  it('rises with sample length at a fixed Sharpe', () => {
    const short = unwrap(probabilisticSharpeRatio({ sharpe: 0.1, n: 50, skewness: 0, kurtosis: 3 }));
    const long = unwrap(probabilisticSharpeRatio({ sharpe: 0.1, n: 5000, skewness: 0, kurtosis: 3 }));
    expect(long.psr).toBeGreaterThan(short.psr);
  });

  it('returns null with undefined_variance when the radicand is non-positive', () => {
    // Large positive skew with a large Sharpe drives 1 - gamma3*SR below zero:
    // radicand = 1 - 6*2 + ((3-1)/4)*4 = 1 - 12 + 2 = -9.
    const result = probabilisticSharpeRatio({ sharpe: 2, n: 100, skewness: 6, kurtosis: 3 });
    expect(result.ok).toBe(false);
    expect(result.value).toBeNull();
    expect(result.ok ? null : result.reason).toBe('undefined_variance');
  });

  it('fails with insufficient_sample below n = 2', () => {
    for (const n of [0, 1, 1.5]) {
      const result = probabilisticSharpeRatio({ sharpe: 0.1, n, skewness: 0, kurtosis: 3 });
      expect(result.ok ? null : result.reason).toBe('insufficient_sample');
    }
  });

  it('fails with non_finite_input on NaN or Infinity anywhere', () => {
    for (const args of [
      { sharpe: Number.NaN, n: 100, skewness: 0, kurtosis: 3 },
      { sharpe: 0.1, n: Number.POSITIVE_INFINITY, skewness: 0, kurtosis: 3 },
      { sharpe: 0.1, n: 100, skewness: Number.NaN, kurtosis: 3 },
      { sharpe: 0.1, n: 100, skewness: 0, kurtosis: Number.NaN },
      { sharpe: 0.1, n: 100, skewness: 0, kurtosis: 3, benchmarkSharpe: Number.NaN },
    ]) {
      const result = probabilisticSharpeRatio(args);
      expect(result.ok).toBe(false);
      expect(result.ok ? null : result.reason).toBe('non_finite_input');
    }
  });

  it('always returns a probability inside [0, 1]', () => {
    for (const sharpe of [-3, -0.5, 0, 0.5, 3]) {
      for (const n of [2, 10, 1000, 1e6]) {
        const result = probabilisticSharpeRatio({ sharpe, n, skewness: 0, kurtosis: 3 });
        if (result.ok) {
          expect(result.value.psr).toBeGreaterThanOrEqual(0);
          expect(result.value.psr).toBeLessThanOrEqual(1);
        }
      }
    }
  });
});

describe('minimumTrackRecordLength', () => {
  it('matches the hand-derived known answer', () => {
    // SR_hat = 0.1, gamma3 = -0.5, gamma4 = 4.0, SR* = 0, confidence = 0.95
    //
    //   radicand = 1.0575                       (as in the PSR case above)
    //   Phi^-1(0.95) = 1.6448536269514722
    //   ratio = 1.6448536269514722 / 0.1 = 16.448536269514722
    //   ratio^2 = 270.5543...
    //   minTRL = 1 + 1.0575 * 270.5543... = 287.11122027058997
    const value = unwrap(
      minimumTrackRecordLength({ sharpe: 0.1, skewness: -0.5, kurtosis: 4.0, confidence: 0.95 }),
    );
    expect(value.minimumTrackRecordLength).toBeCloseTo(287.11122027058997, 10);
    expect(value.periodsRequired).toBe(288);
    expect(value.zConfidence).toBeCloseTo(1.6448536269514722, 13);
  });

  it('matches a second known answer', () => {
    // SR_hat = 0.0625, gamma3 = -0.2, gamma4 = 4.5, SR* = 0, confidence = 0.95
    //   radicand = 1 + 0.0125 + 0.875*0.00390625 = 1.01591796875
    //   minTRL = 1 + 1.01591796875 * (1.6448536269514722/0.0625)^2 = 704.6442138238644
    const value = unwrap(
      minimumTrackRecordLength({ sharpe: 0.0625, skewness: -0.2, kurtosis: 4.5, confidence: 0.95 }),
    );
    expect(value.radicand).toBeCloseTo(1.01591796875, 14);
    expect(value.minimumTrackRecordLength).toBeCloseTo(704.6442138238644, 9);
  });

  it('matches a known answer against a non-zero benchmark at 99% confidence', () => {
    // SR_hat = 0.2, gamma3 = -1.2, gamma4 = 8.0, SR* = 0.05, confidence = 0.99
    //   radicand = 1.31, Phi^-1(0.99) = 2.3263478740408408
    //   minTRL = 1 + 1.31*(2.3263478740408408/0.15)^2 = 316.0925202080526
    const value = unwrap(
      minimumTrackRecordLength({
        sharpe: 0.2,
        skewness: -1.2,
        kurtosis: 8.0,
        benchmarkSharpe: 0.05,
        confidence: 0.99,
      }),
    );
    expect(value.minimumTrackRecordLength).toBeCloseTo(316.0925202080526, 10);
  });

  it('defaults to 95% confidence and a zero benchmark', () => {
    const explicit = unwrap(
      minimumTrackRecordLength({
        sharpe: 0.1,
        skewness: -0.5,
        kurtosis: 4.0,
        confidence: 0.95,
        benchmarkSharpe: 0,
      }),
    );
    const defaulted = unwrap(minimumTrackRecordLength({ sharpe: 0.1, skewness: -0.5, kurtosis: 4.0 }));
    expect(defaulted.minimumTrackRecordLength).toBe(explicit.minimumTrackRecordLength);
  });

  it('needs a longer track record for a higher confidence', () => {
    const at90 = unwrap(minimumTrackRecordLength({ sharpe: 0.1, skewness: 0, kurtosis: 3, confidence: 0.9 }));
    const at99 = unwrap(minimumTrackRecordLength({ sharpe: 0.1, skewness: 0, kurtosis: 3, confidence: 0.99 }));
    expect(at99.minimumTrackRecordLength).toBeGreaterThan(at90.minimumTrackRecordLength);
  });

  it('needs a shorter track record for a bigger edge', () => {
    const weak = unwrap(minimumTrackRecordLength({ sharpe: 0.05, skewness: 0, kurtosis: 3 }));
    const strong = unwrap(minimumTrackRecordLength({ sharpe: 0.5, skewness: 0, kurtosis: 3 }));
    expect(strong.minimumTrackRecordLength).toBeLessThan(weak.minimumTrackRecordLength);
  });

  it('returns null with benchmark_not_exceeded when SR_hat <= SR*', () => {
    const below = minimumTrackRecordLength({
      sharpe: 0.02,
      skewness: 0,
      kurtosis: 3,
      benchmarkSharpe: 0.05,
    });
    expect(below.ok).toBe(false);
    expect(below.value).toBeNull();
    expect(below.ok ? null : below.reason).toBe('benchmark_not_exceeded');

    const equal = minimumTrackRecordLength({
      sharpe: 0.05,
      skewness: 0,
      kurtosis: 3,
      benchmarkSharpe: 0.05,
    });
    expect(equal.ok ? null : equal.reason).toBe('benchmark_not_exceeded');
  });

  it('rejects a confidence outside the open interval (0, 1)', () => {
    for (const confidence of [0, 1, -0.1, 1.5, Number.NaN]) {
      const result = minimumTrackRecordLength({ sharpe: 0.1, skewness: 0, kurtosis: 3, confidence });
      expect(result.ok).toBe(false);
    }
  });

  it('fails with undefined_variance when the radicand is non-positive', () => {
    const result = minimumTrackRecordLength({ sharpe: 2, skewness: 6, kurtosis: 3 });
    expect(result.ok ? null : result.reason).toBe('undefined_variance');
  });

  it('agrees with PSR: at exactly minTRL periods, PSR reaches the confidence level', () => {
    // The two formulas are algebraic inverses of each other, so this is the
    // strongest available consistency check on both.
    const args = { sharpe: 0.12, skewness: -0.4, kurtosis: 4.5, confidence: 0.95 } as const;
    const trl = unwrap(minimumTrackRecordLength(args));
    const psr = unwrap(
      probabilisticSharpeRatio({
        sharpe: args.sharpe,
        n: trl.minimumTrackRecordLength,
        skewness: args.skewness,
        kurtosis: args.kurtosis,
      }),
    );
    expect(psr.psr).toBeCloseTo(0.95, 12);
  });
});

describe('expectedMaximumSharpe', () => {
  it('matches the hand-derived known answer for 10 trials', () => {
    // trials = [0.02,0.05,0.08,0.11,0.04,0.09,0.01,0.07,0.10,0.03]
    //   mean = 0.60 / 10 = 0.06
    //   sum of squared deviations = 0.011
    //   sample variance (ddof=1) = 0.011 / 9 = 0.0012222222222222224
    //   sd = 0.03496029493900931
    //   Phi^-1(1 - 1/10)      = Phi^-1(0.9)               = 1.2815515655446004
    //   Phi^-1(1 - 1/(10*e))  = Phi^-1(0.9632120558828558) = 1.7892417645816283
    //   bracket = (1 - 0.5772156649015329)*1.2815515655446004
    //           + 0.5772156649015329*1.7892417645816283
    //   SR*_0 = sd * bracket = 0.05504842102550379
    const trials = [0.02, 0.05, 0.08, 0.11, 0.04, 0.09, 0.01, 0.07, 0.1, 0.03];
    const value = unwrap(expectedMaximumSharpe(trials));
    expect(value.trials).toBe(10);
    expect(value.trialVariance).toBeCloseTo(0.0012222222222222224, 15);
    expect(value.expectedMaxSharpe).toBeCloseTo(0.05504842102550379, 13);
  });

  it('reproduces the reference NumPy (ddof = 0) convention on request', () => {
    const trials = [0.02, 0.05, 0.08, 0.11, 0.04, 0.09, 0.01, 0.07, 0.1, 0.03];
    const value = unwrap(expectedMaximumSharpe(trials, 0));
    expect(value.trialVariance).toBeCloseTo(0.0011, 15);
    expect(value.expectedMaxSharpe).toBeCloseTo(0.05222351761094817, 13);
  });

  it('uses the documented Euler-Mascheroni constant', () => {
    expect(EULER_MASCHERONI).toBe(0.5772156649015329);
  });

  it('grows with the number of trials at a fixed dispersion', () => {
    const few = unwrap(expectedMaximumSharpe([0.0, 0.1, 0.05, 0.15]));
    const many = unwrap(
      expectedMaximumSharpe(Array.from({ length: 400 }, (_, i) => (i % 4) * 0.05)),
    );
    expect(many.expectedMaxSharpe).toBeGreaterThan(few.expectedMaxSharpe);
  });

  it('is zero when every trial scored the same (no dispersion to exploit)', () => {
    const value = unwrap(expectedMaximumSharpe([0.1, 0.1, 0.1, 0.1]));
    expect(value.trialVariance).toBe(0);
    expect(value.expectedMaxSharpe).toBe(0);
  });

  it('fails with insufficient_trials below N = 2', () => {
    for (const trials of [[], [0.1]]) {
      const result = expectedMaximumSharpe(trials);
      expect(result.ok ? null : result.reason).toBe('insufficient_trials');
    }
  });

  it('stays finite at N = 2, where Phi^-1(1 - 1/N) is exactly zero', () => {
    const value = unwrap(expectedMaximumSharpe([0.1, 0.2]));
    expect(Number.isFinite(value.expectedMaxSharpe)).toBe(true);
    // sample variance of [0.1, 0.2] = 0.005; sd = 0.0707106781...
    // bracket = 0 * (1-gamma) + gamma * Phi^-1(1 - 1/(2e)) = 0.5772... * 0.9004525966377902
    expect(value.expectedMaxSharpe).toBeCloseTo(0.03675225284987566, 13);
  });

  it('fails with non_finite_input when a trial Sharpe is NaN', () => {
    const result = expectedMaximumSharpe([0.1, Number.NaN, 0.2]);
    expect(result.ok ? null : result.reason).toBe('non_finite_input');
  });

  it('uses the quantiles the formula specifies', () => {
    // Guards against an off-by-one in 1 - 1/N vs 1 - 1/(N*e).
    expect(normalInv(1 - 1 / 10)).toBeCloseTo(1.2815515655446004, 13);
    expect(normalInv(1 - 1 / (10 * Math.E))).toBeCloseTo(1.7892417645816283, 13);
  });
});

describe('deflatedSharpeRatio', () => {
  const trials = [0.02, 0.05, 0.08, 0.11, 0.04, 0.09, 0.01, 0.07, 0.1, 0.03];

  it('matches the hand-derived known answer', () => {
    // SR_hat = 0.12, n = 500, gamma3 = -0.3, gamma4 = 4.2, trials as above.
    //   SR*_0 = 0.05504842102550379            (see expectedMaximumSharpe)
    //   radicand = 1 - (-0.3)(0.12) + ((4.2-1)/4)(0.0144)
    //            = 1 + 0.036 + 0.8*0.0144 = 1.04752
    //   z = (0.12 - 0.05504842102550379)*sqrt(499)/sqrt(1.04752)
    //     = 0.06495157897449621 * 22.338307903688676 / 1.023484241...
    //     = 1.4176167116271217
    //   DSR = Phi(z) = 0.9218486508037096
    const value = unwrap(
      deflatedSharpeRatio({ sharpe: 0.12, n: 500, skewness: -0.3, kurtosis: 4.2, trialSharpes: trials }),
    );
    expect(value.expectedMaxSharpe).toBeCloseTo(0.05504842102550379, 13);
    expect(value.radicand).toBeCloseTo(1.04752, 14);
    expect(value.zScore).toBeCloseTo(1.4176167116271217, 12);
    expect(value.dsr).toBeCloseTo(0.9218486508037096, 12);
    expect(value.trials).toBe(10);
    expect(value.inputs.varianceDdof).toBe(1);
  });

  it('reproduces the NumPy ddof = 0 reference when asked', () => {
    const value = unwrap(
      deflatedSharpeRatio({
        sharpe: 0.12,
        n: 500,
        skewness: -0.3,
        kurtosis: 4.2,
        trialSharpes: trials,
        varianceDdof: 0,
      }),
    );
    expect(value.expectedMaxSharpe).toBeCloseTo(0.05222351761094817, 13);
    expect(value.dsr).toBeCloseTo(0.9304662285806209, 12);
  });

  it('is always below the undeflated PSR, because the benchmark is raised', () => {
    const psr = unwrap(probabilisticSharpeRatio({ sharpe: 0.12, n: 500, skewness: -0.3, kurtosis: 4.2 }));
    const dsr = unwrap(
      deflatedSharpeRatio({ sharpe: 0.12, n: 500, skewness: -0.3, kurtosis: 4.2, trialSharpes: trials }),
    );
    expect(dsr.dsr).toBeLessThan(psr.psr);
  });

  it('punishes a wider search: more dispersed trials deflate harder', () => {
    const tight = unwrap(
      deflatedSharpeRatio({
        sharpe: 0.3,
        n: 1000,
        skewness: 0,
        kurtosis: 3,
        trialSharpes: [0.05, 0.06, 0.055, 0.052],
      }),
    );
    const wide = unwrap(
      deflatedSharpeRatio({
        sharpe: 0.3,
        n: 1000,
        skewness: 0,
        kurtosis: 3,
        trialSharpes: [-0.3, 0.4, 0.05, 0.25],
      }),
    );
    expect(wide.dsr).toBeLessThan(tight.dsr);
    expect(wide.expectedMaxSharpe).toBeGreaterThan(tight.expectedMaxSharpe);
  });

  it('punishes more trials at the same dispersion', () => {
    const base = [0.0, 0.1, -0.05, 0.05];
    const few = unwrap(
      deflatedSharpeRatio({ sharpe: 0.3, n: 1000, skewness: 0, kurtosis: 3, trialSharpes: base }),
    );
    const many = unwrap(
      deflatedSharpeRatio({
        sharpe: 0.3,
        n: 1000,
        skewness: 0,
        kurtosis: 3,
        trialSharpes: Array.from({ length: 500 }, (_, i) => base[i % 4] ?? 0),
      }),
    );
    expect(many.dsr).toBeLessThan(few.dsr);
  });

  it('returns null with insufficient_trials below N = 2', () => {
    const result = deflatedSharpeRatio({
      sharpe: 0.12,
      n: 500,
      skewness: 0,
      kurtosis: 3,
      trialSharpes: [0.1],
    });
    expect(result.ok).toBe(false);
    expect(result.value).toBeNull();
    expect(result.ok ? null : result.reason).toBe('insufficient_trials');
  });

  it('propagates the PSR failure reason when the radicand is non-positive', () => {
    const result = deflatedSharpeRatio({
      sharpe: 2,
      n: 100,
      skewness: 6,
      kurtosis: 3,
      trialSharpes: [0.1, 0.2],
    });
    expect(result.ok ? null : result.reason).toBe('undefined_variance');
  });

  it('fails with non_finite_input when a trial Sharpe is not finite', () => {
    const result = deflatedSharpeRatio({
      sharpe: 0.12,
      n: 500,
      skewness: 0,
      kurtosis: 3,
      trialSharpes: [0.1, Number.POSITIVE_INFINITY],
    });
    expect(result.ok ? null : result.reason).toBe('non_finite_input');
  });

  it('always returns a probability inside [0, 1]', () => {
    for (const sharpe of [-1, 0, 0.2, 5]) {
      const result = deflatedSharpeRatio({
        sharpe,
        n: 250,
        skewness: 0,
        kurtosis: 3,
        trialSharpes: trials,
      });
      if (result.ok) {
        expect(result.value.dsr).toBeGreaterThanOrEqual(0);
        expect(result.value.dsr).toBeLessThanOrEqual(1);
      }
    }
  });
});
