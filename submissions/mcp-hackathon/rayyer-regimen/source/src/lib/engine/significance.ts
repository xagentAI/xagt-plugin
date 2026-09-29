import {
  bootstrapCI,
  inferPeriodsPerYear,
  kurtosis,
  maxDrawdown,
  mean,
  minimumTrackRecordLength,
  optimalBlockLength,
  probabilisticSharpeRatio,
  sharpeRatio,
  skewness,
  stdDev,
  toReturns,
  totalReturn,
  tradeStats,
  ulcerIndex,
  wilsonInterval,
  deflatedSharpeRatio,
} from '@/lib/stats';
import type { StatsReason } from '@/lib/stats';
import type { TrackRecord } from '@/lib/sources/types';

/**
 * The significance analysis: is this track record distinguishable from luck?
 *
 * The headline number in crypto strategy marketing is a Sharpe ratio computed over a
 * few weeks. A Sharpe ratio is an estimate, and an estimate from a short, skewed,
 * fat-tailed sample carries an error bar wide enough to swallow the claim. This module
 * puts the error bar back: the Probabilistic Sharpe Ratio gives the probability that
 * the true Sharpe exceeds a benchmark given the observed sample's length, skew and
 * kurtosis, and the Minimum Track Record Length says how much longer the record would
 * have to run before the claim could be made at all.
 *
 * References:
 *  - Bailey, D. and López de Prado, M. (2012), "The Sharpe Ratio Efficient Frontier",
 *    Journal of Risk 15(2) — PSR and MinTRL.
 *  - Bailey, D. and López de Prado, M. (2014), "The Deflated Sharpe Ratio", Journal of
 *    Portfolio Management 40(5) — correcting for selection across trials.
 *
 * Nothing here decides whether to trade. It reports what the evidence supports.
 */

/** How confident PSR has to be before each label applies. Published, not tuned per input. */
export const EVIDENCE_THRESHOLDS = {
  /** Below this many usable returns we decline to grade at all. */
  minimumUsableReturns: 20,
  weak: 0.9,
  supported: 0.95,
  strong: 0.99,
  /**
   * Below this many returns the sample skewness and kurtosis are too noisy for the
   * non-normality correction to mean much. Kurtosis in particular is a fourth-moment
   * estimate and converges slowly. The analysis still runs — it is flagged, not
   * suppressed, because suppressing it would leave the caller with no number at all.
   */
  reliableShapeMoments: 100,
} as const;

export type EvidenceTier =
  /** Too little data to say anything. Regimen refuses rather than guesses. */
  | 'insufficient_evidence'
  /** The record is consistent with having no edge at all. */
  | 'indistinguishable_from_luck'
  /** Positive, but not at a confidence anyone should size on. */
  | 'weak'
  | 'supported'
  | 'strong';

export interface SampleSummary {
  readonly equityPointsSupplied: number;
  readonly usableReturns: number;
  readonly droppedPoints: number;
  readonly firstObservation: string | null;
  readonly lastObservation: string | null;
  readonly spanDays: number | null;
  readonly periodsPerYear: number | null;
  readonly irregularSpacing: boolean;
  readonly annualisationTrustworthy: boolean;
}

export interface PerformanceSummary {
  readonly totalReturn: number | null;
  readonly sharpePerPeriod: number | null;
  readonly sharpeAnnualised: number | null;
  readonly meanReturn: number | null;
  readonly volatilityPerPeriod: number | null;
  readonly skewness: number | null;
  readonly kurtosis: number | null;
  readonly maxDrawdown: number | null;
  readonly ulcerIndex: number | null;
}

export interface EvidenceSummary {
  readonly tier: EvidenceTier;
  readonly headline: string;
  readonly probabilisticSharpe: number | null;
  readonly probabilisticSharpeReason: StatsReason | null;
  readonly benchmarkSharpe: number;
  readonly minimumTrackRecordLength: number | null;
  readonly periodsShortOfSignificance: number | null;
  readonly deflatedSharpe: number | null;
  readonly deflatedSharpeNote: string;
  /**
   * Whether the sample is long enough for the skewness and kurtosis corrections to
   * carry information. Below the threshold they are estimated from too few points to
   * be trusted, which is a known blind spot rather than a detail.
   */
  readonly shapeCorrectionReliable: boolean;
  readonly sharpeConfidenceInterval: { readonly lower: number; readonly upper: number; readonly level: number } | null;
  readonly bootstrap: { readonly resamples: number; readonly seed: number; readonly blockMeanLength: number } | null;
  readonly rationale: readonly string[];
}

export interface DivergenceRow {
  readonly field: string;
  readonly reported: number;
  readonly recomputed: number;
  readonly absoluteDifference: number;
  readonly material: boolean;
}

export interface TradeSummary {
  readonly count: number;
  readonly winRate: number | null;
  readonly winRateInterval: { readonly lower: number; readonly upper: number } | null;
  readonly profitFactor: number | null;
  readonly expectancy: number | null;
}

export interface SignificanceReport {
  readonly label: string;
  readonly sourceId: string;
  readonly sample: SampleSummary;
  readonly performance: PerformanceSummary;
  readonly evidence: EvidenceSummary;
  readonly trades: TradeSummary | null;
  readonly divergences: readonly DivergenceRow[];
  readonly notes: readonly string[];
}

export interface SignificanceOptions {
  /** Sharpe the record must beat. 0 asks only "is there any edge at all?". */
  readonly benchmarkSharpe?: number;
  readonly riskFreePerPeriod?: number;
  readonly confidence?: number;
  readonly bootstrapResamples?: number;
  /** Fixed by default so the same track record always yields the same interval. */
  readonly seed?: number;
  /**
   * Per-period Sharpe ratios from other evaluation windows of the SAME strategy.
   * Supplying them enables the Deflated Sharpe Ratio, which discounts the headline
   * for the number of configurations that were tried before this one was reported.
   */
  readonly trialSharpes?: readonly number[];
}

const DEFAULT_SEED = 0x5eed_1234;
const DEFAULT_RESAMPLES = 2_000;
const DEFAULT_CONFIDENCE = 0.95;

/** A divergence this large between reported and recomputed is worth a reviewer's eye. */
const MATERIAL_SHARPE_DIFFERENCE = 0.15;
const MATERIAL_FRACTION_DIFFERENCE = 0.02;

function isoOrNull(t: number | undefined): string | null {
  return t === undefined ? null : new Date(t).toISOString();
}

export function analyseSignificance(
  record: TrackRecord,
  options: SignificanceOptions = {},
): SignificanceReport {
  const benchmarkSharpe = options.benchmarkSharpe ?? 0;
  const confidence = options.confidence ?? DEFAULT_CONFIDENCE;
  const seed = options.seed ?? DEFAULT_SEED;
  const resamples = options.bootstrapResamples ?? DEFAULT_RESAMPLES;
  const notes: string[] = [];

  const series = toReturns(record.equity, { kind: 'simple' });
  const returns = series.returns;
  const n = returns.length;

  if (series.dropped.length > 0) {
    notes.push(
      `${series.dropped.length} equity point(s) were dropped before analysis: ${[
        ...new Set(series.dropped.map((drop) => drop.code)),
      ].join(', ')}.`,
    );
  }

  const inference = inferPeriodsPerYear(series.timestamps);
  if (inference.irregular) {
    notes.push(
      'Equity points are not evenly spaced, so any annualised figure is an approximation. Per-period figures are exact and are what the evidence tier is based on.',
    );
  }

  const sample: SampleSummary = {
    equityPointsSupplied: record.equity.length,
    usableReturns: n,
    droppedPoints: series.dropped.length,
    firstObservation: isoOrNull(series.timestamps[0]),
    lastObservation: isoOrNull(series.timestamps[series.timestamps.length - 1]),
    spanDays:
      series.timestamps.length >= 2
        ? ((series.timestamps[series.timestamps.length - 1] as number) - (series.timestamps[0] as number)) / 86_400_000
        : null,
    periodsPerYear: inference.periodsPerYear,
    irregularSpacing: inference.irregular,
    annualisationTrustworthy: inference.periodsPerYear !== null && !inference.irregular,
  };

  const sharpe = sharpeRatio(returns, { riskFreePerPeriod: options.riskFreePerPeriod ?? 0 });
  const skew = skewness(returns);
  const kurt = kurtosis(returns, { excess: false });
  const equityValues = record.equity.map((point) => point.equity);
  const drawdown = maxDrawdown(equityValues);
  const ulcer = ulcerIndex(equityValues);

  const sharpePerPeriod = sharpe.ok ? sharpe.value.sharpe : null;
  const sharpeAnnualised =
    sharpePerPeriod !== null && inference.periodsPerYear !== null
      ? sharpePerPeriod * Math.sqrt(inference.periodsPerYear)
      : null;

  const performance: PerformanceSummary = {
    totalReturn: totalReturn(returns, 'simple'),
    sharpePerPeriod,
    sharpeAnnualised,
    meanReturn: mean(returns),
    volatilityPerPeriod: stdDev(returns),
    skewness: skew,
    kurtosis: kurt,
    maxDrawdown: drawdown.ok ? drawdown.value.maxDrawdown : null,
    ulcerIndex: ulcer.ok ? ulcer.value.ulcerIndex : null,
  };

  const evidence = buildEvidence({
    n,
    returns,
    sharpePerPeriod,
    skew,
    kurt,
    benchmarkSharpe,
    confidence,
    seed,
    resamples,
    trialSharpes: options.trialSharpes,
    riskFreePerPeriod: options.riskFreePerPeriod ?? 0,
  });

  return {
    label: record.label,
    sourceId: record.sourceId,
    sample,
    performance,
    evidence,
    trades: summariseTrades(record, confidence),
    divergences: compareReported(record, performance, sharpeAnnualised),
    notes,
  };
}

function summariseTrades(record: TrackRecord, confidence: number): TradeSummary | null {
  if (record.trades.length === 0) return null;
  const stats = tradeStats(record.trades.map((trade) => trade.pnl));
  if (!stats.ok) return null;
  const value = stats.value;
  // A win rate quoted without an interval invites over-reading a 12-trade sample.
  const interval = wilsonInterval(value.wins, value.count, confidence);
  return {
    count: value.count,
    winRate: value.winRate,
    winRateInterval: interval.ok ? { lower: interval.value.lower, upper: interval.value.upper } : null,
    profitFactor: value.profitFactor,
    expectancy: value.expectancy,
  };
}

/**
 * Contrast the figures the source publishes against the ones the equity curve implies.
 *
 * Not an accusation — differing conventions (log versus simple returns, a different
 * annualisation factor, fees included or not) explain most gaps. But a user quoting a
 * dashboard number deserves to know when the curve underneath it says something else,
 * and a reviewer deserves to see that Regimen checked.
 */
function compareReported(
  record: TrackRecord,
  performance: PerformanceSummary,
  sharpeAnnualised: number | null,
): DivergenceRow[] {
  const reported = record.reported;
  if (!reported) return [];
  const rows: DivergenceRow[] = [];

  if (reported.sharpeRatio !== undefined && sharpeAnnualised !== null) {
    const difference = Math.abs(reported.sharpeRatio - sharpeAnnualised);
    rows.push({
      field: 'sharpeRatio (annualised)',
      reported: reported.sharpeRatio,
      recomputed: sharpeAnnualised,
      absoluteDifference: difference,
      material: difference > MATERIAL_SHARPE_DIFFERENCE,
    });
  }

  if (reported.maxDrawdown !== undefined && performance.maxDrawdown !== null) {
    const difference = Math.abs(reported.maxDrawdown - performance.maxDrawdown);
    rows.push({
      field: 'maxDrawdown (fraction)',
      reported: reported.maxDrawdown,
      recomputed: performance.maxDrawdown,
      absoluteDifference: difference,
      material: difference > MATERIAL_FRACTION_DIFFERENCE,
    });
  }

  if (reported.totalReturnPct !== undefined && performance.totalReturn !== null) {
    const recomputedPct = performance.totalReturn * 100;
    const difference = Math.abs(reported.totalReturnPct - recomputedPct);
    rows.push({
      field: 'totalReturnPct',
      reported: reported.totalReturnPct,
      recomputed: recomputedPct,
      absoluteDifference: difference,
      material: difference > 1,
    });
  }

  return rows;
}

interface EvidenceArgs {
  readonly n: number;
  readonly returns: readonly number[];
  readonly sharpePerPeriod: number | null;
  readonly skew: number | null;
  readonly kurt: number | null;
  readonly benchmarkSharpe: number;
  readonly confidence: number;
  readonly seed: number;
  readonly resamples: number;
  readonly trialSharpes: readonly number[] | undefined;
  readonly riskFreePerPeriod: number;
}

function buildEvidence(args: EvidenceArgs): EvidenceSummary {
  const rationale: string[] = [];
  const { n, sharpePerPeriod, skew, kurt, benchmarkSharpe, confidence } = args;

  if (n < EVIDENCE_THRESHOLDS.minimumUsableReturns) {
    return {
      tier: 'insufficient_evidence',
      headline: `Only ${n} usable return${n === 1 ? '' : 's'}. That is too few to distinguish skill from luck at any useful confidence.`,
      probabilisticSharpe: null,
      probabilisticSharpeReason: 'insufficient_sample',
      benchmarkSharpe,
      minimumTrackRecordLength: null,
      periodsShortOfSignificance: null,
      deflatedSharpe: null,
      deflatedSharpeNote: 'Not computed: the sample is too short for any significance statement.',
      shapeCorrectionReliable: false,
      sharpeConfidenceInterval: null,
      bootstrap: null,
      rationale: [
        `Regimen declines to grade a record with fewer than ${EVIDENCE_THRESHOLDS.minimumUsableReturns} usable returns.`,
        'Extend the evaluation window and ask again.',
      ],
    };
  }

  if (sharpePerPeriod === null || skew === null || kurt === null) {
    return {
      tier: 'insufficient_evidence',
      headline:
        'The return series has no usable dispersion, so a Sharpe ratio — and therefore any significance statement — is undefined.',
      probabilisticSharpe: null,
      probabilisticSharpeReason: 'zero_variance',
      benchmarkSharpe,
      minimumTrackRecordLength: null,
      periodsShortOfSignificance: null,
      deflatedSharpe: null,
      deflatedSharpeNote: 'Not computed: the Sharpe ratio it would deflate does not exist.',
      shapeCorrectionReliable: false,
      sharpeConfidenceInterval: null,
      bootstrap: null,
      rationale: ['Every return is identical, so the denominator of the Sharpe ratio is zero.'],
    };
  }

  const shapeCorrectionReliable = n >= EVIDENCE_THRESHOLDS.reliableShapeMoments;

  const psr = probabilisticSharpeRatio({
    sharpe: sharpePerPeriod,
    n,
    skewness: skew,
    kurtosis: kurt,
    benchmarkSharpe,
  });

  const minTrl = minimumTrackRecordLength({
    sharpe: sharpePerPeriod,
    skewness: skew,
    kurtosis: kurt,
    benchmarkSharpe,
    confidence,
  });

  const blockMeanLength = optimalBlockLength(args.returns) ?? 1;
  const ci = bootstrapCI(
    args.returns,
    (sample) => {
      const result = sharpeRatio(sample, { riskFreePerPeriod: args.riskFreePerPeriod });
      return result.ok ? result.value.sharpe : null;
    },
    { level: confidence, resamples: args.resamples, seed: args.seed, blockMeanLength },
  );

  let deflated: number | null = null;
  let deflatedNote =
    'Not computed: no other evaluation windows were supplied, so there is no trial set to deflate against. Run a stability sweep to enable it.';
  if (args.trialSharpes && args.trialSharpes.length >= 2) {
    const dsr = deflatedSharpeRatio({
      sharpe: sharpePerPeriod,
      n,
      skewness: skew,
      kurtosis: kurt,
      trialSharpes: args.trialSharpes,
    });
    if (dsr.ok) {
      deflated = dsr.value.dsr;
      deflatedNote = `Deflated against ${dsr.value.trials} evaluation windows; the selection-adjusted benchmark Sharpe is ${dsr.value.expectedMaxSharpe.toFixed(4)} per period.`;
    } else {
      deflatedNote = `Not computed: ${dsr.message}`;
    }
  }

  const lowerBound = ci.ok ? ci.value.lower : null;

  let psrValue: number | null = null;
  if (psr.ok) {
    psrValue = psr.value.psr;
    rationale.push(
      `Probabilistic Sharpe Ratio is ${(psrValue * 100).toFixed(1)}%: that is the probability the true per-period Sharpe exceeds ${benchmarkSharpe}, given ${n} returns with skewness ${skew.toFixed(2)} and kurtosis ${kurt.toFixed(2)}.`,
    );
  } else {
    rationale.push(`The Probabilistic Sharpe Ratio is undefined here: ${psr.message}`);
  }

  if (!shapeCorrectionReliable) {
    rationale.push(
      `This confidence is corrected for the sample's skewness and kurtosis, but with only ${n} returns those moments are themselves poorly estimated — a strategy whose tail risk has simply not arrived yet will look well-behaved here. Treat the figure as an upper bound on how much is really known.`,
    );
  }

  if (ci.ok) {
    rationale.push(
      `A stationary bootstrap over ${ci.value.resamples} resamples (mean block ${blockMeanLength}) puts the ${(confidence * 100).toFixed(0)}% interval for the per-period Sharpe at [${ci.value.lower.toFixed(4)}, ${ci.value.upper.toFixed(4)}].`,
    );
    if (ci.value.lower <= 0) {
      rationale.push('That interval includes zero, so a Sharpe of zero remains consistent with this sample.');
    }
  }

  let periodsShort: number | null = null;
  if (minTrl.ok) {
    const required = Math.ceil(minTrl.value.minimumTrackRecordLength);
    periodsShort = Math.max(0, required - n);
    rationale.push(
      periodsShort > 0
        ? `At this Sharpe, shape and confidence level, ${required} periods are needed before the claim clears ${(confidence * 100).toFixed(0)}% — ${periodsShort} more than the ${n} observed.`
        : `The record is long enough: ${required} periods were needed and ${n} are present.`,
    );
  } else if (minTrl.reason === 'benchmark_not_exceeded') {
    rationale.push(
      `The observed Sharpe does not exceed the benchmark of ${benchmarkSharpe}, so no amount of additional history would make this claim significant.`,
    );
  }

  const tier = gradeEvidence(psrValue, lowerBound, periodsShort, deflated);

  return {
    tier,
    headline: headlineFor(tier, psrValue, benchmarkSharpe),
    probabilisticSharpe: psrValue,
    probabilisticSharpeReason: psr.ok ? null : psr.reason,
    benchmarkSharpe,
    minimumTrackRecordLength: minTrl.ok ? minTrl.value.minimumTrackRecordLength : null,
    periodsShortOfSignificance: periodsShort,
    deflatedSharpe: deflated,
    deflatedSharpeNote: deflatedNote,
    shapeCorrectionReliable,
    sharpeConfidenceInterval: ci.ok ? { lower: ci.value.lower, upper: ci.value.upper, level: confidence } : null,
    bootstrap: ci.ok ? { resamples: ci.value.resamples, seed: args.seed, blockMeanLength } : null,
    rationale,
  };
}

function gradeEvidence(
  psr: number | null,
  bootstrapLower: number | null,
  periodsShort: number | null,
  deflated: number | null,
): EvidenceTier {
  if (psr === null) return 'insufficient_evidence';

  // The deflated ratio, when available, governs: it is the same statement corrected
  // for how many configurations were tried before this one was shown to anybody.
  const governing = deflated ?? psr;

  if (governing < EVIDENCE_THRESHOLDS.weak) return 'indistinguishable_from_luck';
  if (governing < EVIDENCE_THRESHOLDS.supported) return 'weak';

  const intervalClearsZero = bootstrapLower !== null && bootstrapLower > 0;
  if (!intervalClearsZero) return 'weak';

  if (governing >= EVIDENCE_THRESHOLDS.strong && periodsShort === 0) return 'strong';
  return 'supported';
}

function headlineFor(tier: EvidenceTier, psr: number | null, benchmark: number): string {
  const pct = psr === null ? null : `${(psr * 100).toFixed(1)}%`;
  switch (tier) {
    case 'insufficient_evidence':
      return 'There is not enough data here to say anything about edge.';
    case 'indistinguishable_from_luck':
      return `This record is consistent with having no edge: only ${pct} confidence that the true Sharpe exceeds ${benchmark}.`;
    case 'weak':
      return `Positive but not convincing: ${pct} confidence that the true Sharpe exceeds ${benchmark}.`;
    case 'supported':
      return `The edge is supported by the evidence: ${pct} confidence that the true Sharpe exceeds ${benchmark}.`;
    case 'strong':
      return `Strong evidence of a real edge: ${pct} confidence that the true Sharpe exceeds ${benchmark}, on a record long enough to support the claim.`;
  }
}
