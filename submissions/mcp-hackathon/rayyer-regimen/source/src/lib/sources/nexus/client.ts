import type { ZodType } from 'zod';
import { RegimenError } from '@/lib/errors';
import type { Provenance } from '@/lib/sources/types';

/**
 * Typed client for the OlaXBT Nexus MCP gateway.
 *
 * Three things here are load-bearing and easy to get wrong, so they are handled once,
 * centrally, rather than at each call site:
 *
 *  1. **Rate limiting.** A Nexus Builder key allows 80 requests/minute. A regime map
 *     over a long equity curve wants hundreds of point-in-time reads, so an unpaced
 *     client would spend the whole analysis being told 429. Calls go through a token
 *     bucket pinned below the published ceiling.
 *  2. **Caching.** A point-in-time read is immutable by construction — what the VIX
 *     closed at on 2024-01-15 will not change — so any call carrying an `as_of` in the
 *     past is cached indefinitely. Live reads are not cached at all.
 *  3. **Envelope tolerance.** The gateway is documented by example, not by schema, and
 *     a tool result may arrive bare, wrapped in `{result}`/`{data}`, or in an MCP
 *     content array. All three are unwrapped before validation.
 *
 * Docs: https://nexus.olaxbt.xyz/api/mcp/docs
 */

export const NEXUS_BASE_URL = 'https://nexus.olaxbt.xyz/api/mcp';
export const NEXUS_SOURCE_ID = 'olaxbt-nexus';

/** Published Builder-tier ceiling is 80/min; we pace below it to leave headroom. */
const DEFAULT_REQUESTS_PER_MINUTE = 70;
const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_CACHE_ENTRIES = 5_000;

export type NexusTool =
  | 'get_strategy_signal'
  | 'get_strategy_metrics'
  | 'get_strategy_equity'
  | 'get_strategy_trades'
  | 'run_backtest'
  | 'get_backtest_job'
  | 'get_historical_ohlcv'
  | 'get_historical_funding'
  | 'get_market_snapshot'
  | 'get_open_interest'
  | 'get_vcp'
  | 'get_macro'
  | 'get_historical_coverage'
  | 'get_etf_flow'
  | 'get_oi_ranking'
  | 'get_fear_greed'
  | 'get_news'
  | 'get_sentiment';

export interface NexusCallResult<T> {
  readonly value: T;
  readonly provenance: Provenance;
}

interface CacheEntry {
  readonly value: unknown;
  readonly storedAt: string;
}

/**
 * Process-wide cache of immutable point-in-time reads.
 *
 * Deliberately a plain map rather than an external store: it holds nothing that is
 * not already public market data, it must never become a correctness dependency, and
 * a cold instance simply refetches. Insertion-ordered eviction keeps it bounded.
 */
const immutableCache = new Map<string, CacheEntry>();

function cacheGet(key: string): CacheEntry | undefined {
  return immutableCache.get(key);
}

function cacheSet(key: string, value: unknown): void {
  if (immutableCache.size >= MAX_CACHE_ENTRIES) {
    const oldest = immutableCache.keys().next();
    if (!oldest.done) immutableCache.delete(oldest.value);
  }
  immutableCache.set(key, { value, storedAt: new Date().toISOString() });
}

/** Exposed for tests and for the ops endpoint; never part of an analysis result. */
export function cacheStats() {
  return { entries: immutableCache.size, capacity: MAX_CACHE_ENTRIES };
}

export function clearCache(): void {
  immutableCache.clear();
}

/** A token bucket shared by every call made with the same key. */
class RateLimiter {
  private tokens: number;
  private lastRefill = Date.now();
  private readonly capacity: number;
  private readonly refillPerMs: number;
  private queue: Array<() => void> = [];

  constructor(requestsPerMinute: number) {
    this.capacity = requestsPerMinute;
    this.tokens = requestsPerMinute;
    this.refillPerMs = requestsPerMinute / 60_000;
  }

  private refill(): void {
    const now = Date.now();
    const elapsed = now - this.lastRefill;
    if (elapsed <= 0) return;
    this.tokens = Math.min(this.capacity, this.tokens + elapsed * this.refillPerMs);
    this.lastRefill = now;
  }

  async acquire(signal?: AbortSignal): Promise<void> {
    for (;;) {
      this.refill();
      if (this.tokens >= 1) {
        this.tokens -= 1;
        return;
      }
      const waitMs = Math.ceil((1 - this.tokens) / this.refillPerMs);
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => {
          this.queue = this.queue.filter((entry) => entry !== resolve);
          resolve();
        }, Math.min(waitMs, 1_000));
        this.queue.push(resolve);
        signal?.addEventListener(
          'abort',
          () => {
            clearTimeout(timer);
            reject(new RegimenError('upstream_timeout', 'Cancelled while waiting for rate-limit headroom.'));
          },
          { once: true },
        );
      });
    }
  }
}

const limiters = new Map<string, RateLimiter>();

function limiterFor(keyFingerprint: string, requestsPerMinute: number): RateLimiter {
  let limiter = limiters.get(keyFingerprint);
  if (!limiter) {
    limiter = new RateLimiter(requestsPerMinute);
    limiters.set(keyFingerprint, limiter);
  }
  return limiter;
}

/**
 * Non-reversible, non-identifying label for an API key.
 *
 * Used to key the rate limiter and the cache per tenant, and as the only form in
 * which a key is ever allowed to appear in a log line or a response.
 */
export function fingerprintKey(apiKey: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < apiKey.length; i += 1) {
    const c = apiKey.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 + c, 0x85ebca6b) >>> 0;
  }
  return `${h1.toString(16).padStart(8, '0')}${h2.toString(16).padStart(8, '0')}`;
}

/** Tools whose result depends only on a past date, and is therefore immutable. */
const POINT_IN_TIME_TOOLS: ReadonlySet<NexusTool> = new Set<NexusTool>([
  'get_historical_ohlcv',
  'get_historical_funding',
  'get_market_snapshot',
  'get_open_interest',
  'get_vcp',
  'get_macro',
  'get_fear_greed',
]);

function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

function isImmutable(tool: NexusTool, args: Record<string, unknown>): boolean {
  if (!POINT_IN_TIME_TOOLS.has(tool)) return false;
  const asOf = args['as_of'];
  // Only a strictly past date is safe to cache forever: today's value can still move.
  return typeof asOf === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(asOf) && asOf < todayUtc();
}

/**
 * Pull the tool payload out of whatever the gateway wrapped it in.
 * Returns the original body when no recognised envelope is present.
 */
export function unwrapEnvelope(body: unknown): unknown {
  if (body === null || typeof body !== 'object') return body;
  const record = body as Record<string, unknown>;

  // MCP-style content array carrying JSON as text.
  const content = record['content'];
  if (Array.isArray(content)) {
    for (const block of content) {
      if (block && typeof block === 'object') {
        const entry = block as Record<string, unknown>;
        if (entry['type'] === 'text' && typeof entry['text'] === 'string') {
          try {
            return JSON.parse(entry['text']);
          } catch {
            return entry['text'];
          }
        }
      }
    }
  }

  for (const key of ['structuredContent', 'result', 'data', 'payload'] as const) {
    const inner = record[key];
    if (inner !== undefined && inner !== null && typeof inner === 'object') {
      return unwrapEnvelope(inner);
    }
  }

  return body;
}

export interface NexusClientOptions {
  readonly apiKey: string;
  readonly baseUrl?: string;
  readonly timeoutMs?: number;
  readonly requestsPerMinute?: number;
  /** Injected in tests; defaults to global fetch. */
  readonly fetchImpl?: typeof fetch;
}

export class NexusClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly limiter: RateLimiter;
  private readonly fetchImpl: typeof fetch;
  readonly fingerprint: string;

  constructor(options: NexusClientOptions) {
    const apiKey = options.apiKey?.trim();
    if (!apiKey) {
      throw new RegimenError('missing_credentials', 'A Nexus API key is required.', {
        remedy:
          'Send your Nexus key in the `X-Nexus-Key` header, or call the demo endpoints which use the service key.',
      });
    }
    this.apiKey = apiKey;
    this.baseUrl = options.baseUrl ?? NEXUS_BASE_URL;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.fingerprint = fingerprintKey(apiKey);
    this.limiter = limiterFor(this.fingerprint, options.requestsPerMinute ?? DEFAULT_REQUESTS_PER_MINUTE);
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  /**
   * Invoke one Nexus tool and validate its result.
   *
   * Throws `RegimenError` and nothing else. The upstream body is never forwarded:
   * a Nexus error becomes one of our codes plus a remedy the caller can act on.
   */
  async call<T>(
    tool: NexusTool,
    args: Record<string, unknown>,
    schema: ZodType<T>,
    options: { readonly signal?: AbortSignal } = {},
  ): Promise<NexusCallResult<T>> {
    const cacheable = isImmutable(tool, args);
    const cacheKey = cacheable ? `${this.fingerprint}:${tool}:${JSON.stringify(args)}` : null;

    if (cacheKey) {
      const hit = cacheGet(cacheKey);
      if (hit) {
        const parsed = schema.safeParse(hit.value);
        if (parsed.success) {
          return {
            value: parsed.data,
            provenance: this.provenanceFor(tool, args, hit.storedAt, true),
          };
        }
        immutableCache.delete(cacheKey);
      }
    }

    await this.limiter.acquire(options.signal);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const onAbort = () => controller.abort();
    options.signal?.addEventListener('abort', onAbort, { once: true });

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/tools/call`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'X-API-KEY': this.apiKey,
          accept: 'application/json',
        },
        body: JSON.stringify({ name: tool, arguments: args }),
        signal: controller.signal,
      });
    } catch (cause) {
      throw new RegimenError('upstream_unavailable', `Could not reach the Nexus gateway calling ${tool}.`, {
        cause,
        details: { tool },
        remedy: 'Retry shortly. https://nexus.olaxbt.xyz/api/mcp/health reports gateway liveness.',
      });
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener('abort', onAbort);
    }

    if (!response.ok) throw this.mapHttpError(response.status, tool);

    let body: unknown;
    try {
      body = await response.json();
    } catch (cause) {
      throw new RegimenError('upstream_malformed', `Nexus returned a non-JSON body for ${tool}.`, {
        cause,
        details: { tool },
      });
    }

    const parsed = schema.safeParse(unwrapEnvelope(body));
    if (!parsed.success) {
      throw new RegimenError('upstream_malformed', `Nexus returned an unexpected shape for ${tool}.`, {
        details: {
          tool,
          // Field paths only. Never the values — this is third-party account data.
          missingOrInvalid: parsed.error.issues.slice(0, 8).map((issue) => issue.path.join('.')),
        },
        remedy: 'The upstream contract may have changed. Report the tool name so the adapter can be updated.',
      });
    }

    const fetchedAt = new Date().toISOString();
    if (cacheKey) cacheSet(cacheKey, parsed.data);

    return { value: parsed.data, provenance: this.provenanceFor(tool, args, fetchedAt, false) };
  }

  private provenanceFor(
    tool: NexusTool,
    args: Record<string, unknown>,
    fetchedAt: string,
    cached: boolean,
  ): Provenance {
    const asOf = args['as_of'];
    return {
      source: NEXUS_SOURCE_ID,
      operation: tool,
      ...(typeof asOf === 'string' ? { asOf } : {}),
      fetchedAt,
      cached,
    };
  }

  private mapHttpError(status: number, tool: NexusTool): RegimenError {
    switch (status) {
      case 401:
        return new RegimenError('upstream_unauthorized', 'Nexus rejected the API key.', {
          details: { tool },
          remedy:
            'Check the key is current and was issued for this strategy in Nexus Studio (Profile → API keys). Revoked keys fail immediately.',
        });
      case 400:
        return new RegimenError('upstream_rejected', `Nexus rejected the arguments for ${tool}.`, {
          details: { tool },
          remedy: 'Check required arguments: `symbol` for signals, `as_of` (YYYY-MM-DD) for point-in-time reads.',
        });
      case 404:
        return new RegimenError(
          'upstream_not_published',
          `Nexus has nothing published for ${tool} on this key's strategy yet.`,
          {
            details: { tool },
            remedy:
              'Run a Fire Backtest in Nexus Studio first. Metrics and signals only exist once a strategy has been compiled and run.',
          },
        );
      case 429:
        return new RegimenError('upstream_rate_limited', 'Nexus is rate limiting this key.', {
          details: { tool },
          remedy: 'Too many concurrent backtests, or the per-minute ceiling was hit. Retry after a short pause.',
        });
      case 502:
      case 503:
      case 504:
        return new RegimenError('upstream_unavailable', 'The Nexus strategy engine is unreachable.', {
          details: { tool, status },
          remedy: 'This is upstream. Retry shortly.',
        });
      default:
        return new RegimenError('upstream_rejected', `Nexus returned HTTP ${status} for ${tool}.`, {
          details: { tool, status },
        });
    }
  }
}
