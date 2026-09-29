/**
 * Use case: declare a new payment obligation (ARCHITECTURE.md §8.1).
 *
 *   validate domain invariants
 *   → ChainProvider.getLatestBlock()
 *   → startBlock = latestBlock + 1
 *   → generate pi_ ID
 *   → persist pending intent
 *
 * A provider failure propagates as a retryable upstream error before anything
 * is persisted: the start block is part of the matching boundary, so an intent
 * without one must not exist.
 */
import "server-only";

import {
  paymentIntentViolations,
  type CreatePaymentIntentInput,
  type PaymentIntent,
} from "@/domain/payment-intent";
import { AppError } from "@/lib/errors";
import { newPaymentIntentId } from "@/lib/ids";
import type { ChainProvider } from "@/ports/chain-provider";
import type { PaymentRepository } from "@/ports/payment-repository";

export interface CreatePaymentIntentDeps {
  readonly chainProvider: ChainProvider;
  readonly paymentRepository: PaymentRepository;
  /** Clock seam for tests; defaults to the system clock. */
  readonly now?: () => Date;
}

export async function createPaymentIntent(
  input: CreatePaymentIntentInput,
  deps: CreatePaymentIntentDeps,
): Promise<PaymentIntent> {
  const now = deps.now?.() ?? new Date();
  const violations = paymentIntentViolations(input, now);
  if (violations.length > 0) {
    throw new AppError(
      "VALIDATION_ERROR",
      violations.map((violation) => `${violation.field}: ${violation.message}`).join("; "),
    );
  }

  const latestBlock = await deps.chainProvider.getLatestBlock();

  return deps.paymentRepository.createPaymentIntent({
    ...input,
    id: newPaymentIntentId(),
    startBlock: latestBlock + 1n,
  });
}
