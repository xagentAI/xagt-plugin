/**
 * Drizzle-backed `PaymentRepository`. The only place application code queries
 * `payment_intents`, `matched_transfers` and `reconciliation_attempts`. Rows
 * come back with `bigint` units/blocks and `Date` timestamps via the column
 * modes declared in `src/db/schema.ts`.
 */
import "server-only";

import { and, asc, eq, gte, inArray, lte, sql } from "drizzle-orm";

import type { Database } from "@/db/client";
import { matchedTransfers, paymentIntents, reconciliationAttempts } from "@/db/schema";
import {
  ASSET,
  CHAIN,
  USDC_TOKEN_ADDRESS,
  type MatchedTransfer,
  type NewPaymentIntent,
  type PaymentIntent,
} from "@/domain/payment-intent";
import { transferIdentity } from "@/domain/reconciliation";
import type {
  ApplyReconciliationOutcome,
  EvidenceCursor,
  EvidencePage,
  PaymentRepository,
  ReconciliationAttemptRecord,
  ReconciliationObservation,
} from "@/ports/payment-repository";

type PaymentIntentRow = typeof paymentIntents.$inferSelect;
type MatchedTransferRow = typeof matchedTransfers.$inferSelect;

const INT32_MAX = 2_147_483_647n;

function toDomain(row: PaymentIntentRow): PaymentIntent {
  if (row.chain !== CHAIN || row.asset !== ASSET) {
    // The CHECK constraints make this unreachable; fail loudly rather than mislabel money.
    throw new Error(`payment_intents row ${row.id} has unsupported chain/asset`);
  }
  return {
    id: row.id,
    externalReference: row.externalReference,
    chain: CHAIN,
    asset: ASSET,
    tokenAddress: row.tokenAddress,
    expectedAmountUnits: row.expectedAmountUnits,
    recipientAddress: row.recipientAddress,
    payerAddress: row.payerAddress,
    startBlock: row.startBlock,
    expiryBlock: row.expiryBlock,
    requiredConfirmations: row.requiredConfirmations,
    status: row.status,
    receivedAmountUnits: row.receivedAmountUnits,
    detectedAmountUnits: row.detectedAmountUnits,
    matchConfidence: row.matchConfidence,
    paidAt: row.paidAt,
    lastReconciledBlock: row.lastReconciledBlock,
    lastReconciledAt: row.lastReconciledAt,
    createdAt: row.createdAt,
    expiresAt: row.expiresAt,
    updatedAt: row.updatedAt,
  };
}

function evidenceToDomain(row: MatchedTransferRow): MatchedTransfer {
  return {
    txHash: row.txHash,
    logIndex: row.logIndex,
    blockNumber: row.blockNumber,
    blockHash: row.blockHash,
    fromAddress: row.fromAddress,
    toAddress: row.toAddress,
    amountUnits: row.amountUnits,
    blockTimestamp: row.blockTimestamp,
    association: row.association,
    confirmations: row.confirmations,
    firstSeenAt: row.firstSeenAt,
    lastSeenAt: row.lastSeenAt,
  };
}

/** `confirmations` is an `integer` column: exact `bigint` depth, bounded to the column's range. */
function confirmationsColumnValue(confirmations: bigint): number {
  if (confirmations < 0n) {
    return 0;
  }
  if (confirmations > INT32_MAX) {
    throw new RangeError(`confirmation depth ${confirmations} exceeds the integer column`);
  }
  return Number(confirmations);
}

function attemptRow(intentId: string, attempt: ReconciliationAttemptRecord) {
  return {
    paymentIntentId: intentId,
    requestId: attempt.requestId,
    provider: attempt.provider,
    fromBlock: attempt.fromBlock,
    toBlock: attempt.toBlock,
    latestBlock: attempt.latestBlock,
    candidateCount: attempt.candidateCount,
    resultStatus: attempt.resultStatus,
    errorCode: attempt.errorCode,
    startedAt: attempt.startedAt,
    completedAt: attempt.completedAt,
    durationMs: Math.max(0, Math.round(attempt.completedAt.getTime() - attempt.startedAt.getTime())),
  };
}

export function createDrizzlePaymentRepository(db: Database): PaymentRepository {
  return {
    async createPaymentIntent(intent: NewPaymentIntent): Promise<PaymentIntent> {
      const [row] = await db
        .insert(paymentIntents)
        .values({
          id: intent.id,
          accountId: null,
          externalReference: intent.externalReference,
          chain: CHAIN,
          asset: ASSET,
          tokenAddress: USDC_TOKEN_ADDRESS,
          expectedAmountUnits: intent.expectedAmountUnits,
          recipientAddress: intent.recipientAddress,
          payerAddress: intent.payerAddress,
          startBlock: intent.startBlock,
          expiryBlock: null,
          requiredConfirmations: intent.requiredConfirmations,
          status: "pending",
          receivedAmountUnits: 0n,
          detectedAmountUnits: 0n,
          matchConfidence: "none",
          paidAt: null,
          lastReconciledBlock: null,
          lastReconciledAt: null,
          expiresAt: intent.expiresAt,
        })
        .returning();
      if (row === undefined) {
        throw new Error("insert into payment_intents returned no row");
      }
      return toDomain(row);
    },

    async getPaymentIntentById(id: string): Promise<PaymentIntent | null> {
      const [row] = await db.select().from(paymentIntents).where(eq(paymentIntents.id, id)).limit(1);
      return row === undefined ? null : toDomain(row);
    },

    async applyReconciliation(
      intentId: string,
      observation: ReconciliationObservation,
    ): Promise<ApplyReconciliationOutcome | null> {
      return db.transaction(async (tx) => {
        // Serialize concurrent reconciliations of the same intent (ARCHITECTURE.md §7.5).
        const [locked] = await tx.select().from(paymentIntents).where(eq(paymentIntents.id, intentId)).for("update");
        if (locked === undefined) {
          return null;
        }

        const stale = locked.lastReconciledBlock !== null && observation.latestBlock < locked.lastReconciledBlock;
        const now = new Date();
        const { result } = observation;
        let current = locked;

        if (!stale) {
          for (const transfer of result.transfers) {
            // Identity (intent, tx_hash, log_index) is the double-counting guard: a
            // re-observed transfer refreshes its canonical block details, depth,
            // association and last_seen_at — never a new row. An orphaned identity
            // seen canonically again returns to matched/candidate here.
            await tx
              .insert(matchedTransfers)
              .values({
                paymentIntentId: intentId,
                txHash: transfer.txHash,
                logIndex: transfer.logIndex,
                blockNumber: transfer.blockNumber,
                blockHash: transfer.blockHash,
                fromAddress: transfer.from,
                toAddress: transfer.to,
                amountUnits: transfer.amountUnits,
                blockTimestamp: transfer.blockTimestamp,
                association: transfer.association,
                confirmations: confirmationsColumnValue(transfer.confirmations),
                firstSeenAt: now,
                lastSeenAt: now,
              })
              .onConflictDoUpdate({
                target: [matchedTransfers.paymentIntentId, matchedTransfers.txHash, matchedTransfers.logIndex],
                set: {
                  blockNumber: transfer.blockNumber,
                  blockHash: transfer.blockHash,
                  fromAddress: transfer.from,
                  toAddress: transfer.to,
                  amountUnits: transfer.amountUnits,
                  blockTimestamp: transfer.blockTimestamp,
                  association: transfer.association,
                  confirmations: confirmationsColumnValue(transfer.confirmations),
                  lastSeenAt: now,
                },
              });
          }

          // The scan is a complete canonical view of `window`: live evidence inside it
          // that was not re-observed is no longer canonical. Rows outside the window
          // are untouched — the scan says nothing about them (ARCHITECTURE.md §7.5).
          if (observation.window.fromBlock <= observation.window.toBlock) {
            const seen = new Set(result.transfers.map(transferIdentity));
            const live = await tx
              .select({ id: matchedTransfers.id, txHash: matchedTransfers.txHash, logIndex: matchedTransfers.logIndex })
              .from(matchedTransfers)
              .where(
                and(
                  eq(matchedTransfers.paymentIntentId, intentId),
                  inArray(matchedTransfers.association, ["matched", "candidate"]),
                  gte(matchedTransfers.blockNumber, observation.window.fromBlock),
                  lte(matchedTransfers.blockNumber, observation.window.toBlock),
                ),
              );
            const orphanIds = live.filter((row) => !seen.has(transferIdentity(row))).map((row) => row.id);
            if (orphanIds.length > 0) {
              await tx
                .update(matchedTransfers)
                .set({ association: "orphaned" })
                .where(inArray(matchedTransfers.id, orphanIds));
            }
          }

          // Amounts are the domain's recomputation over the full window, never an increment.
          // The expiry block is written once and never regressed.
          const [updated] = await tx
            .update(paymentIntents)
            .set({
              status: result.status,
              receivedAmountUnits: result.receivedAmountUnits,
              detectedAmountUnits: result.detectedAmountUnits,
              matchConfidence: result.matchConfidence,
              paidAt: result.paidAt,
              expiryBlock: locked.expiryBlock ?? observation.expiryBlock,
              lastReconciledBlock: observation.latestBlock,
              lastReconciledAt: now,
              updatedAt: now,
            })
            .where(eq(paymentIntents.id, intentId))
            .returning();
          if (updated === undefined) {
            throw new Error(`payment_intents row ${intentId} vanished inside its own lock`);
          }
          current = updated;
        }

        await tx.insert(reconciliationAttempts).values(
          attemptRow(intentId, {
            ...observation.attempt,
            latestBlock: observation.latestBlock,
            resultStatus: stale ? null : result.status,
            errorCode: stale ? "STALE_OBSERVATION" : null,
          }),
        );

        return { applied: !stale, intent: toDomain(current) };
      });
    },

    async recordReconciliationAttempt(intentId: string, attempt: ReconciliationAttemptRecord): Promise<void> {
      await db.insert(reconciliationAttempts).values(attemptRow(intentId, attempt));
    },

    async getEvidencePage(intentId, { limit, cursor }): Promise<EvidencePage> {
      const afterCursor =
        cursor === null
          ? undefined
          : sql`(${matchedTransfers.blockNumber}, ${matchedTransfers.logIndex}, ${matchedTransfers.txHash}) > (${cursor.blockNumber.toString()}::bigint, ${cursor.logIndex}::integer, ${cursor.txHash})`;

      const rows = await db
        .select()
        .from(matchedTransfers)
        .where(and(eq(matchedTransfers.paymentIntentId, intentId), afterCursor))
        .orderBy(asc(matchedTransfers.blockNumber), asc(matchedTransfers.logIndex), asc(matchedTransfers.txHash))
        .limit(limit + 1);

      const page = rows.slice(0, limit).map(evidenceToDomain);
      const last = page[page.length - 1];
      const nextCursor: EvidenceCursor | null =
        rows.length > limit && last !== undefined
          ? { blockNumber: last.blockNumber, logIndex: last.logIndex, txHash: last.txHash }
          : null;
      return { items: page, nextCursor };
    },
  };
}
