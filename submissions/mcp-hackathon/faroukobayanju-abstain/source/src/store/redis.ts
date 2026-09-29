/**
 * Upstash Redis store. Production path.
 *
 * The compare-and-set lives in a Lua script because Redis runs a script
 * atomically — no other command interleaves between the GET and the SET, so the
 * head can never fork no matter how many Vercel functions fire at once.
 *
 * Hashing stays in Node: Redis Lua exposes `redis.sha1hex` but not sha256, and
 * shipping sha1 to buy atomicity we can get another way is a bad trade. Node
 * computes the sha256 receipt hash, Lua only decides whether it is allowed to
 * land.
 */
import type { Receipt } from '../receipt/schema.js';
import { StoreUnavailableError, type Head, type ReceiptStore } from './types.js';

/**
 * KEYS[1] head   ARGV[1] expected head JSON ('' when the chain is empty)
 * KEYS[2] list   ARGV[2] new head JSON
 *                ARGV[3] receipt JSON
 * Returns 1 on commit, 0 when another writer won the race.
 */
export const CAS_APPEND_LUA = `
local current = redis.call('GET', KEYS[1])
local expected = ARGV[1]
if expected == '' then expected = false end
if current ~= expected then
  if not (current == false and expected == false) then
    return 0
  end
end
redis.call('RPUSH', KEYS[2], ARGV[3])
redis.call('SET', KEYS[1], ARGV[2])
return 1
`.trim();

export const RATE_LIMIT_LUA = `
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
if count > tonumber(ARGV[2]) then return 0 end
return 1
`.trim();

/** Minimal surface of the Upstash/ioredis client we depend on. */
export interface RedisLike {
  eval(script: string, keys: string[], args: string[]): Promise<unknown>;
  get(key: string): Promise<string | null>;
  lrange(key: string, start: number, stop: number): Promise<string[]>;
}

export class RedisStore implements ReceiptStore {
  constructor(
    private readonly redis: RedisLike,
    private readonly prefix = 'abstain',
  ) {}

  private get headKey(): string {
    return `${this.prefix}:head`;
  }
  private get listKey(): string {
    return `${this.prefix}:receipts`;
  }

  async head(): Promise<Head | null> {
    try {
      const raw = await this.redis.get(this.headKey);
      return raw ? (JSON.parse(raw) as Head) : null;
    } catch (err) {
      throw new StoreUnavailableError(String(err));
    }
  }

  async compareAndAppend(expected: Head | null, receipt: Receipt): Promise<boolean> {
    const nextHead: Head = { seq: receipt.seq, hash: receipt.hash };
    try {
      const res = await this.redis.eval(
        CAS_APPEND_LUA,
        [this.headKey, this.listKey],
        [expected ? JSON.stringify(expected) : '', JSON.stringify(nextHead), JSON.stringify(receipt)],
      );
      return Number(res) === 1;
    } catch (err) {
      // A contended write returns 0; reaching here means Redis itself is
      // unreachable. Surface it so /v1/evaluate can return a named 503 rather
      // than silently dropping a receipt.
      throw new StoreUnavailableError(String(err));
    }
  }

  async get(seq: number): Promise<Receipt | null> {
    const all = await this.all();
    return all.find((r) => r.seq === seq) ?? null;
  }

  async all(): Promise<Receipt[]> {
    try {
      const raw = await this.redis.lrange(this.listKey, 0, -1);
      return raw.map((r) => JSON.parse(r) as Receipt).sort((a, b) => a.seq - b.seq);
    } catch (err) {
      throw new StoreUnavailableError(String(err));
    }
  }

  async allowWrite(scope: string, limit: number, windowMs: number): Promise<boolean> {
    try {
      const bucket = Math.floor(Date.now() / windowMs);
      const result = await this.redis.eval(
        RATE_LIMIT_LUA,
        [`${this.prefix}:rate:${scope}:${bucket}`],
        [String(windowMs), String(limit)],
      );
      return Number(result) === 1;
    } catch (err) {
      throw new StoreUnavailableError(String(err));
    }
  }
}
