/**
 * The statistical core.
 *
 * One question, asked properly: **is this track record distinguishable from
 * luck, and under which market conditions does it hold?**
 *
 * Everything under `@/lib/stats` is pure, deterministic mathematics — no
 * network, no filesystem, no wall-clock, no third-party dependency, and no
 * randomness that is not explicitly seeded. The special functions are
 * implemented in-repo so that every published number traces to a citable
 * algorithm in the same pull request.
 *
 * Two contracts hold across the whole surface:
 *
 *  1. **Nothing throws on user-shaped data.** Short, constant, unsorted,
 *     duplicated and non-finite inputs are ordinary. Fallible functions return
 *     a {@link StatsResult} discriminated on `ok`, carrying a machine-readable
 *     {@link StatsReason} and a human-readable message; leaf moment estimators
 *     return `number | null`.
 *  2. **No public function returns `NaN` or `Infinity`.** The single documented
 *     exception is {@link normalInv}, for which ±∞ at p ∈ {0, 1} is the
 *     mathematically correct answer.
 *
 * And one convention worth repeating at the door: **every Sharpe ratio is per
 * period** unless the identifier says `annualised`. See `sharpe.ts`.
 *
 * @packageDocumentation
 */

// --- Result envelope ---------------------------------------------------------
export { fail, isOk, ok, valueOrNull } from './result';
export type { Failure, StatsReason, StatsResult, Success } from './result';

// --- Special functions and the seeded PRNG -----------------------------------
export { erf, erfc, mulberry32, normalCdf, normalInv, normalPdf } from './numeric';
export type { Rng } from './numeric';

// --- Sample moments ----------------------------------------------------------
export { extent, kurtosis, mean, skewness, stdDev, sum, variance } from './moments';
export type { DdofOptions, KurtosisOptions } from './moments';

// --- Equity curve → returns --------------------------------------------------
export {
  IRREGULAR_SPACING_FRACTION,
  MS_PER_YEAR,
  SPACING_DEVIATION_TOLERANCE,
  inferPeriodsPerYear,
  toReturns,
  totalReturn,
} from './returns';
export type {
  DropReason,
  DropReasonCode,
  EquityPoint,
  PeriodInference,
  ReturnKind,
  ReturnSeries,
  ToReturnsOptions,
} from './returns';

// --- Sharpe ratio and the Bailey / López de Prado significance family --------
export {
  EULER_MASCHERONI,
  annualise,
  deflatedSharpeRatio,
  expectedMaximumSharpe,
  minimumTrackRecordLength,
  probabilisticSharpeRatio,
  sharpeRatio,
} from './sharpe';
export type {
  AnnualisedSharpeValue,
  DeflatedSharpeRatioArgs,
  DeflatedSharpeRatioValue,
  MinimumTrackRecordLengthArgs,
  MinimumTrackRecordLengthValue,
  ProbabilisticSharpeRatioArgs,
  ProbabilisticSharpeRatioValue,
  SharpeInputs,
  SharpeRatioOptions,
  SharpeValue,
} from './sharpe';

// --- Stationary bootstrap ----------------------------------------------------
export { bootstrapCI, optimalBlockLength, stationaryBootstrap } from './bootstrap';
export type {
  BootstrapCIOptions,
  BootstrapCIValue,
  BootstrapStatistic,
  StationaryBootstrapOptions,
  StationaryBootstrapValue,
} from './bootstrap';

// --- Drawdown ----------------------------------------------------------------
export { maxDrawdown, ulcerIndex } from './drawdown';
export type { MaxDrawdownValue, UlcerIndexValue } from './drawdown';

// --- Trade statistics --------------------------------------------------------
export { tradeStats, wilsonInterval } from './trades';
export type { TradeStatsValue, WilsonIntervalValue } from './trades';

// --- Regime attribution ------------------------------------------------------
export { DEFAULT_MIN_SAMPLE, bucketize, compareBuckets, conditionalStats } from './conditional';
export type {
  BucketContribution,
  BucketStats,
  BucketizeValue,
  CompareBucketsOptions,
  CompareBucketsValue,
  ConditionalStatsArgs,
  ConditionalStatsValue,
  ProportionInterval,
} from './conditional';
