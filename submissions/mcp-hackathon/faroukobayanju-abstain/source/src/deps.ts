/**
 * Wire the app from environment.
 *
 *   UPSTASH_REDIS_REST_URL + _TOKEN present ──▶ RedisStore  (durable, atomic CAS)
 *   otherwise                               ──▶ MemoryStore (ephemeral)
 *
 *   NEXUS_MODE=live  + NEXUS_API_KEY        ──▶ real gateway
 *   otherwise                               ──▶ cassette replay
 *
 * Replay + memory is the reviewer's path: clone, `npm test`, reproduce every
 * receipt with no API key and no Redis.
 */
import { NexusClient } from './nexus/client.js';
import { BASE_POLICY } from './policy/base.js';
import { TtlCache } from './nexus/fetch-all.js';
import { MemoryStore } from './store/memory.js';
import { RedisStore } from './store/redis.js';
import { UpstashRest } from './store/upstash.js';
import type { ReceiptStore } from './store/types.js';
import type { Policy } from './types.js';
import type { AppDeps } from './app.js';

/**
 * Bundled, not read from disk. A serverless function's cwd is not the repo
 * root, and an untraced dynamic read would not ship with the deployment.
 */
export function loadBasePolicy(): Policy {
  return { ...BASE_POLICY };
}

/**
 * Vercel's Upstash marketplace integration injects KV_REST_API_URL /
 * KV_REST_API_TOKEN; a direct Upstash setup uses UPSTASH_REDIS_REST_URL /
 * _TOKEN. Accept both, because matching only one name silently degrades the
 * receipt chain to per-instance memory — which looks fine locally and destroys
 * the product's entire claim in production.
 */
export function resolveRedisCredentials(env: NodeJS.ProcessEnv): { url: string; token: string } | null {
  const upstashUrl = env['UPSTASH_REDIS_REST_URL'];
  const upstashToken = env['UPSTASH_REDIS_REST_TOKEN'];
  if (upstashUrl && upstashToken) return { url: upstashUrl, token: upstashToken };

  const kvUrl = env['KV_REST_API_URL'];
  const kvToken = env['KV_REST_API_TOKEN'];
  if (kvUrl && kvToken) return { url: kvUrl, token: kvToken };

  // Never combine a URL from one integration namespace with a token from the
  // other. That produces a credential pair that looks configured but can
  // never authenticate.
  return null;
}

export function buildStore(env: NodeJS.ProcessEnv = process.env): {
  store: ReceiptStore;
  durable: boolean;
} {
  const creds = resolveRedisCredentials(env);
  if (creds) return { store: new RedisStore(new UpstashRest(creds)), durable: true };

  // Never silently ephemeral in production: an evidence chain that resets on a
  // cold start is not evidence.
  if (env['VERCEL_ENV'] === 'production') {
    console.error(
      'FATAL: no Redis credentials (UPSTASH_REDIS_REST_URL/_TOKEN or KV_REST_API_URL/_TOKEN). ' +
        'Receipts would be per-instance and would reset on cold start.',
    );
  }
  return { store: new MemoryStore(), durable: false };
}

export function buildDeps(env: NodeJS.ProcessEnv = process.env): AppDeps {
  const { store, durable } = buildStore(env);
  const client = new NexusClient({
    mode: env['NEXUS_MODE'] === 'live' ? 'live' : 'replay',
    ...(env['NEXUS_API_KEY'] ? { apiKey: env['NEXUS_API_KEY'] } : {}),
  });

  // Replay determinism: a cassette's signal timestamp is frozen while wall
  // clock advances, so SIGNAL_STALE would fail on every replayed decision.
  // Pinning `now` is the same as-of discipline the market checks already use.
  const pinned = env['ABSTAIN_NOW'];

  return {
    client,
    store,
    ...(pinned ? { now: () => Number(pinned) } : {}),
    cache: new TtlCache(60_000),
    basePolicy: loadBasePolicy(),
    accountEquity: Number(env['ACCOUNT_EQUITY'] ?? 100_000),
    env,
    durable,
    probe: async () => {
      const metrics = await client.call('get_strategy_metrics');
      let storeOk = true;
      try {
        await store.head();
      } catch {
        storeOk = false;
      }
      return { nexus: metrics.ok, store: storeOk, durable };
    },
  };
}
