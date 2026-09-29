/**
 * Special functions and the seeded PRNG.
 *
 * These are implemented in-repo rather than pulled from npm so that every
 * number the product publishes can be traced to a citable algorithm sitting in
 * the same pull request. There are no dependencies, no I/O and no unseeded
 * randomness anywhere in this file.
 *
 * Accuracy note: `normalCdf` is a full double-precision algorithm (Hart 1968
 * as transcribed by West 2005), **not** the Abramowitz & Stegun 7.1.26 fit that
 * most JavaScript snippets use — that one is only good to ~7.5e-8 absolute,
 * which is nowhere near enough for the far-tail probabilities the deflated
 * Sharpe ratio produces.
 */

/** 2/√π — the leading constant of the erf Maclaurin series. */
const TWO_OVER_SQRT_PI = 1.1283791670955126;

/** √(2π), the normalising constant of the standard normal density. */
const SQRT_2PI = 2.5066282746310002;

/** √2, used to convert between erf and Φ. */
const SQRT_2 = 1.4142135623730951;

/**
 * Beyond this |x| the standard normal tail underflows to 0 in IEEE-754 double
 * precision (exp(-38.5²/2) ≈ 1e-322 is already subnormal), so short-circuiting
 * here costs no accuracy and avoids relying on subnormal arithmetic.
 */
const NORMAL_TAIL_CUTOFF = 38.5;

/**
 * |x| at which `normalCdf` switches from Hart's rational approximation to the
 * Mills-ratio continued fraction.
 *
 * Hart's fit is ~1e-15 *relative* through the body but drifts to ~5e-10
 * relative by |x| = 6, because it was built to be accurate in absolute terms
 * and the tail probability there is 1e-9. The continued fraction is ~1e-14
 * relative everywhere past |x| = 3, so the crossover sits at 3 where both are
 * still excellent.
 */
const MILLS_CF_CUTOFF = 3;

/** Below this |x| the erf Maclaurin series converges faster than the Φ route and without cancellation. */
const ERF_SERIES_CUTOFF = 0.5;

/**
 * Maclaurin series for erf: erf(x) = (2/√π) · Σₙ (−1)ⁿ x^(2n+1) / (n! (2n+1)).
 *
 * Only used for |x| ≤ 0.5 where x² ≤ 0.25 makes the alternating series
 * converge in ~15 terms with no cancellation. Going through `normalCdf` for
 * small x would instead compute `2Φ(x√2) − 1`, which loses every significant
 * digit as x → 0 (0.5 + δ minus 0.5), and erf(1e-8) has to stay accurate in a
 * *relative* sense.
 *
 * Source: Abramowitz & Stegun (1964), Handbook of Mathematical Functions, 7.1.5.
 */
function erfSeries(x: number): number {
  const xSquared = x * x;
  // term(n) = (−1)ⁿ x^(2n+1) / n!, starting at n = 0.
  let term = x;
  let sum = x;
  for (let n = 1; n < 60; n += 1) {
    term *= -xSquared / n;
    const increment = term / (2 * n + 1);
    sum += increment;
    if (Math.abs(increment) <= Math.abs(sum) * 1e-18) break;
  }
  return TWO_OVER_SQRT_PI * sum;
}

/**
 * Mills ratio M(x) = Φ(−x)/φ(x) for x ≥ 3, as the continued fraction
 *
 *     M(x) = 1 / (x + 1/(x + 2/(x + 3/(x + 4/(x + …)))))
 *
 * evaluated with the modified Lentz algorithm so that convergence is tested
 * rather than guessed at with a fixed truncation depth. Every partial
 * numerator and denominator here is strictly positive for x ≥ 3, so the
 * zero-denominator rescue that Lentz's method normally needs cannot trigger.
 *
 * Sources: Lentz, W. J. (1976), "Generating Bessel functions in Mie scattering
 * calculations using continued fractions", Applied Optics 15(3); Press et al.,
 * Numerical Recipes, §5.2 "Evaluation of Continued Fractions".
 */
function millsRatio(x: number): number {
  const epsilon = 1e-17;
  let f = 1e-300;
  let c = f;
  let d = 0;
  for (let j = 1; j <= 400; j += 1) {
    const a = j === 1 ? 1 : j - 1;
    d = x + a * d;
    c = x + a / c;
    d = 1 / d;
    const delta = c * d;
    f *= delta;
    if (Math.abs(delta - 1) < epsilon) break;
  }
  return f;
}

/**
 * Standard normal cumulative distribution function, Φ(x) = P(Z ≤ x).
 *
 * Two regimes, both double precision:
 *  - **|x| < 3** — Hart's (1968) rational approximation in the form published
 *    by Graeme West, "Better Approximations to Cumulative Normal Functions",
 *    Wilmott Magazine (2005), pp. 70–76. Relative error ~1e-15.
 *  - **|x| ≥ 3** — Φ(−|x|) = φ(|x|)·M(|x|) with the Mills-ratio continued
 *    fraction above. Relative error ~1e-14 all the way to Φ(−37) ≈ 5.73e-300.
 *
 * This is deliberately **not** the Abramowitz & Stegun 7.1.26 fit that most
 * JavaScript snippets use: that one is a single-precision approximation good to
 * ~7.5e-8 absolute, which is meaningless in the tail where the deflated Sharpe
 * ratio lives. West's own listing switches to a 4-level truncated continued
 * fraction at |x| > 7.07 and clamps at |x| > 37; both are relaxed here, because
 * Hart's rational drifts to ~5e-10 relative by |x| = 6 (it was fitted for
 * absolute, not relative, accuracy) and Φ(−37) is perfectly representable.
 *
 * @param x - Any real number. `NaN` in, `NaN` out.
 * @returns Φ(x) in [0, 1].
 */
export function normalCdf(x: number): number {
  if (Number.isNaN(x)) return Number.NaN;
  const absX = Math.abs(x);
  let upperTail: number;
  if (absX > NORMAL_TAIL_CUTOFF) {
    upperTail = 0;
  } else if (absX >= MILLS_CF_CUTOFF) {
    upperTail = (Math.exp((-absX * absX) / 2) / SQRT_2PI) * millsRatio(absX);
  } else {
    const density = Math.exp((-absX * absX) / 2);
    let numerator = 3.52624965998911e-2 * absX + 0.700383064443688;
    numerator = numerator * absX + 6.37396220353165;
    numerator = numerator * absX + 33.912866078383;
    numerator = numerator * absX + 112.079291497871;
    numerator = numerator * absX + 221.213596169931;
    numerator = numerator * absX + 220.206867912376;

    let denominator = 8.83883476483184e-2 * absX + 1.75566716318264;
    denominator = denominator * absX + 16.064177579207;
    denominator = denominator * absX + 86.7807322029461;
    denominator = denominator * absX + 296.564248779674;
    denominator = denominator * absX + 637.333633378831;
    denominator = denominator * absX + 793.826512519948;
    denominator = denominator * absX + 440.413735824752;

    upperTail = (density * numerator) / denominator;
  }
  return x > 0 ? 1 - upperTail : upperTail;
}

/**
 * Standard normal probability density function, φ(x) = exp(−x²/2)/√(2π).
 *
 * Exposed because the Halley refinement in {@link normalInv} needs it and
 * callers rendering a distribution plot would otherwise reimplement it.
 */
export function normalPdf(x: number): number {
  if (Number.isNaN(x)) return Number.NaN;
  return Math.exp((-x * x) / 2) / SQRT_2PI;
}

/**
 * Gauss error function, erf(x) = (2/√π) ∫₀ˣ e^(−t²) dt.
 *
 * Small |x| uses the Maclaurin series (A&S 7.1.5) to preserve relative
 * accuracy near zero; larger |x| uses the identity erf(x) = 1 − 2Φ(−|x|√2)
 * so it inherits the double precision of {@link normalCdf}.
 *
 * @param x - Any real number.
 * @returns erf(x) in (−1, 1). `NaN` in, `NaN` out.
 */
export function erf(x: number): number {
  if (Number.isNaN(x)) return Number.NaN;
  const absX = Math.abs(x);
  if (absX <= ERF_SERIES_CUTOFF) return erfSeries(x);
  if (!Number.isFinite(x)) return x > 0 ? 1 : -1;
  // 2Φ(−|x|√2) is the upper-tail branch of normalCdf, computed without cancellation.
  const tail = 2 * normalCdf(-absX * SQRT_2);
  const magnitude = 1 - tail;
  return x > 0 ? magnitude : -magnitude;
}

/**
 * Complementary error function, erfc(x) = 1 − erf(x).
 *
 * Computed directly from the normal tail for x > 0.5 rather than as
 * `1 − erf(x)`, so it keeps *relative* accuracy deep into the tail where
 * erf(x) has already rounded to 1. erfc(10) ≈ 2.09e-45 comes back with the
 * right exponent instead of 0.
 *
 * Relative accuracy degrades gently beyond x ≈ 5 (to ~1e-13) because the
 * argument scaling x·√2 is itself rounded and the tail is exponentially
 * sensitive to its argument.
 *
 * @param x - Any real number.
 * @returns erfc(x) in (0, 2). `NaN` in, `NaN` out.
 */
export function erfc(x: number): number {
  if (Number.isNaN(x)) return Number.NaN;
  if (x < 0) return 2 - erfc(-x);
  if (!Number.isFinite(x)) return 0;
  if (x <= ERF_SERIES_CUTOFF) return 1 - erfSeries(x);
  return 2 * normalCdf(-x * SQRT_2);
}

// --- Acklam's inverse normal CDF coefficients ---------------------------------
// Peter John Acklam, "An algorithm for computing the inverse normal cumulative
// distribution function" (2003/2010). Relative error of the raw rational
// approximation is below 1.15e-9 over the whole open interval.

const ACKLAM_A = [
  -3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2,
  -3.066479806614716e1, 2.506628277459239,
] as const;

const ACKLAM_B = [
  -5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1,
  -1.328068155288572e1,
] as const;

const ACKLAM_C = [
  -7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734,
  4.374664141464968, 2.938163982698783,
] as const;

const ACKLAM_D = [
  7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416,
] as const;

/** Break points between Acklam's lower-tail, central and upper-tail branches. */
const ACKLAM_P_LOW = 0.02425;
const ACKLAM_P_HIGH = 1 - ACKLAM_P_LOW;

function acklamLowerTail(p: number): number {
  const q = Math.sqrt(-2 * Math.log(p));
  return (
    ((((((ACKLAM_C[0] * q + ACKLAM_C[1]) * q + ACKLAM_C[2]) * q + ACKLAM_C[3]) * q + ACKLAM_C[4]) *
      q +
      ACKLAM_C[5]) /
      ((((ACKLAM_D[0] * q + ACKLAM_D[1]) * q + ACKLAM_D[2]) * q + ACKLAM_D[3]) * q + 1))
  );
}

function acklamCentral(p: number): number {
  const q = p - 0.5;
  const r = q * q;
  return (
    ((((((ACKLAM_A[0] * r + ACKLAM_A[1]) * r + ACKLAM_A[2]) * r + ACKLAM_A[3]) * r + ACKLAM_A[4]) *
      r +
      ACKLAM_A[5]) *
      q) /
    (((((ACKLAM_B[0] * r + ACKLAM_B[1]) * r + ACKLAM_B[2]) * r + ACKLAM_B[3]) * r + ACKLAM_B[4]) *
      r +
      1)
  );
}

/**
 * Inverse standard normal CDF, Φ⁻¹(p), a.k.a. the probit / quantile function.
 *
 * Two stages:
 *  1. Acklam's rational approximation (relative error < 1.15e-9), and
 *  2. a single Halley refinement against {@link normalCdf}:
 *
 *         e = Φ(x) − p
 *         u = e · √(2π) · exp(x²/2)
 *         x ← x − u / (1 + x·u/2)
 *
 *     Halley is cubically convergent, so one pass takes 1e-9 to full double
 *     precision. The refinement is skipped when it would produce a non-finite
 *     value — beyond about |x| = 37, `exp(x²/2)` overflows and the correction
 *     degenerates to NaN, in which case the unrefined Acklam estimate (still
 *     good to ~1e-9 relative) is returned instead.
 *
 * Documented boundary behaviour — this is the one function in the package
 * permitted to return non-finite values, because ±∞ are the mathematically
 * correct answers and callers pass literal 0/1 confidences by accident:
 *  - `p === 0` → `-Infinity`
 *  - `p === 1` → `+Infinity`
 *  - `p < 0`, `p > 1` or `NaN` → `NaN`
 *
 * Source: Peter John Acklam (2003), "An algorithm for computing the inverse
 * normal cumulative distribution function"; refinement step as described in
 * the same note.
 *
 * Round-trip note: `normalCdf(normalInv(p))` recovers `p` to ~1e-14 relative
 * across 300 orders of magnitude, but `normalInv(normalCdf(x))` only recovers
 * `x` well for `x ≲ 2`. That is a limit of the representation, not of either
 * algorithm: for larger x, Φ(x) is a double just under 1 and the tail mass it
 * encodes has already lost its relative resolution. Work in the lower tail.
 *
 * @param p - Probability, normally in the open interval (0, 1).
 * @returns The z such that Φ(z) = p.
 */
export function normalInv(p: number): number {
  if (Number.isNaN(p)) return Number.NaN;
  if (p < 0 || p > 1) return Number.NaN;
  if (p === 0) return Number.NEGATIVE_INFINITY;
  if (p === 1) return Number.POSITIVE_INFINITY;

  let x: number;
  if (p < ACKLAM_P_LOW) {
    x = acklamLowerTail(p);
  } else if (p <= ACKLAM_P_HIGH) {
    x = acklamCentral(p);
  } else {
    x = -acklamLowerTail(1 - p);
  }

  // One Halley step. `error` is the residual in probability space; `u` converts
  // it to distance space by dividing through by the density φ(x).
  const error = normalCdf(x) - p;
  const u = error * SQRT_2PI * Math.exp((x * x) / 2);
  const refined = x - u / (1 + (x * u) / 2);
  return Number.isFinite(refined) ? refined : x;
}

/** A deterministic uniform random source over [0, 1). */
export type Rng = () => number;

/**
 * mulberry32 — a seeded 32-bit PRNG.
 *
 * Chosen because it is 10 lines of integer arithmetic with no state beyond a
 * single uint32, which makes bootstrap reproducibility auditable by reading the
 * function. It passes gjrand's smallcrush-level tests; it is emphatically not a
 * cryptographic generator and must never be used for anything security-bearing.
 *
 * Determinism guarantees relied on elsewhere in this package:
 *  - the same `seed` always yields the same sequence, on every platform, forever;
 *  - all arithmetic is exact 32-bit integer arithmetic (`Math.imul`, `|0`,
 *    `>>>`), so there is no floating-point drift between engines;
 *  - the returned value is `uint32 / 2³²`, i.e. a multiple of 2⁻³² in [0, 1),
 *    and 1 is never returned.
 *
 * @param seed - Any number; coerced by `Math.trunc(seed) >>> 0`. Non-finite
 *   seeds coerce to 0 rather than throwing, so a malformed request degrades to
 *   a fixed, reproducible stream instead of an exception.
 * @returns A function producing the next uniform draw in [0, 1).
 *
 * Source: Tommy Ettinger, mulberry32 (public domain), as catalogued in
 * bryc/code "PRNGs in JavaScript".
 */
export function mulberry32(seed: number): Rng {
  let state = (Number.isFinite(seed) ? Math.trunc(seed) : 0) >>> 0;
  return function next(): number {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
