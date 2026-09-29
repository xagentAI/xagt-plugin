/**
 * Use case: page through the persisted chain evidence of an intent in
 * canonical order. Reads only what the last accepted reconciliation stored;
 * no chain access happens here.
 */
import "server-only";

import { AppError } from "@/lib/errors";
import type { EvidenceCursor, EvidencePage, PaymentRepository } from "@/ports/payment-repository";

export const DEFAULT_EVIDENCE_LIMIT = 50;
export const MAX_EVIDENCE_LIMIT = 100;

export interface GetPaymentEvidenceDeps {
  readonly paymentRepository: PaymentRepository;
}

export interface GetPaymentEvidenceOptions {
  readonly limit: number;
  readonly cursor: EvidenceCursor | null;
}

export async function getPaymentEvidence(
  id: string,
  options: GetPaymentEvidenceOptions,
  deps: GetPaymentEvidenceDeps,
): Promise<EvidencePage> {
  if (!Number.isInteger(options.limit) || options.limit < 1 || options.limit > MAX_EVIDENCE_LIMIT) {
    throw new AppError("VALIDATION_ERROR", `limit must be an integer between 1 and ${MAX_EVIDENCE_LIMIT}`);
  }
  const intent = await deps.paymentRepository.getPaymentIntentById(id);
  if (intent === null) {
    throw new AppError("INTENT_NOT_FOUND", "Payment intent not found");
  }
  return deps.paymentRepository.getEvidencePage(intent.id, options);
}
