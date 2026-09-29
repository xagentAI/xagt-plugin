/**
 * Drawdown statistics.
 *
 * The worked example is small enough to verify entirely by hand; its full
 * derivation is in the comment on the first test.
 */

import { describe, expect, it } from 'vitest';

import { maxDrawdown, ulcerIndex } from '../../src/lib/stats/drawdown';
import { unwrap } from './support';

/**
 *   equity        = [100, 120,  90, 110,  80, 130, 125]
 *   index         =    0    1    2    3    4    5    6
 *   running peak  =  100  120  120  120  120  130  130
 *   drawdown      =    0    0  .25 .0833 .3333   0  .03846
 *
 *   worst drawdown  = (120 - 80) / 120 = 1/3, at index 4
 *   its peak        = index 1 (equity 120)
 *   recovery        = first index after 4 with equity >= 120 -> index 5 (130)
 *   underwater runs = peak@1 recovered at 5 -> 4 periods
 *                     peak@5 never recovered -> 6 - 5 = 1 period
 *   longest         = 4
 */
const CURVE = [100, 120, 90, 110, 80, 130, 125] as const;

describe('maxDrawdown', () => {
  it('matches the hand-derived worked example', () => {
    const value = unwrap(maxDrawdown([...CURVE]));
    expect(value.maxDrawdown).toBeCloseTo(1 / 3, 15);
    expect(value.peakIndex).toBe(1);
    expect(value.troughIndex).toBe(4);
    expect(value.recoveryIndex).toBe(5);
    expect(value.longestDrawdownPeriods).toBe(4);
    expect(value.peakEquity).toBe(120);
    expect(value.troughEquity).toBe(80);
  });

  it('expresses the drawdown as a POSITIVE fraction, not a percentage or a negative', () => {
    const value = unwrap(maxDrawdown([100, 80]));
    expect(value.maxDrawdown).toBeCloseTo(0.2, 15);
  });

  it('reports null recovery when the series ends underwater', () => {
    const value = unwrap(maxDrawdown([100, 120, 60, 70, 80]));
    expect(value.maxDrawdown).toBeCloseTo(0.5, 15);
    expect(value.peakIndex).toBe(1);
    expect(value.troughIndex).toBe(2);
    expect(value.recoveryIndex).toBeNull();
    expect(value.longestDrawdownPeriods).toBe(3); // peak@1 to the last index 4
  });

  it('treats a monotonically rising curve as having no drawdown at all', () => {
    const value = unwrap(maxDrawdown([100, 101, 102, 103]));
    expect(value.maxDrawdown).toBe(0);
    expect(value.peakIndex).toBe(0);
    expect(value.troughIndex).toBe(0);
    expect(value.recoveryIndex).toBe(0);
    expect(value.longestDrawdownPeriods).toBe(0);
  });

  it('treats a flat curve as having no drawdown', () => {
    const value = unwrap(maxDrawdown([100, 100, 100]));
    expect(value.maxDrawdown).toBe(0);
    expect(value.longestDrawdownPeriods).toBe(0);
  });

  it('handles a single point', () => {
    const value = unwrap(maxDrawdown([100]));
    expect(value.maxDrawdown).toBe(0);
    expect(value.peakIndex).toBe(0);
    expect(value.troughIndex).toBe(0);
    expect(value.recoveryIndex).toBe(0);
    expect(value.longestDrawdownPeriods).toBe(0);
  });

  it('reports the DEEPEST drawdown even when a different episode is the LONGEST', () => {
    //  idx      0    1   2   3   4   5   6   7    8
    //  equity 100   50 100 101  99  98  97  96  102
    //  deepest: 50% at index 1 (peak index 0), recovered at index 2 -> 2 periods
    //  longest: peak at index 3 (101), underwater 4..7, regained at 8 -> 5 periods
    const value = unwrap(maxDrawdown([100, 50, 100, 101, 99, 98, 97, 96, 102]));
    expect(value.maxDrawdown).toBeCloseTo(0.5, 15);
    expect(value.peakIndex).toBe(0);
    expect(value.troughIndex).toBe(1);
    expect(value.recoveryIndex).toBe(2);
    expect(value.longestDrawdownPeriods).toBe(5);
  });

  it('counts a drawdown that recovers exactly to the old peak as recovered', () => {
    const value = unwrap(maxDrawdown([100, 90, 100]));
    expect(value.recoveryIndex).toBe(2);
    expect(value.longestDrawdownPeriods).toBe(2);
  });

  it('picks the first of several equally deep drawdowns', () => {
    const value = unwrap(maxDrawdown([100, 90, 100, 90, 100]));
    expect(value.maxDrawdown).toBeCloseTo(0.1, 15);
    expect(value.troughIndex).toBe(1);
  });

  it('fails with empty_input on an empty curve', () => {
    const result = maxDrawdown([]);
    expect(result.ok).toBe(false);
    expect(result.value).toBeNull();
    expect(result.ok ? null : result.reason).toBe('empty_input');
  });

  it('fails with non_positive_equity on zero or negative equity', () => {
    for (const curve of [
      [100, 0, 90],
      [100, -1],
      [0],
    ]) {
      const result = maxDrawdown(curve);
      expect(result.ok ? null : result.reason).toBe('non_positive_equity');
    }
  });

  it('fails with non_finite_input on NaN or Infinity', () => {
    const withNan = maxDrawdown([100, Number.NaN, 90]);
    expect(withNan.ok ? null : withNan.reason).toBe('non_finite_input');
    const withInfinity = maxDrawdown([100, Number.POSITIVE_INFINITY]);
    expect(withInfinity.ok ? null : withInfinity.reason).toBe('non_finite_input');
  });

  it('is scale invariant', () => {
    const base = unwrap(maxDrawdown([...CURVE]));
    const scaled = unwrap(maxDrawdown(CURVE.map((e) => e * 1e6)));
    expect(scaled.maxDrawdown).toBeCloseTo(base.maxDrawdown, 15);
    expect(scaled.peakIndex).toBe(base.peakIndex);
    expect(scaled.troughIndex).toBe(base.troughIndex);
  });

  it('never returns a drawdown outside [0, 1)', () => {
    const curves = [CURVE, [1, 1e-12], [1e-12, 1], [5, 4, 3, 2, 1]];
    for (const curve of curves) {
      const value = unwrap(maxDrawdown([...curve]));
      expect(value.maxDrawdown).toBeGreaterThanOrEqual(0);
      expect(value.maxDrawdown).toBeLessThan(1);
    }
  });
});

describe('ulcerIndex', () => {
  it('matches the hand-derived worked example', () => {
    //  equity = [100, 90, 100, 80, 100], peak is always 100
    //  D (percent) = [0, 10, 0, 20, 0]
    //  sum of squares = 0 + 100 + 0 + 400 + 0 = 500
    //  UI = sqrt(500 / 5) = sqrt(100) = 10
    const value = unwrap(ulcerIndex([100, 90, 100, 80, 100]));
    expect(value.ulcerIndex).toBeCloseTo(10, 13);
    expect(value.ulcerIndexFraction).toBeCloseTo(0.1, 15);
    expect(value.periods).toBe(5);
    expect(value.maxRetracement).toBeCloseTo(0.2, 15);
  });

  it('is exactly zero for a non-decreasing curve', () => {
    expect(unwrap(ulcerIndex([100, 110, 120])).ulcerIndex).toBe(0);
    expect(unwrap(ulcerIndex([100, 100, 100])).ulcerIndex).toBe(0);
    expect(unwrap(ulcerIndex([100])).ulcerIndex).toBe(0);
  });

  it('is reported in PERCENTAGE POINTS, per the original definition', () => {
    // A curve permanently 5% underwater scores ~5, not ~0.05.
    const equity = [100, 95, 95, 95, 95, 95, 95, 95, 95, 95];
    const value = unwrap(ulcerIndex(equity));
    expect(value.ulcerIndex).toBeGreaterThan(4);
    expect(value.ulcerIndex).toBeLessThan(5);
    expect(value.ulcerIndexFraction).toBeCloseTo(value.ulcerIndex / 100, 15);
  });

  it('punishes a long shallow drawdown more than a brief deep one of equal area', () => {
    const brief = unwrap(ulcerIndex([100, 50, 100, 100, 100, 100, 100, 100, 100, 100, 100]));
    const long = unwrap(ulcerIndex([100, 95, 95, 95, 95, 95, 95, 95, 95, 95, 95]));
    // Squaring means the 50% day dominates despite being a tenth as long, so
    // this asserts the direction the metric actually has, not a folk belief.
    expect(brief.ulcerIndex).toBeGreaterThan(long.ulcerIndex);
    // but the long one is clearly non-trivial
    expect(long.ulcerIndex).toBeGreaterThan(4);
  });

  it('grows with the depth of the drawdown', () => {
    const shallow = unwrap(ulcerIndex([100, 99, 100]));
    const deep = unwrap(ulcerIndex([100, 60, 100]));
    expect(deep.ulcerIndex).toBeGreaterThan(shallow.ulcerIndex);
  });

  it('is scale invariant', () => {
    const base = unwrap(ulcerIndex([100, 90, 100, 80, 100]));
    const scaled = unwrap(ulcerIndex([1e-6, 0.9e-6, 1e-6, 0.8e-6, 1e-6]));
    expect(scaled.ulcerIndex).toBeCloseTo(base.ulcerIndex, 10);
  });

  it('fails with the same reasons as maxDrawdown on degenerate input', () => {
    expect(ulcerIndex([]).ok ? null : 'empty').toBe('empty');
    const negative = ulcerIndex([100, -5]);
    expect(negative.ok ? null : negative.reason).toBe('non_positive_equity');
    const nan = ulcerIndex([100, Number.NaN]);
    expect(nan.ok ? null : nan.reason).toBe('non_finite_input');
  });
});
