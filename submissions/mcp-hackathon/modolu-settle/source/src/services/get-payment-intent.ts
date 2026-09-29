/**
 * Use case: read the current persisted state of an intent. No chain access
 * and no reconciliation happen here.
 */
import "server-only";

import type { PaymentIntent } from "@/domain/payment-intent";
import { AppError } from "@/lib/errors";
import type { PaymentRepository } from "@/ports/payment-repository";

export interface GetPaymentIntentDeps {
  readonly paymentRepository: PaymentRepository;
}

export async function getPaymentIntent(id: string, deps: GetPaymentIntentDeps): Promise<PaymentIntent> {
  const intent = await deps.paymentRepository.getPaymentIntentById(id);
  if (intent === null) {
    throw new AppError("INTENT_NOT_FOUND", "Payment intent not found");
  }
  return intent;
}
