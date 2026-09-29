import { describe, expect, it } from "vitest";

import { reconcile, type ObservedTransfer } from "@/domain/reconciliation";
import { AppError } from "@/lib/errors";
import { newPaymentIntentId } from "@/lib/ids";
import { getPaymentEvidence } from "@/services/get-payment-evidence";

import { InMemoryPaymentRepository } from "./fakes";

const PAYER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045";
const RECIPIENT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";

function observed(blockNumber: bigint, logIndex: number, txHash: string): ObservedTransfer {
  return {
    txHash,
    logIndex,
    blockNumber,
    blockHash: `0x${"b".repeat(64)}`,
    from: PAYER,
    to: RECIPIENT,
    amountUnits: 1_000_000n,
    blockTimestamp: new Date(Number(blockNumber) * 2_000),
  };
}

async function seed(count: number) {
  const paymentRepository = new InMemoryPaymentRepository();
  const intent = await paymentRepository.createPaymentIntent({
    id: newPaymentIntentId(),
    externalReference: null,
    expectedAmountUnits: 1_000_000_000n,
    recipientAddress: RECIPIENT,
    payerAddress: PAYER,
    expiresAt: new Date(Date.now() + 60_000),
    requiredConfirmations: 1,
    startBlock: 1n,
  });
  const transfers = Array.from({ length: count }, (_, i) =>
    observed(BigInt(100 + Math.floor(i / 2)), i % 2, `0x${String(i).padStart(64, "0")}`),
  );
  const window = { fromBlock: 1n, toBlock: 10_000n };
  await paymentRepository.applyReconciliation(intent.id, {
    latestBlock: 10_000n,
    window,
    expiryBlock: null,
    result: reconcile({ expectedAmountUnits: 1_000_000_000n, requiredConfirmations: 1, latestBlock: 10_000n, payer: PAYER, window, expiryPassed: false, transfers }),
    attempt: { requestId: "r", provider: "alchemy", fromBlock: 1n, toBlock: 10_000n, candidateCount: count, startedAt: new Date(), completedAt: new Date() },
  });
  return { paymentRepository, intent };
}

describe("getPaymentEvidence", () => {
  it("returns evidence in canonical order and pages with a keyset cursor", async () => {
    const { paymentRepository, intent } = await seed(5);
    const first = await getPaymentEvidence(intent.id, { limit: 2, cursor: null }, { paymentRepository });
    expect(first.items.map((row) => [row.blockNumber, row.logIndex])).toEqual([[100n, 0], [100n, 1]]);
    expect(first.nextCursor).toEqual({ blockNumber: 100n, logIndex: 1, txHash: first.items[1]?.txHash });

    const second = await getPaymentEvidence(intent.id, { limit: 2, cursor: first.nextCursor }, { paymentRepository });
    expect(second.items.map((row) => [row.blockNumber, row.logIndex])).toEqual([[101n, 0], [101n, 1]]);

    const third = await getPaymentEvidence(intent.id, { limit: 2, cursor: second.nextCursor }, { paymentRepository });
    expect(third.items.map((row) => [row.blockNumber, row.logIndex])).toEqual([[102n, 0]]);
    expect(third.nextCursor).toBeNull();
  });

  it("returns an empty page for an intent without evidence", async () => {
    const { paymentRepository, intent } = await seed(0);
    await expect(getPaymentEvidence(intent.id, { limit: 50, cursor: null }, { paymentRepository })).resolves.toEqual({
      items: [],
      nextCursor: null,
    });
  });

  it("throws INTENT_NOT_FOUND for an unknown intent", async () => {
    const { paymentRepository } = await seed(0);
    await expect(getPaymentEvidence(newPaymentIntentId(), { limit: 50, cursor: null }, { paymentRepository })).rejects.toMatchObject({
      code: "INTENT_NOT_FOUND",
    });
  });

  it("rejects limits outside 1..100", async () => {
    const { paymentRepository, intent } = await seed(0);
    for (const limit of [0, 101, 1.5, Number.NaN]) {
      await expect(getPaymentEvidence(intent.id, { limit, cursor: null }, { paymentRepository })).rejects.toBeInstanceOf(AppError);
    }
  });
});
