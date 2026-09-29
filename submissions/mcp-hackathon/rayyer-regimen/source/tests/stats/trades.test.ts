/**
 * Trade statistics and the Wilson score interval.
 *
 * The Wilson reference values were recomputed independently from the published
 * closed form; the 6/10 case is the one most often quoted in textbooks
 * (0.3127, 0.8318), which makes it a convenient external anchor.
 */

import { describe, expect, it } from 'vitest';

import { tradeStats, wilsonInterval } from '../../src/lib/stats/trades';
import { unwrap } from './support';

/**
 *   pnls = [100, -50, 200, -25, 0, 75, -100]     n = 7
 *   wins      = 100, 200, 75      -> 3, gross profit 375
 *   losses    = -50, -25, -100    -> 3, gross loss   175 (positive magnitude)
 *   scratches = 0                 -> 1
 *   total PnL   = 375 - 175 = 200
 *   win rate    = 3/7, loss rate = 3/7, scratch rate = 1/7
 *   profit factor = 375/175 = 2.142857142857143
 *   expectancy    = 200/7  = 28.571428571428573
 *   average win   = 375/3  = 125
 *   average loss  = 175/3  = 58.333333333333336  (positive magnitude)
 *   payoff ratio  = 125 / (175/3) = 2.142857142857143
 */
const PNLS = [100, -50, 200, -25, 0, 75, -100] as const;

describe('tradeStats', () => {
  it('matches the hand-derived worked example', () => {
    const value = unwrap(tradeStats([...PNLS]));
    expect(value.count).toBe(7);
    expect(value.wins).toBe(3);
    expect(value.losses).toBe(3);
    expect(value.scratches).toBe(1);
    expect(value.grossProfit).toBe(375);
    expect(value.grossLoss).toBe(175);
    expect(value.totalPnl).toBe(200);
    expect(value.winRate).toBeCloseTo(3 / 7, 15);
    expect(value.lossRate).toBeCloseTo(3 / 7, 15);
    expect(value.scratchRate).toBeCloseTo(1 / 7, 15);
    expect(value.profitFactor).toBeCloseTo(2.142857142857143, 13);
    expect(value.expectancy).toBeCloseTo(28.571428571428573, 12);
    expect(value.averageWin).toBeCloseTo(125, 13);
    expect(value.averageLoss).toBeCloseTo(58.333333333333336, 12);
    expect(value.payoffRatio).toBeCloseTo(2.142857142857143, 13);
    expect(value.largestWin).toBe(200);
    expect(value.largestLoss).toBe(100);
  });

  it('treats a zero-PnL trade as a scratch, so win rate + loss rate need not be 1', () => {
    const value = unwrap(tradeStats([...PNLS]));
    expect(value.winRate + value.lossRate).toBeCloseTo(6 / 7, 15);
    expect(value.winRate + value.lossRate + value.scratchRate).toBeCloseTo(1, 15);
  });

  it('reports averageLoss and grossLoss as POSITIVE magnitudes', () => {
    const value = unwrap(tradeStats([-10, -20, -30]));
    expect(value.grossLoss).toBe(60);
    expect(value.averageLoss).toBe(20);
    expect(value.largestLoss).toBe(30);
    expect(value.totalPnl).toBe(-60);
  });

  it('satisfies the expectancy identity winRate*avgWin - lossRate*avgLoss', () => {
    const value = unwrap(tradeStats([...PNLS]));
    const identity =
      value.winRate * (value.averageWin ?? 0) - value.lossRate * (value.averageLoss ?? 0);
    expect(identity).toBeCloseTo(value.expectancy, 12);
  });

  it('returns null for profitFactor when there are no losses, NEVER Infinity', () => {
    const value = unwrap(tradeStats([10, 20, 30]));
    expect(value.profitFactor).toBeNull();
    expect(value.payoffRatio).toBeNull();
    expect(value.averageLoss).toBeNull();
    expect(value.largestLoss).toBeNull();
    expect(value.losses).toBe(0);
  });

  it('returns null for payoffRatio when there are no wins', () => {
    const value = unwrap(tradeStats([-10, -20]));
    expect(value.averageWin).toBeNull();
    expect(value.payoffRatio).toBeNull();
    expect(value.profitFactor).toBe(0);
  });

  it('handles an all-scratch series without dividing by zero', () => {
    const value = unwrap(tradeStats([0, 0, 0]));
    expect(value.scratches).toBe(3);
    expect(value.winRate).toBe(0);
    expect(value.lossRate).toBe(0);
    expect(value.expectancy).toBe(0);
    expect(value.profitFactor).toBeNull();
    expect(value.payoffRatio).toBeNull();
  });

  it('handles a single trade', () => {
    const win = unwrap(tradeStats([42]));
    expect(win.count).toBe(1);
    expect(win.winRate).toBe(1);
    expect(win.expectancy).toBe(42);
    expect(win.profitFactor).toBeNull();
  });

  it('fails with empty_input on no trades', () => {
    const result = tradeStats([]);
    expect(result.ok).toBe(false);
    expect(result.value).toBeNull();
    expect(result.ok ? null : result.reason).toBe('empty_input');
  });

  it('fails with non_finite_input on NaN or Infinity', () => {
    const withNan = tradeStats([10, Number.NaN]);
    expect(withNan.ok ? null : withNan.reason).toBe('non_finite_input');
    const withInfinity = tradeStats([10, Number.NEGATIVE_INFINITY]);
    expect(withInfinity.ok ? null : withInfinity.reason).toBe('non_finite_input');
  });

  it('is order independent', () => {
    const forward = unwrap(tradeStats([...PNLS]));
    const reversed = unwrap(tradeStats([...PNLS].reverse()));
    expect(reversed).toEqual(forward);
  });
});

describe('wilsonInterval', () => {
  it('matches the published 6/10 at 95% reference', () => {
    //   p_hat = 0.6, n = 10, z = 1.959963984540054, z^2 = 3.8414588206941245
    //   centre = (0.6 + 3.84146/20) / (1 + 3.84146/10) = 0.572246720013711
    //   half   = (z / 1.38414588) * sqrt(0.6*0.4/10 + 3.84146/400)
    //          = 0.2595729502800528
    //   -> [0.31267376973365824, 0.8318196702937638]
    const value = unwrap(wilsonInterval(6, 10, 0.95));
    expect(value.pointEstimate).toBe(0.6);
    expect(value.centre).toBeCloseTo(0.572246720013711, 14);
    expect(value.lower).toBeCloseTo(0.31267376973365824, 13);
    expect(value.upper).toBeCloseTo(0.8318196702937638, 13);
    expect(value.z).toBeCloseTo(1.959963984540054, 13);
  });

  it('matches the 50/100 at 95% reference', () => {
    const value = unwrap(wilsonInterval(50, 100, 0.95));
    expect(value.centre).toBe(0.5);
    expect(value.lower).toBeCloseTo(0.4038315303659956, 13);
    expect(value.upper).toBeCloseTo(0.5961684696340044, 13);
  });

  it('matches a 90% reference at 3/7', () => {
    const value = unwrap(wilsonInterval(3, 7, 0.9));
    expect(value.z).toBeCloseTo(1.6448536269514722, 13);
    expect(value.lower).toBeCloseTo(0.18644319036395607, 13);
    expect(value.upper).toBeCloseTo(0.7105229089864071, 13);
  });

  it('stays bounded at 0 successes, where the Wald interval collapses to a point', () => {
    const value = unwrap(wilsonInterval(0, 10, 0.95));
    expect(value.pointEstimate).toBe(0);
    expect(value.lower).toBeCloseTo(0, 15);
    expect(value.lower).toBeGreaterThanOrEqual(0);
    expect(value.upper).toBeCloseTo(0.2775327998628892, 13);
    expect(value.upper).toBeGreaterThan(0);
  });

  it('stays bounded at 100% successes', () => {
    const value = unwrap(wilsonInterval(10, 10, 0.95));
    expect(value.pointEstimate).toBe(1);
    expect(value.lower).toBeCloseTo(0.7224672001371107, 13);
    expect(value.upper).toBeCloseTo(1, 15);
    expect(value.upper).toBeLessThanOrEqual(1);
  });

  it('handles the single-observation case', () => {
    const value = unwrap(wilsonInterval(1, 1, 0.95));
    expect(value.lower).toBeCloseTo(0.20654931437723745, 13);
    expect(value.upper).toBeCloseTo(1, 15);
  });

  it('never leaves [0, 1]', () => {
    for (let n = 1; n <= 40; n += 1) {
      for (let k = 0; k <= n; k += 1) {
        const value = unwrap(wilsonInterval(k, n, 0.99));
        expect(value.lower).toBeGreaterThanOrEqual(0);
        expect(value.upper).toBeLessThanOrEqual(1);
        expect(value.lower).toBeLessThanOrEqual(value.upper);
      }
    }
  });

  it('narrows as the sample grows', () => {
    const small = unwrap(wilsonInterval(30, 50, 0.95));
    const large = unwrap(wilsonInterval(3000, 5000, 0.95));
    expect(large.upper - large.lower).toBeLessThan(small.upper - small.lower);
  });

  it('widens as confidence rises', () => {
    const at90 = unwrap(wilsonInterval(60, 100, 0.9));
    const at99 = unwrap(wilsonInterval(60, 100, 0.99));
    expect(at99.upper - at99.lower).toBeGreaterThan(at90.upper - at90.lower);
  });

  it('is symmetric under swapping successes and failures', () => {
    const a = unwrap(wilsonInterval(7, 20, 0.95));
    const b = unwrap(wilsonInterval(13, 20, 0.95));
    expect(a.lower).toBeCloseTo(1 - b.upper, 14);
    expect(a.upper).toBeCloseTo(1 - b.lower, 14);
  });

  it('defaults to 95% confidence', () => {
    expect(unwrap(wilsonInterval(6, 10)).lower).toBe(unwrap(wilsonInterval(6, 10, 0.95)).lower);
  });

  it('rejects malformed counts with invalid_parameter', () => {
    for (const [k, n] of [
      [-1, 10],
      [11, 10],
      [1, 0],
      [1, -5],
      [1.5, 10],
      [1, 10.5],
      [Number.NaN, 10],
    ] as Array<[number, number]>) {
      const result = wilsonInterval(k, n, 0.95);
      expect(result.ok).toBe(false);
      expect(result.value).toBeNull();
      expect(result.ok ? null : result.reason).toBe('invalid_parameter');
    }
  });

  it('rejects a confidence outside (0, 1)', () => {
    for (const confidence of [0, 1, -0.2, 1.4, Number.NaN]) {
      const result = wilsonInterval(5, 10, confidence);
      expect(result.ok).toBe(false);
    }
  });
});
