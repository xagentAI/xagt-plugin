/**
 * Payment intent domain types, status enums and the fixed network constants.
 *
 * Pure TypeScript: no Next.js, Drizzle, `pg`, `viem`, environment or network
 * imports (ARCHITECTURE.md §6). The constants below are code constants, never
 * request input or environment variables; changing the chain, token contract
 * or decimals is an architecture change (ARCHITECTURE.md §2).
 */

export const CHAIN = "base" as const;
export const CHAIN_ID = 8453;
export const ASSET = "USDC" as const;
export const USDC_DECIMALS = 6;
/** Native Circle USDC on Base, lowercase (storage/equality form). */
export const USDC_TOKEN_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
export const DEFAULT_REQUIRED_CONFIRMATIONS = 3;
export const MIN_REQUIRED_CONFIRMATIONS = 1;
export const MAX_REQUIRED_CONFIRMATIONS = 64;
export const MAX_INTENT_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000;
export const MAX_EXTERNAL_REFERENCE_LENGTH = 128;

export const PAYMENT_STATUSES = [
  "pending",
  "detected",
  "partial",
  "paid",
  "overpaid",
  "expired",
  "ambiguous",
] as const;
export type PaymentStatus = (typeof PAYMENT_STATUSES)[number];

export const MATCH_CONFIDENCES = ["none", "exact_payer", "single_sender", "ambiguous"] as const;
export type MatchConfidence = (typeof MATCH_CONFIDENCES)[number];

export const TRANSFER_ASSOCIATIONS = ["matched", "candidate", "orphaned"] as const;
export type TransferAssociation = (typeof TRANSFER_ASSOCIATIONS)[number];

/** A persisted payment obligation. Addresses are lowercase; money is exact token units. */
export interface PaymentIntent {
  readonly id: string;
  readonly externalReference: string | null;
  readonly chain: typeof CHAIN;
  readonly asset: typeof ASSET;
  readonly tokenAddress: string;
  readonly expectedAmountUnits: bigint;
  readonly recipientAddress: string;
  readonly payerAddress: string | null;
  readonly startBlock: bigint;
  readonly expiryBlock: bigint | null;
  readonly requiredConfirmations: number;
  readonly status: PaymentStatus;
  readonly receivedAmountUnits: bigint;
  readonly detectedAmountUnits: bigint;
  readonly matchConfidence: MatchConfidence;
  readonly paidAt: Date | null;
  readonly lastReconciledBlock: bigint | null;
  readonly lastReconciledAt: Date | null;
  readonly createdAt: Date;
  readonly expiresAt: Date;
  readonly updatedAt: Date;
}

/** Validated, normalized input for creating an intent (addresses lowercase, money in units). */
export interface CreatePaymentIntentInput {
  readonly externalReference: string | null;
  readonly expectedAmountUnits: bigint;
  readonly recipientAddress: string;
  readonly payerAddress: string | null;
  readonly expiresAt: Date;
  readonly requiredConfirmations: number;
}

/** Everything the repository needs to insert a new `pending` intent. */
export interface NewPaymentIntent extends CreatePaymentIntentInput {
  readonly id: string;
  readonly startBlock: bigint;
}

/** Persisted chain evidence for an intent (`matched_transfers`, ARCHITECTURE.md §4.2). */
export interface MatchedTransfer {
  readonly txHash: string;
  readonly logIndex: number;
  readonly blockNumber: bigint;
  readonly blockHash: string;
  readonly fromAddress: string;
  readonly toAddress: string;
  readonly amountUnits: bigint;
  readonly blockTimestamp: Date;
  readonly association: TransferAssociation;
  /** Depth observed at the last reconciliation that saw this transfer; cached evidence only. */
  readonly confirmations: number;
  readonly firstSeenAt: Date;
  readonly lastSeenAt: Date;
}

export interface PaymentIntentViolation {
  readonly field: "amount" | "requiredConfirmations" | "expiresAt";
  readonly message: string;
}

/**
 * Domain invariants shared by request validation and the create service.
 * Returns an empty array when `input` is acceptable at instant `now`.
 */
export function paymentIntentViolations(
  input: Pick<CreatePaymentIntentInput, "expectedAmountUnits" | "requiredConfirmations" | "expiresAt">,
  now: Date,
): PaymentIntentViolation[] {
  const violations: PaymentIntentViolation[] = [];

  if (input.expectedAmountUnits <= 0n) {
    violations.push({ field: "amount", message: "must be greater than zero" });
  }

  if (
    !Number.isInteger(input.requiredConfirmations) ||
    input.requiredConfirmations < MIN_REQUIRED_CONFIRMATIONS ||
    input.requiredConfirmations > MAX_REQUIRED_CONFIRMATIONS
  ) {
    violations.push({
      field: "requiredConfirmations",
      message: `must be an integer between ${MIN_REQUIRED_CONFIRMATIONS} and ${MAX_REQUIRED_CONFIRMATIONS}`,
    });
  }

  const expiresAtMs = input.expiresAt.getTime();
  if (Number.isNaN(expiresAtMs) || expiresAtMs <= now.getTime()) {
    violations.push({ field: "expiresAt", message: "must be in the future" });
  } else if (expiresAtMs > now.getTime() + MAX_INTENT_LIFETIME_MS) {
    violations.push({ field: "expiresAt", message: "must be at most 7 days from now" });
  }

  return violations;
}

/** Amount still owed; never negative. */
export function remainingAmountUnits(intent: Pick<PaymentIntent, "expectedAmountUnits" | "receivedAmountUnits">): bigint {
  const remaining = intent.expectedAmountUnits - intent.receivedAmountUnits;
  return remaining > 0n ? remaining : 0n;
}
