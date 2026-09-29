import { describe, expect, it } from "vitest";

import { AppError } from "@/lib/errors";
import { newPaymentIntentId } from "@/lib/ids";
import { getPaymentIntent } from "@/services/get-payment-intent";

import { InMemoryPaymentRepository } from "./fakes";

describe("getPaymentIntent", () => {
  it("returns the persisted intent unchanged", async () => {
    const paymentRepository = new InMemoryPaymentRepository();
    const created = await paymentRepository.createPaymentIntent({
      id: newPaymentIntentId(),
      externalReference: null,
      expectedAmountUnits: 25_000_000n,
      recipientAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
      payerAddress: null,
      expiresAt: new Date(Date.now() + 60_000),
      requiredConfirmations: 3,
      startBlock: 100n,
    });

    await expect(getPaymentIntent(created.id, { paymentRepository })).resolves.toEqual(created);
  });

  it("throws INTENT_NOT_FOUND for an unknown ID", async () => {
    const paymentRepository = new InMemoryPaymentRepository();
    let caught: unknown;
    try {
      await getPaymentIntent(newPaymentIntentId(), { paymentRepository });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(AppError);
    expect(caught).toMatchObject({ code: "INTENT_NOT_FOUND", httpStatus: 404, retryable: false });
  });
});
