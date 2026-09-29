/**
 * Persistence port for payment obligations and their evidence. Repositories
 * are the only layer that runs application database queries; they convert
 * database values to domain types (`bigint` units and block numbers, `Date`
 * timestamps) and own transaction/locking mechanics.
 */
import type { MatchedTransfer, NewPaymentIntent, PaymentIntent, PaymentStatus } from "@/domain/payment-intent";
import type { BlockWindow, ReconciliationResult } from "@/domain/reconciliation";

/** Operational record of one reconcile request (`reconciliation_attempts`). */
export interface ReconciliationAttemptRecord {
  readonly requestId: string;
  readonly provider: "alchemy";
  readonly fromBlock: bigint;
  readonly toBlock: bigint;
  readonly latestBlock: bigint | null;
  readonly candidateCount: number;
  readonly resultStatus: PaymentStatus | null;
  readonly errorCode: string | null;
  readonly startedAt: Date;
  readonly completedAt: Date;
}

/** One complete canonical observation of the chain for an intent, ready to be applied atomically. */
export interface ReconciliationObservation {
  readonly latestBlock: bigint;
  /** Blocks the scan covered completely; stored evidence inside it that was not re-observed becomes `orphaned`. */
  readonly window: BlockWindow;
  /** Resolved expiry boundary to persist, or `null` when not (yet) resolved. Never regresses a stored value. */
  readonly expiryBlock: bigint | null;
  readonly result: ReconciliationResult;
  readonly attempt: Omit<ReconciliationAttemptRecord, "latestBlock" | "resultStatus" | "errorCode">;
}

export interface ApplyReconciliationOutcome {
  /** `false` when the observation was older than the intent's last accepted one and was only recorded. */
  readonly applied: boolean;
  readonly intent: PaymentIntent;
}

/** Keyset position in the canonical evidence order `(blockNumber, logIndex, txHash)`. */
export interface EvidenceCursor {
  readonly blockNumber: bigint;
  readonly logIndex: number;
  readonly txHash: string;
}

export interface EvidencePage {
  readonly items: readonly MatchedTransfer[];
  readonly nextCursor: EvidenceCursor | null;
}

export interface PaymentRepository {
  /** Inserts a new `pending` intent and returns the persisted row. */
  createPaymentIntent(intent: NewPaymentIntent): Promise<PaymentIntent>;
  /** Returns the intent or `null` when no row has that ID. */
  getPaymentIntentById(id: string): Promise<PaymentIntent | null>;

  /**
   * Atomically applies an observation: locks the intent, rejects observations
   * older than `last_reconciled_block` without touching state, upserts evidence
   * by `(intent, txHash, logIndex)` (newest canonical block details win),
   * orphans stored evidence inside `window` that the scan did not re-observe,
   * persists the domain-computed state plus a first-resolved expiry block and
   * records the attempt. Returns `null` when the intent does not exist.
   */
  applyReconciliation(intentId: string, observation: ReconciliationObservation): Promise<ApplyReconciliationOutcome | null>;

  /** Records an attempt that failed before any evidence could be applied. Never mutates intent state. */
  recordReconciliationAttempt(intentId: string, attempt: ReconciliationAttemptRecord): Promise<void>;

  /** Evidence rows in canonical order, keyset-paginated after `cursor`. */
  getEvidencePage(intentId: string, options: { readonly limit: number; readonly cursor: EvidenceCursor | null }): Promise<EvidencePage>;
}
