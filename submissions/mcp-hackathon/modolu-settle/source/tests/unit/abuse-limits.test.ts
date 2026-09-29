/**
 * Semantic abuse bounds (ARCHITECTURE.md §2, §12) at their exact boundaries,
 * through the public request parser. These are code constants, never
 * deployment configuration.
 */
import { describe, expect, it } from "vitest";

import { MAX_INTENT_LIFETIME_MS } from "@/domain/payment-intent";
import { AppError } from "@/lib/errors";
import { parseCreatePaymentIntentRequest } from "@/validation/payment-intents";

const NOW = new Date("2026-09-18T12:00:00.000Z");
const RECIPIENT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const base = { chain: "base", asset: "USDC", amount: "1", recipient: RECIPIENT, expiresAt: "2026-09-19T12:00:00Z" };

function code(body: unknown): string | "OK" {
  try {
    parseCreatePaymentIntentRequest(body, NOW);
    return "OK";
  } catch (error) {
    return (error as AppError).code;
  }
}

describe("semantic abuse limits", () => {
  it("chain and asset are fixed", () => {
    expect(code({ ...base, chain: "base" })).toBe("OK");
    expect(code({ ...base, chain: "ethereum" })).toBe("UNSUPPORTED_CHAIN");
    expect(code({ ...base, chain: "BASE" })).toBe("UNSUPPORTED_CHAIN");
    expect(code({ ...base, asset: "USDT" })).toBe("UNSUPPORTED_ASSET");
    expect(code({ ...base, asset: "usdc" })).toBe("UNSUPPORTED_ASSET");
    expect(code({ ...base, tokenAddress: "0x00" })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, chainId: 8453 })).toBe("VALIDATION_ERROR");
  });

  it("requiredConfirmations is 1..64 inclusive", () => {
    expect(code({ ...base, requiredConfirmations: 1 })).toBe("OK");
    expect(code({ ...base, requiredConfirmations: 64 })).toBe("OK");
    expect(code({ ...base, requiredConfirmations: 0 })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, requiredConfirmations: 65 })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, requiredConfirmations: -1 })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, requiredConfirmations: 1e9 })).toBe("VALIDATION_ERROR");
  });

  it("intent lifetime is at most 7 days and strictly in the future", () => {
    expect(MAX_INTENT_LIFETIME_MS).toBe(7 * 24 * 60 * 60 * 1000);
    expect(code({ ...base, expiresAt: "2026-09-25T12:00:00.000Z" })).toBe("OK"); // exactly 7 days
    expect(code({ ...base, expiresAt: "2026-09-25T12:00:00.001Z" })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, expiresAt: "2026-09-18T12:00:00.000Z" })).toBe("VALIDATION_ERROR"); // == now
    expect(code({ ...base, expiresAt: "2026-09-18T12:00:00.001Z" })).toBe("OK");
    expect(code({ ...base, expiresAt: "2030-01-01T00:00:00Z" })).toBe("VALIDATION_ERROR");
  });

  it("amount is positive, at most 6 decimals, within parser bounds", () => {
    expect(code({ ...base, amount: "0.000001" })).toBe("OK");
    expect(code({ ...base, amount: "0.0000001" })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, amount: "0" })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, amount: "-1" })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, amount: `${"9".repeat(30)}.999999` })).toBe("OK"); // 30 integer digits
    expect(code({ ...base, amount: `${"9".repeat(31)}` })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, amount: "1e3" })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, amount: "Infinity" })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, amount: 25 })).toBe("VALIDATION_ERROR");
  });

  it("externalReference is at most 128 characters", () => {
    expect(code({ ...base, externalReference: "x".repeat(128) })).toBe("OK");
    expect(code({ ...base, externalReference: "x".repeat(129) })).toBe("VALIDATION_ERROR");
    expect(code({ ...base, externalReference: "<script>alert(1)</script>" })).toBe("OK"); // stored as text, rendered as text
  });

  it("addresses are validated with viem; the payer is optional but never lax", () => {
    expect(code({ ...base, recipient: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02914" })).toBe("INVALID_ADDRESS");
    expect(code({ ...base, recipient: "vitalik.eth" })).toBe("INVALID_ADDRESS");
    expect(code({ ...base, payer: "0x1234" })).toBe("INVALID_ADDRESS");
    expect(code({ ...base, payer: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045" })).toBe("OK");
  });

  it("unknown fields and non-object bodies are rejected", () => {
    expect(code({ ...base, extra: true })).toBe("VALIDATION_ERROR");
    expect(code([])).toBe("VALIDATION_ERROR");
    expect(code("string")).toBe("VALIDATION_ERROR");
    expect(code(null)).toBe("VALIDATION_ERROR");
  });
});
