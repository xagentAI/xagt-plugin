/**
 * Sharpe ratio and the Bailey / López de Prado significance family.
 *
 * ──────────────────────────────────────────────────────────────────────────
 *  EVERY Sharpe ratio in this module is **PER PERIOD** unless the identifier
 *  says `annualised`. `sharpeRatio`, `probabilisticSharpeRatio.sharpe`,
 *  `minimumTrackRecordLength.sharpe`, `deflatedSharpeRatio.sharpe` and
 *  `trialSharpes` are all per-period. Feeding an annualised Sharpe into PSR is
 *  the classic bug in this literature: with daily data it inflates SR̂ by √252,
 *  which turns an inconclusive track record into a 1.000 probability.
 *  {@link annualise} is the only function that crosses the boundary, and it
 *  labels its output.
 * ──────────────────────────────────────────────────────────────────────────
 *
 * Sources:
 *  - Bailey, D. & López de Prado, M. (2012), "The Sharpe Ratio Efficient
 *    Frontier", Journal of Risk 15(2) — PSR and MinTRL.
 *  - Bailey, D. & López de Prado, M. (2014), "The Deflated Sharpe Ratio:
 *    Correcting for Selection Bias, Backtest Overfitting and Non-Normality",
 *    Journal of Portfolio Management 40(5) — DSR and the expected maximum
 *    Sharpe of N trials.
 */

import { mean, stdDev, variance } from './moments';
import { normalCdf, normalInv } from './numeric';
import { allFinite } from './internal';
import { fail, ok, type StatsResult } from './result';

/** Euler–Mascheroni constant γ, used in the expected-maximum-Sharpe expansion. */
export const EULER_MASCHERONI = 0.5772156649015329;

/** Inputs echoed back by {@link sharpeRatio} so a caller can render an audit trail. */
export interface SharpeInputs {
  readonly n: number;
  readonly meanReturn: number;
  readonly stdDev: number;
  readonly riskFreePerPeriod: number;
}

/** A per-period Sharpe ratio and the numbers behind it. */
export interface SharpeValue {
  /** (mean − rf) / sample stdDev, **per period**. */
  readonly sharpe: number;
  /** Always `true`; present so a mis-wired annualised value is a type error at the call site. */
  readonly perPeriod: true;
  readonly inputs: SharpeInputs;
}

/** Options for {@link sharpeRatio}. */
export interface SharpeRatioOptions {
  /**
   * Risk-free rate expressed **per period**, matching the sampling frequency of
   * `returns`. Defaults to 0. An annual 4% on daily data is ~0.000159, not 0.04.
   */
  readonly riskFreePerPeriod?: number;
}

/**
 * Per-period Sharpe ratio: `(x̄ − rf) / s`, where `s` is the *sample* standard
 * deviation (ddof = 1).
 *
 * The sample divisor is not arbitrary — the PSR and MinTRL formulas below are
 * derived for the estimator with `n − 1` in the denominator, and mixing in a
 * population standard deviation shifts SR̂ by √(n/(n−1)).
 *
 * @returns `insufficient_sample` for `n < 2`, `non_finite_input` for any bad
 *   element, `zero_variance` when the series is constant (Sharpe is undefined,
 *   not infinite — a flat equity curve has no risk-adjusted anything).
 */
export function sharpeRatio(
  returns: readonly number[],
  options: SharpeRatioOptions = {},
): StatsResult<SharpeValue> {
  const riskFreePerPeriod = options.riskFreePerPeriod ?? 0;
  if (!Number.isFinite(riskFreePerPeriod)) {
    return fail('invalid_parameter', 'riskFreePerPeriod must be a finite number.');
  }
  if (returns.length === 0) return fail('empty_input', 'No returns supplied.');
  if (!allFinite(returns)) {
    return fail('non_finite_input', 'Return series contains a non-finite value.');
  }
  if (returns.length < 2) {
    return fail('insufficient_sample', 'At least 2 returns are required to estimate a standard deviation.');
  }
  const meanReturn = mean(returns);
  const sd = stdDev(returns, { ddof: 1 });
  if (meanReturn === null || sd === null) {
    return fail('insufficient_sample', 'Mean or standard deviation is undefined for this sample.');
  }
  if (sd === 0) {
    return fail('zero_variance', 'All returns are identical, so the Sharpe ratio is undefined.');
  }
  const sharpe = (meanReturn - riskFreePerPeriod) / sd;
  if (!Number.isFinite(sharpe)) {
    return fail('undefined_denominator', 'Sharpe ratio evaluated to a non-finite value.');
  }
  return ok({
    sharpe,
    perPeriod: true,
    inputs: { n: returns.length, meanReturn, stdDev: sd, riskFreePerPeriod },
  });
}

/** An annualised Sharpe ratio, kept structurally distinct from the per-period one. */
export interface AnnualisedSharpeValue {
  readonly annualisedSharpe: number;
  readonly perPeriodSharpe: number;
  readonly periodsPerYear: number;
}

/**
 * Scale a per-period Sharpe to annual: `SR_annual = SR_period · √(periods per year)`.
 *
 * This is the IID square-root-of-time rule. It assumes returns are serially
 * uncorrelated; a strategy with autocorrelated returns (most trend followers,
 * anything holding overnight) violates it and the annualised figure will be
 * optimistic. We do not silently correct for that — see Lo (2002), "The
 * Statistics of Sharpe Ratios", for the autocorrelation-adjusted factor — but
 * the per-period value carried alongside lets a caller redo it.
 *
 * @param sr - Per-period Sharpe ratio.
 * @param periodsPerYear - Typically from `inferPeriodsPerYear`. Must be finite and > 0.
 */
export function annualise(sr: number, periodsPerYear: number): StatsResult<AnnualisedSharpeValue> {
  if (!Number.isFinite(sr)) return fail('non_finite_input', 'Sharpe ratio must be a finite number.');
  if (!Number.isFinite(periodsPerYear) || periodsPerYear <= 0) {
    return fail('invalid_parameter', 'periodsPerYear must be a finite number greater than zero.');
  }
  const annualisedSharpe = sr * Math.sqrt(periodsPerYear);
  if (!Number.isFinite(annualisedSharpe)) {
    return fail('undefined_denominator', 'Annualised Sharpe ratio overflowed.');
  }
  return ok({ annualisedSharpe, perPeriodSharpe: sr, periodsPerYear });
}

/** Arguments to {@link probabilisticSharpeRatio}. */
export interface ProbabilisticSharpeRatioArgs {
  /** Observed Sharpe ratio SR̂, **per period**. */
  readonly sharpe: number;
  /** Number of returns in the track record. */
  readonly n: number;
  /** γ₃, sample skewness of the returns (see `moments.skewness`). */
  readonly skewness: number;
  /** γ₄, **non-excess** sample kurtosis (normal = 3). See `moments.kurtosis`. */
  readonly kurtosis: number;
  /** SR*, the per-period Sharpe being tested against. Defaults to 0. */
  readonly benchmarkSharpe?: number;
}

/** Result payload of {@link probabilisticSharpeRatio}. */
export interface ProbabilisticSharpeRatioValue {
  /** P(SR̂ > SR*) given the observed higher moments, in [0, 1]. */
  readonly psr: number;
  /** The z-score fed to Φ, useful for sanity-checking the magnitude. */
  readonly zScore: number;
  /** `1 − γ₃·SR̂ + ((γ₄−1)/4)·SR̂²`, the variance term under the square root. */
  readonly radicand: number;
  readonly inputs: Required<ProbabilisticSharpeRatioArgs>;
}

/**
 * The estimator variance term shared by PSR and MinTRL:
 *
 *     1 − γ₃·SR̂ + ((γ₄ − 1)/4)·SR̂²
 *
 * This is `(n − 1)·Var[SR̂]` under Mertens' (2002) non-normal asymptotic
 * standard error of the Sharpe ratio, which is what Bailey & López de Prado
 * plug in. Negative skew and fat tails both *increase* it, i.e. make the same
 * Sharpe less significant — which is the entire point of the correction.
 */
function sharpeVarianceTerm(sharpe: number, skewness: number, kurtosis: number): number {
  return 1 - skewness * sharpe + ((kurtosis - 1) / 4) * sharpe * sharpe;
}

/**
 * Probabilistic Sharpe Ratio — the probability that the true Sharpe exceeds a
 * benchmark, given the observed Sharpe, sample length and higher moments.
 *
 *     PSR(SR*) = Φ( (SR̂ − SR*)·√(n − 1) / √(1 − γ₃·SR̂ + ((γ₄ − 1)/4)·SR̂²) )
 *
 * All Sharpe inputs are **per period**. γ₄ is **non-excess**.
 *
 * Source: Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier",
 * equation (3).
 *
 * @returns `undefined_variance` when the radicand is ≤ 0 (a combination of
 *   skew, kurtosis and SR̂ that Mertens' expansion cannot represent — the
 *   estimate simply does not exist, and returning NaN would let it leak into a
 *   report as "—" or, worse, as a sorted-to-the-top row).
 */
export function probabilisticSharpeRatio(
  args: ProbabilisticSharpeRatioArgs,
): StatsResult<ProbabilisticSharpeRatioValue> {
  const benchmarkSharpe = args.benchmarkSharpe ?? 0;
  const { sharpe, n, skewness, kurtosis } = args;

  if (![sharpe, skewness, kurtosis, benchmarkSharpe, n].every((v) => Number.isFinite(v))) {
    return fail('non_finite_input', 'PSR inputs must all be finite numbers.');
  }
  if (n < 2) {
    return fail('insufficient_sample', 'PSR requires at least 2 returns (it scales by sqrt(n - 1)).');
  }

  const radicand = sharpeVarianceTerm(sharpe, skewness, kurtosis);
  if (!(radicand > 0)) {
    return fail(
      'undefined_variance',
      'The Sharpe estimator variance term is non-positive for these skewness/kurtosis values, so PSR is undefined.',
    );
  }

  const zScore = ((sharpe - benchmarkSharpe) * Math.sqrt(n - 1)) / Math.sqrt(radicand);
  if (!Number.isFinite(zScore)) {
    return fail('undefined_denominator', 'PSR z-score evaluated to a non-finite value.');
  }
  const psr = normalCdf(zScore);
  if (!Number.isFinite(psr)) {
    return fail('undefined_denominator', 'PSR evaluated to a non-finite value.');
  }

  return ok({
    psr,
    zScore,
    radicand,
    inputs: { sharpe, n, skewness, kurtosis, benchmarkSharpe },
  });
}

/** Arguments to {@link minimumTrackRecordLength}. */
export interface MinimumTrackRecordLengthArgs {
  /** Observed Sharpe ratio SR̂, **per period**. */
  readonly sharpe: number;
  /** γ₃, sample skewness. */
  readonly skewness: number;
  /** γ₄, **non-excess** sample kurtosis. */
  readonly kurtosis: number;
  /** SR*, the per-period benchmark Sharpe. Defaults to 0. */
  readonly benchmarkSharpe?: number;
  /** Required confidence, in the open interval (0, 1). Defaults to 0.95. */
  readonly confidence?: number;
}

/** Result payload of {@link minimumTrackRecordLength}. */
export interface MinimumTrackRecordLengthValue {
  /** minTRL in **periods**, as a real number. */
  readonly minimumTrackRecordLength: number;
  /** `ceil(minimumTrackRecordLength)` — the first whole period at which the bar is cleared. */
  readonly periodsRequired: number;
  /** Φ⁻¹(confidence). */
  readonly zConfidence: number;
  /** The shared estimator variance term. */
  readonly radicand: number;
  readonly inputs: Required<MinimumTrackRecordLengthArgs>;
}

/**
 * Minimum Track Record Length — how many periods of returns are needed before
 * an observed Sharpe of `sharpe` is statistically distinguishable from
 * `benchmarkSharpe` at the requested confidence.
 *
 *     minTRL = 1 + [1 − γ₃·SR̂ + ((γ₄ − 1)/4)·SR̂²] · ( Φ⁻¹(confidence) / (SR̂ − SR*) )²
 *
 * Reported in the same periods as the returns: 287 on daily data is 287 trading
 * observations, not 287 days of calendar time.
 *
 * Source: Bailey & López de Prado (2012), equation (8).
 *
 * @returns `benchmark_not_exceeded` when `SR̂ ≤ SR*`. This is not a numerical
 *   edge case — it means the track record can never reach significance against
 *   that benchmark no matter how long it runs, because the point estimate
 *   itself is on the wrong side of the bar. Surfacing it as a distinct reason
 *   lets the UI say that rather than print an enormous number.
 */
export function minimumTrackRecordLength(
  args: MinimumTrackRecordLengthArgs,
): StatsResult<MinimumTrackRecordLengthValue> {
  const benchmarkSharpe = args.benchmarkSharpe ?? 0;
  const confidence = args.confidence ?? 0.95;
  const { sharpe, skewness, kurtosis } = args;

  if (![sharpe, skewness, kurtosis, benchmarkSharpe, confidence].every((v) => Number.isFinite(v))) {
    return fail('non_finite_input', 'MinTRL inputs must all be finite numbers.');
  }
  if (!(confidence > 0 && confidence < 1)) {
    return fail('invalid_parameter', 'confidence must lie strictly between 0 and 1.');
  }
  if (sharpe <= benchmarkSharpe) {
    return fail(
      'benchmark_not_exceeded',
      'Observed Sharpe does not exceed the benchmark, so no track record length can make it significant.',
    );
  }

  const radicand = sharpeVarianceTerm(sharpe, skewness, kurtosis);
  if (!(radicand > 0)) {
    return fail(
      'undefined_variance',
      'The Sharpe estimator variance term is non-positive for these skewness/kurtosis values, so MinTRL is undefined.',
    );
  }

  const zConfidence = normalInv(confidence);
  if (!Number.isFinite(zConfidence)) {
    return fail('invalid_parameter', 'confidence maps to a non-finite critical value.');
  }

  const ratio = zConfidence / (sharpe - benchmarkSharpe);
  const minTrl = 1 + radicand * ratio * ratio;
  if (!Number.isFinite(minTrl)) {
    return fail('undefined_denominator', 'MinTRL evaluated to a non-finite value.');
  }

  return ok({
    minimumTrackRecordLength: minTrl,
    periodsRequired: Math.ceil(minTrl),
    zConfidence,
    radicand,
    inputs: { sharpe, skewness, kurtosis, benchmarkSharpe, confidence },
  });
}

/** Arguments to {@link deflatedSharpeRatio}. */
export interface DeflatedSharpeRatioArgs {
  /** Observed Sharpe ratio SR̂ of the selected strategy, **per period**. */
  readonly sharpe: number;
  /** Number of returns in the selected strategy's track record. */
  readonly n: number;
  /** γ₃, sample skewness of the selected strategy's returns. */
  readonly skewness: number;
  /** γ₄, **non-excess** sample kurtosis of the selected strategy's returns. */
  readonly kurtosis: number;
  /**
   * Per-period Sharpe ratios of **all** trials that were run before this one was
   * picked — every parameter set, every variant, every abandoned idea. Its
   * length is N and its dispersion is what drives the deflation. Supplying only
   * the survivors defeats the entire correction.
   */
  readonly trialSharpes: readonly number[];
  /**
   * Divisor correction for the cross-sectional variance of `trialSharpes`.
   *
   * Defaults to **1** (unbiased sample variance), because the trials are a
   * sample of the search that was run. Bailey & López de Prado's own reference
   * snippet uses NumPy's `var`, i.e. ddof = 0; pass `0` to reconcile exactly
   * with that implementation. The two differ by a factor √(N/(N−1)) in SR*₀,
   * which matters for small N.
   */
  readonly varianceDdof?: 0 | 1;
}

/** Result payload of {@link deflatedSharpeRatio}. */
export interface DeflatedSharpeRatioValue {
  /** The deflated Sharpe ratio: PSR evaluated against the expected maximum of N trials. */
  readonly dsr: number;
  /** SR*₀, the Sharpe you would expect the best of N random trials to show by luck alone. */
  readonly expectedMaxSharpe: number;
  /** N, the number of trials. */
  readonly trials: number;
  /** Cross-sectional variance of `trialSharpes` under `varianceDdof`. */
  readonly trialVariance: number;
  readonly zScore: number;
  readonly radicand: number;
  readonly inputs: {
    readonly sharpe: number;
    readonly n: number;
    readonly skewness: number;
    readonly kurtosis: number;
    readonly trials: number;
    readonly varianceDdof: 0 | 1;
  };
}

/**
 * Expected maximum Sharpe ratio of N independent trials:
 *
 *     SR*₀ = √Var({SRₙ}) · [ (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ]
 *
 * with γ the Euler–Mascheroni constant. This is the standard Gumbel-based
 * approximation to E[max of N standard normals], rescaled by the observed
 * dispersion of the trials.
 *
 * Exported because "the best of N random strategies would have scored this by
 * luck" is a number worth showing on its own.
 *
 * Source: Bailey & López de Prado (2014), equation (5).
 */
export function expectedMaximumSharpe(
  trialSharpes: readonly number[],
  varianceDdof: 0 | 1 = 1,
): StatsResult<{ expectedMaxSharpe: number; trials: number; trialVariance: number }> {
  const trials = trialSharpes.length;
  if (trials < 2) {
    return fail(
      'insufficient_trials',
      'At least 2 trial Sharpe ratios are required; the deflation is driven by their dispersion.',
    );
  }
  if (!allFinite(trialSharpes)) {
    return fail('non_finite_input', 'Trial Sharpe ratios must all be finite numbers.');
  }
  const trialVariance = variance(trialSharpes, { ddof: varianceDdof });
  if (trialVariance === null || trialVariance < 0) {
    return fail('undefined_variance', 'Cross-sectional variance of the trial Sharpe ratios is undefined.');
  }
  const upper = normalInv(1 - 1 / trials);
  const gumbel = normalInv(1 - 1 / (trials * Math.E));
  if (!Number.isFinite(upper) || !Number.isFinite(gumbel)) {
    return fail('undefined_denominator', 'Expected-maximum quantiles evaluated to non-finite values.');
  }
  const expectedMaxSharpe =
    Math.sqrt(trialVariance) * ((1 - EULER_MASCHERONI) * upper + EULER_MASCHERONI * gumbel);
  if (!Number.isFinite(expectedMaxSharpe)) {
    return fail('undefined_denominator', 'Expected maximum Sharpe evaluated to a non-finite value.');
  }
  return ok({ expectedMaxSharpe, trials, trialVariance });
}

/**
 * Deflated Sharpe Ratio — the PSR of the selected strategy measured against the
 * Sharpe that the *best of N trials* would be expected to show by chance.
 *
 *     DSR = PSR(SR*₀),  SR*₀ = √Var({SRₙ})·[(1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))]
 *
 * This is the number that answers "is it luck?" honestly: a PSR of 0.99 on a
 * strategy cherry-picked from 500 backtests is not evidence of anything, and
 * the DSR says so.
 *
 * All Sharpe inputs are **per period**; γ₄ is **non-excess**.
 *
 * Source: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio".
 *
 * @returns `insufficient_trials` when fewer than 2 trials are supplied — with
 *   one trial there is no selection to correct for and the honest answer is to
 *   report the PSR instead, not to pretend N = 1 deflation is meaningful.
 */
export function deflatedSharpeRatio(
  args: DeflatedSharpeRatioArgs,
): StatsResult<DeflatedSharpeRatioValue> {
  const varianceDdof = args.varianceDdof ?? 1;
  const { sharpe, n, skewness, kurtosis, trialSharpes } = args;

  const expected = expectedMaximumSharpe(trialSharpes, varianceDdof);
  if (!expected.ok) return expected;

  const psr = probabilisticSharpeRatio({
    sharpe,
    n,
    skewness,
    kurtosis,
    benchmarkSharpe: expected.value.expectedMaxSharpe,
  });
  if (!psr.ok) return psr;

  return ok({
    dsr: psr.value.psr,
    expectedMaxSharpe: expected.value.expectedMaxSharpe,
    trials: expected.value.trials,
    trialVariance: expected.value.trialVariance,
    zScore: psr.value.zScore,
    radicand: psr.value.radicand,
    inputs: {
      sharpe,
      n,
      skewness,
      kurtosis,
      trials: expected.value.trials,
      varianceDdof,
    },
  });
}
