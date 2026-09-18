/**
 * The gate runner.
 *
 *   run ALL eleven checks ──▶ any FAIL  ──▶ ABSTAIN
 *                            otherwise ──▶ EXECUTE
 *
 * There is no bypass. A HOLD signal used to short-circuit to NO_TRADE with an
 * empty checks array; in production that meant the gate never ran at all.
 * A HOLD is now a failing SIGNAL_SUPPORT check, which is what it always was:
 * a reason to refuse, not a reason to skip.
 *
 * Every check runs every time. A receipt that stops at the first failure hides
 * the limits, and the limits are the evidence.
 *
 * Pure: no I/O, no clock, no randomness. `now` and `asOf` are supplied by the
 * caller, so the live API and the chart replay share this exact code path.
 */
import type { CheckResult, GateInput, GateOutcome, Policy } from '../types.js';
import { duplicate, signalStale, signalSupport, sizeBound } from './checks/proposal.js';
import { correlatedCluster, drawdownBudget, lossStreak, notQualified } from './checks/strategy.js';
import { fundingRegime, oiShock } from './checks/market.js';
import { dataGap } from './checks/data.js';

export function runGate(input: GateInput, policy: Policy): GateOutcome {
  const checks: CheckResult[] = [
    signalStale(input, policy),
    signalSupport(input, policy),
    notQualified(input, policy),
    fundingRegime(input, policy),
    oiShock(input, policy),
    drawdownBudget(input, policy),
    correlatedCluster(input, policy),
    lossStreak(input, policy),
    dataGap(input, policy),
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

export { signalStale, signalSupport, sizeBound, duplicate, notQualified, drawdownBudget, lossStreak, correlatedCluster, fundingRegime, oiShock, dataGap };
