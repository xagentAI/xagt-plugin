'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import type { DemoEquityPoint } from '@/lib/demo-curve';
import { emitScopeFreeze } from './scope-freeze';
import styles from './PersistenceScope.module.css';

/**
 * The persistence-mode scope.
 *
 * Every trace on the glass is the supplied track record with its periods drawn again at
 * random. Two thousand of those resampled paths are laid down with additive blending at
 * very low per-path alpha, so the confidence band is never painted as a translucent
 * ribbon — it emerges as glow density where paths pile up, and stays genuinely thin
 * where few paths went. Behind them sit four shaded market-regime bands, so the curve is
 * read against its context without a separate legend.
 *
 * Hold the pointer down, or hold Space on the freeze control, and the phosphor decay
 * stops: the paths keep accumulating while nothing fades, and the interval builds itself
 * under your finger. `prefers-reduced-motion` skips the sweep and renders one finished
 * static frame instead.
 */

const PATHS = 2000;
const SWEEP_MS = 1700;

/** Deterministic, so the same curve always produces the same glass. */
function mulberry32(seed: number): () => number {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const read = (buffer: Float32Array, index: number): number => buffer[index] ?? 0;

interface RegimeBand {
  readonly from: number;
  readonly to: number;
  readonly rgb: string;
}

/** The regime axes, in the hue each one owns across the whole product. */
const REGIME_BANDS: readonly RegimeBand[] = [
  { from: 0.0, to: 0.19, rgb: '255,179,64' }, // p3-amber — volatility
  { from: 0.27, to: 0.42, rgb: '255,95,210' }, // ion-magenta — funding
  { from: 0.52, to: 0.71, rgb: '95,216,255' }, // sky-cyan — open interest
  { from: 0.82, to: 1.0, rgb: '255,138,61' }, // sodium — fear & greed
];

interface Geometry {
  readonly n: number;
  readonly actual: Float32Array;
  readonly paths: Float32Array;
  readonly low: number;
  readonly high: number;
}

/** Per-period simple returns, then the observed cumulative path and its 2,000 resamples. */
function buildGeometry(points: ReadonlyArray<DemoEquityPoint>): Geometry {
  const returns: number[] = [];
  for (let i = 1; i < points.length; i += 1) {
    const previous = points[i - 1];
    const current = points[i];
    if (!previous || !current || previous.equity <= 0) continue;
    returns.push(current.equity / previous.equity - 1);
  }

  const n = Math.max(1, returns.length);
  const actual = new Float32Array(n + 1);
  for (let i = 0; i < returns.length; i += 1) {
    actual[i + 1] = read(actual, i) + (returns[i] ?? 0);
  }

  const random = mulberry32(0x5eed1234);
  const paths = new Float32Array(PATHS * (n + 1));
  let low = Infinity;
  let high = -Infinity;

  for (let p = 0; p < PATHS; p += 1) {
    const offset = p * (n + 1);
    let cumulative = 0;
    for (let i = 0; i < n; i += 1) {
      cumulative += returns[(random() * returns.length) | 0] ?? 0;
      paths[offset + i + 1] = cumulative;
      if (cumulative < low) low = cumulative;
      if (cumulative > high) high = cumulative;
    }
  }

  for (let i = 0; i <= n; i += 1) {
    const value = read(actual, i);
    if (value < low) low = value;
    if (value > high) high = value;
  }

  if (!Number.isFinite(low) || !Number.isFinite(high) || high === low) {
    low = -1;
    high = 1;
  }
  const pad = (high - low) * 0.16;
  return { n, actual, paths, low: low - pad, high: high + pad };
}

export interface PersistenceScopeProps {
  readonly points: ReadonlyArray<DemoEquityPoint>;
  /** The hero content that sits on the glass. */
  readonly children: ReactNode;
}

export function PersistenceScope({ points, children }: PersistenceScopeProps) {
  const screenRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frozenRef = useRef(false);
  const [frozen, setFrozen] = useState(false);

  const setFreeze = useCallback((next: boolean) => {
    if (frozenRef.current === next) return;
    frozenRef.current = next;
    setFrozen(next);
    emitScopeFreeze(next);
  }, []);

  // A press that ends outside the glass, or a window that loses focus, must still release.
  useEffect(() => {
    if (!frozen) return;
    const release = () => setFreeze(false);
    window.addEventListener('pointerup', release);
    window.addEventListener('blur', release);
    return () => {
      window.removeEventListener('pointerup', release);
      window.removeEventListener('blur', release);
    };
  }, [frozen, setFreeze]);

  useEffect(() => {
    const screen = screenRef.current;
    const canvas = canvasRef.current;
    if (!screen || !canvas) return;

    const context = canvas.getContext('2d');
    if (!context) return;

    const geometry = buildGeometry(points);
    const { n, actual, paths } = geometry;

    // The phosphor buffer, plus two downsampled copies used as a cheap two-pass bloom.
    const phosphor = document.createElement('canvas');
    const phosphorCtx = phosphor.getContext('2d');
    const bloomA = document.createElement('canvas');
    const bloomACtx = bloomA.getContext('2d');
    const bloomB = document.createElement('canvas');
    const bloomBCtx = bloomB.getContext('2d');
    if (!phosphorCtx || !bloomACtx || !bloomBCtx) return;

    let width = 0;
    let height = 0;
    let dpr = 1;
    let frame = 0;
    let started = 0;
    let previousIndex = 0;
    let resizeTimer: ReturnType<typeof setTimeout> | undefined;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

    const xOf = (i: number) => (i / n) * width;
    const yOf = (value: number) => height - ((value - geometry.low) / (geometry.high - geometry.low)) * height;

    function measure() {
      const rect = screen!.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      width = Math.max(320, Math.round(rect.width * dpr));
      height = Math.max(240, Math.round(rect.height * dpr));
      canvas!.width = width;
      canvas!.height = height;
      phosphor.width = width;
      phosphor.height = height;
      bloomA.width = Math.max(2, width >> 2);
      bloomA.height = Math.max(2, height >> 2);
      bloomB.width = Math.max(2, width >> 4);
      bloomB.height = Math.max(2, height >> 4);
      phosphorCtx!.clearRect(0, 0, width, height);
    }

    /** Lay down segment [from, to] of every resample, additively. */
    function deposit(from: number, to: number, alpha: number) {
      if (to <= from) return;
      const ctx = phosphorCtx!;
      ctx.globalCompositeOperation = 'lighter';
      ctx.strokeStyle = `rgba(87,242,168,${alpha})`;
      ctx.lineWidth = Math.max(1, dpr * 0.9);
      ctx.beginPath();
      for (let p = 0; p < PATHS; p += 1) {
        const offset = p * (n + 1);
        ctx.moveTo(xOf(from), yOf(read(paths, offset + from)));
        for (let i = from + 1; i <= to; i += 1) ctx.lineTo(xOf(i), yOf(read(paths, offset + i)));
      }
      ctx.stroke();
    }

    function decay(amount: number) {
      const ctx = phosphorCtx!;
      ctx.globalCompositeOperation = 'destination-out';
      ctx.fillStyle = `rgba(0,0,0,${amount})`;
      ctx.fillRect(0, 0, width, height);
      ctx.globalCompositeOperation = 'lighter';
    }

    function drawGraticule() {
      const ctx = context!;
      ctx.save();
      ctx.strokeStyle = 'rgba(71,96,122,.35)';
      ctx.lineWidth = 1;
      for (let i = 1; i < 10; i += 1) {
        const x = Math.round((width * i) / 10) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let j = 1; j < 8; j += 1) {
        const y = Math.round((height * j) / 8) + 0.5;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }
      // The break-even line, dashed in alert-flare: the level the interval still spans.
      const zero = Math.round(yOf(0)) + 0.5;
      ctx.strokeStyle = 'rgba(109,136,163,.5)';
      ctx.lineWidth = Math.max(1, dpr);
      ctx.beginPath();
      ctx.moveTo(0, zero);
      ctx.lineTo(width, zero);
      ctx.stroke();
      ctx.setLineDash([dpr * 2, dpr * 5]);
      ctx.strokeStyle = 'rgba(255,98,71,.45)';
      ctx.beginPath();
      ctx.moveTo(0, zero);
      ctx.lineTo(width, zero);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }

    function drawRegimes() {
      const ctx = context!;
      for (const band of REGIME_BANDS) {
        ctx.fillStyle = `rgba(${band.rgb},.06)`;
        ctx.fillRect(band.from * width, 0, (band.to - band.from) * width, height);
      }
    }

    function drawActual() {
      const ctx = context!;
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(xOf(0), yOf(read(actual, 0)));
      for (let i = 1; i <= n; i += 1) ctx.lineTo(xOf(i), yOf(read(actual, i)));
      ctx.strokeStyle = 'rgba(87,242,168,.28)';
      ctx.lineWidth = Math.max(5, dpr * 5);
      ctx.stroke();
      ctx.strokeStyle = 'rgba(212,255,234,.92)';
      ctx.lineWidth = Math.max(1.4, dpr * 1.4);
      ctx.stroke();
      ctx.restore();
    }

    function drawBeam(x: number) {
      const ctx = context!;
      const gradient = ctx.createLinearGradient(x - width * 0.05, 0, x + width * 0.012, 0);
      gradient.addColorStop(0, 'rgba(87,242,168,0)');
      gradient.addColorStop(0.82, 'rgba(87,242,168,.10)');
      gradient.addColorStop(1, 'rgba(200,255,228,.30)');
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.fillStyle = gradient;
      ctx.fillRect(x - width * 0.05, 0, width * 0.062, height);
      ctx.restore();
    }

    function composite(beamX: number, withBeam: boolean) {
      const ctx = context!;
      ctx.clearRect(0, 0, width, height);
      drawRegimes();
      drawGraticule();
      bloomACtx!.clearRect(0, 0, bloomA.width, bloomA.height);
      bloomACtx!.drawImage(phosphor, 0, 0, bloomA.width, bloomA.height);
      bloomBCtx!.clearRect(0, 0, bloomB.width, bloomB.height);
      bloomBCtx!.drawImage(phosphor, 0, 0, bloomB.width, bloomB.height);
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = 0.85;
      ctx.drawImage(bloomB, 0, 0, width, height);
      ctx.globalAlpha = 0.7;
      ctx.drawImage(bloomA, 0, 0, width, height);
      ctx.globalAlpha = 1;
      ctx.drawImage(phosphor, 0, 0, width, height);
      ctx.restore();
      drawActual();
      if (withBeam) drawBeam(beamX);
    }

    function tick(now: number) {
      if (!started) started = now;
      const phase = ((now - started) % SWEEP_MS) / SWEEP_MS;
      const index = Math.floor(phase * n);
      if (index < previousIndex) previousIndex = 0;
      if (!frozenRef.current) decay(0.015);
      deposit(previousIndex, index, frozenRef.current ? 0.020 : 0.013);
      previousIndex = index;
      composite(phase * width, !frozenRef.current);
      frame = requestAnimationFrame(tick);
    }

    /** Reduced motion still gets a finished composition, never an empty frame. */
    function staticFrame() {
      phosphorCtx!.clearRect(0, 0, width, height);
      deposit(0, n, 0.014);
      deposit(0, n, 0.014);
      deposit(0, n, 0.012);
      composite(0, false);
    }

    function start() {
      if (frame) cancelAnimationFrame(frame);
      measure();
      if (reduced.matches) {
        staticFrame();
        return;
      }
      started = 0;
      previousIndex = 0;
      phosphorCtx!.clearRect(0, 0, width, height);
      frame = requestAnimationFrame(tick);
    }

    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(start, 180);
    };

    // A hidden tab gets no animation frames, so the sweep is stopped rather than left
    // hanging mid-cycle, and restarted from a clean buffer when the glass is seen again.
    const onVisibility = () => {
      if (document.hidden) {
        if (frame) cancelAnimationFrame(frame);
        frame = 0;
        return;
      }
      start();
    };

    start();
    window.addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', onVisibility);
    reduced.addEventListener('change', start);

    return () => {
      if (frame) cancelAnimationFrame(frame);
      clearTimeout(resizeTimer);
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibility);
      reduced.removeEventListener('change', start);
    };
  }, [points]);

  const onScreenPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.target instanceof Element && event.target.closest('a,button,textarea')) return;
    setFreeze(true);
  };

  const onHoldKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== ' ' && event.key !== 'Enter') return;
    event.preventDefault();
    setFreeze(true);
  };

  const onHoldKeyUp = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== ' ' && event.key !== 'Enter') return;
    event.preventDefault();
    setFreeze(false);
  };

  return (
    <div className={styles.crt}>
      <div
        ref={screenRef}
        className={styles.screen}
        onPointerDown={onScreenPointerDown}
        onPointerUp={() => setFreeze(false)}
        onPointerCancel={() => setFreeze(false)}
        onPointerLeave={() => setFreeze(false)}
      >
        <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />
        <div className={styles.scrim} aria-hidden="true" />
        <div className={styles.scan} aria-hidden="true" />
        <div className={styles.vig} aria-hidden="true" />

        <div className={styles.stack}>{children}</div>

        <button
          type="button"
          className={styles.holdButton}
          aria-pressed={frozen}
          onPointerDown={() => setFreeze(true)}
          onPointerUp={() => setFreeze(false)}
          onPointerLeave={() => setFreeze(false)}
          onKeyDown={onHoldKeyDown}
          onKeyUp={onHoldKeyUp}
          onBlur={() => setFreeze(false)}
        >
          <span>Hold</span>
          <b>press &amp; hold / space</b>
          <span className={styles.holdWhy}>{frozen ? 'decay stopped' : 'to freeze the persistence'}</span>
        </button>
      </div>
    </div>
  );
}
