import { describe, expect, it, vi } from 'vitest';
import { MemoryStore } from '../src/store/memory.js';
import { ChainContentionError, appendReceipt } from '../src/store/types.js';
import { GENESIS, canonical, sealReceipt, type ReceiptBody } from '../src/receipt/schema.js';
import { verifyChain } from '../src/receipt/verify.js';
import { RedisStore, CAS_APPEND_LUA, RATE_LIMIT_LUA, type RedisLike } from '../src/store/redis.js';
import { StoreUnavailableError } from '../src/store/types.js';

const body = (n: number): ReceiptBody => ({
  ts: `2026-09-18T00:00:0${n % 10}Z`,
  signal_id: `sig_${n}`,
  as_of: '2026-09-17',
  policy_hash: 'sha256:policy',
  inputs_digest: 'sha256:inputs',
  verdict: n % 2 === 0 ? 'ABSTAIN' : 'EXECUTE',
  checks: [],
});

async function seed(store: MemoryStore, n: number) {
  for (let i = 1; i <= n; i++) await appendReceipt(store, body(i));
}

describe('receipt chain', () => {
  it('links genesis, then each record to its predecessor', async () => {
    const store = new MemoryStore();
    await seed(store, 3);
    const all = await store.all();
    expect(all.map((r) => r.seq)).toEqual([1, 2, 3]);
    expect(all[0]!.prev_hash).toBe(GENESIS);
    expect(all[1]!.prev_hash).toBe(all[0]!.hash);
    expect(all[2]!.prev_hash).toBe(all[1]!.hash);
  });

  it('verifies a clean chain', async () => {
    const store = new MemoryStore();
    await seed(store, 40);
    const res = verifyChain(await store.all());
    expect(res.ok).toBe(true);
    if (res.ok) expect(res.length).toBe(40);
  });

  it('verifies an empty chain', () => {
    expect(verifyChain([])).toEqual({ ok: true, length: 0, head: GENESIS });
  });
});

describe('concurrency — the fork this design exists to prevent', () => {
  it('two concurrent appends produce seq 1 and 2, and verify still passes', async () => {
    // Suspend the first writer between its head read and its commit, which is
    // the exact interleave that forks a naive chain.
    let releaseFirst: (() => void) | undefined;
    let suspended = false;
    const store = new MemoryStore(async () => {
      if (suspended) return;
      suspended = true;
      await new Promise<void>((resolve) => {
        releaseFirst = resolve;
      });
    });

    const a = appendReceipt(store, body(1));
    await new Promise((r) => setImmediate(r)); // let A reach the suspension point
    const b = appendReceipt(store, body(2));
    await new Promise((r) => setImmediate(r)); // let B read the same head
    releaseFirst?.();

    const [ra, rb] = await Promise.all([a, b]);

    expect(new Set([ra.seq, rb.seq])).toEqual(new Set([1, 2]));
    const all = await store.all();
    expect(all).toHaveLength(2);
    expect(verifyChain(all).ok).toBe(true);
  });

  it('ten concurrent appends yield ten unique sequence numbers', async () => {
    const store = new MemoryStore();
    const results = await Promise.all(
      Array.from({ length: 10 }, (_, i) => appendReceipt(store, body(i + 1), 50)),
    );
    expect(new Set(results.map((r) => r.seq)).size).toBe(10);
    expect(verifyChain(await store.all()).ok).toBe(true);
  });

  it('gives up with a named error rather than writing an unlinked record', async () => {
    // A store whose head always moves: every CAS loses.
    const alwaysContended = new MemoryStore();
    const hostile = {
      head: () => alwaysContended.head(),
      compareAndAppend: async () => false,
      get: (s: number) => alwaysContended.get(s),
      all: () => alwaysContended.all(),
      allowWrite: async () => true,
    };
    await expect(appendReceipt(hostile, body(1), 3)).rejects.toThrow(ChainContentionError);
    expect(await alwaysContended.all()).toHaveLength(0);
  });

  it('re-checks duplicate state after CAS contention before authorizing', async () => {
    let releaseFirst: (() => void) | undefined;
    let suspended = false;
    const store = new MemoryStore(async () => {
      if (suspended) return;
      suspended = true;
      await new Promise<void>((resolve) => { releaseFirst = resolve; });
    });
    const sameSignal: ReceiptBody = {
      ...body(1),
      signal_id: 'same',
      verdict: 'EXECUTE',
      checks: [{
        id: 'DUPLICATE', verdict: 'PASS', observed: 'same', threshold: 'unseen', unit: null, source: null,
      }],
    };

    const first = appendReceipt(store, sameSignal);
    await new Promise((resolve) => setImmediate(resolve));
    const second = appendReceipt(store, sameSignal);
    await new Promise((resolve) => setImmediate(resolve));
    releaseFirst?.();

    const receipts = await Promise.all([first, second]);
    expect(receipts.map((receipt) => receipt.verdict).sort()).toEqual(['ABSTAIN', 'EXECUTE']);
    expect(receipts.map((receipt) => receipt.checks[0]?.verdict).sort()).toEqual(['FAIL', 'PASS']);
    expect(verifyChain(await store.all()).ok).toBe(true);
  });

  it('binds a stale decision snapshot to its old head before committing', async () => {
    const store = new MemoryStore();
    const staleSnapshot = await store.all();
    const sameSignal: ReceiptBody = {
      ...body(1),
      signal_id: 'same',
      verdict: 'EXECUTE',
      checks: [{
        id: 'DUPLICATE', verdict: 'PASS', observed: 'same', threshold: 'unseen', unit: null, source: null,
      }],
    };

    const first = await appendReceipt(store, sameSignal);
    const second = await appendReceipt(store, sameSignal, undefined, staleSnapshot);

    expect(first.verdict).toBe('EXECUTE');
    expect(second.verdict).toBe('ABSTAIN');
    expect(second.checks[0]?.verdict).toBe('FAIL');
    expect(verifyChain(await store.all()).ok).toBe(true);
  });
});

describe('tamper detection', () => {
  it('names the exact sequence number of an edited receipt', async () => {
    const store = new MemoryStore();
    await seed(store, 40);
    const all = await store.all();

    // Flip the verdict to something that genuinely differs, so the edit is real.
    const original = all.find((r) => r.seq === 17)!;
    expect(original.verdict).toBe('EXECUTE');
    const tampered = all.map((r) =>
      r.seq === 17 ? { ...r, verdict: 'ABSTAIN' as const } : r,
    );

    const res = verifyChain(tampered);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.divergedAt).toBe(17);
      expect(res.kind).toBe('content');
    }
  });

  it('catches a removed record as a sequence break', async () => {
    const store = new MemoryStore();
    await seed(store, 10);
    const all = (await store.all()).filter((r) => r.seq !== 6);
    const res = verifyChain(all);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.divergedAt).toBe(6);
      expect(res.kind).toBe('sequence');
    }
  });

  it('catches a re-hashed record whose link no longer matches', async () => {
    const store = new MemoryStore();
    await seed(store, 5);
    const all = await store.all();
    // Re-seal seq 3 with different content so its own hash is self-consistent —
    // only the link to seq 4 gives it away.
    const forged = sealReceipt({ ...body(99) }, 3, all[1]!.hash);
    const res = verifyChain([all[0]!, all[1]!, forged, all[3]!, all[4]!]);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.divergedAt).toBe(4);
      expect(res.kind).toBe('link');
    }
  });
});

describe('canonical form', () => {
  it('is key-order independent, so two identical decisions hash identically', () => {
    expect(canonical({ b: 1, a: { d: 2, c: 3 } })).toBe(canonical({ a: { c: 3, d: 2 }, b: 1 }));
  });

  it('preserves array order, which is meaningful for checks[]', () => {
    expect(canonical([1, 2])).not.toBe(canonical([2, 1]));
  });
});

describe('MemoryStore rate limiting', () => {
  it('starts a fresh allowance after the fixed window expires', async () => {
    const now = vi.spyOn(Date, 'now');
    try {
      const store = new MemoryStore();
      now.mockReturnValue(1_000);
      expect(await store.allowWrite('client', 1, 60_000)).toBe(true);
      now.mockReturnValue(60_999);
      expect(await store.allowWrite('client', 1, 60_000)).toBe(false);
      now.mockReturnValue(61_000);
      expect(await store.allowWrite('client', 1, 60_000)).toBe(true);
    } finally {
      now.mockRestore();
    }
  });
});

describe('RedisStore', () => {
  /** A fake that honours the Lua script's contract: compare head, then write. */
  function fakeRedis(): RedisLike & { head: string | null; list: string[] } {
    const state = {
      head: null as string | null,
      list: [] as string[],
      rateCount: 0,
      async eval(script: string, _keys: string[], args: string[]) {
        if (script === RATE_LIMIT_LUA) {
          state.rateCount++;
          return state.rateCount <= Number(args[1]) ? 1 : 0;
        }
        const [expected, nextHead, receipt] = args as [string, string, string];
        const current = state.head ?? '';
        if (current !== expected) return 0;
        state.list.push(receipt);
        state.head = nextHead;
        return 1;
      },
      async get() {
        return state.head;
      },
      async lrange() {
        return state.list;
      },
    };
    return state;
  }

  it('appends through the CAS script and verifies', async () => {
    const store = new RedisStore(fakeRedis());
    for (let i = 1; i <= 5; i++) await appendReceipt(store, body(i));
    const res = verifyChain(await store.all());
    expect(res.ok).toBe(true);
  });

  it('rejects a stale expected head instead of overwriting', async () => {
    const redis = fakeRedis();
    const store = new RedisStore(redis);
    const first = await appendReceipt(store, body(1));
    const stale = sealReceipt(body(2), 2, GENESIS); // built against the empty head
    expect(await store.compareAndAppend(null, stale)).toBe(false);
    expect((await store.all()).map((r) => r.seq)).toEqual([first.seq]);
  });

  it('surfaces an unreachable store as StoreUnavailableError, never a silent drop', async () => {
    const broken: RedisLike = {
      eval: async () => {
        throw new Error('ECONNREFUSED');
      },
      get: async () => {
        throw new Error('ECONNREFUSED');
      },
      lrange: async () => {
        throw new Error('ECONNREFUSED');
      },
    };
    const store = new RedisStore(broken);
    await expect(store.head()).rejects.toThrow(StoreUnavailableError);
  });

  it('enforces the write limit through Redis rather than per serverless instance', async () => {
    const store = new RedisStore(fakeRedis());
    for (let i = 0; i < 20; i++) expect(await store.allowWrite('evaluate', 20, 60_000)).toBe(true);
    expect(await store.allowWrite('evaluate', 20, 60_000)).toBe(false);
  });

  it('ships a Lua script that reads the head before writing', () => {
    expect(CAS_APPEND_LUA).toContain("redis.call('GET', KEYS[1])");
    expect(CAS_APPEND_LUA).toContain("redis.call('RPUSH', KEYS[2], ARGV[3])");
    expect(CAS_APPEND_LUA.indexOf('GET')).toBeLessThan(CAS_APPEND_LUA.indexOf('RPUSH'));
  });
});
