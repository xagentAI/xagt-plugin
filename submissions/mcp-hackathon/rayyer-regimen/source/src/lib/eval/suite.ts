/**
 * THE PRE-REGISTERED EVALUATION SUITE.
 *
 * ──────────────────────────────────────────────────────────────────────────────
 *  This list of cases, every seed in it, and the pass targets in `harness.ts`
 *  were all fixed IN ADVANCE — written down before the engine was ever run
 *  against them. That is the only thing separating an evaluation from a demo.
 *  An evaluation you are allowed to edit after seeing the score is not measuring
 *  the engine, it is measuring how badly you wanted a good number.
 *
 *  So: if the engine fails a target, the finding is the failure. Cases are not
 *  removed, seeds are not resampled, and thresholds are not relaxed. Adding
 *  cases later is fine; deleting or re-seeding the ones below is not, and a
 *  change to this file is a change to the published contract.
 * ──────────────────────────────────────────────────────────────────────────────
 *
 * Shape of the suite, and why each group exists:
 *
 *  - **no_edge (36 cases, the largest group by design)** — the false-positive
 *    traps. Every one is a genuinely edgeless strategy across all three return
 *    shapes and six sample lengths. Over-claiming here is the failure mode that
 *    actually costs people money, so it gets the most cases and the tightest
 *    target.
 *  - **edge_provable (15)** — a real edge on a sample long enough to prove it.
 *    Missing these is a power failure: the engine is too timid to be useful.
 *  - **edge_not_provable (15)** — a real edge on a sample too short to prove it.
 *    Claiming these is NOT a success. The right answer is to decline.
 *  - **regime_planted (4)** — the edge lives only in high-VIX periods, and the
 *    permutation test should find it.
 *  - **regime_null (4)** — identical construction, identical factor series, but
 *    both buckets share one Sharpe. Anything the permutation test "finds" here
 *    it invented.
 *  - **degenerate (8)** — constant equity, three points, duplicated timestamps
 *    and out-of-order timestamps. The only acceptable answer is a refusal.
 *
 * Volatility is held at one value per distribution (normal 1.0%, skewed 1.4%,
 * fat-tailed 0.8% per period) so that the distribution axis is not confounded
 * with a scale axis. It cancels out of every Sharpe anyway; it is fixed only so
 * that the equity curves look like plausible daily records.
 */

import {
  generateCase,
  generateDegenerateCase,
  type CaseSpec,
  type DegenerateKind,
  type GeneratedCase,
  type GenerateCaseOptions,
  type SyntheticDistribution,
} from './synthetic';

/** Which group a case belongs to, which determines how it is scored. */
export type CaseExpectation =
  /** Truly no edge. Must NOT be graded `supported` or `strong`. */
  | 'no_edge'
  /** Real edge, sample long enough. SHOULD be graded `supported` or `strong`. */
  | 'edge_provable'
  /** Real edge, sample too short. Must NOT be graded `supported` or `strong`. */
  | 'edge_not_provable'
  /** Edge concentrated in one factor bucket. The permutation p-value should be ≤ 0.05. */
  | 'regime_planted'
  /** Factor present, no effect planted. The permutation p-value should be > 0.05. */
  | 'regime_null'
  /** Unusable input. Must return `insufficient_evidence`. */
  | 'degenerate';

/** Plain-language statement of what passing means, rendered straight into the scorecard. */
export const EXPECTATION_RULES: Readonly<Record<CaseExpectation, string>> = {
  no_edge: 'must not be graded supported/strong',
  edge_provable: 'should be graded supported/strong',
  edge_not_provable: 'must not be graded supported/strong',
  regime_planted: 'planted factor permutation p <= 0.05',
  regime_null: 'planted factor permutation p > 0.05',
  degenerate: 'must return insufficient_evidence',
};

export interface SyntheticSuiteCase {
  readonly kind: 'synthetic';
  readonly id: string;
  readonly expectation: Exclude<CaseExpectation, 'degenerate'>;
  readonly spec: CaseSpec;
}

export interface DegenerateSuiteCase {
  readonly kind: 'degenerate';
  readonly id: string;
  readonly expectation: 'degenerate';
  readonly degenerate: DegenerateKind;
  readonly seed: number;
}

export type SuiteCase = SyntheticSuiteCase | DegenerateSuiteCase;

/** VIX, because it is the one factor whose regime edges the engine publishes as fixed constants. */
export const REGIME_FACTOR = 'vix';

/** Per-period volatility per shape. Fixed, and irrelevant to every Sharpe in the suite. */
const VOL_NORMAL = 0.01;
const VOL_SKEWED = 0.014;
const VOL_FAT = 0.008;
const VOL_REGIME = 0.012;

// --- Private builders. Seeds are passed in literally at every call site. ------

function noEdgeCase(
  id: string,
  periods: number,
  distribution: SyntheticDistribution,
  volatilityPerPeriod: number,
  seed: number,
): SyntheticSuiteCase {
  return {
    kind: 'synthetic',
    id,
    expectation: 'no_edge',
    spec: { id, periods, trueSharpePerPeriod: 0, volatilityPerPeriod, distribution, seed },
  };
}

function edgeCase(
  expectation: 'edge_provable' | 'edge_not_provable',
  id: string,
  periods: number,
  trueSharpePerPeriod: number,
  distribution: SyntheticDistribution,
  volatilityPerPeriod: number,
  seed: number,
): SyntheticSuiteCase {
  return {
    kind: 'synthetic',
    id,
    expectation,
    spec: { id, periods, trueSharpePerPeriod, volatilityPerPeriod, distribution, seed },
  };
}

function regimeCase(
  expectation: 'regime_planted' | 'regime_null',
  id: string,
  periods: number,
  distribution: SyntheticDistribution,
  volatilityPerPeriod: number,
  activeBucketSharpe: number,
  inactiveBucketSharpe: number,
  seed: number,
): SyntheticSuiteCase {
  return {
    kind: 'synthetic',
    id,
    expectation,
    spec: {
      id,
      // Ignored when a regimeEffect is present; the bucket Sharpes supply the drift.
      trueSharpePerPeriod: 0,
      periods,
      volatilityPerPeriod,
      distribution,
      regimeEffect: { factor: REGIME_FACTOR, activeBucketSharpe, inactiveBucketSharpe },
      seed,
    },
  };
}

function degenerateCase(id: string, degenerate: DegenerateKind, seed: number): DegenerateSuiteCase {
  return { kind: 'degenerate', id, expectation: 'degenerate', degenerate, seed };
}

// --- Group 1: true no-edge. The false-positive traps. ------------------------

const NO_EDGE_CASES: readonly SyntheticSuiteCase[] = [
  noEdgeCase('no-edge/normal/n25/a', 25, 'normal', VOL_NORMAL, 700_001),
  noEdgeCase('no-edge/normal/n25/b', 25, 'normal', VOL_NORMAL, 700_002),
  noEdgeCase('no-edge/normal/n40/a', 40, 'normal', VOL_NORMAL, 700_003),
  noEdgeCase('no-edge/normal/n40/b', 40, 'normal', VOL_NORMAL, 700_004),
  noEdgeCase('no-edge/normal/n60/a', 60, 'normal', VOL_NORMAL, 700_005),
  noEdgeCase('no-edge/normal/n60/b', 60, 'normal', VOL_NORMAL, 700_006),
  noEdgeCase('no-edge/normal/n120/a', 120, 'normal', VOL_NORMAL, 700_007),
  noEdgeCase('no-edge/normal/n120/b', 120, 'normal', VOL_NORMAL, 700_008),
  noEdgeCase('no-edge/normal/n250/a', 250, 'normal', VOL_NORMAL, 700_009),
  noEdgeCase('no-edge/normal/n250/b', 250, 'normal', VOL_NORMAL, 700_010),
  noEdgeCase('no-edge/normal/n500/a', 500, 'normal', VOL_NORMAL, 700_011),
  noEdgeCase('no-edge/normal/n500/b', 500, 'normal', VOL_NORMAL, 700_012),
  noEdgeCase('no-edge/skewed/n25/a', 25, 'skewed', VOL_SKEWED, 700_013),
  noEdgeCase('no-edge/skewed/n25/b', 25, 'skewed', VOL_SKEWED, 700_014),
  noEdgeCase('no-edge/skewed/n40/a', 40, 'skewed', VOL_SKEWED, 700_015),
  noEdgeCase('no-edge/skewed/n40/b', 40, 'skewed', VOL_SKEWED, 700_016),
  noEdgeCase('no-edge/skewed/n60/a', 60, 'skewed', VOL_SKEWED, 700_017),
  noEdgeCase('no-edge/skewed/n60/b', 60, 'skewed', VOL_SKEWED, 700_018),
  noEdgeCase('no-edge/skewed/n120/a', 120, 'skewed', VOL_SKEWED, 700_019),
  noEdgeCase('no-edge/skewed/n120/b', 120, 'skewed', VOL_SKEWED, 700_020),
  noEdgeCase('no-edge/skewed/n250/a', 250, 'skewed', VOL_SKEWED, 700_021),
  noEdgeCase('no-edge/skewed/n250/b', 250, 'skewed', VOL_SKEWED, 700_022),
  noEdgeCase('no-edge/skewed/n500/a', 500, 'skewed', VOL_SKEWED, 700_023),
  noEdgeCase('no-edge/skewed/n500/b', 500, 'skewed', VOL_SKEWED, 700_024),
  noEdgeCase('no-edge/fat/n25/a', 25, 'fat_tailed', VOL_FAT, 700_025),
  noEdgeCase('no-edge/fat/n25/b', 25, 'fat_tailed', VOL_FAT, 700_026),
  noEdgeCase('no-edge/fat/n40/a', 40, 'fat_tailed', VOL_FAT, 700_027),
  noEdgeCase('no-edge/fat/n40/b', 40, 'fat_tailed', VOL_FAT, 700_028),
  noEdgeCase('no-edge/fat/n60/a', 60, 'fat_tailed', VOL_FAT, 700_029),
  noEdgeCase('no-edge/fat/n60/b', 60, 'fat_tailed', VOL_FAT, 700_030),
  noEdgeCase('no-edge/fat/n120/a', 120, 'fat_tailed', VOL_FAT, 700_031),
  noEdgeCase('no-edge/fat/n120/b', 120, 'fat_tailed', VOL_FAT, 700_032),
  noEdgeCase('no-edge/fat/n250/a', 250, 'fat_tailed', VOL_FAT, 700_033),
  noEdgeCase('no-edge/fat/n250/b', 250, 'fat_tailed', VOL_FAT, 700_034),
  noEdgeCase('no-edge/fat/n500/a', 500, 'fat_tailed', VOL_FAT, 700_035),
  noEdgeCase('no-edge/fat/n500/b', 500, 'fat_tailed', VOL_FAT, 700_036),
];

// --- Group 2: real edge, sample long enough to prove it. ---------------------
//
// Lengths chosen against the analytic MinTRL for each shape at 95%. A normal
// record at SR 0.40 needs 20 periods, a skewed one needs 37 and a fat-tailed one
// 24 — which is the whole reason the distribution axis exists. Every length
// below clears the requirement for all three shapes, and the harness re-derives
// the flag from the generator rather than trusting this comment.

const EDGE_PROVABLE_CASES: readonly SyntheticSuiteCase[] = [
  edgeCase('edge_provable', 'edge/normal/sr40/n60', 60, 0.4, 'normal', VOL_NORMAL, 710_001),
  edgeCase('edge_provable', 'edge/normal/sr30/n90', 90, 0.3, 'normal', VOL_NORMAL, 710_002),
  edgeCase('edge_provable', 'edge/normal/sr25/n120', 120, 0.25, 'normal', VOL_NORMAL, 710_003),
  edgeCase('edge_provable', 'edge/normal/sr15/n250', 250, 0.15, 'normal', VOL_NORMAL, 710_004),
  edgeCase('edge_provable', 'edge/normal/sr10/n400', 400, 0.1, 'normal', VOL_NORMAL, 710_005),
  edgeCase('edge_provable', 'edge/skewed/sr40/n60', 60, 0.4, 'skewed', VOL_SKEWED, 710_006),
  edgeCase('edge_provable', 'edge/skewed/sr30/n90', 90, 0.3, 'skewed', VOL_SKEWED, 710_007),
  edgeCase('edge_provable', 'edge/skewed/sr25/n120', 120, 0.25, 'skewed', VOL_SKEWED, 710_008),
  edgeCase('edge_provable', 'edge/skewed/sr15/n250', 250, 0.15, 'skewed', VOL_SKEWED, 710_009),
  edgeCase('edge_provable', 'edge/skewed/sr10/n400', 400, 0.1, 'skewed', VOL_SKEWED, 710_010),
  edgeCase('edge_provable', 'edge/fat/sr40/n60', 60, 0.4, 'fat_tailed', VOL_FAT, 710_011),
  edgeCase('edge_provable', 'edge/fat/sr30/n90', 90, 0.3, 'fat_tailed', VOL_FAT, 710_012),
  edgeCase('edge_provable', 'edge/fat/sr25/n120', 120, 0.25, 'fat_tailed', VOL_FAT, 710_013),
  edgeCase('edge_provable', 'edge/fat/sr15/n250', 250, 0.15, 'fat_tailed', VOL_FAT, 710_014),
  edgeCase('edge_provable', 'edge/fat/sr10/n400', 400, 0.1, 'fat_tailed', VOL_FAT, 710_015),
];

// --- Group 3: real edge, sample too short to prove it. -----------------------
//
// Every length here sits below the MinTRL for its shape while staying above the
// engine's 20-return floor, so the engine DOES grade them and has a real chance
// to over-claim. Declining is the correct answer; these cases measure restraint.

const EDGE_NOT_PROVABLE_CASES: readonly SyntheticSuiteCase[] = [
  edgeCase('edge_not_provable', 'short-edge/normal/sr30/n30', 30, 0.3, 'normal', VOL_NORMAL, 720_001),
  edgeCase('edge_not_provable', 'short-edge/normal/sr25/n25', 25, 0.25, 'normal', VOL_NORMAL, 720_002),
  edgeCase('edge_not_provable', 'short-edge/normal/sr15/n45', 45, 0.15, 'normal', VOL_NORMAL, 720_003),
  edgeCase('edge_not_provable', 'short-edge/normal/sr10/n80', 80, 0.1, 'normal', VOL_NORMAL, 720_004),
  edgeCase('edge_not_provable', 'short-edge/normal/sr08/n150', 150, 0.08, 'normal', VOL_NORMAL, 720_005),
  edgeCase('edge_not_provable', 'short-edge/skewed/sr30/n30', 30, 0.3, 'skewed', VOL_SKEWED, 720_006),
  edgeCase('edge_not_provable', 'short-edge/skewed/sr25/n25', 25, 0.25, 'skewed', VOL_SKEWED, 720_007),
  edgeCase('edge_not_provable', 'short-edge/skewed/sr15/n45', 45, 0.15, 'skewed', VOL_SKEWED, 720_008),
  edgeCase('edge_not_provable', 'short-edge/skewed/sr10/n80', 80, 0.1, 'skewed', VOL_SKEWED, 720_009),
  edgeCase('edge_not_provable', 'short-edge/skewed/sr08/n150', 150, 0.08, 'skewed', VOL_SKEWED, 720_010),
  edgeCase('edge_not_provable', 'short-edge/fat/sr30/n30', 30, 0.3, 'fat_tailed', VOL_FAT, 720_011),
  edgeCase('edge_not_provable', 'short-edge/fat/sr25/n25', 25, 0.25, 'fat_tailed', VOL_FAT, 720_012),
  edgeCase('edge_not_provable', 'short-edge/fat/sr15/n45', 45, 0.15, 'fat_tailed', VOL_FAT, 720_013),
  edgeCase('edge_not_provable', 'short-edge/fat/sr10/n80', 80, 0.1, 'fat_tailed', VOL_FAT, 720_014),
  edgeCase('edge_not_provable', 'short-edge/fat/sr08/n150', 150, 0.08, 'fat_tailed', VOL_FAT, 720_015),
];

// --- Group 4: planted regime effect, and its null control. -------------------
//
// Lengths of 180 and 300 so that all four published VIX buckets clear the regime
// engine's 15-observation minimum. Each planted case is paired with a null case
// of the same length and shape: same factor series construction, same bucket
// split, no difference between the buckets. Any "detection" on the null cases is
// the test finding a pattern in noise, which is the only way to know the
// detections on the planted cases mean anything.

const REGIME_CASES: readonly SyntheticSuiteCase[] = [
  regimeCase('regime_planted', 'regime/planted/normal/n180', 180, 'normal', VOL_REGIME, 0.35, 0.0, 730_001),
  regimeCase('regime_planted', 'regime/planted/normal/n300', 300, 'normal', VOL_REGIME, 0.25, -0.05, 730_002),
  regimeCase('regime_planted', 'regime/planted/skewed/n180', 180, 'skewed', VOL_REGIME, 0.35, 0.0, 730_003),
  regimeCase('regime_planted', 'regime/planted/fat/n300', 300, 'fat_tailed', VOL_REGIME, 0.3, -0.05, 730_004),
  regimeCase('regime_null', 'regime/null/normal/n180', 180, 'normal', VOL_REGIME, 0.0, 0.0, 740_001),
  regimeCase('regime_null', 'regime/null/normal/n300', 300, 'normal', VOL_REGIME, 0.1, 0.1, 740_002),
  regimeCase('regime_null', 'regime/null/skewed/n180', 180, 'skewed', VOL_REGIME, 0.0, 0.0, 740_003),
  regimeCase('regime_null', 'regime/null/fat/n300', 300, 'fat_tailed', VOL_REGIME, 0.1, 0.1, 740_004),
];

// --- Group 5: degenerate traps. ----------------------------------------------
//
// Four distinct ways for input to be unusable, two instances each so a single
// lucky seed cannot carry the group.

const DEGENERATE_CASES: readonly DegenerateSuiteCase[] = [
  degenerateCase('trap/constant-equity/a', 'constant_equity', 750_001),
  degenerateCase('trap/constant-equity/b', 'constant_equity', 750_002),
  degenerateCase('trap/three-points/a', 'too_few_points', 750_003),
  degenerateCase('trap/three-points/b', 'too_few_points', 750_004),
  degenerateCase('trap/duplicate-timestamps/a', 'duplicate_timestamps', 750_005),
  degenerateCase('trap/duplicate-timestamps/b', 'duplicate_timestamps', 750_006),
  degenerateCase('trap/unsorted-timestamps/a', 'unsorted_timestamps', 750_007),
  degenerateCase('trap/unsorted-timestamps/b', 'unsorted_timestamps', 750_008),
];

/** The committed suite: 82 cases, in a fixed order, with fixed seeds. */
export const EVALUATION_SUITE: readonly SuiteCase[] = [
  ...NO_EDGE_CASES,
  ...EDGE_PROVABLE_CASES,
  ...EDGE_NOT_PROVABLE_CASES,
  ...REGIME_CASES,
  ...DEGENERATE_CASES,
];

/**
 * Turn a suite entry into the actual data the engine sees.
 *
 * Kept as a function rather than a pre-built constant so that a suite of 82
 * cases — several of them 500 periods long — is generated on demand instead of
 * at import time, and so the harness can pass generation options through.
 */
export function materialiseCase(entry: SuiteCase, options: GenerateCaseOptions = {}): GeneratedCase {
  if (entry.kind === 'degenerate') {
    return generateDegenerateCase(entry.id, entry.degenerate, entry.seed);
  }
  return generateCase(entry.spec, options);
}

/** Count of cases per expectation group, used by the scorecard header and by tests. */
export function suiteComposition(
  cases: readonly SuiteCase[] = EVALUATION_SUITE,
): Readonly<Record<CaseExpectation, number>> {
  const counts: Record<CaseExpectation, number> = {
    no_edge: 0,
    edge_provable: 0,
    edge_not_provable: 0,
    regime_planted: 0,
    regime_null: 0,
    degenerate: 0,
  };
  for (const entry of cases) counts[entry.expectation] += 1;
  return counts;
}
