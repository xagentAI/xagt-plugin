/**
 * Equity curve cleaning and sampling-frequency inference.
 *
 * These tests lean hard on the messy cases, because the messy cases are the
 * normal ones: uploaded track records arrive unsorted, with retried rows and
 * broker-outage zeros in them.
 */

import { describe, expect, it } from 'vitest';

import {
  IRREGULAR_SPACING_FRACTION,
  MS_PER_YEAR,
  inferPeriodsPerYear,
  toReturns,
  totalReturn,
  type EquityPoint,
} from '../../src/lib/stats/returns';
import { DAY_MS, timestampsEvery } from './support';

describe('toReturns', () => {
  it('differences adjacent equity points into simple returns', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: 100 },
      { t: 2, equity: 110 },
      { t: 3, equity: 99 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(series.returns).toHaveLength(2);
    expect(series.returns[0]).toBeCloseTo(0.1, 15);
    expect(series.returns[1]).toBeCloseTo(-0.1, 15);
    expect(series.dropped).toHaveLength(0);
    expect(series.usablePoints).toBe(3);
  });

  it('computes log returns when asked', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: 100 },
      { t: 2, equity: 110 },
    ];
    const series = toReturns(points, { kind: 'log' });
    expect(series.kind).toBe('log');
    expect(series.returns[0]).toBeCloseTo(Math.log(1.1), 15);
  });

  it('stamps each return with the END of the period that produced it', () => {
    // This is the convention the regime engine joins on. If these were opening
    // timestamps every return would be attributed one period early.
    const points: EquityPoint[] = [
      { t: 1000, equity: 100 },
      { t: 2000, equity: 101 },
      { t: 3000, equity: 102 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(series.timestamps).toEqual([2000, 3000]);
    expect(series.timestamps).toHaveLength(series.returns.length);
  });

  it('sorts unsorted input by timestamp before differencing', () => {
    const points: EquityPoint[] = [
      { t: 3, equity: 121 },
      { t: 1, equity: 100 },
      { t: 2, equity: 110 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(series.timestamps).toEqual([2, 3]);
    expect(series.returns[0]).toBeCloseTo(0.1, 15);
    expect(series.returns[1]).toBeCloseTo(0.1, 15);
  });

  it('collapses duplicate timestamps keeping the LAST row in input order', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: 100 },
      { t: 2, equity: 105 }, // superseded
      { t: 2, equity: 106 }, // the correction that arrived later
      { t: 3, equity: 110 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(series.usablePoints).toBe(3);
    expect(series.returns[0]).toBeCloseTo(0.06, 15);
    expect(series.returns[1]).toBeCloseTo(110 / 106 - 1, 15);
    expect(series.dropped).toHaveLength(1);
    expect(series.dropped[0]?.code).toBe('duplicate_timestamp');
    expect(series.dropped[0]?.index).toBe(1);
  });

  it('applies "last wins" by input order even when the duplicates arrive out of order', () => {
    const points: EquityPoint[] = [
      { t: 5, equity: 200 },
      { t: 1, equity: 100 },
      { t: 5, equity: 300 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(series.returns).toHaveLength(1);
    expect(series.returns[0]).toBeCloseTo(2, 15); // 300/100 - 1
  });

  it('rejects non-positive equity and reports the offending row index', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: 100 },
      { t: 2, equity: 0 },
      { t: 3, equity: -50 },
      { t: 4, equity: 120 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(series.usablePoints).toBe(2);
    expect(series.returns).toHaveLength(1);
    expect(series.dropped.map((d) => d.code)).toEqual(['non_positive_equity', 'non_positive_equity']);
    expect(series.dropped.map((d) => d.index)).toEqual([1, 2]);
  });

  it('rejects non-finite equity and non-finite timestamps separately', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: 100 },
      { t: 2, equity: Number.NaN },
      { t: Number.POSITIVE_INFINITY, equity: 110 },
      { t: 4, equity: Number.POSITIVE_INFINITY },
      { t: 5, equity: 120 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(series.dropped.map((d) => d.code).sort()).toEqual([
      'non_finite_equity',
      'non_finite_equity',
      'non_finite_timestamp',
    ]);
    expect(series.returns).toHaveLength(1);
  });

  it('returns an empty series rather than throwing on empty input', () => {
    const series = toReturns([], { kind: 'simple' });
    expect(series.returns).toEqual([]);
    expect(series.timestamps).toEqual([]);
    expect(series.dropped).toEqual([]);
    expect(series.usablePoints).toBe(0);
  });

  it('returns an empty series for a single point (no period to difference)', () => {
    const series = toReturns([{ t: 1, equity: 100 }], { kind: 'simple' });
    expect(series.returns).toEqual([]);
    expect(series.usablePoints).toBe(1);
  });

  it('returns an empty series when every row is invalid', () => {
    const series = toReturns(
      [
        { t: 1, equity: -1 },
        { t: 2, equity: Number.NaN },
      ],
      { kind: 'simple' },
    );
    expect(series.returns).toEqual([]);
    expect(series.dropped).toHaveLength(2);
  });

  it('never mutates the caller\'s array', () => {
    const points: EquityPoint[] = [
      { t: 3, equity: 110 },
      { t: 1, equity: 100 },
    ];
    const snapshot = points.map((p) => ({ ...p }));
    toReturns(points, { kind: 'simple' });
    expect(points).toEqual(snapshot);
  });

  it('keeps log and simple returns consistent: log = ln(1 + simple)', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: 100 },
      { t: 2, equity: 87 },
      { t: 3, equity: 143 },
      { t: 4, equity: 141 },
    ];
    const simple = toReturns(points, { kind: 'simple' });
    const log = toReturns(points, { kind: 'log' });
    for (let i = 0; i < simple.returns.length; i += 1) {
      expect(log.returns[i] ?? 0).toBeCloseTo(Math.log(1 + (simple.returns[i] ?? 0)), 14);
    }
  });

  it('produces only finite returns even for an extreme equity ratio', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: Number.MIN_VALUE },
      { t: 2, equity: Number.MAX_VALUE },
    ];
    const series = toReturns(points, { kind: 'simple' });
    for (const r of series.returns) expect(Number.isFinite(r)).toBe(true);
    // Either the return was kept as a finite number or it was dropped, but it
    // must never be Infinity.
    expect(series.returns.length + series.dropped.length).toBeGreaterThan(0);
  });
});

describe('inferPeriodsPerYear', () => {
  it('derives a daily frequency from the median spacing', () => {
    const inference = inferPeriodsPerYear(timestampsEvery(100, DAY_MS));
    expect(inference.medianSpacingMs).toBe(DAY_MS);
    expect(inference.periodsPerYear).toBeCloseTo(365.2425, 10);
    expect(inference.irregular).toBe(false);
    expect(inference.spacingCount).toBe(99);
  });

  it('derives an hourly frequency', () => {
    const hour = 60 * 60 * 1000;
    const inference = inferPeriodsPerYear(timestampsEvery(500, hour));
    expect(inference.periodsPerYear).toBeCloseTo((365.2425 * 24), 8);
    expect(inference.irregular).toBe(false);
  });

  it('derives a weekly frequency', () => {
    const inference = inferPeriodsPerYear(timestampsEvery(60, 7 * DAY_MS));
    expect(inference.periodsPerYear).toBeCloseTo(365.2425 / 7, 10);
  });

  it('uses MS_PER_YEAR consistently', () => {
    const inference = inferPeriodsPerYear(timestampsEvery(10, DAY_MS));
    expect(inference.periodsPerYear).toBe(MS_PER_YEAR / DAY_MS);
  });

  it('is not fooled by one enormous gap, because it uses the median not the mean', () => {
    const timestamps = timestampsEvery(50, DAY_MS);
    const last = timestamps[timestamps.length - 1] ?? 0;
    timestamps.push(last + 200 * DAY_MS); // strategy switched off for half a year
    const inference = inferPeriodsPerYear(timestamps);
    expect(inference.medianSpacingMs).toBe(DAY_MS);
    expect(inference.periodsPerYear).toBeCloseTo(365.2425, 10);
    // A single outlier out of 50 is well under the irregularity threshold.
    expect(inference.irregular).toBe(false);
  });

  it('treats daily bars with weekend gaps as REGULAR', () => {
    // 4 weeks x 5 trading days = 20 points, 19 gaps, of which 3 span a weekend.
    // 3/19 = 0.158, comfortably under the 0.25 threshold.
    const timestamps: number[] = [];
    let t = 0;
    for (let week = 0; week < 4; week += 1) {
      for (let day = 0; day < 5; day += 1) {
        timestamps.push(t);
        t += day === 4 ? 3 * DAY_MS : DAY_MS;
      }
    }
    const inference = inferPeriodsPerYear(timestamps);
    expect(inference.medianSpacingMs).toBe(DAY_MS);
    expect(inference.irregular).toBe(false);
    expect(inference.deviatingFraction).toBeLessThanOrEqual(IRREGULAR_SPACING_FRACTION);
  });

  it('flags a genuinely event-driven series as irregular', () => {
    const timestamps = [0, 1_000, 2_000, 100_000, 1_000_000, 1_000_050];
    const inference = inferPeriodsPerYear(timestamps);
    expect(inference.irregular).toBe(true);
    expect(inference.deviatingFraction).toBeGreaterThan(IRREGULAR_SPACING_FRACTION);
    // Still returns a usable estimate alongside the warning.
    expect(inference.periodsPerYear).not.toBeNull();
  });

  it('flags monthly bars as regular despite 28-31 day months', () => {
    const monthLengths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    const timestamps = [0];
    let t = 0;
    for (const days of monthLengths) {
      t += days * DAY_MS;
      timestamps.push(t);
    }
    const inference = inferPeriodsPerYear(timestamps);
    expect(inference.irregular).toBe(false);
    expect(inference.periodsPerYear).toBeGreaterThan(11);
    expect(inference.periodsPerYear).toBeLessThan(13);
  });

  it('returns nulls rather than guessing 252 or 365 when it cannot tell', () => {
    expect(inferPeriodsPerYear([])).toMatchObject({ periodsPerYear: null, medianSpacingMs: null });
    expect(inferPeriodsPerYear([1000])).toMatchObject({ periodsPerYear: null, medianSpacingMs: null });
  });

  it('returns nulls when every spacing is non-positive', () => {
    const inference = inferPeriodsPerYear([5, 5, 5, 5]);
    expect(inference.periodsPerYear).toBeNull();
    expect(inference.medianSpacingMs).toBeNull();
    expect(inference.spacingCount).toBe(0);
  });

  it('skips non-positive gaps instead of treating them as zero-length periods', () => {
    // Descending pair in the middle; the surrounding daily rhythm must survive.
    const inference = inferPeriodsPerYear([0, DAY_MS, 2 * DAY_MS, DAY_MS, 3 * DAY_MS, 4 * DAY_MS]);
    expect(inference.medianSpacingMs).toBe(DAY_MS);
    expect(inference.spacingCount).toBe(4);
  });

  it('never returns NaN or Infinity', () => {
    for (const timestamps of [[], [1], [1, 1], [0, Number.MAX_VALUE], timestampsEvery(5, 1)]) {
      const inference = inferPeriodsPerYear(timestamps);
      if (inference.periodsPerYear !== null) expect(Number.isFinite(inference.periodsPerYear)).toBe(true);
      if (inference.medianSpacingMs !== null) expect(Number.isFinite(inference.medianSpacingMs)).toBe(true);
      expect(Number.isFinite(inference.deviatingFraction)).toBe(true);
    }
  });
});

describe('totalReturn', () => {
  it('compounds simple returns multiplicatively', () => {
    // (1.1)(0.9) - 1 = -0.01
    expect(totalReturn([0.1, -0.1])).toBeCloseTo(-0.01, 15);
    expect(totalReturn([0.5, 0.5])).toBeCloseTo(1.25, 15);
  });

  it('sums log returns and exponentiates', () => {
    const r = [Math.log(1.1), Math.log(0.9)];
    expect(totalReturn(r, 'log')).toBeCloseTo(-0.01, 14);
  });

  it('returns 0 for an empty series', () => {
    expect(totalReturn([])).toBe(0);
    expect(totalReturn([], 'log')).toBe(0);
  });

  it('returns null on non-finite input', () => {
    expect(totalReturn([0.1, Number.NaN])).toBeNull();
    expect(totalReturn([0.1, Number.POSITIVE_INFINITY], 'log')).toBeNull();
  });

  it('agrees with the equity ratio it came from', () => {
    const points: EquityPoint[] = [
      { t: 1, equity: 100 },
      { t: 2, equity: 87 },
      { t: 3, equity: 143 },
    ];
    const series = toReturns(points, { kind: 'simple' });
    expect(totalReturn(series.returns)).toBeCloseTo(143 / 100 - 1, 14);
  });
});
