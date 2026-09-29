/**
 * Regime attribution — the engine that answers "under which market conditions
 * does this edge actually hold?".
 *
 * The governing principle of this module: **thin evidence is reported, not
 * hidden.** A bucket with four observations is exactly the kind of finding the
 * product exists to expose — "your entire edge comes from four days in March" —
 * so buckets below `minSample` are returned in full and flagged
 * `sufficient: false`. Filtering them out would launder a lucky streak into a
 * clean-looking table.
 */

import { at, allFinite } from './internal';
import { mean as meanOf, stdDev } from './moments';
import { totalReturn as compoundReturns, type ReturnKind } from './returns';
import { sharpeRatio } from './sharpe';
import { wilsonInterval } from './trades';
import { fail, ok, type StatsReason, type StatsResult } from './result';

/** Default `minSample`: below ~20 observations a per-period Sharpe is noise. */
export const DEFAULT_MIN_SAMPLE = 20;

/** A confidence interval on a proportion. */
export interface ProportionInterval {
  readonly lower: number;
  readonly upper: number;
}

/** Everything known about one regime bucket. */
export interface BucketStats {
  readonly label: string;
  /** Number of returns attributed to this bucket. */
  readonly count: number;
  /** Mean period return, or `null` when undefined (empty bucket). */
  readonly mean: number | null;
  /** Sample standard deviation (ddof = 1), or `null` when `count < 2`. */
  readonly stdDev: number | null;
  /** **Per-period** Sharpe ratio within the bucket, or `null` when undefined. */
  readonly sharpe: number | null;
  /** Why `sharpe` is `null`, when it is. `null` when the Sharpe was computed. */
  readonly sharpeReason: StatsReason | null;
  /** Count of strictly positive returns. A zero return is not a win. */
  readonly wins: number;
  /** `wins / count`, or `null` for an empty bucket. */
  readonly winRate: number | null;
  /** Wilson score interval on the win rate, or `null` for an empty bucket. */
  readonly winRateInterval: ProportionInterval | null;
  /**
   * Compounded return of trading **only** this bucket: `Π(1 + rᵢ) − 1` for
   * simple returns, `exp(Σrᵢ) − 1` for log returns. The bucket's periods are
   * not contiguous in time, so this is a counterfactual ("what if I had only
   * traded this regime"), not a realised path.
   */
  readonly totalReturn: number | null;
  /**
   * Plain sum of the bucket's returns.
   *
   * This is the *additive* contribution used for attribution shares in
   * {@link compareBuckets}: compounded returns do not decompose across buckets,
   * sums do.
   */
  readonly sumReturns: number;
  /** `count >= minSample`. */
  readonly sufficient: boolean;
}

/** Arguments to {@link conditionalStats}. */
export interface ConditionalStatsArgs {
  readonly returns: readonly number[];
  /**
   * `labels[i]` is the regime bucket for `returns[i]`.
   *
   * `null` means "this observation could not be classified" (typically a
   * non-finite regime value from {@link bucketize}); such observations are
   * excluded from every bucket and counted in `unlabelled`.
   */
  readonly labels: readonly (string | null)[];
  /** Minimum observations for a bucket to be marked `sufficient`. Defaults to {@link DEFAULT_MIN_SAMPLE}. */
  readonly minSample?: number;
  /** How `totalReturn` compounds. Defaults to `'simple'`. */
  readonly returnKind?: ReturnKind;
  /** Per-period risk-free rate used for every bucket's Sharpe. Defaults to 0. */
  readonly riskFreePerPeriod?: number;
  /** Coverage for the win-rate Wilson interval. Defaults to 0.95. */
  readonly confidence?: number;
}

/** Result payload of {@link conditionalStats}. */
export interface ConditionalStatsValue {
  /** One entry per distinct label, sorted by label ascending for deterministic rendering. */
  readonly buckets: BucketStats[];
  readonly minSample: number;
  /** Observations that carried a label. */
  readonly labelled: number;
  /** Observations whose label was `null` and were therefore excluded. */
  readonly unlabelled: number;
  /** Whole-series figures, computed over the labelled observations only. */
  readonly overall: {
    readonly count: number;
    readonly mean: number | null;
    readonly sumReturns: number;
    readonly totalReturn: number | null;
  };
}

/**
 * Per-bucket statistics for a labelled return series.
 *
 * Buckets are keyed by label string; two observations sharing a label share a
 * bucket, which is how {@link bucketize} can deliberately merge both tails into
 * one "extreme" regime.
 *
 * @returns `length_mismatch` when `returns` and `labels` disagree in length,
 *   `empty_input` for an empty series, `non_finite_input` for a bad return,
 *   `invalid_parameter` for a non-integer or negative `minSample`.
 */
export function conditionalStats(args: ConditionalStatsArgs): StatsResult<ConditionalStatsValue> {
  const { returns, labels } = args;
  const minSample = args.minSample ?? DEFAULT_MIN_SAMPLE;
  const returnKind = args.returnKind ?? 'simple';
  const riskFreePerPeriod = args.riskFreePerPeriod ?? 0;
  const confidence = args.confidence ?? 0.95;

  if (returns.length !== labels.length) {
    return fail('length_mismatch', 'returns and labels must have the same length.');
  }
  if (returns.length === 0) return fail('empty_input', 'No returns supplied.');
  if (!allFinite(returns)) {
    return fail('non_finite_input', 'Return series contains a non-finite value.');
  }
  if (!Number.isInteger(minSample) || minSample < 0) {
    return fail('invalid_parameter', 'minSample must be a non-negative integer.');
  }
  if (!(confidence > 0 && confidence < 1)) {
    return fail('invalid_parameter', 'confidence must lie strictly between 0 and 1.');
  }
  if (!Number.isFinite(riskFreePerPeriod)) {
    return fail('invalid_parameter', 'riskFreePerPeriod must be a finite number.');
  }

  const grouped = new Map<string, number[]>();
  const labelledReturns: number[] = [];
  let unlabelled = 0;

  for (let i = 0; i < returns.length; i += 1) {
    const label = labels[i];
    if (label === null || label === undefined) {
      unlabelled += 1;
      continue;
    }
    const value = at(returns, i);
    labelledReturns.push(value);
    const bucket = grouped.get(label);
    if (bucket === undefined) grouped.set(label, [value]);
    else bucket.push(value);
  }

  const buckets: BucketStats[] = [];
  // Sorted by label so the output order never depends on input order or on
  // Map insertion order, which keeps snapshot tests and UI diffs stable.
  for (const label of [...grouped.keys()].sort()) {
    const values = grouped.get(label) ?? [];
    buckets.push(summariseBucket(label, values, minSample, returnKind, riskFreePerPeriod, confidence));
  }

  let sumReturns = 0;
  for (const r of labelledReturns) sumReturns += r;

  return ok({
    buckets,
    minSample,
    labelled: labelledReturns.length,
    unlabelled,
    overall: {
      count: labelledReturns.length,
      mean: meanOf(labelledReturns),
      sumReturns,
      totalReturn: compoundReturns(labelledReturns, returnKind),
    },
  });
}

function summariseBucket(
  label: string,
  values: readonly number[],
  minSample: number,
  returnKind: ReturnKind,
  riskFreePerPeriod: number,
  confidence: number,
): BucketStats {
  const count = values.length;
  let wins = 0;
  let sumReturns = 0;
  for (const value of values) {
    if (value > 0) wins += 1;
    sumReturns += value;
  }

  const sharpe = sharpeRatio(values, { riskFreePerPeriod });
  const wilson = count > 0 ? wilsonInterval(wins, count, confidence) : null;

  return {
    label,
    count,
    mean: meanOf(values),
    stdDev: stdDev(values, { ddof: 1 }),
    sharpe: sharpe.ok ? sharpe.value.sharpe : null,
    sharpeReason: sharpe.ok ? null : sharpe.reason,
    wins,
    winRate: count > 0 ? wins / count : null,
    winRateInterval:
      wilson !== null && wilson.ok ? { lower: wilson.value.lower, upper: wilson.value.upper } : null,
    totalReturn: compoundReturns(values, returnKind),
    sumReturns,
    sufficient: count >= minSample,
  };
}

/** Result payload of {@link bucketize}. */
export interface BucketizeValue {
  /** `labels[i]` is the bucket for `values[i]`, or `null` when `values[i]` was non-finite. */
  readonly labels: (string | null)[];
  /** Count of values that landed in a bucket. */
  readonly assigned: number;
  /** Count of values that could not be classified. */
  readonly unassigned: number;
  /** Observed count per label, for a quick histogram. */
  readonly counts: Record<string, number>;
}

/**
 * Map numeric regime values (realised volatility, trend strength, VIX level, …)
 * into named buckets.
 *
 * **Edge convention: buckets are left-closed and right-open, `[lo, hi)`**, with
 * open outer edges:
 *
 * ```text
 *   labels[0]              v <  edges[0]
 *   labels[i]   edges[i-1] ≤ v <  edges[i]
 *   labels[k]   edges[k-1] ≤ v            (k = edges.length)
 * ```
 *
 * So `edges = [0.01, 0.02]` with `labels = ['low', 'mid', 'high']` puts exactly
 * 0.01 in `'mid'` and exactly 0.02 in `'high'`. Half-open intervals are chosen
 * so that a value can never fall into two buckets and the buckets tile the real
 * line with no gaps.
 *
 * Duplicate labels are permitted and merge their buckets — which is how you map
 * both tails of a distribution to a single `'extreme'` regime.
 *
 * @param values - Regime observations, aligned with a return series.
 * @param edges - Strictly ascending, finite boundaries.
 * @param labels - Bucket names, exactly `edges.length + 1` of them.
 * @returns `invalid_parameter` when the edges are not strictly ascending/finite
 *   or the label count is wrong. Non-finite *values* are not an error: they map
 *   to `null` and are counted in `unassigned`, because one missing VIX print
 *   should not void the whole analysis.
 */
export function bucketize(
  values: readonly number[],
  edges: readonly number[],
  labels: readonly string[],
): StatsResult<BucketizeValue> {
  if (labels.length !== edges.length + 1) {
    return fail(
      'invalid_parameter',
      'labels must contain exactly edges.length + 1 entries (one bucket per interval, including both outer ones).',
    );
  }
  if (labels.length === 0) {
    return fail('invalid_parameter', 'At least one label is required.');
  }
  if (!allFinite(edges)) {
    return fail('invalid_parameter', 'edges must all be finite numbers.');
  }
  for (let i = 1; i < edges.length; i += 1) {
    if (!(at(edges, i) > at(edges, i - 1))) {
      return fail('invalid_parameter', 'edges must be strictly ascending.');
    }
  }
  for (const label of labels) {
    if (label.length === 0) return fail('invalid_parameter', 'labels must be non-empty strings.');
  }

  const out: (string | null)[] = [];
  const counts: Record<string, number> = {};
  for (const label of labels) counts[label] = 0;

  let assigned = 0;
  let unassigned = 0;

  for (let i = 0; i < values.length; i += 1) {
    const value = at(values, i);
    if (!Number.isFinite(value)) {
      out.push(null);
      unassigned += 1;
      continue;
    }
    let bucket = edges.length; // default: the open top bucket
    for (let e = 0; e < edges.length; e += 1) {
      if (value < at(edges, e)) {
        bucket = e;
        break;
      }
    }
    const label = labels[bucket];
    if (label === undefined) {
      out.push(null);
      unassigned += 1;
      continue;
    }
    out.push(label);
    counts[label] = (counts[label] ?? 0) + 1;
    assigned += 1;
  }

  return ok({ labels: out, assigned, unassigned, counts });
}

/** Options for {@link compareBuckets}. */
export interface CompareBucketsOptions {
  /**
   * Share of the additive total return above which a single bucket triggers
   * `concentrationWarning`. Defaults to 0.6 — "most of the return came from one
   * regime" is the intended reading, and 60% of the total from one of several
   * buckets is the point at which the headline number stops describing the
   * strategy and starts describing that regime.
   */
  readonly concentrationThreshold?: number;
}

/** A bucket's additive contribution to the series total. */
export interface BucketContribution {
  readonly label: string;
  readonly sumReturns: number;
  /** `sumReturns / (total sum of returns)`. Only defined when the total is positive. */
  readonly share: number | null;
}

/** Result payload of {@link compareBuckets}. */
export interface CompareBucketsValue {
  /** Best sufficient bucket by per-period Sharpe, or `null` when none is rankable. */
  readonly best: BucketStats | null;
  /** Worst sufficient bucket by per-period Sharpe, or `null` when none is rankable. */
  readonly worst: BucketStats | null;
  /** `best.sharpe − worst.sharpe`, or `null` when fewer than 2 buckets are rankable. */
  readonly sharpeSpread: number | null;
  /** `best.mean − worst.mean` for the same two buckets, or `null`. */
  readonly meanSpread: number | null;
  readonly sufficientCount: number;
  readonly insufficientCount: number;
  /** Buckets excluded from ranking because they are insufficient or have no defined Sharpe. */
  readonly rankableCount: number;
  /** Additive contributions, sorted by `sumReturns` descending. */
  readonly contributions: BucketContribution[];
  /** The single largest contributor, or `null` when shares are undefined. */
  readonly topContributor: BucketContribution | null;
  /** `true` when one bucket's share meets or exceeds `concentrationThreshold`. */
  readonly concentrationWarning: boolean;
  readonly concentrationThreshold: number;
  /** Additive total across all buckets. */
  readonly totalSumReturns: number;
}

/**
 * Compare regime buckets: the spread between the best and worst *sufficient*
 * bucket, and a warning when one regime dominates the whole track record.
 *
 * Ranking is by **per-period Sharpe** and considers only buckets that are both
 * `sufficient` and have a defined Sharpe. Insufficient buckets are still
 * counted and still appear in `contributions` — they are excluded from
 * *ranking*, not from the report, because "best regime" is a claim and a
 * six-observation bucket cannot support one.
 *
 * Attribution shares use the additive sum of returns rather than the compounded
 * total, because compounded returns do not decompose across a partition of the
 * periods. Shares are only defined when the additive total is positive; on a
 * losing track record the ratio flips sign and means nothing, so `share` is
 * `null` and no concentration warning is raised.
 *
 * @param stats - The `buckets` array from {@link conditionalStats}.
 * @returns `empty_input` when no buckets are supplied.
 */
export function compareBuckets(
  stats: readonly BucketStats[],
  options: CompareBucketsOptions = {},
): StatsResult<CompareBucketsValue> {
  const concentrationThreshold = options.concentrationThreshold ?? 0.6;
  if (stats.length === 0) return fail('empty_input', 'No buckets supplied.');
  if (!(concentrationThreshold > 0 && concentrationThreshold <= 1)) {
    return fail('invalid_parameter', 'concentrationThreshold must lie in (0, 1].');
  }

  let sufficientCount = 0;
  let insufficientCount = 0;
  let totalSumReturns = 0;
  const rankable: BucketStats[] = [];

  for (const bucket of stats) {
    if (bucket.sufficient) sufficientCount += 1;
    else insufficientCount += 1;
    totalSumReturns += bucket.sumReturns;
    if (bucket.sufficient && bucket.sharpe !== null) rankable.push(bucket);
  }

  let best: BucketStats | null = null;
  let worst: BucketStats | null = null;
  for (const bucket of rankable) {
    const sharpe = bucket.sharpe ?? 0;
    if (best === null || sharpe > (best.sharpe ?? 0)) best = bucket;
    if (worst === null || sharpe < (worst.sharpe ?? 0)) worst = bucket;
  }

  const rankableEnough = rankable.length >= 2 && best !== null && worst !== null;
  const sharpeSpread =
    rankableEnough && best?.sharpe != null && worst?.sharpe != null
      ? best.sharpe - worst.sharpe
      : null;
  const meanSpread =
    rankableEnough && best?.mean != null && worst?.mean != null ? best.mean - worst.mean : null;

  const sharesDefined = totalSumReturns > 0;
  const contributions: BucketContribution[] = stats
    .map((bucket) => ({
      label: bucket.label,
      sumReturns: bucket.sumReturns,
      share: sharesDefined ? bucket.sumReturns / totalSumReturns : null,
    }))
    .sort((a, b) => b.sumReturns - a.sumReturns);

  const topContributor = sharesDefined ? (contributions[0] ?? null) : null;
  const concentrationWarning =
    stats.length > 1 &&
    topContributor !== null &&
    topContributor.share !== null &&
    topContributor.share >= concentrationThreshold;

  return ok({
    // With a single rankable bucket `best` is that bucket but `worst` is not
    // meaningful, so it is withheld along with the spreads.
    best,
    worst: rankableEnough ? worst : null,
    sharpeSpread,
    meanSpread,
    sufficientCount,
    insufficientCount,
    rankableCount: rankable.length,
    contributions,
    topContributor,
    concentrationWarning,
    concentrationThreshold,
    totalSumReturns,
  });
}
