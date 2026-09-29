/**
 * Special functions.
 *
 * Reference values are `scipy.stats.norm` / CPython `math.erf` output at full
 * double precision. scipy's `ndtr` is an independent implementation (Cephes),
 * so agreeing with it to 1e-14 is genuine cross-validation rather than a
 * tautology against our own code.
 */

import { describe, expect, it } from 'vitest';

import { erf, erfc, mulberry32, normalCdf, normalInv, normalPdf } from '../../src/lib/stats/numeric';

/** Assert |got − want| ≤ tol · |want| (pure relative error; `want` must be non-zero). */
function expectRelativeClose(got: number, want: number, tol: number): void {
  const rel = Math.abs(got - want) / Math.abs(want);
  expect(rel, `got=${got} want=${want} rel=${rel}`).toBeLessThanOrEqual(tol);
}

describe('normalCdf', () => {
  // Reference: scipy.stats.norm.cdf, printed with repr() at full precision.
  const reference: ReadonlyArray<readonly [number, number]> = [
    [0, 0.5],
    [0.5, 0.6914624612740131],
    [1, 0.8413447460685429],
    [-1, 0.15865525393145707],
    [1.96, 0.9750021048517795],
    [2, 0.9772498680518208],
    [-2, 0.0227501319481792],
    [3, 0.9986501019683699],
    [-3, 0.001349898031630093],
    [5, 0.9999997133484281],
    [-7.5, 3.1908916729108844e-14],
  ];

  it.each(reference)('matches the scipy reference at x = %s', (x, want) => {
    expectRelativeClose(normalCdf(x), want, 1e-14);
  });

  // The whole point of not using Abramowitz & Stegun 7.1.26: that fit is good
  // to ~7.5e-8 ABSOLUTE, so at x = -8 it returns something around 1e-8 instead
  // of 6.2e-16 — an eight-order-of-magnitude error in exactly the region where
  // the deflated Sharpe ratio is evaluated.
  const deepTail: ReadonlyArray<readonly [number, number]> = [
    [-5, 2.8665157187919333e-7],
    [-6, 9.865876450376948e-10],
    [-8, 6.22096057427174e-16],
    [-10, 7.61985302416047e-24],
    [-20, 2.7536241186061556e-89],
    [-37, 5.7255712225239266e-300],
  ];

  // 5e-13 rather than 1e-14 because the reference itself is a double: at
  // Phi(-37) ~ 5.7e-300 both implementations are accumulating their own
  // rounding through an exp() of -684 and a continued fraction, and scipy's
  // Cephes routine is not exact either.
  it.each(deepTail)('keeps RELATIVE accuracy in the deep tail at x = %s', (x, want) => {
    expectRelativeClose(normalCdf(x), want, 5e-13);
  });

  it('is exactly 0.5 at the origin', () => {
    expect(normalCdf(0)).toBe(0.5);
  });

  it('is symmetric: Phi(-x) = 1 - Phi(x)', () => {
    for (const x of [0.1, 0.7, 1.3, 2.2, 2.9]) {
      expectRelativeClose(normalCdf(-x), 1 - normalCdf(x), 1e-14);
    }
  });

  it('is monotonically non-decreasing across the crossover between its two branches', () => {
    // The implementation switches from Hart's rational fit to the Mills-ratio
    // continued fraction at |x| = 3; a discontinuity there would be invisible
    // in spot checks but would break any root-finding built on top.
    let previous = normalCdf(-4);
    for (let x = -4; x <= 4; x += 0.001) {
      const current = normalCdf(x);
      expect(current).toBeGreaterThanOrEqual(previous);
      previous = current;
    }
  });

  it('has no visible seam at the |x| = 3 branch crossover', () => {
    // A jump between the rational and continued-fraction branches would show up
    // as a wrong DERIVATIVE across the seam, so straddle it with a central
    // difference and check it still reproduces phi(3). Comparing two nearby
    // values directly would prove nothing: Phi genuinely changes by ~3.3e-10
    // relative per 1e-10 of x at this point.
    const h = 1e-5;
    const slope = (normalCdf(-3 + h) - normalCdf(-3 - h)) / (2 * h);
    expectRelativeClose(slope, normalPdf(3), 1e-9);
  });

  it('saturates to 0 and 1 beyond the representable tail', () => {
    expect(normalCdf(-40)).toBe(0);
    expect(normalCdf(40)).toBe(1);
    expect(normalCdf(Number.NEGATIVE_INFINITY)).toBe(0);
    expect(normalCdf(Number.POSITIVE_INFINITY)).toBe(1);
  });

  it('propagates NaN', () => {
    expect(Number.isNaN(normalCdf(Number.NaN))).toBe(true);
  });

  it('never leaves [0, 1]', () => {
    for (let x = -45; x <= 45; x += 0.37) {
      const p = normalCdf(x);
      expect(p).toBeGreaterThanOrEqual(0);
      expect(p).toBeLessThanOrEqual(1);
    }
  });
});

describe('normalPdf', () => {
  it('matches known density values', () => {
    // phi(0) = 1/sqrt(2*pi) = 0.3989422804014327
    expectRelativeClose(normalPdf(0), 0.3989422804014327, 1e-15);
    // phi(1) = exp(-0.5)/sqrt(2*pi) = 0.24197072451914337
    expectRelativeClose(normalPdf(1), 0.24197072451914337, 1e-15);
    expectRelativeClose(normalPdf(-1), 0.24197072451914337, 1e-15);
  });

  it('propagates NaN', () => {
    expect(Number.isNaN(normalPdf(Number.NaN))).toBe(true);
  });
});

describe('normalInv', () => {
  // Reference: scipy.stats.norm.ppf.
  const reference: ReadonlyArray<readonly [number, number]> = [
    [0.5, 0],
    [0.975, 1.959963984540054],
    [0.95, 1.6448536269514722],
    [0.99, 2.3263478740408408],
    [0.999, 3.090232306167813],
    [0.025, -1.9599639845400545],
    [0.05, -1.6448536269514729],
    [0.01, -2.3263478740408408],
    [0.001, -3.090232306167813],
    [0.2, -0.8416212335729142],
    [0.8, 0.8416212335729143],
  ];

  it.each(reference)('matches the scipy reference at p = %s', (p, want) => {
    if (want === 0) {
      expect(Math.abs(normalInv(p))).toBeLessThan(1e-15);
      return;
    }
    expectRelativeClose(normalInv(p), want, 1e-14);
  });

  it('stays accurate at Acklam branch boundaries', () => {
    // p_low = 0.02425 is where the lower-tail branch hands over to the central
    // one; a coefficient typo shows up here before anywhere else.
    expectRelativeClose(normalInv(0.02425), -1.972961051311885, 1e-14);
    expectRelativeClose(normalInv(1 - 0.02425), 1.972961051311885, 1e-14);
  });

  it('resolves the far tail, where the raw Acklam fit alone would not', () => {
    expectRelativeClose(normalInv(1e-10), -6.361340902404056, 1e-13);
    expectRelativeClose(normalInv(1e-100), -21.273453560965322, 1e-13);
  });

  it('survives the smallest representable probability without NaN', () => {
    // exp(x^2/2) overflows past |x| ~ 37, so the Halley correction degenerates;
    // the implementation must fall back to the unrefined estimate rather than
    // return NaN.
    const z = normalInv(Number.MIN_VALUE);
    expect(Number.isFinite(z)).toBe(true);
    expect(z).toBeLessThan(-38);
    expect(z).toBeGreaterThan(-39);
  });

  it('returns +/-Infinity exactly at the closed endpoints', () => {
    expect(normalInv(0)).toBe(Number.NEGATIVE_INFINITY);
    expect(normalInv(1)).toBe(Number.POSITIVE_INFINITY);
  });

  it('returns NaN outside [0, 1] and for NaN input', () => {
    expect(Number.isNaN(normalInv(-0.001))).toBe(true);
    expect(Number.isNaN(normalInv(1.001))).toBe(true);
    expect(Number.isNaN(normalInv(-1))).toBe(true);
    expect(Number.isNaN(normalInv(2))).toBe(true);
    expect(Number.isNaN(normalInv(Number.NaN))).toBe(true);
  });

  it('is antisymmetric: Phi^-1(p) = -Phi^-1(1 - p)', () => {
    for (const p of [0.001, 0.01, 0.0242, 0.1, 0.3, 0.49]) {
      expectRelativeClose(normalInv(p), -normalInv(1 - p), 1e-12);
    }
  });

  it('is strictly increasing in p', () => {
    let previous = normalInv(1e-6);
    for (let p = 1e-6 + 1e-3; p < 1; p += 1e-3) {
      const current = normalInv(p);
      expect(current).toBeGreaterThan(previous);
      previous = current;
    }
  });
});

describe('normalCdf / normalInv round trip', () => {
  it('recovers x from Phi(x) to ~1e-14 wherever the round trip is well conditioned', () => {
    // Restricted to x <= 2 on the upper side ON PURPOSE. For larger x, Phi(x)
    // is stored as 1 - eps and the tail mass loses relative resolution in the
    // double itself: at x = 6 the tail is 1e-9 and a double near 1 resolves
    // only ~1e-16 absolute, so the best achievable round trip is ~1e-7. That is
    // a limit of the representation, not of the algorithm, which is why the
    // *probability-space* round trip below is the strict one.
    let worst = 0;
    for (let x = -8; x <= 2; x += 0.0017) {
      worst = Math.max(worst, Math.abs(normalInv(normalCdf(x)) - x));
    }
    expect(worst).toBeLessThan(1e-14);
  });

  it('degrades gracefully, not catastrophically, on the saturating upper side', () => {
    for (let x = 2; x <= 6; x += 0.25) {
      expect(Math.abs(normalInv(normalCdf(x)) - x)).toBeLessThan(1e-7);
    }
  });

  it('recovers p from Phi^-1(p) to ~1e-14 relative across the body', () => {
    let worst = 0;
    for (let k = 1; k < 1000; k += 1) {
      const p = k / 1000;
      worst = Math.max(worst, Math.abs(normalCdf(normalInv(p)) - p) / p);
    }
    expect(worst).toBeLessThan(1e-14);
  });

  it('recovers p from Phi^-1(p) across 300 orders of magnitude in the tail', () => {
    let worst = 0;
    for (let e = -300; e <= -1; e += 1) {
      const p = 10 ** e;
      worst = Math.max(worst, Math.abs(normalCdf(normalInv(p)) - p) / p);
    }
    expect(worst).toBeLessThan(1e-12);
  });
});

describe('erf', () => {
  // Reference: CPython math.erf (which is its own C implementation).
  const reference: ReadonlyArray<readonly [number, number]> = [
    [0.1, 0.1124629160182849],
    [0.5, 0.5204998778130465],
    [1, 0.8427007929497149],
    [2, 0.9953222650189527],
    [3, 0.9999779095030014],
    [-1, -0.8427007929497149],
  ];

  it.each(reference)('matches the reference at x = %s', (x, want) => {
    expectRelativeClose(erf(x), want, 1e-15);
  });

  it('is exactly 0 at the origin', () => {
    expect(erf(0)).toBe(0);
  });

  it('keeps relative accuracy for tiny x, where 2*Phi(x*sqrt2) - 1 would not', () => {
    // erf(1e-8) ~ 2e-8/sqrt(pi). Routing this through the normal CDF would
    // subtract 0.5 from 0.5 and lose every significant digit.
    expectRelativeClose(erf(1e-8), 1.1283791670955126e-8, 1e-15);
    expectRelativeClose(erf(1e-15), 1.1283791670955126e-15, 1e-14);
  });

  it('is odd: erf(-x) = -erf(x)', () => {
    for (const x of [0.05, 0.3, 0.9, 2.5, 4]) {
      expect(erf(-x)).toBe(-erf(x));
    }
  });

  it('saturates at +/-1 for infinite input', () => {
    expect(erf(Number.POSITIVE_INFINITY)).toBe(1);
    expect(erf(Number.NEGATIVE_INFINITY)).toBe(-1);
  });

  it('propagates NaN', () => {
    expect(Number.isNaN(erf(Number.NaN))).toBe(true);
  });
});

describe('erfc', () => {
  const reference: ReadonlyArray<readonly [number, number]> = [
    [0.5, 0.4795001221869534],
    [1, 0.1572992070502851],
    [-1, 1.842700792949715],
  ];

  it.each(reference)('matches the reference at x = %s', (x, want) => {
    expectRelativeClose(erfc(x), want, 1e-15);
  });

  it('keeps relative accuracy deep in the tail, where 1 - erf(x) is exactly 0', () => {
    expectRelativeClose(erfc(3), 2.209049699858544e-5, 1e-14);
    expectRelativeClose(erfc(5), 1.5374597944280351e-12, 1e-13);
    expectRelativeClose(erfc(10), 2.088487583762545e-45, 1e-13);
  });

  it('satisfies erfc(x) = 1 - erf(x) in the body', () => {
    for (const x of [0.05, 0.25, 0.5, 0.75, 1.2]) {
      expectRelativeClose(erfc(x), 1 - erf(x), 1e-14);
    }
  });

  it('satisfies erfc(-x) = 2 - erfc(x)', () => {
    for (const x of [0.3, 1, 2.5]) {
      expectRelativeClose(erfc(-x), 2 - erfc(x), 1e-15);
    }
  });

  it('saturates at 0 and 2 for infinite input', () => {
    expect(erfc(Number.POSITIVE_INFINITY)).toBe(0);
    expect(erfc(Number.NEGATIVE_INFINITY)).toBe(2);
  });

  it('propagates NaN', () => {
    expect(Number.isNaN(erfc(Number.NaN))).toBe(true);
  });
});

describe('mulberry32', () => {
  it('is deterministic: the same seed replays the same stream', () => {
    const a = mulberry32(42);
    const b = mulberry32(42);
    const first = Array.from({ length: 64 }, () => a());
    const second = Array.from({ length: 64 }, () => b());
    expect(first).toEqual(second);
  });

  it('produces different streams for different seeds', () => {
    const a = Array.from({ length: 64 }, mulberry32(1));
    const b = Array.from({ length: 64 }, mulberry32(2));
    expect(a).not.toEqual(b);
  });

  it('stays inside [0, 1)', () => {
    const rng = mulberry32(12345);
    for (let i = 0; i < 20_000; i += 1) {
      const u = rng();
      expect(u).toBeGreaterThanOrEqual(0);
      expect(u).toBeLessThan(1);
    }
  });

  it('is roughly uniform: mean ~ 0.5 and every decile is populated', () => {
    const rng = mulberry32(777);
    const deciles = new Array<number>(10).fill(0);
    let total = 0;
    const n = 100_000;
    for (let i = 0; i < n; i += 1) {
      const u = rng();
      total += u;
      const bin = Math.min(9, Math.floor(u * 10));
      deciles[bin] = (deciles[bin] ?? 0) + 1;
    }
    expect(Math.abs(total / n - 0.5)).toBeLessThan(0.01);
    for (const count of deciles) {
      expect(count).toBeGreaterThan(n / 10 - 1500);
      expect(count).toBeLessThan(n / 10 + 1500);
    }
  });

  it('coerces fractional and negative seeds without throwing', () => {
    expect(() => mulberry32(-1)()).not.toThrow();
    expect(() => mulberry32(3.7)()).not.toThrow();
    expect(mulberry32(3.7)()).toBe(mulberry32(3)());
  });

  it('degrades a non-finite seed to a fixed reproducible stream rather than throwing', () => {
    expect(mulberry32(Number.NaN)()).toBe(mulberry32(0)());
    expect(mulberry32(Number.POSITIVE_INFINITY)()).toBe(mulberry32(0)());
  });

  it('does not repeat itself over a long run', () => {
    const rng = mulberry32(99);
    const seen = new Set<number>();
    for (let i = 0; i < 50_000; i += 1) seen.add(rng());
    // Birthday collisions in a 2^32 space over 50k draws are expected to be
    // fewer than a handful; a broken generator would collapse far harder.
    expect(seen.size).toBeGreaterThan(49_990);
  });
});
