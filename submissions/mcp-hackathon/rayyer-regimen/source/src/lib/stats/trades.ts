/**
 * Trade-level statistics and the Wilson score interval for a win rate.
 *
 * Conventions fixed here, because every one of them is somewhere reported
 * differently and the differences are silent:
 *  - a trade with **exactly zero** PnL is a *scratch*: it counts toward `count`
 *    but is neither a win nor a loss, so `winRate + lossRate ≤ 1`;
 *  - `averageLoss`, `grossLoss` and `payoffRatio` are all expressed as
 *    **positive magnitudes**, so a payoff ratio of 2 means the average winner
 *    is twice the size of the average loser;
 *  - `profitFactor` is `null` when there are no losing trades — **not**
 *    `Infinity`. A strategy with no losers has an undefined profit factor and a
 *    tiny sample, and rendering "∞" next to it is how a three-trade backtest
 *    ends up at the top of a leaderboard.
 */

import { at } from './internal';
import { normalInv } from './numeric';
import { fail, ok, type StatsResult } from './result';

/** Result payload of {@link tradeStats}. */
export interface TradeStatsValue {
  /** Total number of trades, including scratches. */
  readonly count: number;
  /** Trades with PnL > 0. */
  readonly wins: number;
  /** Trades with PnL < 0. */
  readonly losses: number;
  /** Trades with PnL exactly 0. */
  readonly scratches: number;
  /** `wins / count`. */
  readonly winRate: number;
  /** `losses / count`. */
  readonly lossRate: number;
  /** `scratches / count`. */
  readonly scratchRate: number;
  /** Sum of winning PnL (positive). */
  readonly grossProfit: number;
  /** Sum of losing PnL as a positive magnitude. */
  readonly grossLoss: number;
  /** Net PnL across all trades. */
  readonly totalPnl: number;
  /** `grossProfit / grossLoss`, or `null` when `grossLoss` is 0. */
  readonly profitFactor: number | null;
  /**
   * Mean PnL per trade — the amount a randomly chosen trade is worth.
   *
   * Identical to `winRate·averageWin − lossRate·averageLoss` (scratches
   * contribute zero to both sides), which is the form usually quoted.
   */
  readonly expectancy: number;
  /** Mean PnL of winning trades, or `null` when there are none. */
  readonly averageWin: number | null;
  /** Mean PnL of losing trades **as a positive magnitude**, or `null` when there are none. */
  readonly averageLoss: number | null;
  /** `averageWin / averageLoss`, or `null` when either side is empty. */
  readonly payoffRatio: number | null;
  /** Largest single win, or `null` when there are no wins. */
  readonly largestWin: number | null;
  /** Largest single loss as a positive magnitude, or `null` when there are no losses. */
  readonly largestLoss: number | null;
}

/**
 * Aggregate per-trade PnL into the standard trade-statistics block.
 *
 * PnL may be in currency or in return units; every output is in the same unit
 * as the input except the rates and ratios, which are dimensionless.
 *
 * @returns `empty_input` for `[]` and `non_finite_input` for any NaN/±Infinity.
 */
export function tradeStats(pnls: readonly number[]): StatsResult<TradeStatsValue> {
  const count = pnls.length;
  if (count === 0) return fail('empty_input', 'No trades supplied.');

  let wins = 0;
  let losses = 0;
  let scratches = 0;
  let grossProfit = 0;
  let grossLoss = 0;
  let largestWin: number | null = null;
  let largestLoss: number | null = null;

  for (let i = 0; i < count; i += 1) {
    const pnl = at(pnls, i);
    if (!Number.isFinite(pnl)) {
      return fail('non_finite_input', 'Trade PnL series contains a non-finite value.');
    }
    if (pnl > 0) {
      wins += 1;
      grossProfit += pnl;
      if (largestWin === null || pnl > largestWin) largestWin = pnl;
    } else if (pnl < 0) {
      losses += 1;
      grossLoss += -pnl;
      const magnitude = -pnl;
      if (largestLoss === null || magnitude > largestLoss) largestLoss = magnitude;
    } else {
      scratches += 1;
    }
  }

  const totalPnl = grossProfit - grossLoss;
  const averageWin = wins > 0 ? grossProfit / wins : null;
  const averageLoss = losses > 0 ? grossLoss / losses : null;

  // Deliberately null, never Infinity: see the module comment.
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : null;
  const payoffRatio =
    averageWin !== null && averageLoss !== null && averageLoss > 0 ? averageWin / averageLoss : null;

  const value: TradeStatsValue = {
    count,
    wins,
    losses,
    scratches,
    winRate: wins / count,
    lossRate: losses / count,
    scratchRate: scratches / count,
    grossProfit,
    grossLoss,
    totalPnl,
    profitFactor,
    expectancy: totalPnl / count,
    averageWin,
    averageLoss,
    payoffRatio,
    largestWin,
    largestLoss,
  };

  if (!Number.isFinite(value.expectancy) || !Number.isFinite(totalPnl)) {
    return fail('non_finite_input', 'Trade PnL aggregation overflowed to a non-finite value.');
  }
  return ok(value);
}

/** Result payload of {@link wilsonInterval}. */
export interface WilsonIntervalValue {
  /** Observed proportion `successes / trials`. */
  readonly pointEstimate: number;
  /** Lower bound, clamped to [0, 1]. */
  readonly lower: number;
  /** Upper bound, clamped to [0, 1]. */
  readonly upper: number;
  /** Centre of the Wilson interval — note this is *not* `pointEstimate`; it is shrunk toward ½. */
  readonly centre: number;
  /** Two-sided critical value Φ⁻¹(1 − (1 − confidence)/2). */
  readonly z: number;
  readonly confidence: number;
  readonly successes: number;
  readonly trials: number;
}

/**
 * Wilson score interval for a binomial proportion.
 *
 *     centre     = (p̂ + z²/2n) / (1 + z²/n)
 *     halfWidth  = z/(1 + z²/n) · √( p̂(1 − p̂)/n + z²/4n² )
 *
 * Preferred over the normal-approximation ("Wald") interval because Wald
 * degenerates to a zero-width interval at p̂ = 0 or 1 — which is exactly where a
 * short track record lands, and exactly where a fake certainty is most
 * damaging. Wilson stays bounded, asymmetric and sensible at 0/10 and 10/10.
 *
 * Bounds are clamped to [0, 1]; the algebra can push them a hair outside
 * through floating-point rounding alone.
 *
 * Source: Wilson, E. B. (1927), "Probable Inference, the Law of Succession, and
 * Statistical Inference", JASA 22(158), pp. 209–212.
 *
 * @param successes - Count of successes; must be an integer in `[0, trials]`.
 * @param trials - Total count; must be a positive integer.
 * @param confidence - Two-sided coverage in (0, 1). Defaults to 0.95.
 */
export function wilsonInterval(
  successes: number,
  trials: number,
  confidence = 0.95,
): StatsResult<WilsonIntervalValue> {
  if (!Number.isInteger(trials) || trials < 1) {
    return fail('invalid_parameter', 'trials must be a positive integer.');
  }
  if (!Number.isInteger(successes) || successes < 0 || successes > trials) {
    return fail('invalid_parameter', 'successes must be an integer between 0 and trials.');
  }
  if (!(confidence > 0 && confidence < 1)) {
    return fail('invalid_parameter', 'confidence must lie strictly between 0 and 1.');
  }

  const z = normalInv(1 - (1 - confidence) / 2);
  if (!Number.isFinite(z)) {
    return fail('invalid_parameter', 'confidence maps to a non-finite critical value.');
  }

  const n = trials;
  const pHat = successes / n;
  const zSquaredOverN = (z * z) / n;
  const denominator = 1 + zSquaredOverN;
  const centre = (pHat + zSquaredOverN / 2) / denominator;
  const halfWidth =
    (z / denominator) * Math.sqrt((pHat * (1 - pHat)) / n + (z * z) / (4 * n * n));

  if (!Number.isFinite(centre) || !Number.isFinite(halfWidth)) {
    return fail('undefined_denominator', 'Wilson interval evaluated to a non-finite value.');
  }

  return ok({
    pointEstimate: pHat,
    lower: Math.min(Math.max(centre - halfWidth, 0), 1),
    upper: Math.min(Math.max(centre + halfWidth, 0), 1),
    centre,
    z,
    confidence,
    successes,
    trials,
  });
}
