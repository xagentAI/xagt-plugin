/**
 * Stationary bootstrap and percentile confidence intervals.
 *
 * The IID bootstrap is wrong for financial return series: volatility clusters,
 * so resampling observations independently destroys exactly the dependence
 * structure that makes a track record's uncertainty larger than the textbook
 * formula suggests. The stationary bootstrap resamples *blocks* of random
 * geometric length instead, preserving short-range dependence while remaining
 * stationary (unlike a fixed block length).
 *
 * Determinism is a hard requirement: every draw comes from the seeded
 * `mulberry32` stream, so a given `(series, options, seed)` triple always
 * produces bit-for-bit identical output. There is no `Math.random` anywhere in
 * this package.
 *
 * Source: Politis, D. & Romano, J. (1994), "The Stationary Bootstrap", Journal
 * of the American Statistical Association 89(428), pp. 1303–1313.
 */

import { at, quantileType7, sortedAscending } from './internal';
import { mulberry32 } from './numeric';
import { fail, ok, type StatsResult } from './result';

/** Options for {@link stationaryBootstrap}. */
export interface StationaryBootstrapOptions {
  /**
   * Mean geometric block length, `1/p`. Must be ≥ 1 and finite.
   *
   * `1` degenerates to the IID bootstrap (every step starts a new block);
   * larger values preserve longer dependence at the cost of variability.
   */
  readonly blockMeanLength: number;
  /** Number of resampled series to generate. Must be a positive integer. */
  readonly resamples: number;
  /** Seed for `mulberry32`. Any finite number; identical seeds give identical output. */
  readonly seed: number;
}

/** Resampled index arrays plus the settings that produced them. */
export interface StationaryBootstrapValue {
  /**
   * `indices[r][t]` is the position in the original series that resample `r`
   * takes for its `t`-th observation. Index arrays rather than values, because
   * the same resample often has to be applied to several parallel series
   * (returns and their regime labels, say) and they must line up.
   */
  readonly indices: number[][];
  readonly n: number;
  readonly blockMeanLength: number;
  readonly resamples: number;
  readonly seed: number;
  /** `p = 1 / blockMeanLength`, the per-step probability of starting a new block. */
  readonly restartProbability: number;
}

/**
 * Generate stationary-bootstrap index arrays.
 *
 * Algorithm, per resample, with `p = 1/blockMeanLength`:
 *  - `t = 0`: draw a uniform starting index in `[0, n)`;
 *  - `t > 0`: with probability `p` draw a fresh uniform starting index,
 *    otherwise continue the current block with `(previous + 1) mod n`.
 *
 * The modulo is the circular wrap-around of Politis & Romano: the series is
 * treated as a circle so that blocks starting near the end do not have to be
 * truncated, which is what keeps the resampled series stationary.
 *
 * Block lengths are therefore geometric with mean `1/p`, drawn implicitly by
 * the per-step Bernoulli rather than by sampling a length up front — the two
 * are equivalent and the per-step form keeps the RNG call pattern simple, which
 * matters because that pattern is part of the reproducibility contract.
 */
export function stationaryBootstrap(
  series: readonly number[],
  options: StationaryBootstrapOptions,
): StatsResult<StationaryBootstrapValue> {
  const { blockMeanLength, resamples, seed } = options;
  const n = series.length;
  if (n === 0) return fail('empty_input', 'Cannot bootstrap an empty series.');
  if (n < 2) return fail('insufficient_sample', 'The stationary bootstrap requires at least 2 observations.');
  if (!Number.isFinite(blockMeanLength) || blockMeanLength < 1) {
    return fail('invalid_parameter', 'blockMeanLength must be a finite number greater than or equal to 1.');
  }
  if (!Number.isInteger(resamples) || resamples < 1) {
    return fail('invalid_parameter', 'resamples must be a positive integer.');
  }
  if (!Number.isFinite(seed)) {
    return fail('invalid_parameter', 'seed must be a finite number.');
  }

  const restartProbability = 1 / blockMeanLength;
  const rng = mulberry32(seed);
  const indices: number[][] = [];

  for (let r = 0; r < resamples; r += 1) {
    const row: number[] = new Array<number>(n);
    let current = Math.floor(rng() * n) % n;
    row[0] = current;
    for (let t = 1; t < n; t += 1) {
      if (rng() < restartProbability) {
        current = Math.floor(rng() * n) % n;
      } else {
        current = (current + 1) % n;
      }
      row[t] = current;
    }
    indices.push(row);
  }

  return ok({ indices, n, blockMeanLength, resamples, seed, restartProbability });
}

/**
 * Heuristic block length: `n^(1/3)`, rounded and clamped to `[1, n]`.
 *
 * **This is a heuristic, not an estimator.** The principled choice is the
 * Politis & White (2004) plug-in rule (corrected by Patton, Politis & White
 * 2009), which estimates the optimal block length from the autocovariance
 * structure of the series. That needs a spectral density estimate and a
 * flat-top lag window; it is deliberately not implemented here, because a
 * badly-tuned plug-in is worse than an honest rule of thumb. The `n^(1/3)` rate
 * is the correct asymptotic order for the stationary bootstrap under standard
 * mixing conditions, so this gets the scaling right and the constant wrong.
 *
 * @returns `null` for an empty series.
 */
export function optimalBlockLength(series: readonly number[]): number | null {
  const n = series.length;
  if (n === 0) return null;
  const heuristic = Math.round(Math.cbrt(n));
  return Math.min(Math.max(heuristic, 1), n);
}

/** A statistic over a resampled series. Return `null` when it is undefined for that sample. */
export type BootstrapStatistic = (sample: number[]) => number | null;

/** Options for {@link bootstrapCI}. */
export interface BootstrapCIOptions {
  /** Seed for `mulberry32`. Required — an unseeded confidence interval is not reproducible. */
  readonly seed: number;
  /** Number of resamples. Defaults to 1000. */
  readonly resamples?: number;
  /** Two-sided coverage level in (0, 1). Defaults to 0.95. */
  readonly level?: number;
  /** Mean block length. Defaults to {@link optimalBlockLength} of the series. */
  readonly blockMeanLength?: number;
}

/** A percentile bootstrap confidence interval and its full provenance. */
export interface BootstrapCIValue {
  /** The statistic evaluated on the original series. */
  readonly pointEstimate: number;
  /** Lower bound at `(1 − level)/2`. */
  readonly lower: number;
  /** Upper bound at `1 − (1 − level)/2`. */
  readonly upper: number;
  readonly level: number;
  readonly resamples: number;
  readonly seed: number;
  /**
   * Always `'percentile'`.
   *
   * The percentile interval is used rather than BCa because BCa's acceleration
   * term needs a jackknife over the *blocks*, and a half-implemented BCa would
   * be silently miscalibrated. Percentile intervals are known to under-cover
   * for skewed statistics; that limitation is stated here rather than hidden.
   */
  readonly method: 'percentile';
  readonly blockMeanLength: number;
  /** Replicates that produced a usable value (the rest were `null`/non-finite). */
  readonly usableResamples: number;
}

/**
 * Percentile confidence interval for an arbitrary statistic, via the stationary
 * bootstrap.
 *
 * Reproducibility contract: two calls with the same `series`, `statistic`,
 * `seed`, `resamples`, `level` and `blockMeanLength` return bit-for-bit
 * identical numbers, on any platform. Nothing here consults the clock, the
 * environment, or an unseeded generator.
 *
 * Quantiles use the R type-7 / NumPy `linear` convention (see `internal.ts`).
 *
 * @returns `undefined_statistic` when the statistic is undefined on the
 *   original series, and `insufficient_sample` when fewer than 2 replicates
 *   produced a usable value.
 */
export function bootstrapCI(
  series: readonly number[],
  statistic: BootstrapStatistic,
  options: BootstrapCIOptions,
): StatsResult<BootstrapCIValue> {
  const level = options.level ?? 0.95;
  const resamples = options.resamples ?? 1000;
  if (!(level > 0 && level < 1)) {
    return fail('invalid_parameter', 'level must lie strictly between 0 and 1.');
  }

  const fallbackBlock = optimalBlockLength(series);
  const blockMeanLength = options.blockMeanLength ?? fallbackBlock ?? 1;

  const samples = stationaryBootstrap(series, {
    blockMeanLength,
    resamples,
    seed: options.seed,
  });
  if (!samples.ok) return samples;

  const pointEstimate = statistic([...series]);
  if (pointEstimate === null || !Number.isFinite(pointEstimate)) {
    return fail('undefined_statistic', 'The statistic is undefined on the original series.');
  }

  const replicates: number[] = [];
  for (const row of samples.value.indices) {
    const resampled: number[] = new Array<number>(row.length);
    for (let i = 0; i < row.length; i += 1) {
      resampled[i] = at(series, at(row, i));
    }
    const value = statistic(resampled);
    if (value !== null && Number.isFinite(value)) replicates.push(value);
  }

  if (replicates.length < 2) {
    return fail(
      'insufficient_sample',
      'Fewer than 2 bootstrap replicates produced a usable statistic; the interval would be meaningless.',
    );
  }

  const sorted = sortedAscending(replicates);
  const alpha = (1 - level) / 2;
  const lower = quantileType7(sorted, alpha);
  const upper = quantileType7(sorted, 1 - alpha);
  if (!Number.isFinite(lower) || !Number.isFinite(upper)) {
    return fail('undefined_denominator', 'Bootstrap quantiles evaluated to non-finite values.');
  }

  return ok({
    pointEstimate,
    lower,
    upper,
    level,
    resamples,
    seed: options.seed,
    method: 'percentile',
    blockMeanLength,
    usableResamples: replicates.length,
  });
}
