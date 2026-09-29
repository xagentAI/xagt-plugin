/**
 * Chain verification — the endpoint that closes the demo.
 *
 * Recomputes every hash from genesis and reports the FIRST sequence number
 * where the stored record disagrees with the recomputed one. "Invalid" is not
 * a useful answer; "seq 17" is, because it points at the tampered record.
 *
 * Checks three independent things, because a chain can break three ways:
 *   1. sequence numbers are 1..N with no gaps or repeats  (a fork shows up here)
 *   2. each prev_hash equals the previous record's hash   (a splice shows up here)
 *   3. each hash equals sha256 of its own canonical body  (an edit shows up here)
 */
import { GENESIS, hashReceipt, type Receipt } from './schema.js';

export type VerifyResult =
  | { ok: true; length: number; head: string }
  | { ok: false; divergedAt: number; kind: DivergenceKind; detail: string; length: number };

export type DivergenceKind = 'sequence' | 'link' | 'content';

export function verifyChain(records: readonly Receipt[]): VerifyResult {
  const chain = [...records].sort((a, b) => a.seq - b.seq);
  if (chain.length === 0) return { ok: true, length: 0, head: GENESIS };

  let prevHash = GENESIS;
  for (let i = 0; i < chain.length; i++) {
    const r = chain[i]!;
    const expectedSeq = i + 1;

    if (r.seq !== expectedSeq) {
      return {
        ok: false,
        divergedAt: expectedSeq,
        kind: 'sequence',
        detail: `expected seq ${expectedSeq}, found ${r.seq}`,
        length: chain.length,
      };
    }

    if (r.prev_hash !== prevHash) {
      return {
        ok: false,
        divergedAt: r.seq,
        kind: 'link',
        detail: `prev_hash ${r.prev_hash} does not match the hash of seq ${r.seq - 1}`,
        length: chain.length,
      };
    }

    const { hash, ...unsealed } = r;
    const recomputed = hashReceipt(unsealed);
    if (recomputed !== hash) {
      return {
        ok: false,
        divergedAt: r.seq,
        kind: 'content',
        detail: `stored hash ${hash} but body hashes to ${recomputed}`,
        length: chain.length,
      };
    }

    prevHash = hash;
  }

  return { ok: true, length: chain.length, head: prevHash };
}
