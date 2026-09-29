/**
 * Checks that need only the proposal, the signal, and local chain state.
 * No market data, so these never contribute to DATA_GAP.
 */
import type { CheckResult, GateInput, Policy } from '../../types.js';
import { secondsToMs } from '../../util/parse.js';

/**
 * #1 SIGNAL_STALE — a signal older than the live tick cadence is not a
 * current opinion. Nexus emits at 15m in this deployment, so the default
 * 1800s allows one missed tick before refusing.
 */
export function signalStale(input: GateInput, policy: Policy): CheckResult {
  const { signal } = input.data;
  if (!signal.ok) {
    return {
      id: 'SIGNAL_STALE',
      verdict: 'SKIPPED',
      observed: null,
      threshold: policy.max_signal_age_s,
      unit: 's',
      source: { call: 'get_strategy_signal', outcome: signal.outcome, ...(signal.error ? { error: signal.error } : {}) },
      reason: `signal ${signal.outcome}; DATA_GAP carries the refusal`,
    };
  }

  const ageS = (input.now - secondsToMs(signal.value.timestamp)) / 1000;
  const invalidFuture = ageS < 0;
  return {
    id: 'SIGNAL_STALE',
    verdict: invalidFuture || ageS > policy.max_signal_age_s ? 'FAIL' : 'PASS',
    observed: Number(ageS.toFixed(1)),
    threshold: policy.max_signal_age_s,
    unit: 's',
    source: { call: 'get_strategy_signal', outcome: 'ok' },
    ...(invalidFuture ? { reason: 'signal timestamp is in the future' } : {}),
  };
}

/**
 * #9 SIZE_BOUND — a notional outside the configured band is a malformed
 * proposal, not a market judgement. Pure input validation, checked here so it
 * lands in the receipt like everything else rather than 400-ing silently.
 */
export function sizeBound(input: GateInput, policy: Policy): CheckResult {
  const n = input.proposal.notional;
  const outOfBand = n < policy.min_notional || n > policy.max_notional;
  return {
    id: 'SIZE_BOUND',
    verdict: outOfBand ? 'FAIL' : 'PASS',
    observed: n,
    threshold: `${policy.min_notional}..${policy.max_notional}`,
    unit: 'USDT',
    source: null,
    ...(outOfBand
      ? { reason: n < policy.min_notional ? 'below min_notional' : 'above max_notional' }
      : {}),
  };
}

/**
 * #10 DUPLICATE — replay protection. A signal id already committed to the
 * receipt chain must not be acted on twice; without this, a retried request
 * doubles a position and the chain records two authorizations for one decision.
 */
export function duplicate(input: GateInput): CheckResult {
  const seen = input.seenSignalIds.has(input.proposal.signalId);
  return {
    id: 'DUPLICATE',
    verdict: seen ? 'FAIL' : 'PASS',
    observed: input.proposal.signalId,
    threshold: 'unseen',
    unit: null,
    source: null,
    ...(seen ? { reason: 'signal_id already present in the receipt chain' } : {}),
  };
}

/**
 * #11 SIGNAL_SUPPORT — does the strategy's current signal back this proposal?
 *
 * Until 2026-09-18 a HOLD signal short-circuited the whole gate to NO_TRADE.
 * That was wrong twice over. Abstain gates what an agent PROPOSES, not what
 * the strategy happens to be emitting, and an agent proposing a BUY into a
 * HOLD is exactly the case most worth refusing. It also meant that in
 * production, where this strategy sits at HOLD nearly always, the gate never
 * actually ran: 70 consecutive receipts contained zero checks.
 *
 *   signal BUY  + proposal BUY   ⇒ PASS
 *   signal BUY  + proposal SELL  ⇒ FAIL  (proposal contradicts the strategy)
 *   signal HOLD + any proposal   ⇒ FAIL  (no directional signal backs it)
 *   signal unavailable           ⇒ SKIPPED (DATA_GAP carries the refusal)
 */
export function signalSupport(input: GateInput, policy: Policy): CheckResult {
  const { signal } = input.data;
  const side = input.proposal.side;

  if (!policy.require_signal_support) {
    return {
      id: 'SIGNAL_SUPPORT',
      verdict: 'SKIPPED',
      observed: signal.ok ? signal.value.trade_intent : null,
      threshold: side,
      unit: null,
      source: null,
      reason: 'require_signal_support is false in this policy',
    };
  }

  if (!signal.ok) {
    return {
      id: 'SIGNAL_SUPPORT',
      verdict: 'SKIPPED',
      observed: null,
      threshold: side,
      unit: null,
      source: {
        call: 'get_strategy_signal',
        outcome: signal.outcome,
        ...(signal.error ? { error: signal.error } : {}),
      },
      reason: `signal ${signal.outcome}; DATA_GAP carries the refusal`,
    };
  }

  const intent = signal.value.trade_intent;
  const supported = intent === side;
  return {
    id: 'SIGNAL_SUPPORT',
    verdict: supported ? 'PASS' : 'FAIL',
    observed: intent,
    threshold: side,
    unit: null,
    source: { call: 'get_strategy_signal', outcome: 'ok' },
    ...(supported
      ? {}
      : {
          reason:
            intent === 'HOLD'
              ? `strategy signals HOLD; no directional signal backs a ${side}`
              : `strategy signals ${intent}; proposal is ${side}`,
        }),
    detail: {
      trade_intent: intent,
      proposed_side: side,
      ...(signal.value.confidence !== undefined ? { confidence: signal.value.confidence } : {}),
    },
  };
}
