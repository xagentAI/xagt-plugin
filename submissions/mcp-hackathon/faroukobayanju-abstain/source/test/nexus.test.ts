import { describe, expect, it } from 'vitest';
import { NexusClient, cassetteName, unwrap } from '../src/nexus/client.js';
import { KNOWN_TOOLS, classify } from '../src/nexus/errors.js';
import { TtlCache, fetchAll, resolveAsOf, todayIso } from '../src/nexus/fetch-all.js';
import { absent, failed, present, type Coverage, type Metrics } from '../src/types.js';

const noSleep = async () => {};

function respond(status: number, body: unknown, ok = status < 400): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  } as unknown as Response;
}

function clientWith(fetchImpl: typeof fetch) {
  return new NexusClient({ mode: 'live', apiKey: 'test-api-key', fetchImpl, sleep: noSleep });
}

function validPayload(tool: string): Record<string, unknown> {
  switch (tool) {
    case 'get_historical_coverage':
      return { start: '2025-01-01', end: '2026-09-16' };
    case 'get_strategy_signal':
      return { symbol: 'BTC/USDT', trade_intent: 'BUY', reasoning_log: 'test', timestamp: 1_789_689_600 };
    case 'get_strategy_metrics':
      return {
        sharpe_ratio: 1, trading_period_days: 90, estimated_aum_usdt: 100_000,
        profit_factor: 1.2, max_drawdown: '5%', total_return_pct: 10,
        win_rate_pct: 55, trade_count: 20, status: 'QUALIFIED_FOR_OKX_LISTING',
      };
    case 'get_strategy_equity':
      return { run_id: 'r', points: [{ t: 1, equity: 100_000 }] };
    case 'get_strategy_trades':
      return { run_id: 'r', trades: [] };
    case 'get_historical_funding':
      return { symbol: 'BTC/USDT', as_of_date: '2026-09-16', last_funding_rate: 0 };
    case 'get_open_interest':
      return { symbol: 'BTC/USDT', as_of_date: '2026-09-16', open_interest: 100, open_interest_prev: 99 };
    default:
      return {};
  }
}

describe('envelope unwrapping', () => {
  it('unwraps the gateway wrapper exactly once', () => {
    const wrapped = { ok: true, name: 'get_strategy_metrics', strategy_id: 'str_x', content: { sharpe_ratio: 0.2989 } };
    expect(unwrap<Metrics>(wrapped, 'get_strategy_metrics')).toEqual({ sharpe_ratio: 0.2989 });
  });

  it('accepts a bare payload so hand-written cassettes need no wrapper', () => {
    expect(unwrap<{ a: number }>({ a: 1 }, 't')).toEqual({ a: 1 });
  });

  it('rejects ok:false rather than handing back junk', () => {
    expect(() => unwrap({ ok: false, content: {} }, 't')).toThrow('ok:false');
  });
});

describe('error classification — fail closed, never throw at the call site', () => {
  it('401 becomes a failure and is not retried', async () => {
    let calls = 0;
    const c = clientWith(async () => {
      calls++;
      return respond(401, { error: 'unauthorized' });
    });
    expect(await c.call('get_strategy_metrics')).toEqual(failed('NexusAuthError'));
    expect(calls).toBe(1);
  });

  it('400 becomes a failure and is not retried', async () => {
    let calls = 0;
    const c = clientWith(async () => {
      calls++;
      return respond(400, 'missing symbol');
    });
    expect(await c.call('get_strategy_signal')).toEqual(failed('NexusBadRequestError'));
    expect(calls).toBe(1);
  });

  it('404 on a KNOWN tool is an ABSENCE, not a failure', async () => {
    const c = clientWith(async () => respond(404, { detail: 'Not Found' }));
    expect(await c.call('get_strategy_metrics')).toEqual(absent());
  });

  it('404 on an UNKNOWN tool is a failure — our bug, not a data gap', async () => {
    const c = clientWith(async () => respond(404, { detail: 'Not Found' }));
    expect(await c.call('get_stratgy_metrics')).toEqual(failed('NexusUnknownToolError'));
  });

  it('429 retries once, then fails', async () => {
    let calls = 0;
    const c = clientWith(async () => {
      calls++;
      return respond(429, 'slow down');
    });
    expect(await c.call('run_backtest')).toEqual(failed('NexusRateLimitError'));
    expect(calls).toBe(2);
  });

  it('502 retries once, then fails', async () => {
    let calls = 0;
    const c = clientWith(async () => {
      calls++;
      return respond(502, 'bad gateway');
    });
    expect(await c.call('get_strategy_equity')).toEqual(failed('NexusUpstreamError'));
    expect(calls).toBe(2);
  });

  it('a network error retries twice, then fails', async () => {
    let calls = 0;
    const c = clientWith(async () => {
      calls++;
      throw new Error('ECONNRESET');
    });
    expect(await c.call('get_strategy_trades')).toEqual(failed('NexusTimeoutError'));
    expect(calls).toBe(3);
  });

  it('recovers when a retry succeeds', async () => {
    let calls = 0;
    const c = clientWith(async () => {
      calls++;
      return calls === 1 ? respond(502, 'x') : respond(200, { ok: true, content: validPayload('get_strategy_metrics') });
    });
    expect(await c.call<Metrics>('get_strategy_metrics')).toEqual(present(validPayload('get_strategy_metrics')));
  });

  it('a non-JSON body is a parse failure, not a silent empty result', async () => {
    const c = clientWith(async () =>
      ({ ok: true, status: 200, json: async () => { throw new Error('bad'); }, text: async () => '' }) as unknown as Response,
    );
    expect(await c.call('get_strategy_metrics')).toEqual(failed('NexusParseError'));
  });

  it('rejects malformed numeric payloads before they can pass a gate comparison', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { ...validPayload('get_historical_funding'), last_funding_rate: 'not-a-number' },
    }));
    expect(await c.call('get_historical_funding')).toEqual(failed('NexusParseError'));
  });

  it('rejects a payload for a different requested market or date', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: validPayload('get_historical_funding'),
    }));
    expect(await c.call('get_historical_funding', {
      symbol: 'ETH/USDT',
      as_of: '2026-09-17',
    })).toEqual(failed('NexusParseError'));
  });

  it('accepts open interest with no prior snapshot — the live gateway never sends one', async () => {
    const payload = validPayload('get_open_interest');
    delete payload['open_interest_prev'];
    const c = clientWith(async () => respond(200, { ok: true, content: payload }));
    const r = await c.call('get_open_interest', { symbol: 'BTC/USDT', as_of: '2026-09-16' });
    expect(r.ok).toBe(true);
  });

  it('rejects an empty equity series instead of treating missing evidence as usable', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { run_id: 'r', points: [] },
    }));
    expect(await c.call('get_strategy_equity')).toEqual(failed('NexusParseError'));
  });

  it('rejects an invalid strategy signal intent at the trust boundary', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { ...validPayload('get_strategy_signal'), trade_intent: 'WAIT' },
    }));
    expect(await c.call('get_strategy_signal', { symbol: 'BTC/USDT' }))
      .toEqual(failed('NexusParseError'));
  });

  it('rejects a nonpositive strategy signal timestamp', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { ...validPayload('get_strategy_signal'), timestamp: 0 },
    }));
    expect(await c.call('get_strategy_signal', { symbol: 'BTC/USDT' }))
      .toEqual(failed('NexusParseError'));
  });

  it('rejects invalid strategy metrics instead of comparing malformed values', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { ...validPayload('get_strategy_metrics'), sharpe_ratio: Number.NaN },
    }));
    expect(await c.call('get_strategy_metrics')).toEqual(failed('NexusParseError'));
  });

  it('rejects malformed values inside an equity point', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { run_id: 'r', points: [{ t: 1, equity: 'unknown' }] },
    }));
    expect(await c.call('get_strategy_equity')).toEqual(failed('NexusParseError'));
  });

  it('rejects nonpositive equity instead of turning it into zero drawdown', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { run_id: 'r', points: [{ t: 1, equity: 0 }] },
    }));
    expect(await c.call('get_strategy_equity')).toEqual(failed('NexusParseError'));
  });

  it('rejects out-of-order equity points that could hide current drawdown', async () => {
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { run_id: 'r', points: [{ t: 200, equity: 80 }, { t: 100, equity: 100 }] },
    }));
    expect(await c.call('get_strategy_equity')).toEqual(failed('NexusParseError'));
  });

  it('rejects malformed values inside a trade record', async () => {
    const trade = {
      symbol: 'BTC/USDT',
      exit_reason: 'signal',
      direction: 1,
      entry_price: 'unknown',
      exit_price: 101,
      size: 1,
      leverage: 1,
      pnl: 1,
      pnl_pct: 1,
      holding_bars: 1,
      commission: 0,
      entry_bar_index: 1,
      exit_bar_index: 2,
      entry_ts_ms: 1,
      exit_ts_ms: 2,
    };
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { run_id: 'r', trades: [trade] },
    }));
    expect(await c.call('get_strategy_trades')).toEqual(failed('NexusParseError'));
  });

  it('rejects a trade direction outside the documented 1/-1 domain', async () => {
    const trade = {
      symbol: 'BTC/USDT', exit_reason: 'signal', direction: 0,
      entry_price: 100, exit_price: 101, size: 1, leverage: 1, pnl: 1, pnl_pct: 1,
      holding_bars: 1, commission: 0, entry_bar_index: 1, exit_bar_index: 2,
      entry_ts_ms: 1, exit_ts_ms: 2,
    };
    const c = clientWith(async () => respond(200, {
      ok: true,
      content: { run_id: 'r', trades: [trade] },
    }));
    expect(await c.call('get_strategy_trades')).toEqual(failed('NexusParseError'));
  });

  it('classifies every documented status', () => {
    expect(classify(401, 'get_strategy_metrics', '').name).toBe('NexusAuthError');
    expect(classify(400, 'get_strategy_signal', '').name).toBe('NexusBadRequestError');
    expect(classify(404, 'get_strategy_metrics', '').name).toBe('NexusNotPublishedError');
    expect(classify(404, 'nope', '').name).toBe('NexusUnknownToolError');
    expect(classify(429, 'run_backtest', '').name).toBe('NexusRateLimitError');
    expect(classify(503, 'get_macro', '').name).toBe('NexusUpstreamError');
  });

  it('knows all 18 tools the gateway serves', () => {
    expect(KNOWN_TOOLS.size).toBe(18);
    expect(KNOWN_TOOLS.has('get_historical_coverage')).toBe(true);
  });
});

describe('cassette replay — how a reviewer with no key reproduces receipts', () => {
  it('names cassettes by tool, symbol and as_of', () => {
    expect(cassetteName('get_strategy_metrics', {})).toBe('get_strategy_metrics.json');
    expect(cassetteName('get_strategy_signal', { symbol: 'BTC/USDT' })).toBe('get_strategy_signal.BTC-USDT.json');
    expect(cassetteName('get_historical_funding', { symbol: 'BTC/USDT', as_of: '2026-09-17' })).toBe(
      'get_historical_funding.BTC-USDT.2026-09-17.json',
    );
  });

  it('serves the recorded metrics with no network and no API key', async () => {
    const c = new NexusClient({ mode: 'replay', fixtureDir: 'fixtures' });
    const got = await c.call<Metrics>('get_strategy_metrics');
    expect(got.ok).toBe(true);
    if (got.ok) {
      expect(got.value.sharpe_ratio).toBe(0.2989);
      expect(got.value.status).toBe('NOT_QUALIFIED');
    }
  });

  it('treats a missing cassette as absent, so DATA_GAP carries the refusal', async () => {
    const c = new NexusClient({ mode: 'replay', fixtureDir: 'fixtures' });
    expect(await c.call('get_fear_greed')).toEqual(absent());
  });
});

describe('TtlCache', () => {
  it('serves a hit inside the window', () => {
    let t = 0;
    const cache = new TtlCache(60_000, () => t);
    cache.set('k', present(1));
    t = 59_000;
    expect(cache.get('k')).toEqual(present(1));
  });

  it('expires past the window', () => {
    let t = 0;
    const cache = new TtlCache(60_000, () => t);
    cache.set('k', present(1));
    t = 61_000;
    expect(cache.get('k')).toBeUndefined();
  });

  it('never caches a failure — a transient 502 must not pin a refusal', () => {
    const cache = new TtlCache(60_000);
    cache.set('k', failed('NexusUpstreamError'));
    expect(cache.get('k')).toBeUndefined();
  });

  it('does cache an absence, which is a real and stable fact', () => {
    const cache = new TtlCache(60_000);
    cache.set('k', absent());
    expect(cache.get('k')).toEqual(absent());
  });
});

describe('as_of resolution — the thing that would have made EXECUTE unreachable', () => {
  it('uses the last date Nexus actually has', () => {
    const coverage = present<Coverage>({ start: '2025-01-01', end: '2026-09-16' });
    expect(resolveAsOf(coverage, '2026-09-18')).toBe('2026-09-16');
  });

  it('falls back to today when coverage is unavailable — DATA_GAP still refuses', () => {
    expect(resolveAsOf(failed('NexusTimeoutError'), '2026-09-18')).toBe('2026-09-18');
  });

  it('accepts the plausible field spellings, since catalog.json pins none', () => {
    for (const k of ['end', 'end_date', 'latest', 'to', 'max_date', 'last']) {
      expect(resolveAsOf(present({ [k]: '2026-09-16' } as Coverage), '2026-09-18')).toBe('2026-09-16');
    }
  });

  it('trims a datetime down to a date', () => {
    expect(resolveAsOf(present({ end: '2026-09-16T00:00:00Z' } as Coverage), '2026-09-18')).toBe('2026-09-16');
  });

  // The live bug: an unrecognised shape yielded `undefined`, which flowed into
  // get_historical_funding(as_of) and produced a receipt with no as_of at all.
  it('NEVER returns undefined for an unrecognised coverage shape', () => {
    const weird = present({ coverage: { first: 'x' } } as unknown as Coverage);
    const got = resolveAsOf(weird, '2026-09-18');
    expect(got).toBe('2026-09-18');
    expect(got).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('formats today as a UTC ISO date', () => {
    expect(todayIso(Date.UTC(2026, 8, 18, 23, 59))).toBe('2026-09-18');
  });
});

describe('fetchAll', () => {
  it('issues the seven data calls in parallel after resolving coverage', async () => {
    const started: string[] = [];
    let inFlight = 0;
    let maxInFlight = 0;
    const c = new NexusClient({
      mode: 'live',
      apiKey: 'test-api-key',
      sleep: noSleep,
      fetchImpl: async (_url, init) => {
        const name = JSON.parse(String((init as RequestInit).body)).name as string;
        started.push(name);
        inFlight++;
        maxInFlight = Math.max(maxInFlight, inFlight);
        await new Promise((r) => setImmediate(r));
        inFlight--;
        const payload = validPayload(name);
        return respond(200, { ok: true, content: payload });
      },
    });

    const res = await fetchAll(c, 'BTC/USDT', Date.UTC(2026, 8, 18), new TtlCache(60_000));
    expect(res.asOf).toBe('2026-09-16');
    expect(started[0]).toBe('get_historical_coverage');
    expect(maxInFlight).toBeGreaterThan(1);
    // coverage, then signal/metrics/equity/trades/funding/OI(as_of)/OI(as_of-1)
    expect(started).toHaveLength(8);
    expect(started.filter((n) => n === 'get_open_interest')).toHaveLength(2);
  });

  it('one failing call does not prevent the other six from returning', async () => {
    const c = new NexusClient({
      mode: 'live',
      apiKey: 'test-api-key',
      sleep: noSleep,
      fetchImpl: async (_url, init) => {
        const name = JSON.parse(String((init as RequestInit).body)).name as string;
        if (name === 'get_open_interest') return respond(502, 'down');
        const payload = validPayload(name);
        return respond(200, { ok: true, content: payload });
      },
    });

    const { data } = await fetchAll(c, 'BTC/USDT', Date.UTC(2026, 8, 18), new TtlCache(60_000));
    expect(data.openInterest).toEqual(failed('NexusUpstreamError'));
    expect(data.signal.ok).toBe(true);
    expect(data.metrics.ok).toBe(true);
    expect(data.funding.ok).toBe(true);
  });

  it('passes the resolved as_of to the point-in-time calls, plus the day before for OI', async () => {
    const seen: Record<string, unknown> = {};
    const oiCalls: unknown[] = [];
    const c = new NexusClient({
      mode: 'live',
      apiKey: 'test-api-key',
      sleep: noSleep,
      fetchImpl: async (_url, init) => {
        const parsed = JSON.parse(String((init as RequestInit).body)) as { name: string; arguments: Record<string, unknown> };
        seen[parsed.name] = parsed.arguments;
        if (parsed.name === 'get_open_interest') oiCalls.push(parsed.arguments);
        const payload = validPayload(parsed.name);
        if ('symbol' in payload && typeof parsed.arguments['symbol'] === 'string') {
          payload['symbol'] = parsed.arguments['symbol'];
        }
        return respond(200, { ok: true, content: payload });
      },
    });

    await fetchAll(c, 'ETH/USDT', Date.UTC(2026, 8, 18), new TtlCache(60_000));
    expect(seen['get_historical_funding']).toEqual({ as_of: '2026-09-16', symbol: 'ETH/USDT' });
    // Two OI calls: the resolved date and the day before it, so OI_SHOCK has a
    // baseline to diff against without a gateway-supplied one.
    expect(oiCalls).toEqual([
      { as_of: '2026-09-16', symbol: 'ETH/USDT' },
      { as_of: '2026-09-15', symbol: 'ETH/USDT' },
    ]);
  });
});

describe('payload validation must accept what the gateway actually sends', () => {
  const liveOiShape = {
    symbol: 'ETH/USDT',
    as_of_date: '2026-06-19',
    price: 1710.31,
    open_interest: 2321976.899,
    open_interest_usd: 4168370053.5,
    long_short_ratio: 1.52186879,
    funding_rate: -2.7e-7,
  };

  // Requiring open_interest_prev rejected every live payload as a parse error,
  // which failed DATA_GAP and abstained on everything. It was invisible only
  // because a HOLD signal used to bypass the gate entirely.
  it('accepts a live get_open_interest payload with no open_interest_prev', async () => {
    const c = clientWith(async () => respond(200, { ok: true, content: liveOiShape }));
    const r = await c.call('get_open_interest', { symbol: 'ETH/USDT', as_of: '2026-06-19' });
    expect(r.ok).toBe(true);
  });

  it('still rejects a non-positive baseline when the gateway does send one', async () => {
    const c = clientWith(async () =>
      respond(200, { ok: true, content: { ...liveOiShape, open_interest_prev: 0 } }),
    );
    expect(await c.call('get_open_interest', { symbol: 'ETH/USDT', as_of: '2026-06-19' })).toEqual(
      failed('NexusParseError'),
    );
  });

  // Nexus returns null open_interest for some (symbol, date) pairs. A usable
  // payload must validate; a null one must fail closed rather than be treated
  // as a real reading of zero.
  it('accepts every recorded OI cassette that carries a usable reading', async () => {
    const c = new NexusClient({ mode: 'replay', fixtureDir: 'fixtures' });
    const { readdirSync, readFileSync } = await import('node:fs');
    const files = readdirSync('fixtures').filter((f) => f.startsWith('get_open_interest.'));
    expect(files.length).toBeGreaterThan(10);

    let usable = 0;
    let nulled = 0;
    for (const f of files) {
      const [, sym, date] = f.replace('.json', '').split('.');
      const content = JSON.parse(readFileSync(`fixtures/${f}`, 'utf8')).content as Record<string, unknown>;
      const r = await c.call('get_open_interest', { symbol: sym!.replace('-', '/'), as_of: date! });
      if (content['open_interest'] === null) {
        expect(r.ok, `${f} has a null reading and must fail closed`).toBe(false);
        nulled++;
      } else {
        expect(r.ok, `${f} is usable and must validate`).toBe(true);
        usable++;
      }
    }
    expect(usable).toBeGreaterThan(0);
    // Documents the gateway behaviour rather than pretending it does not happen.
    expect(usable + nulled).toBe(files.length);
  });
});

describe('coverage field names — guessed wrong once already', () => {
  it('reads the live {first, last} shape', () => {
    expect(resolveAsOf(present({ first: '2021-01-01', last: '2026-09-18' } as Coverage), '2026-09-30'))
      .toBe('2026-09-18');
  });

  it('still reads the {start, end} shape', () => {
    expect(resolveAsOf(present({ start: '2025-01-01', end: '2026-09-16' } as Coverage), '2026-09-30'))
      .toBe('2026-09-16');
  });
});
