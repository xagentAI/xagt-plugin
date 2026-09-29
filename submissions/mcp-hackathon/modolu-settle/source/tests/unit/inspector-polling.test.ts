import { describe, expect, it } from "vitest";

import { MAX_CONSECUTIVE_FAILURES, POLL_INTERVAL_MS, decidePolling } from "@/components/inspector-polling";
import type { PaymentStatus } from "@/lib/public-api";

const base = { consecutiveFailures: 0, pageVisible: true, reconciling: false };

describe("decidePolling", () => {
  it("polls every 7 seconds", () => {
    expect(POLL_INTERVAL_MS).toBe(7_000);
  });

  it.each<PaymentStatus>(["pending", "detected", "partial"])("continues polling for %s", (status) => {
    expect(decidePolling({ ...base, status })).toBe("poll");
  });

  it.each<PaymentStatus>(["paid", "overpaid", "expired", "ambiguous"])("stops polling for %s", (status) => {
    expect(decidePolling({ ...base, status })).toBe("stop:terminal");
  });

  it("waits until the intent has loaded", () => {
    expect(decidePolling({ ...base, status: null })).toBe("wait:unloaded");
  });

  it("stops after repeated hard failures and never on a terminal status regardless", () => {
    expect(decidePolling({ ...base, status: "pending", consecutiveFailures: MAX_CONSECUTIVE_FAILURES })).toBe("stop:failures");
    expect(decidePolling({ ...base, status: "pending", consecutiveFailures: MAX_CONSECUTIVE_FAILURES - 1 })).toBe("poll");
    expect(decidePolling({ ...base, status: "paid", consecutiveFailures: 99 })).toBe("stop:terminal");
  });

  it("waits while the tab is hidden or a reconciliation is in flight", () => {
    expect(decidePolling({ ...base, status: "detected", pageVisible: false })).toBe("wait:hidden");
    expect(decidePolling({ ...base, status: "detected", reconciling: true })).toBe("wait:busy");
  });
});
