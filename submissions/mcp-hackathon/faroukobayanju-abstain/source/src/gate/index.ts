/**
 * The gate runner.
 *
 *   ┌─ trade_intent == HOLD ──▶ NO_TRADE   (checks[] empty, reason stated)
 *   │
 *   ├─ run ALL ten checks ─────▶ any FAIL  ──▶ ABSTAIN
 *   │                            otherwise ──▶ EXECUTE
 *   └─
 *
 * Every check runs every time. A receipt that stops at the first failure hides
 * the limits, and the limits are the evidence.
 *
 * Pure: no I/O, no clock, no randomness. `now` and `asOf` are supplied by the
 * caller, so the live API and the chart replay share this exact code path.
 */
import type { CheckResult, GateInput, GateOutcome, Policy } from '../types.js';
import { duplicate, signalStale, sizeBound } from './checks/proposal.js';
import { correlatedCluster, drawdownBudget, lossStreak, notQualified } from './checks/strategy.js';
import { fundingRegime, oiShock } from './checks/market.js';
import { dataGap } from './checks/data.js';

export function runGate(input: GateInput, policy: Policy): GateOutcome {
  // A HOLD proposes nothing, so there is nothing to authorize or refuse.
  // It still writes a receipt: a chain with holes invites the question of
  // what was left out.
  if (input.data.signal.ok && input.data.signal.value.trade_intent === 'HOLD') {
    return {
      verdict: 'NO_TRADE',
      checks: [],
      asOf: input.asOf,
      reason: 'strategy signal is HOLD; no trade proposed, so no gating required',
    };
  }

  const checks: CheckResult[] = [
    signalStale(input, policy),
    notQualified(input, policy),
    fundingRegime(input, policy),
    oiShock(input, policy),
    drawdownBudget(input, policy),
    correlatedCluster(input, policy),
    lossStreak(input, policy),
    dataGap(input),
    sizeBound(input, policy),
    duplicate(input),
  ];

  const failed = checks.filter((c) => c.verdict === 'FAIL');
  return {
    verdict: failed.length > 0 ? 'ABSTAIN' : 'EXECUTE',
    checks,
    asOf: input.asOf,
    ...(failed.length > 0
      ? { reason: failed.map((c) => c.id).join(', ') }
      : {}),
  };
}

export { signalStale, sizeBound, duplicate, notQualified, drawdownBudget, lossStreak, correlatedCluster, fundingRegime, oiShock, dataGap };
