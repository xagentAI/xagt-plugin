'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { SCOPE_FREEZE_EVENT } from './scope-freeze';
import type { ScopeFreezeDetail } from './scope-freeze';
import styles from './ScopeReadout.module.css';

/**
 * The telemetry line on the glass.
 *
 * The values are rendered as real text on the server, so they are present for a screen
 * reader, for a crawler and with JavaScript off. On a client that allows motion the line
 * re-acquires — digits scramble and lock, left to right — once on arrival and again each
 * time the persistence is frozen, which is the moment the band the numbers describe is
 * being built on the glass behind them.
 */

export type ReadoutTone = 'lit' | 'warn' | 'flare' | 'plain';

export interface ReadoutField {
  readonly key: string;
  readonly value: string;
  readonly tone: ReadoutTone;
}

const GLYPHS = '0123456789+-.%';
const STABLE = new Set([' ', ',', '[', ']', '/', '(', ')', '−', '+']);
const RESOLVE_MS = 1100;

export interface ScopeStatusProps {
  readonly live: boolean;
  readonly children: string;
}

/** The status lamp and its one line. Magenta and beating when the sweep is live. */
export function ScopeStatus({ live, children }: ScopeStatusProps) {
  return (
    <p className={styles.eyebrow}>
      <span className={live ? styles.lamp : `${styles.lamp} ${styles.lampOff}`} aria-hidden="true" />
      {children}
    </p>
  );
}

export interface ScopeReadoutProps {
  readonly fields: readonly ReadoutField[];
}

export function ScopeReadout({ fields }: ScopeReadoutProps) {
  const [display, setDisplay] = useState<readonly string[]>(() => fields.map((field) => field.value));
  const [resolving, setResolving] = useState(false);
  const frameRef = useRef(0);

  const resolve = useCallback(() => {
    if (typeof window === 'undefined') return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    cancelAnimationFrame(frameRef.current);
    const startedAt = performance.now();
    setResolving(true);

    const step = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / RESOLVE_MS);
      setDisplay(
        fields.map((field, index) => {
          const local = Math.max(0, Math.min(1, (progress - index * 0.06) / 0.55));
          const locked = Math.floor(local * field.value.length);
          let out = '';
          for (let i = 0; i < field.value.length; i += 1) {
            const character = field.value[i] ?? '';
            out += i < locked || STABLE.has(character) ? character : (GLYPHS[(Math.random() * GLYPHS.length) | 0] ?? '0');
          }
          return out;
        }),
      );
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(step);
        return;
      }
      setDisplay(fields.map((field) => field.value));
      setResolving(false);
    };

    frameRef.current = requestAnimationFrame(step);
  }, [fields]);

  useEffect(() => {
    const timer = setTimeout(resolve, 400);
    const onFreeze = (event: Event) => {
      const detail = (event as CustomEvent<ScopeFreezeDetail>).detail;
      if (detail?.frozen) resolve();
    };
    window.addEventListener(SCOPE_FREEZE_EVENT, onFreeze);
    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(frameRef.current);
      window.removeEventListener(SCOPE_FREEZE_EVENT, onFreeze);
    };
  }, [resolve]);

  return (
    <p className={styles.telemetry}>
      {fields.map((field, index) => (
        <span key={field.key} className={styles.field}>
          {index > 0 ? (
            <span className={styles.sep} aria-hidden="true">
              ·
            </span>
          ) : null}
          <span className={styles.key}>{field.key} </span>
          <span className={resolving ? styles.scrambling : styles[field.tone]}>{display[index] ?? field.value}</span>
        </span>
      ))}
    </p>
  );
}

export interface ScopeUnavailableProps {
  readonly reason: string;
}

/**
 * What the glass says when the live analysis could not be reached. The page renders;
 * it just declines to invent the numbers it could not compute.
 */
export function ScopeUnavailable({ reason }: ScopeUnavailableProps) {
  return (
    <p className={styles.unavailable}>
      LIVE FIGURES UNAVAILABLE RIGHT NOW
      <span>{reason}</span>
    </p>
  );
}
