/**
 * Policy loading: one base file plus a one-key overlay.
 *
 * The demo's second act claims "same signal, same thresholds, one rule changed."
 * Two independent policy files would let an unrelated threshold drift and make
 * that claim false without anyone noticing. An overlay makes the difference
 * structurally impossible to get wrong — exactly one key can differ.
 *
 * The hash covers the MERGED result, so a receipt's policy_hash identifies the
 * rules that actually applied, not the file they came from.
 */
import { createHash } from 'node:crypto';
import type { Policy } from '../types.js';

export type PolicyName = 'strict' | 'permissive';

export const OVERLAYS: Record<PolicyName, Partial<Policy>> = {
  strict: { require_qualified: true },
  permissive: { require_qualified: false },
};

export function mergePolicy(base: Policy, name: PolicyName): Policy {
  return { ...base, ...OVERLAYS[name] };
}

/** Stable key order so the same rules always hash the same. */
export function canonicalize(policy: Policy): string {
  const keys = Object.keys(policy).sort() as (keyof Policy)[];
  return JSON.stringify(keys.map((k) => [k, policy[k]]));
}

export function policyHash(policy: Policy): string {
  return 'sha256:' + createHash('sha256').update(canonicalize(policy)).digest('hex');
}

/** Keys where two merged policies differ. Used by the drift test. */
export function policyDiff(a: Policy, b: Policy): (keyof Policy)[] {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]) as Set<keyof Policy>;
  return [...keys].filter((k) => a[k] !== b[k]).sort();
}
