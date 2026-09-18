/**
 * Upstash Redis over its REST API, implemented with plain `fetch`.
 *
 * The @upstash/redis SDK would work, but the three commands this store needs
 * (GET, LRANGE, EVAL) are a few lines each over REST, and a dependency added
 * for that is a dependency to audit, pin, and declare in the submission.
 *
 * REST protocol: POST the command as a JSON array, get back { result } or
 * { error }.
 *     ["GET", "abstain:head"]
 *     ["EVAL", "<lua>", "2", "k1", "k2", "a1", "a2", "a3"]
 */
import { StoreUnavailableError } from './types.js';
import type { RedisLike } from './redis.js';

export interface UpstashOptions {
  url: string;
  token: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export class UpstashRest implements RedisLike {
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(private readonly opts: UpstashOptions) {
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.timeoutMs = opts.timeoutMs ?? 5_000;
  }

  private async command<T>(args: string[]): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await this.fetchImpl(this.opts.url, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.opts.token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
      if (!res.ok) {
        throw new StoreUnavailableError(`upstash HTTP ${res.status}`);
      }
      const body = (await res.json()) as { result?: unknown; error?: string };
      if (body.error) throw new StoreUnavailableError(`upstash: ${body.error}`);
      return body.result as T;
    } catch (err) {
      if (err instanceof StoreUnavailableError) throw err;
      throw new StoreUnavailableError(String(err));
    } finally {
      clearTimeout(timer);
    }
  }

  async get(key: string): Promise<string | null> {
    return this.command<string | null>(['GET', key]);
  }

  async lrange(key: string, start: number, stop: number): Promise<string[]> {
    return (await this.command<string[] | null>(['LRANGE', key, String(start), String(stop)])) ?? [];
  }

  async eval(script: string, keys: string[], args: string[]): Promise<unknown> {
    return this.command(['EVAL', script, String(keys.length), ...keys, ...args]);
  }
}
