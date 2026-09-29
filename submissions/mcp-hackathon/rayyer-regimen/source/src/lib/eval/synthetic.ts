/**
 * Seeded generation of LABELLED synthetic track records.
 *
 * The engine answers "is this distinguishable from luck?". There is exactly one
 * honest way to check that answer: feed it records whose truth we already know —
 * some with a planted edge, most without — and count how often it agrees. Real
 * strategies cannot do this job because nobody knows their true Sharpe.
 *
 * Three properties are load-bearing here.
 *
 *  1. **Determinism.** Every draw comes from `mulberry32` seeded by the case's own
 *     `seed`. There is no `Math.random` and no `Date.now` anywhere in this file, so
 *     the scorecard is a fact about the engine rather than a fact about the day it
 *     was run.
 *
 *  2. **Sampling noise is preserved.** Shapes are standardised by their *population*
 *     moments, not by the realised sample moments of each draw. This matters more
 *     than it looks: dividing each sample by its own realised mean and standard
 *     deviation would pin the observed Sharpe to the true Sharpe exactly, a
 *     no-edge case would show SR̂ = 0 every single time, and the measured false
 *     positive rate would be 0.00 by construction rather than by merit. The whole
 *     point of a false-positive trap is that luck sometimes produces a flattering
 *     sample. `momentMatching: 'sample'` is available for tests that want the
 *     realised moments pinned exactly, and is deliberately not what the suite uses.
 *
 *  3. **Shape varies at a fixed population Sharpe.** `normal`, `skewed` and
 *     `fat_tailed` all standardise to population mean 0 and population standard
 *     deviation 1 before the drift and volatility are applied, so the only thing
 *     that changes across the distribution axis is the third and fourth moment —
 *     which is exactly what the Probabilistic Sharpe Ratio claims to correct for.
 *     If PSR is doing its job, a skewed record should need a longer track record to
 *     reach the same confidence as a normal one at the same Sharpe.
 */

import { mean, stdDev } from '../stats/moments';
import { mulberry32, type Rng } from '../stats/numeric';
import { minimumTrackRecordLength } from '../stats/sharpe';
import type { EquityPoint, Provenance, RegimeObservation, RegimeSeries, TrackRecord } from '../sources/types';

// --- Fixed constants ---------------------------------------------------------

/** Source id stamped on every synthetic record, so nothing confuses one for real data. */
export const SYNTHETIC_SOURCE_ID = 'synthetic-eval';

/** Every curve starts here. A round number makes an equity column readable at a glance. */
export const STARTING_EQUITY = 10_000;

/** One calendar day in milliseconds; synthetic curves are daily. */
export const DAY_MS = 86_400_000;

/** Fixed start date (2021-01-01 UTC). Hard-coded so no clock enters generation. */
export const SYNTHETIC_EPOCH_MS = Date.UTC(2021, 0, 1);

/** Fixed provenance timestamp. A real `fetchedAt` would make the suite non-reproducible. */
export const SYNTHETIC_FETCHED_AT = '2021-01-01T00:00:00.000Z';

/**
 * Confidence used for the `provableAtThisLength` flag.
 *
 * 95% because that is the level the engine's own Minimum Track Record Length
 * defaults to; grading against a different bar would be grading against a
 * different question.
 */
export const PROVABILITY_CONFIDENCE = 0.95;

/**
 * Floor on a single period return, so equity is strictly positive by construction.
 *
 * At the volatilities the suite uses (≤ 2% per period) a draw this extreme would be
 * a 45-sigma event even under Student-t, so the clamp never binds in practice. It
 * exists so that the invariant "equity > 0 always" is a property of the code rather
 * than a property of the seeds.
 */
export const MINIMUM_PERIOD_RETURN = -0.9;

/**
 * Degrees of freedom for the fat-tailed generator.
 *
 * Five rather than four, and the reason is not cosmetic: a Student-t with ν = 4 has
 * no finite fourth moment, so its population kurtosis — and therefore the analytic
 * Minimum Track Record Length that `provableAtThisLength` is computed from — does
 * not exist. ν = 5 gives a population kurtosis of exactly 9 (excess 6, three times
 * the normal's excess-0) which is unambiguously fat-tailed while leaving the
 * grading maths defined.
 */
export const STUDENT_T_DEGREES_OF_FREEDOM = 5;

/** Probability that a given period falls in the regime-effect's ACTIVE bucket. */
export const ACTIVE_BUCKET_PROBABILITY = 0.5;

/** Offset applied to the case seed for the regime stream, so it never aliases the return stream. */
const REGIME_STREAM_OFFSET = 0x5f37_1a03;

// --- Specification -----------------------------------------------------------

export type SyntheticDistribution = 'normal' | 'skewed' | 'fat_tailed';

/** A planted regime effect: the edge exists only inside one bucket of one factor. */
export interface RegimeEffectSpec {
  /**
   * Factor key, joined against `FACTOR_BUCKETING` in the regime engine.
   *
   * Values are emitted on the VIX scale (roughly 8–45), so `'vix'` is the key whose
   * published fixed edges line up with what this generator plants. Passing another
   * key still produces a usable series, but the engine will tercile-split it.
   */
  readonly factor: string;
  readonly activeBucketSharpe: number;
  readonly inactiveBucketSharpe: number;
}

export interface CaseSpec {
  readonly id: string;
  /**
   * Number of RETURN periods.
   *
   * The equity curve therefore carries `periods + 1` points. Periods rather than
   * points because Minimum Track Record Length is denominated in returns, and the
   * grading compares the two directly — an off-by-one here would silently shift
   * every provability verdict.
   */
  readonly periods: number;
  /**
   * True per-period Sharpe. `0` means genuinely no edge.
   *
   * Ignored when `regimeEffect` is set: there the per-period drift comes from the
   * bucket Sharpes, and the blended population Sharpe is computed for you and
   * reported as `truth.trueSharpePerPeriod`.
   */
  readonly trueSharpePerPeriod: number;
  readonly volatilityPerPeriod: number;
  readonly distribution: SyntheticDistribution;
  readonly regimeEffect?: RegimeEffectSpec;
  readonly seed: number;
}

/** Why a degenerate case is degenerate. Each one is a different way for input to be unusable. */
export type DegenerateKind =
  /** Every equity value identical: zero variance, so the Sharpe ratio does not exist. */
  | 'constant_equity'
  /** Three points, two returns. Nothing can be inferred from that. */
  | 'too_few_points'
  /** Timestamps repeat, so most rows collapse during cleaning. */
  | 'duplicate_timestamps'
  /** Timestamps arrive out of order. */
  | 'unsorted_timestamps';

/**
 * Ground truth: what the engine SHOULD be able to say, not merely what is true.
 *
 * `provableAtThisLength` is the flag that keeps the grading honest. A true edge of
 * 0.1 Sharpe per period needs roughly 273 normal periods before it clears 95%
 * confidence; on a 25-period sample it is real and unprovable at the same time, and
 * an engine that claims it anyway is wrong, not perceptive. Counting that as a
 * missed detection would reward exactly the behaviour this product exists to stop.
 */
export interface CaseTruth {
  readonly hasEdge: boolean;
  /** Population per-period Sharpe of the whole series (blended, for regime cases). */
  readonly trueSharpePerPeriod: number;
  readonly periods: number;
  readonly distribution: SyntheticDistribution;
  /** Population skewness of the standardised shape. */
  readonly populationSkewness: number;
  /** Population NON-EXCESS kurtosis of the standardised shape (normal = 3). */
  readonly populationKurtosis: number;
  /** `true` when `periods` reaches the analytic MinTRL at {@link PROVABILITY_CONFIDENCE}. */
  readonly provableAtThisLength: boolean;
  /** Analytic MinTRL in periods; `null` when the true Sharpe does not exceed 0. */
  readonly minimumTrackRecordLength: number | null;
  /** `ceil(minimumTrackRecordLength)`; `null` when MinTRL is undefined. */
  readonly periodsRequired: number | null;
  /** Factor key carrying the planted effect, or `null`. */
  readonly regimeFactor: string | null;
  /** `true` only when the two bucket Sharpes actually differ. */
  readonly plantedRegimeEffect: boolean;
  /** Set when the case is a degenerate trap rather than a sampled strategy. */
  readonly degenerate: DegenerateKind | null;
}

export interface GeneratedCase {
  readonly spec: CaseSpec;
  readonly truth: CaseTruth;
  readonly record: TrackRecord;
  readonly regimes?: RegimeSeries;
}

/** How the shape draws are normalised. See the module docblock for why this matters. */
export type MomentMatching =
  /** Standardise by the distribution's known population moments; sampling noise survives. */
  | 'population'
  /** Standardise by the draw's own realised moments; realised mean and sd hit the target exactly. */
  | 'sample';

export interface GenerateCaseOptions {
  /** Defaults to `'population'`. `'sample'` destroys sampling noise — see the docblock. */
  readonly momentMatching?: MomentMatching;
}

// --- Population moments of each shape ----------------------------------------

/** Mean, standard deviation, skewness and NON-EXCESS kurtosis of a distribution. */
export interface PopulationMoments {
  readonly mean: number;
  readonly sd: number;
  readonly skewness: number;
  readonly kurtosis: number;
}

/**
 * The skewed shape: a two-component normal mixture.
 *
 *     X ~ N(0.25, 0.60²)  with probability 0.90
 *     X ~ N(-2.25, 1.40²) with probability 0.10
 *
 * The components are chosen so the mixture mean is exactly zero
 * (0.9 · 0.25 + 0.1 · (−2.25) = 0) and so the rare component is a long left tail —
 * the shape of a strategy that collects small premiums and occasionally gives a
 * large piece back. That produces a population skewness near −1.96 and a population
 * kurtosis near 8.66, both far enough from normal that the PSR correction has
 * something real to correct.
 *
 * Negative rather than positive skew on purpose: negative skew makes the same
 * Sharpe LESS significant under Mertens' variance term, so this is the direction
 * where an engine ignoring shape would over-claim.
 */
const SKEW_MIXTURE_WEIGHT = 0.9;
const SKEW_MIXTURE_BODY = { mean: 0.25, sd: 0.6 } as const;
const SKEW_MIXTURE_TAIL = { mean: -2.25, sd: 1.4 } as const;

/**
 * Closed-form central moments of a two-component normal mixture.
 *
 * For a mixture Σ wᵢ·N(mᵢ, sᵢ²) with overall mean m and deviations dᵢ = mᵢ − m:
 *
 *     μ₂ = Σ wᵢ (sᵢ² + dᵢ²)
 *     μ₃ = Σ wᵢ (3 sᵢ² dᵢ + dᵢ³)
 *     μ₄ = Σ wᵢ (3 sᵢ⁴ + 6 sᵢ² dᵢ² + dᵢ⁴)
 *
 * Computed here rather than hard-coded so that changing the mixture constants
 * cannot silently desynchronise the moments the grading depends on.
 */
function normalMixtureMoments(): PopulationMoments {
  const w = SKEW_MIXTURE_WEIGHT;
  const q = 1 - w;
  const m = w * SKEW_MIXTURE_BODY.mean + q * SKEW_MIXTURE_TAIL.mean;
  const d1 = SKEW_MIXTURE_BODY.mean - m;
  const d2 = SKEW_MIXTURE_TAIL.mean - m;
  const v1 = SKEW_MIXTURE_BODY.sd * SKEW_MIXTURE_BODY.sd;
  const v2 = SKEW_MIXTURE_TAIL.sd * SKEW_MIXTURE_TAIL.sd;

  const mu2 = w * (v1 + d1 * d1) + q * (v2 + d2 * d2);
  const mu3 = w * (3 * v1 * d1 + d1 ** 3) + q * (3 * v2 * d2 + d2 ** 3);
  const mu4 = w * (3 * v1 * v1 + 6 * v1 * d1 * d1 + d1 ** 4) + q * (3 * v2 * v2 + 6 * v2 * d2 * d2 + d2 ** 4);

  return {
    mean: m,
    sd: Math.sqrt(mu2),
    skewness: mu3 / mu2 ** 1.5,
    kurtosis: mu4 / (mu2 * mu2),
  };
}

const SKEW_MIXTURE_MOMENTS = normalMixtureMoments();

/**
 * Population moments of each shape AFTER standardisation.
 *
 * Mean 0 and standard deviation 1 across the board — that is the point of
 * standardising — with skewness and kurtosis carrying the difference. These are the
 * values `provableAtThisLength` is computed from, because the honest question is
 * "how long would this record have to be, given the shape it is actually drawn
 * from?", not "given a normal one".
 */
export const STANDARDISED_MOMENTS: Readonly<Record<SyntheticDistribution, PopulationMoments>> = {
  normal: { mean: 0, sd: 1, skewness: 0, kurtosis: 3 },
  skewed: {
    mean: 0,
    sd: 1,
    skewness: SKEW_MIXTURE_MOMENTS.skewness,
    kurtosis: SKEW_MIXTURE_MOMENTS.kurtosis,
  },
  fat_tailed: {
    mean: 0,
    sd: 1,
    skewness: 0,
    // Student-t kurtosis: 3 + 6/(ν − 4), finite for ν > 4. At ν = 5 that is exactly 9.
    kurtosis: 3 + 6 / (STUDENT_T_DEGREES_OF_FREEDOM - 4),
  },
};

// --- Draws -------------------------------------------------------------------

/**
 * Box–Muller on the seeded uniform stream, with the second variate cached.
 *
 * Box–Muller converts a pair of uniforms into a pair of exact standard normals:
 *
 *     r = √(−2 ln u₁),  z₀ = r·cos(2πu₂),  z₁ = r·sin(2πu₂)
 *
 * Caching `z₁` means no draw is thrown away, so the stream position advances
 * predictably and a case with `n` periods is a prefix-stable extension of the same
 * case with fewer. `u₁` is floored at 2⁻⁵³ because `mulberry32` can return exactly
 * zero (probability 2⁻³²) and `ln 0` would poison the whole series.
 */
function createNormalStream(rng: Rng): () => number {
  let spare: number | null = null;
  return function nextNormal(): number {
    if (spare !== null) {
      const value = spare;
      spare = null;
      return value;
    }
    const u1 = Math.max(rng(), Number.EPSILON / 2);
    const u2 = rng();
    const radius = Math.sqrt(-2 * Math.log(u1));
    const angle = 2 * Math.PI * u2;
    spare = radius * Math.sin(angle);
    return radius * Math.cos(angle);
  };
}

/**
 * One standardised draw from the requested shape: population mean 0, population sd 1.
 *
 *  - `normal` — a Box–Muller variate, already standard.
 *  - `skewed` — the two-component mixture above, re-centred and re-scaled by its
 *    closed-form mean and standard deviation.
 *  - `fat_tailed` — Student-t via the definition t = Z / √(V/ν) with V ~ χ²ᵥ built
 *    as the sum of ν squared standard normals, then divided by √(ν/(ν−2)) which is
 *    the t's population standard deviation. Constructing χ² from normals rather than
 *    from a gamma sampler keeps the whole file on one auditable primitive.
 */
function standardisedDraw(distribution: SyntheticDistribution, rng: Rng, nextNormal: () => number): number {
  if (distribution === 'normal') return nextNormal();

  if (distribution === 'skewed') {
    const component = rng() < SKEW_MIXTURE_WEIGHT ? SKEW_MIXTURE_BODY : SKEW_MIXTURE_TAIL;
    const raw = component.mean + component.sd * nextNormal();
    return (raw - SKEW_MIXTURE_MOMENTS.mean) / SKEW_MIXTURE_MOMENTS.sd;
  }

  const nu = STUDENT_T_DEGREES_OF_FREEDOM;
  const z = nextNormal();
  let chiSquare = 0;
  for (let i = 0; i < nu; i += 1) {
    const g = nextNormal();
    chiSquare += g * g;
  }
  const t = z / Math.sqrt(chiSquare / nu);
  const populationSd = Math.sqrt(nu / (nu - 2));
  return t / populationSd;
}

/** Re-centre and re-scale a draw to realised mean 0 and realised sample sd 1. */
function standardiseToSample(values: number[]): void {
  const m = mean(values);
  const sd = stdDev(values, { ddof: 1 });
  if (m === null || sd === null || sd === 0) return;
  for (let i = 0; i < values.length; i += 1) {
    values[i] = ((values[i] as number) - m) / sd;
  }
}

// --- Construction ------------------------------------------------------------

function provenance(operation: string): Provenance {
  return {
    source: SYNTHETIC_SOURCE_ID,
    operation,
    fetchedAt: SYNTHETIC_FETCHED_AT,
    cached: false,
  };
}

/** Compound a return series into a strictly positive daily equity curve from {@link STARTING_EQUITY}. */
function buildEquityCurve(returns: readonly number[]): EquityPoint[] {
  const points: EquityPoint[] = [{ t: SYNTHETIC_EPOCH_MS, equity: STARTING_EQUITY }];
  let level = STARTING_EQUITY;
  for (let i = 0; i < returns.length; i += 1) {
    level *= 1 + (returns[i] as number);
    points.push({ t: SYNTHETIC_EPOCH_MS + (i + 1) * DAY_MS, equity: level });
  }
  return points;
}

/** UTC calendar date of an epoch-millisecond timestamp, `YYYY-MM-DD`. */
function utcDate(epochMs: number): string {
  return new Date(epochMs).toISOString().slice(0, 10);
}

/**
 * Population Sharpe of the whole series.
 *
 * With no regime effect that is simply the specified drift. With one, the series is
 * a 50/50 mixture of two drifts at a common volatility, so the mean is the average
 * of the two bucket means while the variance picks up the between-bucket term:
 *
 *     SR = (p·a + (1−p)·i) / √(1 + p(1−p)(a − i)²)
 *
 * Reporting the blend rather than either bucket keeps `hasEdge` an honest statement
 * about the record the engine is actually handed.
 */
function populationSharpe(spec: CaseSpec): number {
  const effect = spec.regimeEffect;
  if (effect === undefined) return spec.trueSharpePerPeriod;
  const p = ACTIVE_BUCKET_PROBABILITY;
  const gap = effect.activeBucketSharpe - effect.inactiveBucketSharpe;
  const blendedMean = p * effect.activeBucketSharpe + (1 - p) * effect.inactiveBucketSharpe;
  return blendedMean / Math.sqrt(1 + p * (1 - p) * gap * gap);
}

/**
 * Resolve `provableAtThisLength` from the analytic Minimum Track Record Length.
 *
 * This calls the engine's own `minimumTrackRecordLength` rather than reimplementing
 * Bailey & López de Prado's equation (8). Reimplementing it would make the grader
 * agree with the engine only by coincidence; calling it means the flag is the same
 * arithmetic the engine would do, applied to the TRUE Sharpe instead of the
 * estimated one — which is the only difference that should exist.
 */
function resolveProvability(
  trueSharpe: number,
  periods: number,
  moments: PopulationMoments,
): { provable: boolean; minTrl: number | null; periodsRequired: number | null } {
  const result = minimumTrackRecordLength({
    sharpe: trueSharpe,
    skewness: moments.skewness,
    kurtosis: moments.kurtosis,
    benchmarkSharpe: 0,
    confidence: PROVABILITY_CONFIDENCE,
  });
  if (!result.ok) return { provable: false, minTrl: null, periodsRequired: null };
  return {
    provable: periods >= result.value.periodsRequired,
    minTrl: result.value.minimumTrackRecordLength,
    periodsRequired: result.value.periodsRequired,
  };
}

interface RegimeSchedulePoint {
  readonly active: boolean;
  readonly factorValue: number;
}

/**
 * Decide, per period, which bucket it falls in and what factor value puts it there.
 *
 * Values are emitted on the VIX scale so that the engine's PUBLISHED fixed edges
 * ([15, 20, 30]) do the bucketing — inactive periods land uniformly in [8, 20) and
 * therefore split across "calm" and "normal", active periods land uniformly in
 * [20, 45) and split across "elevated" and "stressed". Four populated buckets rather
 * than two makes the permutation test do real work: it has to find a spread that
 * survives relabelling across a realistic split, not a two-way one.
 *
 * The factor stream is seeded separately from the return stream so that changing the
 * planted Sharpes does not reshuffle which days are stressed.
 */
function buildRegimeSchedule(periods: number, seed: number): RegimeSchedulePoint[] {
  const rng = mulberry32(seed + REGIME_STREAM_OFFSET);
  const schedule: RegimeSchedulePoint[] = [];
  for (let i = 0; i < periods; i += 1) {
    const active = rng() < ACTIVE_BUCKET_PROBABILITY;
    const factorValue = active ? 20 + rng() * 25 : 8 + rng() * 12;
    schedule.push({ active, factorValue });
  }
  return schedule;
}

/**
 * Build the `RegimeSeries` aligned to the END timestamp of each return period.
 *
 * End-of-period, because that is the convention `toReturns` publishes and the regime
 * engine joins on. Aligning to the opening timestamp instead would shift every
 * attribution by one day and quietly destroy the planted effect.
 */
function buildRegimeSeries(
  factor: string,
  equity: readonly EquityPoint[],
  schedule: readonly RegimeSchedulePoint[],
): RegimeSeries {
  const observations: RegimeObservation[] = [];
  const stamp = [provenance('synthetic_regimes')];
  for (let i = 0; i < schedule.length; i += 1) {
    const point = equity[i + 1];
    const entry = schedule[i];
    if (point === undefined || entry === undefined) continue;
    observations.push({
      date: utcDate(point.t),
      factors: { [factor]: entry.factorValue },
      provenance: stamp,
    });
  }
  return { sourceId: SYNTHETIC_SOURCE_ID, observations, factorKeys: [factor] };
}

/**
 * Generate one labelled case: a track record, optionally a regime series, and the
 * ground truth the engine will be graded against.
 *
 * Everything is a pure function of `spec` (and `options`), so two calls with the
 * same arguments produce byte-identical output on any machine.
 */
export function generateCase(spec: CaseSpec, options: GenerateCaseOptions = {}): GeneratedCase {
  const matching = options.momentMatching ?? 'population';
  const periods = Math.max(0, Math.trunc(spec.periods));
  const moments = STANDARDISED_MOMENTS[spec.distribution];

  const rng = mulberry32(spec.seed);
  const nextNormal = createNormalStream(rng);
  const shape: number[] = [];
  for (let i = 0; i < periods; i += 1) shape.push(standardisedDraw(spec.distribution, rng, nextNormal));
  if (matching === 'sample') standardiseToSample(shape);

  const effect = spec.regimeEffect;
  const schedule = effect === undefined ? null : buildRegimeSchedule(periods, spec.seed);

  const returns: number[] = [];
  for (let i = 0; i < periods; i += 1) {
    const entry = schedule?.[i];
    const driftSharpe =
      effect === undefined || entry === undefined
        ? spec.trueSharpePerPeriod
        : entry.active
          ? effect.activeBucketSharpe
          : effect.inactiveBucketSharpe;
    const raw = spec.volatilityPerPeriod * (driftSharpe + (shape[i] as number));
    returns.push(raw > MINIMUM_PERIOD_RETURN ? raw : MINIMUM_PERIOD_RETURN);
  }

  const equity = buildEquityCurve(returns);
  const trueSharpe = populationSharpe(spec);
  const provability = resolveProvability(trueSharpe, periods, moments);

  const record: TrackRecord = {
    sourceId: SYNTHETIC_SOURCE_ID,
    label: spec.id,
    equity,
    trades: [],
    provenance: [provenance('synthetic_track_record')],
  };

  const truth: CaseTruth = {
    hasEdge: trueSharpe > 0,
    trueSharpePerPeriod: trueSharpe,
    periods,
    distribution: spec.distribution,
    populationSkewness: moments.skewness,
    populationKurtosis: moments.kurtosis,
    provableAtThisLength: provability.provable,
    minimumTrackRecordLength: provability.minTrl,
    periodsRequired: provability.periodsRequired,
    regimeFactor: effect?.factor ?? null,
    plantedRegimeEffect: effect !== undefined && effect.activeBucketSharpe !== effect.inactiveBucketSharpe,
    degenerate: null,
  };

  if (effect === undefined || schedule === null) return { spec, truth, record };
  return { spec, truth, record, regimes: buildRegimeSeries(effect.factor, equity, schedule) };
}

// --- Degenerate traps --------------------------------------------------------

/** How many raw equity points each degenerate trap supplies. Fixed so the suite is stable. */
const DEGENERATE_POINTS: Readonly<Record<DegenerateKind, number>> = {
  constant_equity: 60,
  too_few_points: 3,
  duplicate_timestamps: 24,
  unsorted_timestamps: 18,
};

/** Rows sharing each timestamp in the `duplicate_timestamps` trap. 24 rows collapse to 8. */
const DUPLICATE_RUN_LENGTH = 3;

/**
 * Build a case that is not a strategy at all, but a shape of input the engine has to
 * refuse.
 *
 * Every trap is constructed so the ONLY defensible answer is `insufficient_evidence`.
 * That is deliberate: "constant equity" has no variance so no Sharpe exists, and each
 * of the other three leaves fewer than the engine's 20 usable returns once the curve
 * has been cleaned. A grader that accepted "weak" here would be scoring an engine
 * that invents a verdict from nothing.
 */
export function generateDegenerateCase(id: string, kind: DegenerateKind, seed: number): GeneratedCase {
  const count = DEGENERATE_POINTS[kind];
  const rng = mulberry32(seed);
  const points: EquityPoint[] = [];

  if (kind === 'constant_equity') {
    for (let i = 0; i < count; i += 1) {
      points.push({ t: SYNTHETIC_EPOCH_MS + i * DAY_MS, equity: STARTING_EQUITY });
    }
  } else if (kind === 'too_few_points') {
    points.push({ t: SYNTHETIC_EPOCH_MS, equity: STARTING_EQUITY });
    points.push({ t: SYNTHETIC_EPOCH_MS + DAY_MS, equity: STARTING_EQUITY * 1.025 });
    points.push({ t: SYNTHETIC_EPOCH_MS + 2 * DAY_MS, equity: STARTING_EQUITY * 0.998 });
  } else if (kind === 'duplicate_timestamps') {
    let level = STARTING_EQUITY;
    for (let i = 0; i < count; i += 1) {
      level *= 1 + (rng() - 0.5) * 0.02;
      points.push({ t: SYNTHETIC_EPOCH_MS + Math.floor(i / DUPLICATE_RUN_LENGTH) * DAY_MS, equity: level });
    }
  } else {
    // Distinct daily timestamps, then a seeded Fisher-Yates so the ARRIVAL order is
    // non-monotonic while the underlying calendar is intact.
    const levels: number[] = [];
    let level = STARTING_EQUITY;
    for (let i = 0; i < count; i += 1) {
      level *= 1 + (rng() - 0.5) * 0.02;
      levels.push(level);
    }
    const order: number[] = [];
    for (let i = 0; i < count; i += 1) order.push(i);
    for (let i = order.length - 1; i > 0; i -= 1) {
      const j = Math.floor(rng() * (i + 1));
      const a = order[i] as number;
      const b = order[j] as number;
      order[i] = b;
      order[j] = a;
    }
    for (const index of order) {
      points.push({ t: SYNTHETIC_EPOCH_MS + index * DAY_MS, equity: levels[index] as number });
    }
  }

  const spec: CaseSpec = {
    id,
    periods: Math.max(0, count - 1),
    trueSharpePerPeriod: 0,
    volatilityPerPeriod: 0,
    distribution: 'normal',
    seed,
  };

  const truth: CaseTruth = {
    hasEdge: false,
    trueSharpePerPeriod: 0,
    periods: spec.periods,
    distribution: 'normal',
    populationSkewness: 0,
    populationKurtosis: 3,
    provableAtThisLength: false,
    minimumTrackRecordLength: null,
    periodsRequired: null,
    regimeFactor: null,
    plantedRegimeEffect: false,
    degenerate: kind,
  };

  const record: TrackRecord = {
    sourceId: SYNTHETIC_SOURCE_ID,
    label: id,
    equity: points,
    trades: [],
    provenance: [provenance(`synthetic_degenerate_${kind}`)],
  };

  return { spec, truth, record };
}
