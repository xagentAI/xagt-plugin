import { describe, expect, it } from "vitest";

import type { PaymentIntent } from "@/domain/payment-intent";
import { AppError } from "@/lib/errors";
import {
  parseCreatePaymentIntentRequest,
  parsePaymentIntentId,
  toPaymentIntentResponse,
} from "@/validation/payment-intents";

const NOW = new Date("2026-09-17T12:00:00.000Z");
const RECIPIENT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const PAYER = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045";

const validRequest = {
  externalReference: "INV-204",
  chain: "base",
  asset: "USDC",
  amount: "850.00",
  recipient: RECIPIENT,
  payer: PAYER,
  expiresAt: "2026-09-18T18:00:00Z",
  requiredConfirmations: 3,
};

function without(key: keyof typeof validRequest): Record<string, unknown> {
  const copy: Record<string, unknown> = { ...validRequest };
  delete copy[key];
  return copy;
}

function expectAppError(fn: () => unknown, code: string, messagePattern?: RegExp): void {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(AppError);
    expect((error as AppError).code).toBe(code);
    if (messagePattern !== undefined) {
      expect((error as AppError).message).toMatch(messagePattern);
    }
    return;
  }
  expect.unreachable(`expected ${code}`);
}

describe("parseCreatePaymentIntentRequest", () => {
  it("normalizes a full valid request", () => {
    expect(parseCreatePaymentIntentRequest(validRequest, NOW)).toEqual({
      externalReference: "INV-204",
      expectedAmountUnits: 850_000_000n,
      recipientAddress: RECIPIENT.toLowerCase(),
      payerAddress: PAYER.toLowerCase(),
      expiresAt: new Date("2026-09-18T18:00:00.000Z"),
      requiredConfirmations: 3,
    });
  });

  it("applies defaults: payer optional, externalReference optional, confirmations 3", () => {
    const input = parseCreatePaymentIntentRequest(
      { chain: "base", asset: "USDC", amount: "1", recipient: RECIPIENT, expiresAt: "2026-09-18T18:00:00Z" },
      NOW,
    );
    expect(input.payerAddress).toBeNull();
    expect(input.externalReference).toBeNull();
    expect(input.requiredConfirmations).toBe(3);
  });

  it("rejects unknown fields", () => {
    expectAppError(
      () => parseCreatePaymentIntentRequest({ ...validRequest, tokenAddress: "0x00", chainId: 1 }, NOW),
      "VALIDATION_ERROR",
      /unknown field\(s\): tokenAddress, chainId/,
    );
  });

  it.each([
    ["missing chain", without("chain"), /chain/],
    ["missing asset", without("asset"), /asset/],
    ["missing amount", without("amount"), /amount/],
    ["missing recipient", without("recipient"), /recipient/],
    ["missing expiresAt", without("expiresAt"), /expiresAt/],
    ["numeric amount", { ...validRequest, amount: 850 }, /amount/],
    ["non-object body", "not an object", /./],
    ["null body", null, /./],
    ["array body", [], /./],
    ["externalReference too long", { ...validRequest, externalReference: "x".repeat(129) }, /externalReference/],
    ["fractional confirmations", { ...validRequest, requiredConfirmations: 2.5 }, /requiredConfirmations/],
    ["string confirmations", { ...validRequest, requiredConfirmations: "3" }, /requiredConfirmations/],
    ["expiry with offset", { ...validRequest, expiresAt: "2026-09-18T18:00:00+02:00" }, /expiresAt/],
    ["expiry without zone", { ...validRequest, expiresAt: "2026-09-18T18:00:00" }, /expiresAt/],
    ["expiry not a timestamp", { ...validRequest, expiresAt: "tomorrow" }, /expiresAt/],
  ])("returns VALIDATION_ERROR for %s", (_label, body, pattern) => {
    expectAppError(() => parseCreatePaymentIntentRequest(body, NOW), "VALIDATION_ERROR", pattern);
  });

  it("returns UNSUPPORTED_CHAIN / UNSUPPORTED_ASSET for other rails", () => {
    expectAppError(() => parseCreatePaymentIntentRequest({ ...validRequest, chain: "ethereum" }, NOW), "UNSUPPORTED_CHAIN");
    expectAppError(() => parseCreatePaymentIntentRequest({ ...validRequest, chain: "Base" }, NOW), "UNSUPPORTED_CHAIN");
    expectAppError(() => parseCreatePaymentIntentRequest({ ...validRequest, asset: "USDT" }, NOW), "UNSUPPORTED_ASSET");
    expectAppError(() => parseCreatePaymentIntentRequest({ ...validRequest, asset: "usdc" }, NOW), "UNSUPPORTED_ASSET");
  });

  it("returns INVALID_ADDRESS for bad recipient or payer", () => {
    expectAppError(
      () => parseCreatePaymentIntentRequest({ ...validRequest, recipient: "0xRecipient" }, NOW),
      "INVALID_ADDRESS",
      /recipient/,
    );
    expectAppError(
      () => parseCreatePaymentIntentRequest({ ...validRequest, payer: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02914" }, NOW),
      "INVALID_ADDRESS",
      /payer/,
    );
  });

  it.each(["0", "0.00", "-1", "1e3", "1.0000001", "NaN", "Infinity", ""])(
    "returns VALIDATION_ERROR for amount %j",
    (amount) => {
      expectAppError(() => parseCreatePaymentIntentRequest({ ...validRequest, amount }, NOW), "VALIDATION_ERROR", /amount/);
    },
  );

  it("enforces the expiry window relative to now", () => {
    expectAppError(
      () => parseCreatePaymentIntentRequest({ ...validRequest, expiresAt: "2026-09-17T12:00:00Z" }, NOW),
      "VALIDATION_ERROR",
      /expiresAt: must be in the future/,
    );
    expect(parseCreatePaymentIntentRequest({ ...validRequest, expiresAt: "2026-09-24T12:00:00Z" }, NOW).expiresAt).toEqual(
      new Date("2026-09-24T12:00:00.000Z"),
    );
    expectAppError(
      () => parseCreatePaymentIntentRequest({ ...validRequest, expiresAt: "2026-09-24T12:00:00.001Z" }, NOW),
      "VALIDATION_ERROR",
      /expiresAt: must be at most 7 days from now/,
    );
  });

  it("enforces confirmation bounds", () => {
    expect(parseCreatePaymentIntentRequest({ ...validRequest, requiredConfirmations: 1 }, NOW).requiredConfirmations).toBe(1);
    expect(parseCreatePaymentIntentRequest({ ...validRequest, requiredConfirmations: 64 }, NOW).requiredConfirmations).toBe(64);
    expectAppError(
      () => parseCreatePaymentIntentRequest({ ...validRequest, requiredConfirmations: 0 }, NOW),
      "VALIDATION_ERROR",
      /requiredConfirmations/,
    );
    expectAppError(
      () => parseCreatePaymentIntentRequest({ ...validRequest, requiredConfirmations: 65 }, NOW),
      "VALIDATION_ERROR",
      /requiredConfirmations/,
    );
  });

  it("reports several semantic problems in one message", () => {
    expectAppError(
      () =>
        parseCreatePaymentIntentRequest(
          { ...validRequest, amount: "0", requiredConfirmations: 99, expiresAt: "2020-01-01T00:00:00Z" },
          NOW,
        ),
      "VALIDATION_ERROR",
      /amount: .*; requiredConfirmations: .*; expiresAt: /,
    );
  });
});

describe("parsePaymentIntentId", () => {
  it("accepts a well-formed ID and rejects others", () => {
    const id = `pi_${"A".repeat(32)}`;
    expect(parsePaymentIntentId(id)).toBe(id);
    expectAppError(() => parsePaymentIntentId("pi_nope"), "VALIDATION_ERROR", /id must be/);
    expectAppError(() => parsePaymentIntentId(undefined), "VALIDATION_ERROR");
  });
});

describe("toPaymentIntentResponse", () => {
  const intent: PaymentIntent = {
    id: `pi_${"A".repeat(32)}`,
    externalReference: "INV-204",
    chain: "base",
    asset: "USDC",
    tokenAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    expectedAmountUnits: 850_000_000n,
    recipientAddress: RECIPIENT.toLowerCase(),
    payerAddress: PAYER.toLowerCase(),
    startBlock: 35_000_001n,
    expiryBlock: null,
    requiredConfirmations: 3,
    status: "pending",
    receivedAmountUnits: 0n,
    detectedAmountUnits: 0n,
    matchConfidence: "none",
    paidAt: null,
    lastReconciledBlock: null,
    lastReconciledAt: null,
    createdAt: new Date("2026-09-17T12:00:00.000Z"),
    expiresAt: new Date("2026-09-18T18:00:00.000Z"),
    updatedAt: new Date("2026-09-17T12:00:00.000Z"),
  };

  it("produces the public camelCase shape with decimal money and checksummed addresses", () => {
    expect(toPaymentIntentResponse(intent)).toEqual({
      id: intent.id,
      status: "pending",
      externalReference: "INV-204",
      chain: "base",
      asset: "USDC",
      expectedAmount: "850.00",
      receivedAmount: "0.00",
      remainingAmount: "850.00",
      recipient: RECIPIENT,
      payer: PAYER,
      requiredConfirmations: 3,
      matchConfidence: "none",
      paidAt: null,
      createdAt: "2026-09-17T12:00:00.000Z",
      expiresAt: "2026-09-18T18:00:00.000Z",
    });
  });

  it("never exposes internals and is JSON-serializable (no bigint)", () => {
    const response = toPaymentIntentResponse(intent) as unknown as Record<string, unknown>;
    for (const key of ["accountId", "tokenAddress", "expectedAmountUnits", "startBlock", "updatedAt", "lastReconciledBlock"]) {
      expect(response).not.toHaveProperty(key);
    }
    expect(() => JSON.stringify(response)).not.toThrow();
  });

  it("handles a partially received intent and a null payer", () => {
    const response = toPaymentIntentResponse({
      ...intent,
      payerAddress: null,
      receivedAmountUnits: 500_000_000n,
      status: "partial",
      matchConfidence: "single_sender",
      paidAt: new Date("2026-09-17T14:31:02.000Z"),
    });
    expect(response.payer).toBeNull();
    expect(response.receivedAmount).toBe("500.00");
    expect(response.remainingAmount).toBe("350.00");
    expect(response.paidAt).toBe("2026-09-17T14:31:02.000Z");
  });
});
