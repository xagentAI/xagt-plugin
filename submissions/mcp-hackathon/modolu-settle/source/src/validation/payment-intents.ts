/**
 * HTTP contract for payment intents: request parsing (untrusted JSON →
 * `CreatePaymentIntentInput`) and the public response representation
 * (`PaymentIntent` → camelCase JSON). Money crosses this boundary as decimal
 * strings and addresses as EIP-55 checksummed strings (ARCHITECTURE.md §4.4, §9).
 */
import { z } from "zod";

import { formatUsdcAmount, parseUsdcAmount } from "@/domain/money";
import {
  ASSET,
  CHAIN,
  DEFAULT_REQUIRED_CONFIRMATIONS,
  MAX_EXTERNAL_REFERENCE_LENGTH,
  paymentIntentViolations,
  remainingAmountUnits,
  type CreatePaymentIntentInput,
  type MatchConfidence,
  type PaymentIntent,
  type PaymentStatus,
} from "@/domain/payment-intent";
import { normalizeAddress, toChecksumAddress } from "@/lib/addresses";
import { AppError } from "@/lib/errors";
import { isPaymentIntentId } from "@/lib/ids";

/** Structural shape of the create request; semantic rules are applied afterwards. */
const createRequestSchema = z
  .object({
    externalReference: z.string().max(MAX_EXTERNAL_REFERENCE_LENGTH).optional(),
    chain: z.string(),
    asset: z.string(),
    amount: z.string(),
    recipient: z.string(),
    payer: z.string().optional(),
    // UTC ISO-8601 with a trailing "Z"; offsets are rejected.
    expiresAt: z.iso.datetime({ offset: false, message: "must be a UTC ISO-8601 timestamp ending in Z" }),
    requiredConfirmations: z.int().optional(),
  })
  .strict();

function describeIssue(issue: z.core.$ZodIssue): string {
  const path = issue.path.map(String).join(".");
  if (issue.code === "unrecognized_keys") {
    return `unknown field(s): ${issue.keys.join(", ")}`;
  }
  return path === "" ? issue.message : `${path}: ${issue.message}`;
}

/**
 * Validates an untrusted request body and returns normalized domain input.
 * Throws `UNSUPPORTED_CHAIN`, `UNSUPPORTED_ASSET`, `INVALID_ADDRESS` or
 * `VALIDATION_ERROR` (ARCHITECTURE.md §9).
 */
export function parseCreatePaymentIntentRequest(body: unknown, now: Date): CreatePaymentIntentInput {
  const parsed = createRequestSchema.safeParse(body);
  if (!parsed.success) {
    throw new AppError("VALIDATION_ERROR", parsed.error.issues.map(describeIssue).join("; "));
  }
  const request = parsed.data;

  if (request.chain !== CHAIN) {
    throw new AppError("UNSUPPORTED_CHAIN", `chain must be "${CHAIN}"`);
  }
  if (request.asset !== ASSET) {
    throw new AppError("UNSUPPORTED_ASSET", `asset must be "${ASSET}"`);
  }

  const recipientAddress = normalizeAddress(request.recipient);
  if (recipientAddress === null) {
    throw new AppError("INVALID_ADDRESS", "recipient must be a valid Base address");
  }
  let payerAddress: string | null = null;
  if (request.payer !== undefined) {
    payerAddress = normalizeAddress(request.payer);
    if (payerAddress === null) {
      throw new AppError("INVALID_ADDRESS", "payer must be a valid Base address");
    }
  }

  const problems: string[] = [];
  const amount = parseUsdcAmount(request.amount);
  if (!amount.ok) {
    problems.push(`amount: ${amount.reason}`);
  }

  const input: CreatePaymentIntentInput = {
    externalReference: request.externalReference ?? null,
    expectedAmountUnits: amount.ok ? amount.units : 0n,
    recipientAddress,
    payerAddress,
    expiresAt: new Date(request.expiresAt),
    requiredConfirmations: request.requiredConfirmations ?? DEFAULT_REQUIRED_CONFIRMATIONS,
  };

  for (const violation of paymentIntentViolations(input, now)) {
    // The amount problem above already explains a zero-units placeholder.
    if (violation.field === "amount" && !amount.ok) {
      continue;
    }
    problems.push(`${violation.field}: ${violation.message}`);
  }
  if (problems.length > 0) {
    throw new AppError("VALIDATION_ERROR", problems.join("; "));
  }
  return input;
}

/** Validates a path parameter as an opaque intent ID. */
export function parsePaymentIntentId(value: unknown): string {
  if (!isPaymentIntentId(value)) {
    throw new AppError("VALIDATION_ERROR", "id must be a payment intent ID of the form pi_<32 url-safe characters>");
  }
  return value;
}

/** Public JSON representation of an intent. Never exposes token units, account_id or database internals. */
export interface PaymentIntentResponse {
  readonly id: string;
  readonly status: PaymentStatus;
  readonly externalReference: string | null;
  readonly chain: typeof CHAIN;
  readonly asset: typeof ASSET;
  readonly expectedAmount: string;
  readonly receivedAmount: string;
  readonly remainingAmount: string;
  readonly recipient: string;
  readonly payer: string | null;
  readonly requiredConfirmations: number;
  readonly matchConfidence: MatchConfidence;
  readonly paidAt: string | null;
  readonly createdAt: string;
  readonly expiresAt: string;
}

export function toPaymentIntentResponse(intent: PaymentIntent): PaymentIntentResponse {
  return {
    id: intent.id,
    status: intent.status,
    externalReference: intent.externalReference,
    chain: intent.chain,
    asset: intent.asset,
    expectedAmount: formatUsdcAmount(intent.expectedAmountUnits),
    receivedAmount: formatUsdcAmount(intent.receivedAmountUnits),
    remainingAmount: formatUsdcAmount(remainingAmountUnits(intent)),
    recipient: toChecksumAddress(intent.recipientAddress),
    payer: intent.payerAddress === null ? null : toChecksumAddress(intent.payerAddress),
    requiredConfirmations: intent.requiredConfirmations,
    matchConfidence: intent.matchConfidence,
    paidAt: intent.paidAt === null ? null : intent.paidAt.toISOString(),
    createdAt: intent.createdAt.toISOString(),
    expiresAt: intent.expiresAt.toISOString(),
  };
}
