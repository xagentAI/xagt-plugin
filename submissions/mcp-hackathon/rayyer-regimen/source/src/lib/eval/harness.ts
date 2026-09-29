/**
 * The grader.
 *
 * `runEvaluation` pushes the pre-registered suite through the real engine —
 * `analyseSignificance`, and `buildRegimeMap` for the regime cases — and scores
 * the answers against ground truth the engine never sees.
 *
 * The six numbers it reports are chosen so that no single one can be gamed
 * without wrecking another:
 *
 *  - **False positive rate** falls to zero if the engine simply refuses to ever
 *    say anything, which **power** then catches.
 *  - **Power** rises if the engine grades everything confidently, which the
 *    false positive rate then catches.
 *  - **Restraint** is the one that is easy to forget and hardest to fake: a real
 *    edge on a sample too short to prove it must still be declined. An engine
 *    that scores well on power and false positives but badly on restraint is one
 *    that gets lucky on sample size rather than one that understands it.
 *  - **Correct refusals** covers input that is not a strategy at all.
 *  - **Calibration** asks whether "95% confident" means anything: across cases
 *    reporting a PSR in a band, how often was there actually an edge?
 *  - **Regime detection** is scored against its own null control, because a
 *    permutation test that fires on planted effects is worthless unless it stays
 *    quiet on the ones with nothing planted.
 *
 * Nothing in here can change the engine's answers; it only records them.
 */

import { analyseSignificance, type EvidenceTier, type SignificanceReport } from '../engine/significance';
import { buildRegimeMap, type FactorReport } from '../engine/regime';
import {
  EVALUATION_SUITE,
  EXPECTATION_RULES,
  materialiseCase,
  suiteComposition,
  type CaseExpectation,
  type SuiteCase,
} from './suite';
import { PROVABILITY_CONFIDENCE, type GenerateCaseOptions, type SyntheticDistribution } from './synthetic';

/**
 * The tiers that count as the engine making a claim.
 *
 * `weak` is deliberately NOT here. The engine's own copy calls it "positive but
 * not convincing", and a grader that treated it as a claim would be punishing the
 * engine for hedging — which is the behaviour we want.
 */
export const CONFIDENT_TIERS: readonly EvidenceTier[] = ['supported', 'strong'];

/** Significance level at which a regime permutation p-value counts as a detection. */
export const REGIME_ALPHA = 0.05;

/**
 * PRE-REGISTERED TARGETS.
 *
 * Written down before the engine was run against the suite, and not to be moved
 * afterwards. The two the brief fixes explicitly are the false positive rate
 * (≤ 0.05, the conventional bar and the one that matters commercially) and
 * correct refusals (1.00 — a refusal is not a statistical judgement call, it is
 * either right or it is a bug). The other four are set here at levels a
 * usable engine should clear comfortably; they are part of the contract from
 * this commit onward.
 */
export interface PreRegisteredTargets {
  readonly maxFalsePositiveRate: number;
  readonly minPower: number;
  readonly minCorrectRefusals: number;
  readonly minRestraint: number;
  readonly minRegimeDetectionRate: number;
  readonly maxRegimeFalsePositiveRate: number;
}

export const PRE_REGISTERED_TARGETS: PreRegisteredTargets = {
  maxFalsePositiveRate: 0.05,
  minPower: 0.8,
  minCorrectRefusals: 1,
  minRestraint: 0.9,
  minRegimeDetectionRate: 0.75,
  maxRegimeFalsePositiveRate: 0.05,
};

/** One row of the per-case table. */
export interface CaseOutcome {
  readonly id: string;
  readonly group: CaseExpectation;
  /** The pass rule for this group, in words. */
  readonly expectation: string;
  readonly distribution: SyntheticDistribution;
  readonly periods: number;
  readonly hasEdge: boolean;
  readonly trueSharpePerPeriod: number;
  readonly provableAtThisLength: boolean;
  /** Analytic MinTRL at 95% for the true Sharpe and shape; `null` when there is no edge. */
  readonly periodsRequired: number | null;
  readonly observedTier: EvidenceTier;
  readonly observedSharpePerPeriod: number | null;
  /**
   * Sample skewness and NON-EXCESS kurtosis, as the engine measured them.
   *
   * Recorded next to the population values because the gap between them is the
   * mechanism behind most of the interesting failures: the PSR correction for
   * non-normality is driven by the SAMPLE third and fourth moments, and on a short
   * window those are estimated from whichever tail events happened to show up.
   */
  readonly observedSkewness: number | null;
  readonly observedKurtosis: number | null;
  readonly populationSkewness: number;
  readonly populationKurtosis: number;
  readonly probabilisticSharpe: number | null;
  /** `true` when the engine graded this `supported` or `strong`. */
  readonly claimed: boolean;
  /** Permutation p-value on the planted factor, for regime cases only. */
  readonly regimePValue: number | null;
  readonly usableReturns: number;
  readonly pass: boolean;
  readonly note: string;
}

/** A rate with the counts behind it, because "0.05" from 2 cases is not a rate. */
export interface ScoredRate {
  readonly value: number | null;
  readonly numerator: number;
  readonly denominator: number;
}

export interface CalibrationBucket {
  readonly label: string;
  readonly lowerInclusive: number;
  readonly upperExclusive: number;
  readonly count: number;
  readonly withEdge: number;
  /** Observed fraction that truly had an edge; `null` when the bucket is empty. */
  readonly observedFraction: number | null;
}

export interface RegimeScore {
  readonly plantedCases: number;
  readonly detected: number;
  readonly detectionRate: ScoredRate;
  readonly nullCases: number;
  readonly falsePositives: number;
  readonly falsePositiveRate: ScoredRate;
  readonly alpha: number;
}

export interface EvaluationMetrics {
  readonly falsePositiveRate: ScoredRate;
  readonly power: ScoredRate;
  readonly correctRefusals: ScoredRate;
  readonly restraint: ScoredRate;
  readonly regime: RegimeScore;
}

export interface EvaluationSettings {
  readonly suiteSize: number;
  readonly composition: Readonly<Record<CaseExpectation, number>>;
  readonly benchmarkSharpe: number;
  readonly bootstrapResamples: number;
  readonly significanceSeed: number;
  readonly permutationResamples: number;
  readonly regimeSeed: number;
  readonly provabilityConfidence: number;
  readonly confidentTiers: readonly EvidenceTier[];
  readonly regimeAlpha: number;
  readonly momentMatching: NonNullable<GenerateCaseOptions['momentMatching']>;
}

export interface EvaluationReport {
  readonly settings: EvaluationSettings;
  readonly targets: PreRegisteredTargets;
  readonly metrics: EvaluationMetrics;
  readonly calibration: readonly CalibrationBucket[];
  readonly cases: readonly CaseOutcome[];
  /**
   * Cases whose DECLARED group disagrees with the generator's ground truth — for
   * example an `edge_provable` case whose length turns out to fall short of the
   * analytic MinTRL. Non-empty means the suite is mislabelled, which invalidates
   * the group it appears in, so it fails the run outright.
   */
  readonly integrityWarnings: readonly string[];
  readonly failures: readonly string[];
  readonly passed: boolean;
}

export interface EvaluationOptions {
  readonly cases?: readonly SuiteCase[];
  readonly benchmarkSharpe?: number;
  readonly bootstrapResamples?: number;
  readonly significanceSeed?: number;
  readonly permutationResamples?: number;
  readonly regimeSeed?: number;
  readonly momentMatching?: NonNullable<GenerateCaseOptions['momentMatching']>;
}

const DEFAULT_BOOTSTRAP_RESAMPLES = 2_000;
const DEFAULT_SIGNIFICANCE_SEED = 0x5eed_1234;
const DEFAULT_PERMUTATION_RESAMPLES = 2_000;
const DEFAULT_REGIME_SEED = 0xc0ffee;

/**
 * Confidence bands for the calibration table.
 *
 * The bands are the engine's own published decision boundaries (0.90 weak, 0.95
 * supported, 0.99 strong) plus a catch-all below 0.5, so the table answers the
 * question a user actually has: when this thing says 95-to-99 percent, how often
 * is it right?
 */
export const CALIBRATION_BANDS: readonly { label: string; lower: number; upper: number }[] = [
  { label: '< 0.50', lower: Number.NEGATIVE_INFINITY, upper: 0.5 },
  { label: '0.50 - 0.90', lower: 0.5, upper: 0.9 },
  { label: '0.90 - 0.95', lower: 0.9, upper: 0.95 },
  { label: '0.95 - 0.99', lower: 0.95, upper: 0.99 },
  { label: '>= 0.99', lower: 0.99, upper: Number.POSITIVE_INFINITY },
];

function rate(numerator: number, denominator: number): ScoredRate {
  return { value: denominator === 0 ? null : numerator / denominator, numerator, denominator };
}

/** `true` when the engine made a claim a reader would size a position on. */
function isClaim(tier: EvidenceTier): boolean {
  return CONFIDENT_TIERS.includes(tier);
}

/**
 * Cross-check the declared group against what the generator actually produced.
 *
 * A suite that says "provable" about a case that is not provable measures nothing,
 * and would do it silently. This turns that into a loud failure.
 */
function integrityWarning(
  entry: SuiteCase,
  truth: { hasEdge: boolean; provableAtThisLength: boolean; plantedRegimeEffect: boolean; degenerate: string | null },
): string | null {
  switch (entry.expectation) {
    case 'no_edge':
      return truth.hasEdge ? `${entry.id}: declared no_edge but the generator planted an edge.` : null;
    case 'edge_provable':
      if (!truth.hasEdge) return `${entry.id}: declared edge_provable but has no edge.`;
      return truth.provableAtThisLength
        ? null
        : `${entry.id}: declared edge_provable but the sample is shorter than the analytic MinTRL.`;
    case 'edge_not_provable':
      if (!truth.hasEdge) return `${entry.id}: declared edge_not_provable but has no edge.`;
      return truth.provableAtThisLength
        ? `${entry.id}: declared edge_not_provable but the sample already clears the analytic MinTRL.`
        : null;
    case 'regime_planted':
      return truth.plantedRegimeEffect ? null : `${entry.id}: declared regime_planted but both buckets share a Sharpe.`;
    case 'regime_null':
      return truth.plantedRegimeEffect ? `${entry.id}: declared regime_null but an effect was planted.` : null;
    case 'degenerate':
      return truth.degenerate === null ? `${entry.id}: declared degenerate but is an ordinary sampled case.` : null;
  }
}

/** Decide pass/fail and write the one-line explanation that goes in the table. */
function scoreCase(
  expectation: CaseExpectation,
  report: SignificanceReport,
  regimePValue: number | null,
): { pass: boolean; note: string } {
  const tier = report.evidence.tier;
  const claimed = isClaim(tier);

  switch (expectation) {
    case 'no_edge':
      return claimed
        ? { pass: false, note: `False positive: graded ${tier} on a record with no edge.` }
        : { pass: true, note: `Declined to claim an edge (${tier}).` };
    case 'edge_provable':
      return claimed
        ? { pass: true, note: `Detected the edge (${tier}).` }
        : { pass: false, note: `Missed a provable edge: graded ${tier}.` };
    case 'edge_not_provable':
      return claimed
        ? { pass: false, note: `Over-claimed: graded ${tier} on a sample shorter than the required track record.` }
        : { pass: true, note: `Correctly declined an unprovable edge (${tier}).` };
    case 'regime_planted':
      if (regimePValue === null) return { pass: false, note: 'No permutation test was produced for the planted factor.' };
      return regimePValue <= REGIME_ALPHA
        ? { pass: true, note: `Found the planted regime effect (p = ${regimePValue.toFixed(4)}).` }
        : { pass: false, note: `Missed the planted regime effect (p = ${regimePValue.toFixed(4)}).` };
    case 'regime_null':
      if (regimePValue === null) return { pass: true, note: 'No permutation test produced, so nothing was claimed.' };
      return regimePValue > REGIME_ALPHA
        ? { pass: true, note: `No regime effect claimed (p = ${regimePValue.toFixed(4)}).` }
        : { pass: false, note: `Claimed a regime effect that was never planted (p = ${regimePValue.toFixed(4)}).` };
    case 'degenerate':
      return tier === 'insufficient_evidence'
        ? { pass: true, note: 'Refused to grade unusable input.' }
        : { pass: false, note: `Graded unusable input as ${tier}.` };
  }
}

/** Pull the permutation p-value for the planted factor out of a regime map. */
function plantedFactorPValue(factors: readonly FactorReport[], factor: string): number | null {
  const match = factors.find((report) => report.key === factor);
  return match?.permutation?.pValue ?? null;
}

function buildCalibration(outcomes: readonly CaseOutcome[]): CalibrationBucket[] {
  return CALIBRATION_BANDS.map((band) => {
    let count = 0;
    let withEdge = 0;
    for (const outcome of outcomes) {
      const psr = outcome.probabilisticSharpe;
      if (psr === null) continue;
      if (psr < band.lower || psr >= band.upper) continue;
      count += 1;
      if (outcome.hasEdge) withEdge += 1;
    }
    return {
      label: band.label,
      lowerInclusive: band.lower,
      upperExclusive: band.upper,
      count,
      withEdge,
      observedFraction: count === 0 ? null : withEdge / count,
    };
  });
}

/**
 * Run the pre-registered suite through the engine and score it.
 *
 * Defaults match the engine's own defaults (2,000 bootstrap resamples, 2,000
 * permutations, the same seeds) so the scorecard describes the engine as it is
 * actually configured in production rather than a cheaper variant of it.
 */
export function runEvaluation(options: EvaluationOptions = {}): EvaluationReport {
  const cases = options.cases ?? EVALUATION_SUITE;
  const benchmarkSharpe = options.benchmarkSharpe ?? 0;
  const bootstrapResamples = options.bootstrapResamples ?? DEFAULT_BOOTSTRAP_RESAMPLES;
  const significanceSeed = options.significanceSeed ?? DEFAULT_SIGNIFICANCE_SEED;
  const permutationResamples = options.permutationResamples ?? DEFAULT_PERMUTATION_RESAMPLES;
  const regimeSeed = options.regimeSeed ?? DEFAULT_REGIME_SEED;
  const momentMatching = options.momentMatching ?? 'population';

  const outcomes: CaseOutcome[] = [];
  const integrityWarnings: string[] = [];

  for (const entry of cases) {
    const generated = materialiseCase(entry, { momentMatching });
    const warning = integrityWarning(entry, generated.truth);
    if (warning !== null) integrityWarnings.push(warning);

    const report = analyseSignificance(generated.record, {
      benchmarkSharpe,
      bootstrapResamples,
      seed: significanceSeed,
    });

    let regimePValue: number | null = null;
    const factor = generated.truth.regimeFactor;
    if (generated.regimes !== undefined && factor !== null) {
      const map = buildRegimeMap(generated.record, generated.regimes, {
        permutationResamples,
        seed: regimeSeed,
        factorKeys: [factor],
      });
      regimePValue = plantedFactorPValue(map.factors, factor);
    }

    const scored = scoreCase(entry.expectation, report, regimePValue);

    outcomes.push({
      id: entry.id,
      group: entry.expectation,
      expectation: EXPECTATION_RULES[entry.expectation],
      distribution: generated.truth.distribution,
      periods: generated.truth.periods,
      hasEdge: generated.truth.hasEdge,
      trueSharpePerPeriod: generated.truth.trueSharpePerPeriod,
      provableAtThisLength: generated.truth.provableAtThisLength,
      periodsRequired: generated.truth.periodsRequired,
      observedTier: report.evidence.tier,
      observedSharpePerPeriod: report.performance.sharpePerPeriod,
      observedSkewness: report.performance.skewness,
      observedKurtosis: report.performance.kurtosis,
      populationSkewness: generated.truth.populationSkewness,
      populationKurtosis: generated.truth.populationKurtosis,
      probabilisticSharpe: report.evidence.probabilisticSharpe,
      claimed: isClaim(report.evidence.tier),
      regimePValue,
      usableReturns: report.sample.usableReturns,
      pass: scored.pass,
      note: scored.note,
    });
  }

  const inGroup = (group: CaseExpectation): CaseOutcome[] => outcomes.filter((outcome) => outcome.group === group);

  const noEdge = inGroup('no_edge');
  const provable = inGroup('edge_provable');
  const notProvable = inGroup('edge_not_provable');
  const traps = inGroup('degenerate');
  const planted = inGroup('regime_planted');
  const nullRegime = inGroup('regime_null');

  const falsePositiveRate = rate(noEdge.filter((o) => o.claimed).length, noEdge.length);
  const power = rate(provable.filter((o) => o.claimed).length, provable.length);
  const correctRefusals = rate(
    traps.filter((o) => o.observedTier === 'insufficient_evidence').length,
    traps.length,
  );
  const restraint = rate(notProvable.filter((o) => !o.claimed).length, notProvable.length);

  const detected = planted.filter((o) => o.regimePValue !== null && o.regimePValue <= REGIME_ALPHA).length;
  const regimeFalsePositives = nullRegime.filter(
    (o) => o.regimePValue !== null && o.regimePValue <= REGIME_ALPHA,
  ).length;

  const regime: RegimeScore = {
    plantedCases: planted.length,
    detected,
    detectionRate: rate(detected, planted.length),
    nullCases: nullRegime.length,
    falsePositives: regimeFalsePositives,
    falsePositiveRate: rate(regimeFalsePositives, nullRegime.length),
    alpha: REGIME_ALPHA,
  };

  const metrics: EvaluationMetrics = { falsePositiveRate, power, correctRefusals, restraint, regime };

  const failures: string[] = [];
  const check = (
    label: string,
    observed: ScoredRate,
    target: number,
    direction: 'at_most' | 'at_least',
  ): void => {
    if (observed.value === null) {
      failures.push(`${label}: no cases in this group, so the target could not be evaluated.`);
      return;
    }
    const ok = direction === 'at_most' ? observed.value <= target : observed.value >= target;
    if (!ok) {
      failures.push(
        `${label}: measured ${observed.value.toFixed(4)} (${observed.numerator}/${observed.denominator}), target ${
          direction === 'at_most' ? '<=' : '>='
        } ${target.toFixed(2)}.`,
      );
    }
  };

  check('False positive rate', falsePositiveRate, PRE_REGISTERED_TARGETS.maxFalsePositiveRate, 'at_most');
  check('Power', power, PRE_REGISTERED_TARGETS.minPower, 'at_least');
  check('Correct refusals', correctRefusals, PRE_REGISTERED_TARGETS.minCorrectRefusals, 'at_least');
  check('Restraint', restraint, PRE_REGISTERED_TARGETS.minRestraint, 'at_least');
  check('Regime detection rate', regime.detectionRate, PRE_REGISTERED_TARGETS.minRegimeDetectionRate, 'at_least');
  check(
    'Regime false positive rate',
    regime.falsePositiveRate,
    PRE_REGISTERED_TARGETS.maxRegimeFalsePositiveRate,
    'at_most',
  );

  for (const warning of integrityWarnings) failures.push(`Suite integrity: ${warning}`);

  return {
    settings: {
      suiteSize: cases.length,
      composition: suiteComposition(cases),
      benchmarkSharpe,
      bootstrapResamples,
      significanceSeed,
      permutationResamples,
      regimeSeed,
      provabilityConfidence: PROVABILITY_CONFIDENCE,
      confidentTiers: CONFIDENT_TIERS,
      regimeAlpha: REGIME_ALPHA,
      momentMatching,
    },
    targets: PRE_REGISTERED_TARGETS,
    metrics,
    calibration: buildCalibration(outcomes),
    cases: outcomes,
    integrityWarnings,
    failures,
    passed: failures.length === 0,
  };
}
