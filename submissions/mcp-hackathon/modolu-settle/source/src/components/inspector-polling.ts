/**
 * Browser polling policy for the inspector (ARCHITECTURE.md §8.3): reconcile
 * every 7 seconds while the page is open and the obligation can still change.
 * Pure so it can be tested without a DOM.
 */
import { isTerminalStatus, type PaymentStatus } from "@/lib/public-api";

export const POLL_INTERVAL_MS = 7_000;
/** Consecutive hard failures after which polling pauses rather than hammering the API. */
export const MAX_CONSECUTIVE_FAILURES = 3;

export interface PollingFacts {
  readonly status: PaymentStatus | null;
  readonly consecutiveFailures: number;
  readonly pageVisible: boolean;
  readonly reconciling: boolean;
}

export type PollingDecision =
  | "poll"
  | "stop:terminal"
  | "stop:failures"
  | "wait:hidden"
  | "wait:busy"
  | "wait:unloaded";

export function decidePolling(facts: PollingFacts): PollingDecision {
  if (facts.status === null) {
    return "wait:unloaded";
  }
  if (isTerminalStatus(facts.status)) {
    return "stop:terminal";
  }
  if (facts.consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
    return "stop:failures";
  }
  if (!facts.pageVisible) {
    return "wait:hidden";
  }
  if (facts.reconciling) {
    return "wait:busy";
  }
  return "poll";
}
