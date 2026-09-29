import { bucketize, conditionalStats, mulberry32, toReturns } from '@/lib/stats';
import type { BucketStats } from '@/lib/stats';
import type { RegimeSeries, TrackRecord } from '@/lib/sources/types';

/**
 * Regime attribution: where does this strategy actually make its money?
 *
 * An aggregate Sharpe ratio hides the shape of a strategy. A record that looks
 * decent overall is often one regime of excellent returns surrounded by noise, which
 * matters enormously — it means the edge is a bet on conditions, and the conditions
 * can end. This module joins each period's return to the market conditions that held
 * on that UTC date and reports performance per condition bucket.
 *
 * Two things keep the result honest:
 *
 *  1. **Point-in-time joins only.** Each factor is read with an explicit `as_of`, so
 *     nothing in a bucket could have been known only after the fact.
 *  2. **A permutation test.** Slice a return series eight ways and the best-looking
 *     bucket will look good by chance alone, so the observed between-bucket dispersion
 *     is compared against the dispersion obtained by randomly reshuffling the regime
 *     labels many times. Without that p-value a regime map is just a machine for
 *     finding flattering subsets.
 */

export type BucketingMethod = 'fixed_edges' | 'terciles';

export interface FactorBucketing {
  readonly method: BucketingMethod;
  readonly edges?: readonly number[];
  readonly labels?: readonly string[];
  readonly note: string;
}

/**
 * Published bucket definitions.
 *
 * Factors with a natural, widely-understood scale get FIXED edges chosen from
 * convention rather than from this dataset — picking edges that flatter the data is
 * the oldest way to manufacture a regime effect. Factors with no natural scale are
 * split into terciles of their own observed distribution, which is disclosed per
 * factor because it does depend on the sample.
 */
export const FACTOR_BUCKETING: Record<string, FactorBucketing> = {
  vix: {
    method: 'fixed_edges',
    edges: [15, 20, 30],
    labels: ['calm (<15)', 'normal (15-20)', 'elevated (20-30)', 'stressed (>30)'],
    note: 'Conventional VIX regime boundaries, fixed in advance and independent of this strategy.',
  },
  fundingRate: {
    method: 'fixed_edges',
    edges: [-0.0001, 0.0001],
    labels: ['negative (<-1bp)', 'neutral (+/-1bp)', 'positive (>1bp)'],
    note: 'Symmetric around flat funding at one basis point per interval.',
  },
  longShortRatio: {
    method: 'fixed_edges',
    edges: [1, 2],
    labels: ['short-skewed (<1)', 'balanced (1-2)', 'long-skewed (>2)'],
    note: 'Parity at 1.0; 2.0 marks a heavily one-sided book.',
  },
  fearGreed: {
    method: 'fixed_edges',
    edges: [25, 45, 55, 75],
    labels: ['extreme fear', 'fear', 'neutral', 'greed', 'extreme greed'],
    note: 'The index publisher’s own bands.',
  },
  trendTemplatePassed: {
    method: 'fixed_edges',
    edges: [3, 6],
    labels: ['few gates (<3)', 'some gates (3-6)', 'most gates (>6)'],
    note: 'Count of Minervini trend-template conditions met that day.',
  },
  us10y: { method: 'terciles', note: 'No conventional regime boundaries; split into terciles of the observed range.' },
  fedFunds: {
    method: 'terciles',
    note: 'No conventional regime boundaries; split into terciles of the observed range.',
  },
  openInterestUsd: {
    method: 'terciles',
    note: 'Notional scale is venue-specific; split into terciles of the observed range.',
  },
};

export interface PermutationResult {
  readonly pValue: number;
  readonly resamples: number;
  readonly seed: number;
  /** The statistic the p-value is computed from. */
  readonly statistic: 'weighted_between_bucket_variance';
  readonly observedStatistic: number;
  /** Best-minus-worst Sharpe, reported because it reads well — not what is tested. */
  readonly observedSpread: number | null;
  readonly interpretation: string;
}

export interface FactorReport {
  readonly key: string;
  readonly bucketingMethod: BucketingMethod;
  readonly bucketingNote: string;
  readonly edges: readonly number[] | null;
  readonly observationsMatched: number;
  readonly observationsMissing: number;
  readonly buckets: readonly BucketStats[];
  readonly sufficientBuckets: number;
  readonly best: { readonly label: string; readonly sharpe: number } | null;
  readonly worst: { readonly label: string; readonly sharpe: number } | null;
  readonly spread: number | null;
  readonly dispersion: number | null;
  readonly permutation: PermutationResult | null;
  readonly warnings: readonly string[];
}

export interface RegimeMapReport {
  readonly label: string;
  readonly alignment: {
    readonly usableReturns: number;
    readonly datesCovered: number;
    readonly returnsWithoutRegime: number;
  };
  readonly minSample: number;
  readonly factors: readonly FactorReport[];
  readonly warnings: readonly string[];
}

export interface RegimeMapOptions {
  /** Below this many observations a bucket is reported but flagged unusable. */
  readonly minSample?: number;
  readonly permutationResamples?: number;
  readonly seed?: number;
  readonly factorKeys?: readonly string[];
}

const DEFAULT_MIN_SAMPLE = 15;
const DEFAULT_PERMUTATIONS = 2_000;
const DEFAULT_SEED = 0xc0ffee;

function utcDate(epochMs: number): string {
  return new Date(epochMs).toISOString().slice(0, 10);
}

/** Tercile edges from the observed values. Returns null when they are degenerate. */
function tercileEdges(values: readonly number[]): [number, number] | null {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length < 6) return null;
  const lower = sorted[Math.floor(sorted.length / 3)];
  const upper = sorted[Math.floor((2 * sorted.length) / 3)];
  if (lower === undefined || upper === undefined || lower === upper) return null;
  return [lower, upper];
}

/** Fisher-Yates using a seeded PRNG, so a reported p-value is reproducible. */
function shuffled<T>(items: readonly T[], rng: () => number): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    const a = copy[i] as T;
    const b = copy[j] as T;
    copy[i] = b;
    copy[j] = a;
  }
  return copy;
}

function spreadOf(buckets: readonly BucketStats[]): number | null {
  const sharpes = buckets.filter((bucket) => bucket.sufficient && bucket.sharpe !== null).map((b) => b.sharpe as number);
  if (sharpes.length < 2) return null;
  return Math.max(...sharpes) - Math.min(...sharpes);
}

/**
 * Between-bucket dispersion: the observation-weighted variance of the bucket Sharpe
 * ratios around their weighted mean.
 *
 * This, and not the best-minus-worst spread, is what the permutation test runs on.
 * A range statistic only ever sees two buckets, ignores how many observations stand
 * behind them, and grows with the number of buckets purely by chance — measured
 * against a planted regime effect it could not separate signal from the null at all.
 * A weighted variance uses every bucket, discounts the thin ones, and is the standard
 * between-group dispersion measure. The spread is still reported, because it is what a
 * reader intuitively wants to see; it just is not what the p-value is computed from.
 */
function dispersionOf(buckets: readonly BucketStats[]): number | null {
  const usable = buckets.filter((bucket) => bucket.sufficient && bucket.sharpe !== null);
  if (usable.length < 2) return null;

  const totalCount = usable.reduce((total, bucket) => total + bucket.count, 0);
  if (totalCount === 0) return null;

  const weightedMean =
    usable.reduce((total, bucket) => total + bucket.count * (bucket.sharpe as number), 0) / totalCount;

  return (
    usable.reduce((total, bucket) => {
      const deviation = (bucket.sharpe as number) - weightedMean;
      return total + bucket.count * deviation * deviation;
    }, 0) / totalCount
  );
}

export function buildRegimeMap(
  record: TrackRecord,
  regimes: RegimeSeries,
  options: RegimeMapOptions = {},
): RegimeMapReport {
  const minSample = options.minSample ?? DEFAULT_MIN_SAMPLE;
  const permutationResamples = options.permutationResamples ?? DEFAULT_PERMUTATIONS;
  const seed = options.seed ?? DEFAULT_SEED;
  const warnings: string[] = [];

  const series = toReturns(record.equity, { kind: 'simple' });
  const byDate = new Map(regimes.observations.map((observation) => [observation.date, observation]));

  // Each return is attributed to the UTC date its period CLOSED on, which is the last
  // day whose conditions could have influenced it.
  const dates = series.timestamps.map(utcDate);
  const matchedDates = dates.filter((date) => byDate.has(date));

  if (matchedDates.length === 0) {
    warnings.push(
      'No equity date matched a regime observation. The strategy period may fall outside the data source’s coverage window.',
    );
  }

  const keys = options.factorKeys ?? regimes.factorKeys;
  const factors: FactorReport[] = [];

  for (const key of keys) {
    const bucketing = FACTOR_BUCKETING[key] ?? {
      method: 'terciles' as const,
      note: 'No published bucketing for this factor; split into terciles of the observed range.',
    };

    const values: number[] = [];
    const indices: number[] = [];
    let missing = 0;

    dates.forEach((date, index) => {
      const observation = byDate.get(date);
      const raw = observation?.factors[key];
      if (typeof raw === 'number' && Number.isFinite(raw)) {
        values.push(raw);
        indices.push(index);
      } else {
        missing += 1;
      }
    });

    const factorWarnings: string[] = [];

    if (values.length < minSample) {
      factors.push({
        key,
        bucketingMethod: bucketing.method,
        bucketingNote: bucketing.note,
        edges: bucketing.edges ? [...bucketing.edges] : null,
        observationsMatched: values.length,
        observationsMissing: missing,
        buckets: [],
        sufficientBuckets: 0,
        best: null,
        worst: null,
        spread: null,
        dispersion: null,
        permutation: null,
        warnings: [
          `Only ${values.length} period(s) carried a value for this factor, below the minimum of ${minSample}. No attribution is reported.`,
        ],
      });
      continue;
    }

    let edges: readonly number[] | null = bucketing.edges ?? null;
    let labels: readonly string[] | null = bucketing.labels ?? null;

    if (bucketing.method === 'terciles' || edges === null) {
      const derived = tercileEdges(values);
      if (derived === null) {
        factors.push({
          key,
          bucketingMethod: 'terciles',
          bucketingNote: bucketing.note,
          edges: null,
          observationsMatched: values.length,
          observationsMissing: missing,
          buckets: [],
          sufficientBuckets: 0,
          best: null,
          worst: null,
          spread: null,
          dispersion: null,
          permutation: null,
          warnings: ['This factor barely varied over the period, so splitting it would not describe anything.'],
        });
        continue;
      }
      edges = derived;
      labels = [`low (<${derived[0].toPrecision(4)})`, 'mid', `high (>${derived[1].toPrecision(4)})`];
    }

    const bucketed = bucketize(values, edges, labels as readonly string[]);
    if (!bucketed.ok) {
      factors.push({
        key,
        bucketingMethod: bucketing.method,
        bucketingNote: bucketing.note,
        edges: [...edges],
        observationsMatched: values.length,
        observationsMissing: missing,
        buckets: [],
        sufficientBuckets: 0,
        best: null,
        worst: null,
        spread: null,
        dispersion: null,
        permutation: null,
        warnings: [bucketed.message],
      });
      continue;
    }

    const alignedReturns = indices.map((index) => series.returns[index] as number);
    const stats = conditionalStats({
      returns: alignedReturns,
      labels: bucketed.value.labels,
      minSample,
    });

    if (!stats.ok) {
      factors.push({
        key,
        bucketingMethod: bucketing.method,
        bucketingNote: bucketing.note,
        edges: [...edges],
        observationsMatched: values.length,
        observationsMissing: missing,
        buckets: [],
        sufficientBuckets: 0,
        best: null,
        worst: null,
        spread: null,
        dispersion: null,
        permutation: null,
        warnings: [stats.message],
      });
      continue;
    }

    const buckets = stats.value.buckets;
    const sufficient = buckets.filter((bucket) => bucket.sufficient && bucket.sharpe !== null);
    const observedSpread = spreadOf(buckets);
    const observedDispersion = dispersionOf(buckets);

    if (sufficient.length < buckets.length) {
      factorWarnings.push(
        `${buckets.length - sufficient.length} of ${buckets.length} buckets hold fewer than ${minSample} periods and are shown but not used for the spread.`,
      );
    }

    let best: FactorReport['best'] = null;
    let worst: FactorReport['worst'] = null;
    if (sufficient.length >= 1) {
      const sorted = [...sufficient].sort((a, b) => (b.sharpe as number) - (a.sharpe as number));
      const top = sorted[0] as BucketStats;
      const bottom = sorted[sorted.length - 1] as BucketStats;
      best = { label: top.label, sharpe: top.sharpe as number };
      worst = { label: bottom.label, sharpe: bottom.sharpe as number };
    }

    let permutation: PermutationResult | null = null;
    if (observedDispersion !== null && sufficient.length >= 2) {
      const factorSeed = seed + hashKey(key);
      const rng = mulberry32(factorSeed);
      let atLeastAsExtreme = 0;
      for (let i = 0; i < permutationResamples; i += 1) {
        const permutedLabels = shuffled(bucketed.value.labels, rng);
        const nullStats = conditionalStats({ returns: alignedReturns, labels: permutedLabels, minSample });
        if (!nullStats.ok) continue;
        const nullDispersion = dispersionOf(nullStats.value.buckets);
        if (nullDispersion !== null && nullDispersion >= observedDispersion) atLeastAsExtreme += 1;
      }
      // Add-one smoothing: a finite permutation set cannot establish a p-value of zero.
      const pValue = (atLeastAsExtreme + 1) / (permutationResamples + 1);
      permutation = {
        pValue,
        resamples: permutationResamples,
        seed: factorSeed,
        statistic: 'weighted_between_bucket_variance',
        observedStatistic: observedDispersion,
        observedSpread,
        interpretation:
          pValue <= 0.05
            ? 'Performance differs across these buckets by more than random relabelling produces, so the split describes something real about the strategy.'
            : 'Randomly reshuffling the regime labels produces differences this large often enough that this split is not evidence of a regime effect.',
      };
    }

    factors.push({
      key,
      bucketingMethod: bucketing.method,
      bucketingNote: bucketing.note,
      edges: [...edges],
      observationsMatched: values.length,
      observationsMissing: missing,
      buckets,
      sufficientBuckets: sufficient.length,
      best,
      worst,
      spread: observedSpread,
      dispersion: observedDispersion,
      permutation,
      warnings: factorWarnings,
    });
  }

  if (factors.every((factor) => factor.permutation === null)) {
    warnings.push(
      'No factor produced two sufficiently populated buckets, so no regime effect could be tested at this sample size.',
    );
  }

  return {
    label: record.label,
    alignment: {
      usableReturns: series.returns.length,
      datesCovered: matchedDates.length,
      returnsWithoutRegime: series.returns.length - matchedDates.length,
    },
    minSample,
    factors,
    warnings,
  };
}

/** Stable per-factor offset so each factor's permutation draw is independent but reproducible. */
function hashKey(key: string): number {
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (Math.imul(hash, 31) + key.charCodeAt(i)) | 0;
  return Math.abs(hash) % 100_000;
}
