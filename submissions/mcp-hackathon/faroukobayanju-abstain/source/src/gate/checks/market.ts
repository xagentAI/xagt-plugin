/**
 * Checks sourced from point-in-time market data. Both tools require an
 * `as_of` UTC date, which the caller resolves from get_historical_coverage and
 * records in the receipt — so a reviewer can re-fetch the same date and
 * reproduce the observed values.
 */
import type { CheckResult, GateInput, Policy } from '../../types.js';

/**
 * #3 FUNDING_REGIME — refuse to hold the side that is paying. Positive funding
 * means longs pay shorts, so a BUY into strongly positive funding bleeds carry;
 * a SELL into strongly negative funding does the same. Direction matters: a
 * large funding rate in your favour is not a reason to refuse.
 */
export function fundingRegime(input: GateInput, policy: Policy): CheckResult {
  const { funding } = input.data;
  if (!funding.ok) {
    return {
      id: 'FUNDING_REGIME',
      verdict: 'SKIPPED',
      observed: null,
      threshold: policy.max_funding_rate,
      unit: 'rate_per_8h',
      source: { call: 'get_historical_funding', outcome: funding.outcome, ...(funding.error ? { error: funding.error } : {}) },
      reason: `funding ${funding.outcome} for as_of=${input.asOf}; DATA_GAP carries the refusal`,
    };
  }

  const rate = funding.value.last_funding_rate;
  const against =
    input.proposal.side === 'BUY'
      ? rate > policy.max_funding_rate
      : rate < -policy.max_funding_rate;

  return {
    id: 'FUNDING_REGIME',
    verdict: against ? 'FAIL' : 'PASS',
    observed: rate,
    threshold: input.proposal.side === 'BUY' ? policy.max_funding_rate : -policy.max_funding_rate,
    unit: 'rate_per_8h',
    source: { call: 'get_historical_funding', outcome: 'ok' },
    detail: { side: input.proposal.side, as_of: input.asOf, pays_to_hold: against },
  };
}

/**
 * #4 OI_SHOCK — a large one-day move in open interest means positioning is
 * crowding or unwinding fast, which is when stops cluster. Needs the previous
 * snapshot; when the gateway omits it there is nothing to compare against and
 * the check skips rather than inventing a baseline.
 */
export function oiShock(input: GateInput, policy: Policy): CheckResult {
  const { openInterest } = input.data;
  if (!openInterest.ok) {
    return {
      id: 'OI_SHOCK',
      verdict: 'SKIPPED',
      observed: null,
      threshold: policy.max_oi_delta_pct,
      unit: '%',
      source: { call: 'get_open_interest', outcome: openInterest.outcome, ...(openInterest.error ? { error: openInterest.error } : {}) },
      reason: `open interest ${openInterest.outcome} for as_of=${input.asOf}; DATA_GAP carries the refusal`,
    };
  }

  const oi = openInterest.value;
  // Prefer a gateway-supplied baseline; otherwise use the previous UTC day,
  // which fetch-all now retrieves explicitly. Live responses omit
  // open_interest_prev entirely, which left this check permanently SKIPPED.
  const prevDatum = input.data.openInterestPrev;
  const prev = oi.open_interest_prev ?? (prevDatum.ok ? prevDatum.value.open_interest : undefined);
  if (prev === undefined || prev <= 0) {
    return {
      id: 'OI_SHOCK',
      verdict: 'SKIPPED',
      observed: oi.open_interest,
      threshold: policy.max_oi_delta_pct,
      unit: '%',
      source: { call: 'get_open_interest', outcome: 'absent' },
      reason: `no previous open-interest snapshot to diff against (prev day ${prevDatum.ok ? 'present but zero' : prevDatum.outcome})`,
    };
  }

  const deltaPct = (Math.abs(oi.open_interest - prev) / prev) * 100;
  return {
    id: 'OI_SHOCK',
    verdict: deltaPct > policy.max_oi_delta_pct ? 'FAIL' : 'PASS',
    observed: Number(deltaPct.toFixed(2)),
    threshold: policy.max_oi_delta_pct,
    unit: '%',
    source: { call: 'get_open_interest', outcome: 'ok' },
    detail: {
      open_interest: oi.open_interest,
      previous: prev,
      as_of: input.asOf,
      baseline: oi.open_interest_prev !== undefined ? 'gateway' : 'previous_utc_day',
    },
  };
}
