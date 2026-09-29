/**
 * The one place that talks to Nexus.
 *
 * Nexus is a REST gateway, not JSON-RPC:
 *
 *     POST https://nexus.olaxbt.xyz/api/mcp/tools/call
 *     X-API-KEY: nxk_...
 *     {"name":"get_strategy_metrics","arguments":{}}
 *
 * and every response is wrapped:
 *
 *     {"ok":true,"name":"...","strategy_id":"str_...","content":{ ...payload... }}
 *
 * This module unwraps `content` exactly once and maps every failure onto a named
 * error class, so no call site can reach into `.content` itself or accidentally
 * swallow an error. Callers get a `Datum<T>` — never a throw.
 *
 * NEXUS_MODE=replay serves recorded cassettes instead of the network, which is
 * how a reviewer with no API key reproduces every receipt.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  NexusNotPublishedError,
  NexusParseError,
  NexusTimeoutError,
  RETRIES,
  classify,
  type NexusError,
} from './errors.js';
import { absent, failed, present, type Datum } from '../types.js';
import { validateToolPayload } from './validate.js';

export interface ClientOptions {
  baseUrl?: string;
  apiKey?: string;
  /** 'live' hits the network; 'replay' reads fixtures/. */
  mode?: 'live' | 'replay';
  fixtureDir?: string;
  timeoutMs?: number;
  /** Injected for tests; defaults to global fetch. */
  fetchImpl?: typeof fetch;
  /** Injected for tests so backoff does not actually sleep. */
  sleep?: (ms: number) => Promise<void>;
}

const DEFAULT_BASE = 'https://nexus.olaxbt.xyz/api/mcp';
const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export class NexusClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly mode: 'live' | 'replay';
  private readonly fixtureDir: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(opts: ClientOptions = {}) {
    this.baseUrl = opts.baseUrl ?? process.env['NEXUS_BASE_URL'] ?? DEFAULT_BASE;
    this.apiKey = opts.apiKey ?? process.env['NEXUS_API_KEY'] ?? '';
    this.mode = opts.mode ?? (process.env['NEXUS_MODE'] === 'live' ? 'live' : 'replay');
    this.fixtureDir = opts.fixtureDir ?? 'fixtures';
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.sleep = opts.sleep ?? defaultSleep;
  }

  /**
   * Fetch one tool. Never throws: every outcome is a Datum, because the gate
   * fails closed and needs to record WHY rather than crash.
   *
   *   ok        ──▶ { ok: true, value }
   *   404 known ──▶ { ok: false, outcome: 'absent' }        the datum does not exist
   *   anything  ──▶ { ok: false, outcome: 'failed', error } the call did not work
   *   else
   */
  async call<T>(tool: string, args: Record<string, unknown> = {}): Promise<Datum<T>> {
    if (this.mode === 'replay') return this.replay<T>(tool, args);

    let lastError: NexusError | undefined;
    // attempt 0 is the real call; further attempts are the retry budget.
    for (let attempt = 0; attempt <= 2; attempt++) {
      try {
        return present(await this.once<T>(tool, args));
      } catch (err) {
        const e = err as NexusError;
        lastError = e;

        // A known tool with no published data is an ABSENCE, not a failure.
        if (e instanceof NexusNotPublishedError) return absent<T>();

        const budget = RETRIES[e.name] ?? 0;
        if (attempt >= budget) break;
        await this.sleep(200 * 2 ** attempt);
      }
    }
    return failed<T>(lastError?.name ?? 'NexusParseError');
  }

  private async once<T>(tool: string, args: Record<string, unknown>): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}/tools/call`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-KEY': this.apiKey },
        body: JSON.stringify({ name: tool, arguments: args }),
        signal: controller.signal,
      });
    } catch (err) {
      throw new NexusTimeoutError(`network failure calling ${tool}: ${String(err)}`, tool);
    } finally {
      clearTimeout(timer);
    }

    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw classify(res.status, tool, detail.slice(0, 200));
    }

    let body: unknown;
    try {
      body = await res.json();
    } catch {
      throw new NexusParseError(`non-JSON body from ${tool}`, tool, res.status);
    }
    return validateToolPayload<T>(tool, unwrap<unknown>(body, tool), args);
  }

  private replay<T>(tool: string, args: Record<string, unknown>): Datum<T> {
    const name = cassetteName(tool, args);
    try {
      const raw = readFileSync(join(this.fixtureDir, name), 'utf8');
      return present(validateToolPayload<T>(tool, unwrap<unknown>(JSON.parse(raw), tool), args));
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === 'ENOENT') return absent<T>();
      return failed<T>('NexusParseError');
    }
  }
}

/**
 * Unwrap the gateway envelope. Accepts a bare payload too, so hand-written
 * cassettes do not have to fake the wrapper.
 */
export function unwrap<T>(body: unknown, tool: string): T {
  if (body === null || typeof body !== 'object') {
    throw new NexusParseError(`${tool} returned a non-object body`, tool);
  }
  const obj = body as Record<string, unknown>;
  if (!('content' in obj)) return obj as T;

  if (obj['ok'] === false) {
    throw new NexusParseError(`${tool} returned ok:false`, tool);
  }
  const content = obj['content'];
  if (content === null || typeof content !== 'object') {
    throw new NexusParseError(`${tool} envelope has no usable content`, tool);
  }
  return content as T;
}

/** `get_historical_funding` + {symbol:'BTC/USDT'} → `get_historical_funding.BTC-USDT.json` */
export function cassetteName(tool: string, args: Record<string, unknown>): string {
  const symbol = typeof args['symbol'] === 'string' ? args['symbol'] : undefined;
  const asOf = typeof args['as_of'] === 'string' ? args['as_of'] : undefined;
  const parts = [tool];
  if (symbol) parts.push(symbol.replace('/', '-'));
  if (asOf) parts.push(asOf);
  return `${parts.join('.')}.json`;
}
