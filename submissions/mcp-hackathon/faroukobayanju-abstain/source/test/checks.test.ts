import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  correlatedCluster,
  dataGap,
  drawdownBudget,
  duplicate,
  fundingRegime,
  lossStreak,
  notQualified,
  oiShock,
  runGate,
  signalStale,
  sizeBound,
} from '../src/gate/index.js';
import { mergePolicy, policyDiff, policyHash } from '../src/policy/index.js';
import { PercentParseError, parsePercentString } from '../src/util/parse.js';
import {
  AFTER_CLUSTER_MS,
  BAR_50_MS,
  BASE_POLICY,
  COVERAGE,
  EQUITY_DRAWDOWN,
  SIGNAL_HOLD,
  TRADES_CLUSTER,
  absent,
  buyingSignal,
  failed,
  hostileFunding,
  makeInput,
  present,
  shockedOi,
} from './helpers.js';

const STRICT = mergePolicy(BASE_POLICY, 'strict');
const PERMISSIVE = mergePolicy(BASE_POLICY, 'permissive');

describe('#1 SIGNAL_STALE', () => {
  it('passes a fresh signal', () => {
    const r = signalStale(makeInput(), STRICT);
    expect(r.verdict).toBe('PASS');
  });

  it('fails one second past the threshold', () => {
    const ts = 1789682946;
    const now = ts * 1000 + (STRICT.max_signal_age_s + 1) * 1000;
    const r = signalStale(makeInput({ now, data: { signal: present(buyingSignal(ts)) } }), STRICT);
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe(1801);
    expect(r.threshold).toBe(1800);
  });

  it('passes exactly at the threshold (boundary is inclusive)', () => {
    const ts = 1789682946;
    const now = ts * 1000 + STRICT.max_signal_age_s * 1000;
    const r = signalStale(makeInput({ now, data: { signal: present(buyingSignal(ts)) } }), STRICT);
    expect(r.verdict).toBe('PASS');
    expect(r.observed).toBe(1800);
  });

  it('fails closed when the signal timestamp is in the future', () => {
    const now = 1_789_682_946_000;
    const r = signalStale(makeInput({
      now,
      data: { signal: present(buyingSignal(now / 1000 + 1)) },
    }), STRICT);
    expect(r.verdict).toBe('FAIL');
    expect(r.reason).toBe('signal timestamp is in the future');
  });

  it('skips when the signal could not be read, naming the outcome', () => {
    const r = signalStale(makeInput({ data: { signal: failed('NexusTimeoutError') } }), STRICT);
    expect(r.verdict).toBe('SKIPPED');
    expect(r.source).toMatchObject({ outcome: 'failed', error: 'NexusTimeoutError' });
  });
});

describe('#2 NOT_QUALIFIED', () => {
  it('fails under strict policy and names the failing sub-gate', () => {
    const r = notQualified(makeInput({ data: { metrics: present({ ...BASE_METRICS() }) } }), STRICT);
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe('NOT_QUALIFIED');
    expect(r.detail?.['sharpe_ratio']).toMatchObject({ observed: 0.2989, gate: '> 2.0', pass: false });
    expect(r.detail?.['trading_period_days']).toMatchObject({ pass: true });
    expect(r.detail?.['estimated_aum_usdt']).toMatchObject({ pass: true });
  });

  it('is skipped under permissive policy', () => {
    const r = notQualified(makeInput({ data: { metrics: present(BASE_METRICS()) } }), PERMISSIVE);
    expect(r.verdict).toBe('SKIPPED');
    expect(r.reason).toContain('require_qualified');
  });

  it('passes when the strategy actually qualifies', () => {
    const r = notQualified(makeInput(), STRICT);
    expect(r.verdict).toBe('PASS');
  });
});

describe('#3 FUNDING_REGIME', () => {
  it('fails a BUY into strongly positive funding', () => {
    const r = fundingRegime(makeInput({ side: 'BUY', data: { funding: present(hostileFunding) } }), STRICT);
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe(0.0019);
    expect(r.detail).toMatchObject({ pays_to_hold: true });
  });

  it('passes a SELL into the same funding — direction matters', () => {
    const r = fundingRegime(makeInput({ side: 'SELL', data: { funding: present(hostileFunding) } }), STRICT);
    expect(r.verdict).toBe('PASS');
  });

  it('skips when funding is absent for the resolved as_of', () => {
    const r = fundingRegime(makeInput({ data: { funding: absent() } }), STRICT);
    expect(r.verdict).toBe('SKIPPED');
    expect(r.reason).toContain('2026-09-17');
  });
});

describe('#4 OI_SHOCK', () => {
  it('fails a 25% one-day move', () => {
    const r = oiShock(makeInput({ data: { openInterest: present(shockedOi) } }), STRICT);
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe(25);
  });

  it('passes a calm move', () => {
    expect(oiShock(makeInput(), STRICT).verdict).toBe('PASS');
  });

  it('skips rather than inventing a baseline when there is no previous snapshot', () => {
    const r = oiShock(
      makeInput({ data: { openInterest: present({ symbol: 'BTC/USDT', as_of_date: '2026-09-17', open_interest: 1 }) } }),
      STRICT,
    );
    expect(r.verdict).toBe('SKIPPED');
    expect(r.reason).toContain('previous');
  });
});

describe('#5 DRAWDOWN_BUDGET', () => {
  it('reproduces the reported 7.62% drawdown from the real equity curve', () => {
    const r = drawdownBudget(makeInput({ data: { equity: present(EQUITY_DRAWDOWN) } }), STRICT);
    expect(r.observed).toBe(7.62);
    expect(r.verdict).toBe('FAIL');
    expect(r.threshold).toBe(5);
  });

  it('reports the sample count so precision is not overclaimed', () => {
    const r = drawdownBudget(makeInput({ data: { equity: present(EQUITY_DRAWDOWN) } }), STRICT);
    expect(r.detail?.['sample_count']).toBe(7);
  });

  it('passes a flat curve', () => {
    expect(drawdownBudget(makeInput(), STRICT).verdict).toBe('PASS');
  });
});

describe('#6 CORRELATED_CLUSTER — the bar-50 evidence', () => {
  it('refuses a BTC long while ETH and SOL are open long at bar 50', () => {
    const r = correlatedCluster(
      makeInput({ now: BAR_50_MS, side: 'BUY', data: { trades: present(TRADES_CLUSTER) } }),
      STRICT,
    );
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe(3);
    expect(r.threshold).toBe(2);
    expect(r.detail?.['concurrent_symbols']).toEqual(['ETH/USDT', 'SOL/USDT']);
  });

  it('allows the same proposal once the cluster has closed', () => {
    const r = correlatedCluster(
      makeInput({ now: AFTER_CLUSTER_MS, side: 'BUY', data: { trades: present(TRADES_CLUSTER) } }),
      STRICT,
    );
    expect(r.verdict).toBe('PASS');
    expect(r.observed).toBe(1);
  });

  it('does not count opposite-direction positions as correlated', () => {
    const r = correlatedCluster(
      makeInput({ now: BAR_50_MS, side: 'SELL', data: { trades: present(TRADES_CLUSTER) } }),
      STRICT,
    );
    expect(r.verdict).toBe('PASS');
  });

  it('fails on the single-symbol sub-condition before reading trades', () => {
    const r = correlatedCluster(
      makeInput({ notional: 25_000, accountEquity: 100_000, data: { trades: absent() } }),
      STRICT,
    );
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe(25);
    expect(r.reason).toContain('single-symbol');
  });
});

describe('#7 LOSS_STREAK', () => {
  it('fails at three consecutive closed losers', () => {
    const r = lossStreak(
      makeInput({ now: AFTER_CLUSTER_MS, data: { trades: present(TRADES_CLUSTER) } }),
      STRICT,
    );
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe(3);
  });

  it('only counts trades already closed at the decision time', () => {
    const r = lossStreak(makeInput({ now: BAR_50_MS, data: { trades: present(TRADES_CLUSTER) } }), STRICT);
    expect(r.verdict).toBe('PASS');
    expect(r.observed).toBe(0);
  });

  it('passes when the last closed trade was a winner', () => {
    expect(lossStreak(makeInput(), STRICT).verdict).toBe('PASS');
  });
});

describe('#8 DATA_GAP — the fail-closed carrier', () => {
  it('passes when every datum is present and coverage spans as_of', () => {
    const r = dataGap(makeInput());
    expect(r.verdict).toBe('PASS');
    expect(r.observed).toBe(0);
  });

  it('fails and distinguishes absent from failed', () => {
    const r = dataGap(makeInput({ data: { funding: absent(), openInterest: failed('NexusTimeoutError') } }));
    expect(r.verdict).toBe('FAIL');
    expect(r.observed).toBe(2);
    expect(r.detail?.['missing']).toEqual([
      { name: 'funding', call: 'get_historical_funding', outcome: 'absent' },
      { name: 'openInterest', call: 'get_open_interest', outcome: 'failed', error: 'NexusTimeoutError' },
    ]);
  });

  it('fails when as_of falls outside the published coverage window', () => {
    const r = dataGap(makeInput({ asOf: '2030-01-01' }));
    expect(r.verdict).toBe('FAIL');
    expect(r.reason).toContain('outside coverage');
  });
});

describe('#9 SIZE_BOUND', () => {
  it('passes inside the band', () => {
    expect(sizeBound(makeInput(), STRICT).verdict).toBe('PASS');
  });
  it('fails below min_notional', () => {
    const r = sizeBound(makeInput({ notional: 1 }), STRICT);
    expect(r.verdict).toBe('FAIL');
    expect(r.reason).toContain('below');
  });
  it('fails above max_notional', () => {
    const r = sizeBound(makeInput({ notional: 999_999 }), STRICT);
    expect(r.verdict).toBe('FAIL');
    expect(r.reason).toContain('above');
  });
});

describe('#10 DUPLICATE', () => {
  it('passes an unseen signal id', () => {
    expect(duplicate(makeInput()).verdict).toBe('PASS');
  });
  it('fails a signal id already in the chain', () => {
    const r = duplicate(makeInput({ signalId: 'sig_x', seen: ['sig_x'] }));
    expect(r.verdict).toBe('FAIL');
  });
});

describe('gate runner', () => {
  it('returns EXECUTE with all ten checks recorded when nothing fails', () => {
    const out = runGate(makeInput(), STRICT);
    expect(out.verdict).toBe('EXECUTE');
    expect(out.checks).toHaveLength(10);
  });

  it('runs every check even after one fails — the limits are the evidence', () => {
    const out = runGate(makeInput({ data: { funding: present(hostileFunding) } }), STRICT);
    expect(out.verdict).toBe('ABSTAIN');
    expect(out.checks).toHaveLength(10);
    expect(out.checks.filter((c) => c.verdict === 'PASS').length).toBeGreaterThan(5);
  });

  it('routes HOLD to NO_TRADE with a receipt and an empty checks array', () => {
    const out = runGate(makeInput({ data: { signal: present(SIGNAL_HOLD) } }), STRICT);
    expect(out.verdict).toBe('NO_TRADE');
    expect(out.checks).toEqual([]);
    expect(out.reason).toContain('HOLD');
  });

  it('fails closed to ABSTAIN when Nexus is unreachable', () => {
    const out = runGate(
      makeInput({
        data: {
          signal: failed('NexusAuthError'),
          metrics: failed('NexusAuthError'),
          equity: failed('NexusAuthError'),
          trades: failed('NexusAuthError'),
          funding: failed('NexusAuthError'),
          openInterest: failed('NexusAuthError'),
          coverage: failed('NexusAuthError'),
        },
      }),
      STRICT,
    );
    expect(out.verdict).toBe('ABSTAIN');
    expect(out.checks.find((c) => c.id === 'DATA_GAP')?.verdict).toBe('FAIL');
  });

  it('records the resolved as_of so the decision can be re-fetched', () => {
    expect(runGate(makeInput({ asOf: '2026-06-23' }), STRICT).asOf).toBe('2026-06-23');
  });

  it('same signal, two policies, two verdicts', () => {
    const input = makeInput({ data: { metrics: present(BASE_METRICS()) } });
    expect(runGate(input, STRICT).verdict).toBe('ABSTAIN');
    expect(runGate(input, PERMISSIVE).verdict).toBe('EXECUTE');
  });
});

describe('policy', () => {
  it('strict and permissive differ in exactly one key', () => {
    expect(policyDiff(STRICT, PERMISSIVE)).toEqual(['require_qualified']);
  });

  it('hashes the merged result, not the file', () => {
    expect(policyHash(STRICT)).not.toBe(policyHash(PERMISSIVE));
    expect(policyHash(STRICT)).toBe(policyHash({ ...BASE_POLICY, require_qualified: true }));
  });

  it('is key-order independent', () => {
    const reversed = Object.fromEntries(Object.entries(STRICT).reverse()) as typeof STRICT;
    expect(policyHash(reversed)).toBe(policyHash(STRICT));
  });
});

describe('policy.base.json artifact', () => {
  it('is identical to the bundled module, so the two cannot drift', () => {
    const onDisk = JSON.parse(readFileSync('policy.base.json', 'utf8'));
    expect(onDisk).toEqual({ ...BASE_POLICY });
  });
});

describe('parsePercentString', () => {
  it('parses the percent string Nexus actually returns', () => {
    expect(parsePercentString('7.62%')).toBe(7.62);
  });
  it('accepts a bare number', () => {
    expect(parsePercentString(1.0697)).toBe(1.0697);
  });
  it('throws rather than returning NaN, so a bad parse cannot pass a threshold', () => {
    expect(() => parsePercentString('n/a')).toThrow(PercentParseError);
    expect(() => parsePercentString(undefined)).toThrow(PercentParseError);
  });
});

/** The real metrics payload: NOT_QUALIFIED on sharpe alone. */
function BASE_METRICS() {
  return {
    sharpe_ratio: 0.2989,
    trading_period_days: 90,
    estimated_aum_usdt: 100000.0,
    profit_factor: 1.1497,
    max_drawdown: '7.62%',
    total_return_pct: 1.0697,
    win_rate_pct: 52.63,
    trade_count: 19,
    status: 'NOT_QUALIFIED' as const,
  };
}
