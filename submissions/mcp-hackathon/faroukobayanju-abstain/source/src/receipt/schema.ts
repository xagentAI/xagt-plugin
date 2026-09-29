/**
 * Receipt schema and hashing.
 *
 *   seq 1        seq 2        seq 3
 *   ┌──────┐     ┌──────┐     ┌──────┐
 *   │ prev ├────▶│ prev ├────▶│ prev │
 *   │ body │     │ body │     │ body │
 *   │ hash │     │ hash │     │ hash │
 *   └──────┘     └──────┘     └──────┘
 *
 * hash(n) = sha256(canonical({ ...body, seq, prev_hash }))
 * prev_hash(n) = hash(n-1), or GENESIS for the first record.
 *
 * Canonical form sorts object keys recursively, so two runs that produce the
 * same decision produce the same bytes and therefore the same hash. Without
 * that, key-insertion order alone would break verification.
 */
import { createHash } from 'node:crypto';
import type { CheckResult, Verdict } from '../types.js';

export const GENESIS = 'sha256:' + '0'.repeat(64);

export interface ReceiptBody {
  /** ISO-8601 UTC. */
  ts: string;
  signal_id: string;
  /** The resolved date #3 and #4 were fetched for. Makes the decision re-fetchable. */
  as_of: string;
  policy_hash: string;
  /** Digest of every Nexus payload consulted, so a reviewer can detect stale config. */
  inputs_digest: string;
  verdict: Verdict;
  checks: CheckResult[];
  reason?: string;
}

export interface Receipt extends ReceiptBody {
  seq: number;
  prev_hash: string;
  hash: string;
}

/** Recursively key-sorted JSON. Arrays keep their order; objects do not have one. */
export function canonical(value: unknown): string {
  return JSON.stringify(sortDeep(value));
}

function sortDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value === null || typeof value !== 'object') return value;
  const obj = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(obj).sort()) {
    if (obj[k] !== undefined) out[k] = sortDeep(obj[k]);
  }
  return out;
}

export function sha256(input: string): string {
  return 'sha256:' + createHash('sha256').update(input).digest('hex');
}

/** The hash covers everything except the hash field itself. */
export function hashReceipt(r: Omit<Receipt, 'hash'>): string {
  return sha256(canonical(r));
}

export function sealReceipt(body: ReceiptBody, seq: number, prevHash: string): Receipt {
  const unsealed = { ...body, seq, prev_hash: prevHash };
  return { ...unsealed, hash: hashReceipt(unsealed) };
}

/** Digest of the raw Nexus payloads an evaluation consulted. */
export function inputsDigest(payloads: Record<string, unknown>): string {
  return sha256(canonical(payloads));
}
