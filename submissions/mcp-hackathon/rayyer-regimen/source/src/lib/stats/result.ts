/**
 * The result envelope every fallible public function in this package returns.
 *
 * Design rule for the whole statistics core: **never throw on user-shaped data
 * and never hand back `NaN` or `Infinity`.** A track record supplied by a user
 * is routinely too short, constant, or full of holes; those are ordinary
 * outcomes, not exceptions. Callers get a discriminated union so the UI can
 * render either a number with its audit trail or a specific, machine-readable
 * explanation of why no number exists.
 */

/**
 * Machine-readable failure codes.
 *
 * These are part of the public contract: UI copy, telemetry and tests key off
 * them, so treat renames as breaking changes.
 */
export type StatsReason =
  /** The input array had no elements at all. */
  | 'empty_input'
  /** Fewer observations than the estimator needs to be defined. */
  | 'insufficient_sample'
  /** A `NaN` or `±Infinity` reached a function that requires finite input. */
  | 'non_finite_input'
  /** Sample standard deviation is exactly zero, so a ratio to it is undefined. */
  | 'zero_variance'
  /** A variance-like term is non-positive, so its square root is undefined. */
  | 'undefined_variance'
  /** A denominator is zero or otherwise unusable. */
  | 'undefined_denominator'
  /** Equity is zero or negative, so a return/drawdown fraction is undefined. */
  | 'non_positive_equity'
  /** Two parallel arrays disagree on length. */
  | 'length_mismatch'
  /** A caller-supplied option is out of its documented domain. */
  | 'invalid_parameter'
  /** `SR̂ ≤ SR*`, so the track record can never clear the benchmark. */
  | 'benchmark_not_exceeded'
  /** The deflated Sharpe ratio needs at least two trials. */
  | 'insufficient_trials'
  /** A caller-supplied statistic returned null / non-finite where a value was required. */
  | 'undefined_statistic';

/** A computed value plus, by convention, the inputs it was computed from. */
export interface Success<T> {
  readonly ok: true;
  readonly value: T;
}

/**
 * No value exists. `value` is pinned to `null` so `result.value` is always
 * safe to read and is never `NaN`.
 */
export interface Failure {
  readonly ok: false;
  readonly value: null;
  readonly reason: StatsReason;
  /** Human-readable, safe to surface directly in a UI. Never contains user data verbatim. */
  readonly message: string;
}

/** Discriminated result: narrow on `.ok`. */
export type StatsResult<T> = Success<T> | Failure;

/** Wrap a computed value as a success. */
export function ok<T>(value: T): Success<T> {
  return { ok: true, value };
}

/** Build a failure carrying a machine-readable reason and human-readable message. */
export function fail(reason: StatsReason, message: string): Failure {
  return { ok: false, value: null, reason, message };
}

/** Type guard narrowing a {@link StatsResult} to its success branch. */
export function isOk<T>(result: StatsResult<T>): result is Success<T> {
  return result.ok;
}

/**
 * The value when the result succeeded, otherwise `null`.
 *
 * Convenience for call sites that only need the number and will render a
 * placeholder for the failure case.
 */
export function valueOrNull<T>(result: StatsResult<T>): T | null {
  return result.ok ? result.value : null;
}
