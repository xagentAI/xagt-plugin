/**
 * #8 DATA_GAP — the fail-closed carrier.
 *
 * Every other check that cannot read its input returns SKIPPED and points here.
 * This one turns "we could not see" into a refusal, so a Nexus outage, an
 * expired key, or an unpublished snapshot can never be mistaken for permission
 * to trade. Without it, missing data would silently become EXECUTE, and a gate
 * that authorizes on no information is worse than no gate.
 *
 * `absent` and `failed` stay distinct in the receipt: "Nexus has no OI snapshot
 * for this date" and "the OI call timed out" are different facts.
 */
import type {
  Policy, CheckResult, Datum, GateInput } from '../../types.js';
import { dateWithin } from '../../util/parse.js';

interface Required {
  name: string;
  call: string;
  datum: Datum<unknown>;
}

export function dataGap(input: GateInput, policy: Policy): CheckResult {
  const d = input.data;
  if (!policy.require_data_complete) {
    return {
      id: 'DATA_GAP',
      verdict: 'SKIPPED',
      observed: null,
      threshold: 0,
      unit: 'gaps',
      source: null,
      reason: 'require_data_complete is false in this policy',
    };
  }
  const required: Required[] = [
    { name: 'signal', call: 'get_strategy_signal', datum: d.signal },
    { name: 'metrics', call: 'get_strategy_metrics', datum: d.metrics },
    { name: 'equity', call: 'get_strategy_equity', datum: d.equity },
    { name: 'trades', call: 'get_strategy_trades', datum: d.trades },
    { name: 'funding', call: 'get_historical_funding', datum: d.funding },
    { name: 'openInterest', call: 'get_open_interest', datum: d.openInterest },
    { name: 'coverage', call: 'get_historical_coverage', datum: d.coverage },
  ];

  const missing = required
    .filter((r) => !r.datum.ok)
    .map((r) => {
      const bad = r.datum as Extract<Datum<unknown>, { ok: false }>;
      return { name: r.name, call: r.call, outcome: bad.outcome, ...(bad.error ? { error: bad.error } : {}) };
    });

  // Coverage must actually span the date the market checks were fetched for,
  // otherwise #3 and #4 read a window Nexus never had.
  // Only assert coverage when both bounds actually parsed. An unreadable
  // coverage payload is reported as a gap in `missing`, not silently ignored.
  let coverageGap: string | null = null;
  if (d.coverage.ok) {
    const cov = d.coverage.value as Record<string, unknown>;
    const pick = (keys: string[]): string | undefined => {
      for (const k of keys) {
        const v = cov[k];
        if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v)) return v.slice(0, 10);
      }
      return undefined;
    };
    const start = pick(['first', 'start', 'from', 'min_date']);
    const end = pick(['last', 'end', 'end_date', 'latest', 'to', 'max_date']);
    if (typeof start === 'string' && typeof end === 'string') {
      if (!dateWithin(input.asOf, start, end)) {
        coverageGap = `as_of=${input.asOf} outside coverage ${start}..${end}`;
      }
    } else {
      coverageGap = 'coverage payload has no readable start/end bounds';
    }
  }

  const failed = missing.length > 0 || coverageGap !== null;

  return {
    id: 'DATA_GAP',
    verdict: failed ? 'FAIL' : 'PASS',
    observed: missing.length + (coverageGap ? 1 : 0),
    threshold: 0,
    unit: 'gaps',
    source: null,
    ...(coverageGap ? { reason: coverageGap } : {}),
    detail: {
      as_of: input.asOf,
      missing,
      ...(d.coverage.ok ? { coverage: d.coverage.value } : {}),
    },
  };
}
