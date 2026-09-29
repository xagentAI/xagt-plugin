import { describe, expect, it } from "vitest";

import {
  DEFAULT_REQUIRED_CONFIRMATIONS,
  MAX_INTENT_LIFETIME_MS,
  MAX_REQUIRED_CONFIRMATIONS,
  MIN_REQUIRED_CONFIRMATIONS,
  paymentIntentViolations,
  remainingAmountUnits,
} from "@/domain/payment-intent";

const NOW = new Date("2026-09-17T12:00:00.000Z");
const valid = {
  expectedAmountUnits: 850_000_000n,
  requiredConfirmations: DEFAULT_REQUIRED_CONFIRMATIONS,
  expiresAt: new Date(NOW.getTime() + 60 * 60 * 1000),
};

describe("paymentIntentViolations", () => {
  it("accepts a valid input", () => {
    expect(paymentIntentViolations(valid, NOW)).toEqual([]);
  });

  it("fixes the confirmation defaults and bounds", () => {
    expect(DEFAULT_REQUIRED_CONFIRMATIONS).toBe(3);
    expect(MIN_REQUIRED_CONFIRMATIONS).toBe(1);
    expect(MAX_REQUIRED_CONFIRMATIONS).toBe(64);
    expect(MAX_INTENT_LIFETIME_MS).toBe(7 * 24 * 60 * 60 * 1000);
  });

  it.each([1, 3, 64])("accepts requiredConfirmations = %d", (requiredConfirmations) => {
    expect(paymentIntentViolations({ ...valid, requiredConfirmations }, NOW)).toEqual([]);
  });

  it.each([0, 65, -1, 1.5, Number.NaN])("rejects requiredConfirmations = %s", (requiredConfirmations) => {
    expect(paymentIntentViolations({ ...valid, requiredConfirmations }, NOW)).toEqual([
      { field: "requiredConfirmations", message: "must be an integer between 1 and 64" },
    ]);
  });

  it("rejects non-positive amounts", () => {
    expect(paymentIntentViolations({ ...valid, expectedAmountUnits: 0n }, NOW)).toEqual([
      { field: "amount", message: "must be greater than zero" },
    ]);
    expect(paymentIntentViolations({ ...valid, expectedAmountUnits: -5n }, NOW)).toHaveLength(1);
  });

  it("rejects expiry at or before now", () => {
    expect(paymentIntentViolations({ ...valid, expiresAt: NOW }, NOW)).toEqual([
      { field: "expiresAt", message: "must be in the future" },
    ]);
    expect(paymentIntentViolations({ ...valid, expiresAt: new Date(NOW.getTime() - 1) }, NOW)).toHaveLength(1);
    expect(paymentIntentViolations({ ...valid, expiresAt: new Date(Number.NaN) }, NOW)).toHaveLength(1);
  });

  it("accepts exactly 7 days and rejects one millisecond more", () => {
    const limit = new Date(NOW.getTime() + MAX_INTENT_LIFETIME_MS);
    expect(paymentIntentViolations({ ...valid, expiresAt: limit }, NOW)).toEqual([]);
    expect(paymentIntentViolations({ ...valid, expiresAt: new Date(limit.getTime() + 1) }, NOW)).toEqual([
      { field: "expiresAt", message: "must be at most 7 days from now" },
    ]);
  });

  it("reports every violation at once", () => {
    const violations = paymentIntentViolations(
      { expectedAmountUnits: 0n, requiredConfirmations: 99, expiresAt: NOW },
      NOW,
    );
    expect(violations.map((violation) => violation.field)).toEqual([
      "amount",
      "requiredConfirmations",
      "expiresAt",
    ]);
  });
});

describe("remainingAmountUnits", () => {
  it("subtracts received from expected and floors at zero", () => {
    expect(remainingAmountUnits({ expectedAmountUnits: 850_000_000n, receivedAmountUnits: 0n })).toBe(850_000_000n);
    expect(remainingAmountUnits({ expectedAmountUnits: 850_000_000n, receivedAmountUnits: 500_000_000n })).toBe(
      350_000_000n,
    );
    expect(remainingAmountUnits({ expectedAmountUnits: 850_000_000n, receivedAmountUnits: 900_000_000n })).toBe(0n);
  });
});
