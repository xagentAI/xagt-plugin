import { mulberry32, normalInv, probabilisticSharpeRatio, sharpeRatio, skewness, kurtosis, toReturns } from '@/lib/stats';
import type { TrackRecord } from '@/lib/sources/types';

/**
 * Regimen attacking its own verdict.
 *
 * A validation tool that only ever confirms edges is worthless, and a reader has no
 * way to tell a working detector from a flattering one by looking at a single result.
 * So every analysis can be run against controls whose answer is known in advance:
 *
 *  1. **The mean-centred control.** Take the strategy's own returns and subtract their
 *     mean. The result has identical volatility, skew and kurtosis, and a true Sharpe
 *     of exactly zero. A correct engine must grade it near 50% confidence. If it
 *     grades it highly, the engine is broken and nothing else on the page is reliable.
 *  2. **The null-strategy distribution.** Simulate many strategies with the same
 *     length and volatility but no edge at all, grade each, and report where the real
 *     strategy's confidence sits among them. This converts the headline into a
 *     percentile against pure luck, which is the number a sceptic actually wants.
 *
 * Both controls are seeded, so a published result can be reproduced exactly.
 */

export interface ControlOutcome {
  readonly name: string;
  readonly description: string;
  readonly expected: string;
  readonly observed: number | null;
  readonly passed: boolean;
  readonly detail: string;
}

export interface NullDistributionResult {
  readonly simulations: number;
  readonly seed: number;
  readonly observedPsr: number | null;
  readonly percentileAmongNull: number | null;
  readonly nullMedianPsr: number | null;
  readonly nullP95Psr: number | null;
  readonly empiricalPValue: number | null;
  readonly interpretation: string;
}

export interface SelfAttackReport {
  readonly label: string;
  readonly controls: readonly ControlOutcome[];
  readonly nullDistribution: NullDistributionResult | null;
  readonly verdict: 'engine_sane' | 'engine_suspect' | 'not_run';
  readonly notes: readonly string[];
}

export interface SelfAttackOptions {
  readonly simulations?: number;
  readonly seed?: number;
  readonly benchmarkSharpe?: number;
}

const DEFAULT_SIMULATIONS = 1_000;
const DEFAULT_SEED = 0xdecafbad;

/** A mean-centred series must grade within this band of 50%, or the engine is wrong. */
const CENTRED_CONTROL_TOLERANCE = 0.1;

/** Box-Muller on a seeded uniform stream. */
function gaussian(rng: () => number): number {
  let u = rng();
  while (u <= Number.EPSILON) u = rng();
  const v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function psrOf(returns: readonly number[], benchmarkSharpe: number): number | null {
  const sharpe = sharpeRatio(returns, { riskFreePerPeriod: 0 });
  const skew = skewness(returns);
  const kurt = kurtosis(returns, { excess: false });
  if (!sharpe.ok || skew === null || kurt === null) return null;
  const psr = probabilisticSharpeRatio({
    sharpe: sharpe.value.sharpe,
    n: returns.length,
    skewness: skew,
    kurtosis: kurt,
    benchmarkSharpe,
  });
  return psr.ok ? psr.value.psr : null;
}

export function runSelfAttack(record: TrackRecord, options: SelfAttackOptions = {}): SelfAttackReport {
  const simulations = options.simulations ?? DEFAULT_SIMULATIONS;
  const seed = options.seed ?? DEFAULT_SEED;
  const benchmarkSharpe = options.benchmarkSharpe ?? 0;
  const notes: string[] = [];

  const series = toReturns(record.equity, { kind: 'simple' });
  const returns = series.returns;

  if (returns.length < 20) {
    return {
      label: record.label,
      controls: [],
      nullDistribution: null,
      verdict: 'not_run',
      notes: ['The sample is too short for the controls to mean anything.'],
    };
  }

  const observedPsr = psrOf(returns, benchmarkSharpe);

  const controls: ControlOutcome[] = [];

  // Control 1 — the strategy's own returns with the edge removed.
  const meanReturn = returns.reduce((total, value) => total + value, 0) / returns.length;
  const centred = returns.map((value) => value - meanReturn);
  const centredPsr = psrOf(centred, benchmarkSharpe);
  const centredPassed = centredPsr !== null && Math.abs(centredPsr - 0.5) <= CENTRED_CONTROL_TOLERANCE;
  controls.push({
    name: 'mean_centred',
    description:
      'This strategy’s own returns with their mean subtracted. Same volatility, same skew, same tails, but a true Sharpe of exactly zero.',
    expected: `Confidence near 50% (within ${(CENTRED_CONTROL_TOLERANCE * 100).toFixed(0)} points)`,
    observed: centredPsr,
    passed: centredPassed,
    detail: centredPassed
      ? 'The engine correctly found no edge once the edge was removed.'
      : 'The engine did NOT return a neutral verdict on a series with no edge. Treat every other number on this report as unreliable and report this.',
  });

  // Control 2 — a null distribution of edgeless strategies of the same shape.
  const volatility = Math.sqrt(
    centred.reduce((total, value) => total + value * value, 0) / Math.max(1, centred.length - 1),
  );

  let nullDistribution: NullDistributionResult | null = null;
  if (volatility > 0 && observedPsr !== null) {
    const rng = mulberry32(seed);
    const nullPsrs: number[] = [];
    for (let i = 0; i < simulations; i += 1) {
      const simulated = Array.from({ length: returns.length }, () => gaussian(rng) * volatility);
      const psr = psrOf(simulated, benchmarkSharpe);
      if (psr !== null) nullPsrs.push(psr);
    }

    if (nullPsrs.length >= 50) {
      nullPsrs.sort((a, b) => a - b);
      const below = nullPsrs.filter((value) => value < observedPsr).length;
      const atLeastAsHigh = nullPsrs.filter((value) => value >= observedPsr).length;
      const percentile = below / nullPsrs.length;
      const pValue = (atLeastAsHigh + 1) / (nullPsrs.length + 1);
      nullDistribution = {
        simulations: nullPsrs.length,
        seed,
        observedPsr,
        percentileAmongNull: percentile,
        nullMedianPsr: nullPsrs[Math.floor(nullPsrs.length / 2)] ?? null,
        nullP95Psr: nullPsrs[Math.floor(nullPsrs.length * 0.95)] ?? null,
        empiricalPValue: pValue,
        interpretation:
          pValue <= 0.05
            ? `Only ${(pValue * 100).toFixed(1)}% of edgeless strategies of this length and volatility score as well as this one.`
            : `${(pValue * 100).toFixed(1)}% of edgeless strategies of this length and volatility score at least as well as this one — which is too many to call this result unusual.`,
      };
    } else {
      notes.push('The null simulation produced too few usable draws to report a percentile.');
    }
  }

  if (!centredPassed) {
    notes.push(
      'The mean-centred control failed. This is a statement about Regimen, not about the strategy, and it is published rather than hidden.',
    );
  }

  return {
    label: record.label,
    controls,
    nullDistribution,
    verdict: centredPassed ? 'engine_sane' : 'engine_suspect',
    notes,
  };
}

/**
 * The Sharpe ratio a strategy with NO edge would need to look significant at a given
 * confidence, for a given sample length. Useful as a plain-language yardstick: "at 40
 * observations, pure luck clears a Sharpe of X about 5% of the time."
 */
export function luckThresholdSharpe(n: number, confidence = 0.95): number | null {
  if (!Number.isFinite(n) || n < 2) return null;
  const z = normalInv(confidence);
  if (!Number.isFinite(z)) return null;
  return z / Math.sqrt(n - 1);
}
