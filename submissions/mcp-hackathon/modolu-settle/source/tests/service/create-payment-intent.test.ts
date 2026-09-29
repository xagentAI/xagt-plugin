import { describe, expect, it } from "vitest";

import type { CreatePaymentIntentInput } from "@/domain/payment-intent";
import { AppError } from "@/lib/errors";
import { createPaymentIntent } from "@/services/create-payment-intent";

import { FakeChainProvider, InMemoryPaymentRepository } from "./fakes";

const NOW = new Date("2026-09-17T12:00:00.000Z");
const RECIPIENT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const PAYER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045";

const input: CreatePaymentIntentInput = {
  externalReference: "INV-204",
  expectedAmountUnits: 850_000_000n,
  recipientAddress: RECIPIENT,
  payerAddress: PAYER,
  expiresAt: new Date("2026-09-18T18:00:00.000Z"),
  requiredConfirmations: 3,
};

function deps(chainProvider: FakeChainProvider) {
  const paymentRepository = new InMemoryPaymentRepository(() => NOW);
  return { chainProvider, paymentRepository, now: () => NOW };
}

describe("createPaymentIntent", () => {
  it("reads the latest block once and persists startBlock = latest + 1", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 35_000_000n });
    const d = deps(chainProvider);

    const intent = await createPaymentIntent(input, d);

    expect(chainProvider.calls).toBe(1);
    expect(intent.startBlock).toBe(35_000_001n);
    expect(d.paymentRepository.intents.get(intent.id)?.startBlock).toBe(35_000_001n);
  });

  it("returns a pending intent with the initial state and a pi_ ID", async () => {
    const d = deps(new FakeChainProvider({ latestBlock: 1n }));
    const intent = await createPaymentIntent(input, d);

    expect(intent.id).toMatch(/^pi_[A-Za-z0-9_-]{32}$/);
    expect(intent).toMatchObject({
      status: "pending",
      chain: "base",
      asset: "USDC",
      tokenAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
      expectedAmountUnits: 850_000_000n,
      receivedAmountUnits: 0n,
      detectedAmountUnits: 0n,
      matchConfidence: "none",
      expiryBlock: null,
      paidAt: null,
      lastReconciledBlock: null,
      lastReconciledAt: null,
      externalReference: "INV-204",
      recipientAddress: RECIPIENT,
      payerAddress: PAYER,
      requiredConfirmations: 3,
      expiresAt: input.expiresAt,
    });
  });

  it("generates a fresh ID for every intent", async () => {
    const d = deps(new FakeChainProvider({ latestBlock: 1n }));
    const first = await createPaymentIntent(input, d);
    const second = await createPaymentIntent(input, d);
    expect(first.id).not.toBe(second.id);
    expect(d.paymentRepository.intents.size).toBe(2);
  });

  it("persists nothing when the chain provider fails, and propagates the retryable error", async () => {
    const providerError = new AppError("UPSTREAM_UNAVAILABLE", "Blockchain provider is temporarily unavailable");
    const d = deps(new FakeChainProvider({ error: providerError }));

    await expect(createPaymentIntent(input, d)).rejects.toBe(providerError);
    expect(d.paymentRepository.intents.size).toBe(0);
  });

  it("persists nothing when the chain provider throws an unexpected error", async () => {
    const d = deps(new FakeChainProvider({ error: new Error("socket hang up") }));
    await expect(createPaymentIntent(input, d)).rejects.toThrow("socket hang up");
    expect(d.paymentRepository.intents.size).toBe(0);
  });

  it("keeps the default confirmation threshold of 3 when supplied by validation", async () => {
    const d = deps(new FakeChainProvider({ latestBlock: 1n }));
    const intent = await createPaymentIntent({ ...input, requiredConfirmations: 3 }, d);
    expect(intent.requiredConfirmations).toBe(3);
  });

  it("stores a null payer when none was supplied", async () => {
    const d = deps(new FakeChainProvider({ latestBlock: 1n }));
    const intent = await createPaymentIntent({ ...input, payerAddress: null }, d);
    expect(intent.payerAddress).toBeNull();
  });

  it("rejects domain-invalid input before touching the chain or the repository", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 1n });
    const d = deps(chainProvider);

    for (const bad of [
      { ...input, expectedAmountUnits: 0n },
      { ...input, requiredConfirmations: 65 },
      { ...input, expiresAt: NOW },
      { ...input, expiresAt: new Date("2026-10-01T00:00:00.000Z") },
    ]) {
      await expect(createPaymentIntent(bad, d)).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    }
    expect(chainProvider.calls).toBe(0);
    expect(d.paymentRepository.intents.size).toBe(0);
  });
});
