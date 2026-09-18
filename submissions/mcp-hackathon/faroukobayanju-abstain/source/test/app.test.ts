import { describe, expect, it, vi } from 'vitest';
import { createApp } from '../src/app.js';
import { NexusClient } from '../src/nexus/client.js';
import { TtlCache } from '../src/nexus/fetch-all.js';
import { MemoryStore } from '../src/store/memory.js';
import { StoreUnavailableError, type ReceiptStore } from '../src/store/types.js';
import { BASE_POLICY } from './helpers.js';

const COMMIT = 'a'.repeat(40);
const KEY = 'test-write-key';

const ENV = {
  VERCEL_GIT_COMMIT_SHA: COMMIT,
  ABSTAIN_WRITE_KEY: KEY,
} as unknown as NodeJS.ProcessEnv;

function app(store: ReceiptStore = new MemoryStore(), env: NodeJS.ProcessEnv = ENV) {
  return createApp({
    client: new NexusClient({ mode: 'replay', fixtureDir: 'fixtures' }),
    store,
    cache: new TtlCache(60_000),
    basePolicy: BASE_POLICY,
    accountEquity: 100_000,
    now: () => Date.UTC(2026, 8, 18, 0, 0, 0),
    env,
  });
}

const post = (a: ReturnType<typeof app>, path: string, body?: unknown, headers: Record<string, string> = {}) =>
  a.request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

const VALID = { symbol: 'BTC/USDT', side: 'BUY', notional: 15_000 };

describe('hard gate: GET /health', () => {
  it('returns ok and the exact 40-char commit', async () => {
    const res = await app().request('/health');
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({
      status: 'ok',
      service: 'faroukobayanju-abstain',
      commit: COMMIT,
      commit_reviewable: true,
    });
    // The gate accepts the commit in the body or this header; supply both.
    expect(res.headers.get('x-source-commit')).toBe(COMMIT);
  });

  it('stays ok with NO Nexus key and a completely broken store', async () => {
    // The gate must not be hostage to a third party for twelve days.
    const broken: ReceiptStore = {
      head: async () => { throw new StoreUnavailableError('down'); },
      compareAndAppend: async () => { throw new StoreUnavailableError('down'); },
      get: async () => { throw new StoreUnavailableError('down'); },
      all: async () => { throw new StoreUnavailableError('down'); },
      allowWrite: async () => { throw new StoreUnavailableError('down'); },
    };
    const res = await app(broken, { VERCEL_GIT_COMMIT_SHA: COMMIT } as NodeJS.ProcessEnv).request('/health');
    expect(res.status).toBe(200);
    expect((await res.json()).status).toBe('ok');
  });

  it('flags a commit that would not satisfy the gate', async () => {
    const res = await app(new MemoryStore(), {} as NodeJS.ProcessEnv).request('/health');
    const body = await res.json();
    expect(body.commit).toBe('unknown');
    expect(body.commit_reviewable).toBe(false);
  });
});

describe('hard gate: GET /.well-known/xagent-verification.json', () => {
  it('matches the shape the automated online gate requires', async () => {
    const a = app();
    const wk = await (await a.request('/.well-known/xagent-verification.json')).json();
    const health = await (await a.request('/health')).json();
    expect(wk.schemaVersion).toBe(1);
    // MUST equal the submission directory name, not the bare project name.
    expect(wk.slug).toBe('faroukobayanju-abstain');
    expect(wk.commit).toBe(health.commit);
  });
});

describe('GET /v1/ready — dependency probe, no gate reads it', () => {
  it('reports 503 when a dependency is down without touching /health', async () => {
    const a = createApp({
      client: new NexusClient({ mode: 'replay', fixtureDir: 'fixtures' }),
      store: new MemoryStore(),
      cache: new TtlCache(60_000),
      basePolicy: BASE_POLICY,
      accountEquity: 100_000,
      env: ENV,
      probe: async () => ({ nexus: true, store: false }),
    });
    const ready = await a.request('/v1/ready');
    expect(ready.status).toBe(503);
    expect((await a.request('/health')).status).toBe(200);
  });
});

describe('write auth on POST /v1/evaluate', () => {
  it('rejects a missing key', async () => {
    const res = await post(app(), '/v1/evaluate', VALID);
    expect(res.status).toBe(401);
    expect((await res.json()).reason).toContain('X-ABSTAIN-KEY');
  });

  it('rejects a wrong key', async () => {
    const res = await post(app(), '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': 'nope' });
    expect(res.status).toBe(401);
  });

  it('refuses everything when no key is configured — fail closed, not open', async () => {
    const res = await post(app(new MemoryStore(), { VERCEL_GIT_COMMIT_SHA: COMMIT } as NodeJS.ProcessEnv), '/v1/evaluate', VALID, {
      'X-ABSTAIN-KEY': '',
    });
    expect(res.status).toBe(401);
  });

  it('leaves every read endpoint open', async () => {
    const a = app();
    expect((await a.request('/v1/receipts')).status).toBe(200);
    expect((await a.request('/v1/policy')).status).toBe(200);
    expect((await post(a, '/v1/verify')).status).toBe(200);
  });
});

describe('input validation', () => {
  const cases: [string, unknown, string][] = [
    ['missing symbol', { side: 'BUY', notional: 1 }, 'symbol'],
    ['symbol without a pair separator', { symbol: 'BTC', side: 'BUY', notional: 1 }, 'symbol'],
    ['bad side', { symbol: 'BTC/USDT', side: 'LONG', notional: 1 }, 'side'],
    ['negative notional', { symbol: 'BTC/USDT', side: 'BUY', notional: -5 }, 'notional'],
    ['notional as a string', { symbol: 'BTC/USDT', side: 'BUY', notional: '100' }, 'notional'],
    ['unknown policy', { ...VALID, policy: 'loose' }, 'policy'],
    ['caller-supplied signal identity', { ...VALID, signalId: 'bypass' }, 'signalId'],
  ];
  for (const [name, body, field] of cases) {
    it(`rejects ${name} and names the field`, async () => {
      const res = await post(app(), '/v1/evaluate', body, { 'X-ABSTAIN-KEY': KEY });
      expect(res.status).toBe(400);
      expect((await res.json()).field).toBe(field);
    });
  }

  it('rejects a non-JSON body without crashing', async () => {
    const res = await app().request('/v1/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-ABSTAIN-KEY': KEY },
      body: 'not json',
    });
    expect(res.status).toBe(400);
  });
});

describe('POST /v1/evaluate — the three demo acts', () => {
  it('act 3: the recorded signal is HOLD, so the proposal is REFUSED with all checks named', async () => {
    const store = new MemoryStore();
    const res = await post(app(store), '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    expect(res.status).toBe(200);
    const body = await res.json();
    // Previously NO_TRADE with an empty checks array, which meant the live API
    // never demonstrated the gate at all.
    expect(body.verdict).toBe('ABSTAIN');
    expect(body.checks).toHaveLength(11);
    const support = body.checks.find((c: { id: string }) => c.id === 'SIGNAL_SUPPORT');
    expect(support.verdict).toBe('FAIL');
    expect(support.observed).toBe('HOLD');
    expect((await store.all())).toHaveLength(1);
  });

  it('records the resolved as_of so the decision can be re-fetched', async () => {
    const res = await post(app(), '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    expect((await res.json()).as_of).toBe('2026-09-17');
  });

  it('strict and permissive produce different policy hashes', async () => {
    const a = app();
    const strict = await (await post(a, '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY })).json();
    const permissive = await (
      await post(a, '/v1/evaluate', { ...VALID, policy: 'permissive' }, { 'X-ABSTAIN-KEY': KEY })
    ).json();
    expect(strict.policy_hash).not.toBe(permissive.policy_hash);
  });

  it('appends one receipt per call and the chain still verifies', async () => {
    const store = new MemoryStore();
    const a = app(store);
    for (let i = 0; i < 5; i++) {
      await post(a, '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    }
    expect(await store.all()).toHaveLength(5);
    expect((await (await post(a, '/v1/verify')).json()).ok).toBe(true);
  });

  it('returns a named 503 and writes NO receipt when the store is down', async () => {
    const broken: ReceiptStore = {
      head: async () => { throw new StoreUnavailableError('ECONNREFUSED'); },
      compareAndAppend: async () => { throw new StoreUnavailableError('ECONNREFUSED'); },
      get: async () => null,
      all: async () => [],
      allowWrite: async () => { throw new StoreUnavailableError('ECONNREFUSED'); },
    };
    const res = await post(app(broken), '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.error).toBe('store_unavailable');
    expect(body.receipt_written).toBe(false);
  });
});

describe('public reads', () => {
  it('paginates receipts and reports the total', async () => {
    const store = new MemoryStore();
    const a = app(store);
    for (let i = 0; i < 4; i++) {
      await post(a, '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    }
    const body = await (await a.request('/v1/receipts?from=2&to=3')).json();
    expect(body.count).toBe(2);
    expect(body.total).toBe(4);
    expect(body.receipts.map((r: { seq: number }) => r.seq)).toEqual([2, 3]);
  });

  it('404s an unknown seq and 400s a malformed one', async () => {
    const a = app();
    expect((await a.request('/v1/receipts/99')).status).toBe(404);
    expect((await a.request('/v1/receipts/abc')).status).toBe(400);
  });

  it('exposes the policy with its hash', async () => {
    const body = await (await app().request('/v1/policy?policy=permissive')).json();
    expect(body.name).toBe('permissive');
    expect(body.policy.require_qualified).toBe(false);
    expect(body.policy_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  });

  it('rejects an unknown policy name', async () => {
    expect((await app().request('/v1/policy?policy=loose')).status).toBe(400);
  });

  it('verify returns 409 on a broken chain so a client cannot ignore it', async () => {
    const store = new MemoryStore();
    const a = app(store);
    await post(a, '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    const all = await store.all();
    // Tamper in place.
    (all[0] as { verdict: string }).verdict = 'EXECUTE';
    const res = await post(a, '/v1/verify');
    expect(res.status).toBe(409);
    expect((await res.json()).divergedAt).toBe(1);
  });

  it('404s an unknown path with a JSON body, not an HTML page', async () => {
    const res = await app().request('/nope');
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('not_found');
  });
});

describe('store durability is loud, never silent', () => {
  it('accepts the Vercel Upstash integration variable names', async () => {
    const { resolveRedisCredentials } = await import('../src/deps.js');
    expect(resolveRedisCredentials({ KV_REST_API_URL: 'u', KV_REST_API_TOKEN: 't' } as NodeJS.ProcessEnv))
      .toEqual({ url: 'u', token: 't' });
  });

  it('accepts the direct Upstash variable names', async () => {
    const { resolveRedisCredentials } = await import('../src/deps.js');
    expect(resolveRedisCredentials({ UPSTASH_REDIS_REST_URL: 'u', UPSTASH_REDIS_REST_TOKEN: 't' } as NodeJS.ProcessEnv))
      .toEqual({ url: 'u', token: 't' });
  });

  it('returns null when only one half is present, rather than half-configuring', async () => {
    const { resolveRedisCredentials } = await import('../src/deps.js');
    expect(resolveRedisCredentials({ KV_REST_API_URL: 'u' } as NodeJS.ProcessEnv)).toBeNull();
  });

  it('never combines a URL and token from different integration namespaces', async () => {
    const { resolveRedisCredentials } = await import('../src/deps.js');
    expect(resolveRedisCredentials({
      UPSTASH_REDIS_REST_URL: 'direct-url',
      KV_REST_API_TOKEN: 'marketplace-token',
    } as NodeJS.ProcessEnv)).toBeNull();
  });

  it('logs loudly and returns an explicitly ephemeral store when production credentials are missing', async () => {
    const { buildStore } = await import('../src/deps.js');
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const built = buildStore({ VERCEL_ENV: 'production' } as NodeJS.ProcessEnv);
      expect(built.durable).toBe(false);
      expect(built.store).toBeInstanceOf(MemoryStore);
      expect(error).toHaveBeenCalledWith(expect.stringContaining('FATAL: no Redis credentials'));
    } finally {
      error.mockRestore();
    }
  });

  it('/v1/ready is NOT ready when receipts are ephemeral', async () => {
    const a = createApp({
      client: new NexusClient({ mode: 'replay', fixtureDir: 'fixtures' }),
      store: new MemoryStore(),
      cache: new TtlCache(60_000),
      basePolicy: BASE_POLICY,
      accountEquity: 100_000,
      env: ENV,
      durable: false,
      probe: async () => ({ nexus: true, store: true, durable: false }),
    });
    const res = await a.request('/v1/ready');
    expect(res.status).toBe(503);
    expect((await res.json()).warning).toContain('cold start');
  });

  it('refuses production evaluations when receipts are ephemeral', async () => {
    const store = new MemoryStore();
    const a = createApp({
      client: new NexusClient({ mode: 'replay', fixtureDir: 'fixtures' }),
      store,
      cache: new TtlCache(60_000),
      basePolicy: BASE_POLICY,
      accountEquity: 100_000,
      env: { ...ENV, VERCEL_ENV: 'production' },
      durable: false,
    });
    const res = await post(a, '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe('store_not_durable');
    expect(await store.all()).toHaveLength(0);
  });

  it('bounds authenticated writes per client before they can grow the chain too quickly', async () => {
    const a = app();
    for (let i = 0; i < 20; i++) {
      expect((await post(a, '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY })).status).toBe(200);
    }
    const limited = await post(a, '/v1/evaluate', VALID, { 'X-ABSTAIN-KEY': KEY });
    expect(limited.status).toBe(429);
    expect(limited.headers.get('retry-after')).toBe('60');
  });

  it('does not let malformed requests exhaust the valid-write allowance', async () => {
    const a = app();
    for (let i = 0; i < 25; i++) {
      expect((await post(a, '/v1/evaluate', { symbol: 'BTC' }, {
        'X-ABSTAIN-KEY': KEY,
        'X-Forwarded-For': '198.51.100.7',
      })).status).toBe(400);
    }
    expect((await post(a, '/v1/evaluate', VALID, {
      'X-ABSTAIN-KEY': KEY,
      'X-Forwarded-For': '198.51.100.7',
    })).status).toBe(200);
  });

  it('rejects an oversized declared request before parsing or rate limiting it', async () => {
    const res = await app().request('/v1/evaluate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': '16385',
        'X-ABSTAIN-KEY': KEY,
      },
      body: JSON.stringify(VALID),
    });
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: 'payload_too_large', max_bytes: 16384 });
  });

  it('rejects an oversized body even when Content-Length is absent', async () => {
    const res = await app().request('/v1/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-ABSTAIN-KEY': KEY },
      body: JSON.stringify({ ...VALID, padding: 'x'.repeat(16_384) }),
    });
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: 'payload_too_large', max_bytes: 16384 });
  });

  it('enforces the global limiter after the client limiter allows the request', async () => {
    const backing = new MemoryStore();
    const store: ReceiptStore = {
      head: () => backing.head(),
      compareAndAppend: (expected, receipt) => backing.compareAndAppend(expected, receipt),
      get: (seq) => backing.get(seq),
      all: () => backing.all(),
      allowWrite: async (scope) => scope !== 'evaluate:global',
    };
    const res = await post(app(store), '/v1/evaluate', VALID, {
      'X-ABSTAIN-KEY': KEY,
      'X-Forwarded-For': '198.51.100.10',
    });
    expect(res.status).toBe(429);
    expect(res.headers.get('retry-after')).toBe('60');
    expect(await res.json()).toMatchObject({ error: 'rate_limited', limit: 200, window_ms: 60_000 });
    expect(await backing.all()).toHaveLength(0);
  });

  it('normalizes the first forwarded client identity and keeps clients in separate scopes', async () => {
    const backing = new MemoryStore();
    const scopes: string[] = [];
    const store: ReceiptStore = {
      head: () => backing.head(),
      compareAndAppend: (expected, receipt) => backing.compareAndAppend(expected, receipt),
      get: (seq) => backing.get(seq),
      all: () => backing.all(),
      allowWrite: async (scope) => {
        scopes.push(scope);
        return true;
      },
    };
    const a = app(store);
    const forwarded = [
      '198.51.100.7, 10.0.0.1',
      'client id/with spaces',
      'a'.repeat(80),
      undefined,
    ];
    for (const value of forwarded) {
      const headers: Record<string, string> = { 'X-ABSTAIN-KEY': KEY };
      if (value !== undefined) headers['X-Forwarded-For'] = value;
      expect((await post(a, '/v1/evaluate', VALID, headers)).status).toBe(200);
    }
    expect(scopes.filter((scope) => scope.startsWith('evaluate:client:'))).toEqual([
      'evaluate:client:198.51.100.7',
      'evaluate:client:client_id_with_spaces',
      `evaluate:client:${'a'.repeat(64)}`,
      'evaluate:client:unknown',
    ]);
  });
});
