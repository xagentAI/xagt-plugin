import { describe, expect, it } from "vitest";

import { isPaymentIntentId, newPaymentIntentId, newRequestId } from "@/lib/ids";

describe("newPaymentIntentId", () => {
  it("produces pi_ + 32 base64url characters (192 bits)", () => {
    const id = newPaymentIntentId();
    expect(id).toMatch(/^pi_[A-Za-z0-9_-]{32}$/);
    expect(id).toHaveLength(35);
    expect(Buffer.from(id.slice(3), "base64url")).toHaveLength(24);
  });

  it("is unique and non-sequential across many draws", () => {
    const ids = Array.from({ length: 2000 }, () => newPaymentIntentId());
    expect(new Set(ids).size).toBe(ids.length);
    const sorted = [...ids].sort();
    expect(sorted).not.toEqual(ids);
  });

  it("is distinct from request IDs", () => {
    expect(newRequestId()).toMatch(/^req_/);
    expect(isPaymentIntentId(newRequestId())).toBe(false);
  });
});

describe("isPaymentIntentId", () => {
  it("accepts generated IDs", () => {
    expect(isPaymentIntentId(newPaymentIntentId())).toBe(true);
  });

  it.each([
    "",
    "pi_",
    "pi_short",
    `pi_${"a".repeat(31)}`,
    `pi_${"a".repeat(33)}`,
    `pi_${"a".repeat(31)}+`,
    `pi_${"a".repeat(31)}/`,
    `pi_${"a".repeat(31)}=`,
    `PI_${"a".repeat(32)}`,
    `req_${"a".repeat(32)}`,
    "550e8400-e29b-41d4-a716-446655440000",
    42,
    null,
    undefined,
  ])("rejects %j", (value) => {
    expect(isPaymentIntentId(value)).toBe(false);
  });
});
