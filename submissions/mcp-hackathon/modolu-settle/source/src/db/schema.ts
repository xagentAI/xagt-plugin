/**
 * Drizzle schema — the single source of truth for the PostgreSQL structure
 * described in ARCHITECTURE.md §4. Every change here ships with a generated
 * migration in `drizzle/` (`pnpm db:generate`); nothing applies schema at
 * runtime.
 */
import { sql } from "drizzle-orm";
import {
  bigint,
  check,
  index,
  integer,
  numeric,
  pgEnum,
  pgTable,
  smallint,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
} from "drizzle-orm/pg-core";

import {
  DEFAULT_REQUIRED_CONFIRMATIONS,
  MATCH_CONFIDENCES,
  MAX_REQUIRED_CONFIRMATIONS,
  MIN_REQUIRED_CONFIRMATIONS,
  PAYMENT_STATUSES,
  TRANSFER_ASSOCIATIONS,
} from "@/domain/payment-intent";

export const paymentStatusEnum = pgEnum("payment_status", PAYMENT_STATUSES);
export const matchConfidenceEnum = pgEnum("match_confidence", MATCH_CONFIDENCES);
export const transferAssociationEnum = pgEnum("transfer_association", TRANSFER_ASSOCIATIONS);

/** Exact integer token units; PostgreSQL `numeric(78,0)` ⇄ TypeScript `bigint`. */
const tokenUnits = (name: string) => numeric(name, { precision: 78, scale: 0, mode: "bigint" });
const blockNumber = (name: string) => bigint(name, { mode: "bigint" });
const timestamptz = (name: string) => timestamp(name, { withTimezone: true, mode: "date" });

/** One declared payment obligation (ARCHITECTURE.md §4.1). */
export const paymentIntents = pgTable(
  "payment_intents",
  {
    id: varchar("id", { length: 40 }).primaryKey(),
    /** Reserved future ownership hook; always NULL in v1. No accounts table exists. */
    accountId: uuid("account_id"),
    externalReference: varchar("external_reference", { length: 128 }),
    chain: varchar("chain", { length: 16 }).notNull(),
    asset: varchar("asset", { length: 16 }).notNull(),
    tokenAddress: varchar("token_address", { length: 42 }).notNull(),
    expectedAmountUnits: tokenUnits("expected_amount_units").notNull(),
    recipientAddress: varchar("recipient_address", { length: 42 }).notNull(),
    payerAddress: varchar("payer_address", { length: 42 }),
    startBlock: blockNumber("start_block").notNull(),
    expiryBlock: blockNumber("expiry_block"),
    requiredConfirmations: smallint("required_confirmations")
      .notNull()
      .default(DEFAULT_REQUIRED_CONFIRMATIONS),
    status: paymentStatusEnum("status").notNull().default("pending"),
    receivedAmountUnits: tokenUnits("received_amount_units").notNull().default(sql`0`),
    detectedAmountUnits: tokenUnits("detected_amount_units").notNull().default(sql`0`),
    matchConfidence: matchConfidenceEnum("match_confidence").notNull().default("none"),
    paidAt: timestamptz("paid_at"),
    lastReconciledBlock: blockNumber("last_reconciled_block"),
    lastReconciledAt: timestamptz("last_reconciled_at"),
    createdAt: timestamptz("created_at").notNull().defaultNow(),
    expiresAt: timestamptz("expires_at").notNull(),
    updatedAt: timestamptz("updated_at").notNull().defaultNow(),
  },
  (table) => [
    index("payment_intents_status_expires_at_idx").on(table.status, table.expiresAt),
    index("payment_intents_recipient_created_at_idx").on(table.recipientAddress, table.createdAt),
    check("payment_intents_chain_check", sql`${table.chain} = 'base'`),
    check("payment_intents_asset_check", sql`${table.asset} = 'USDC'`),
    check("payment_intents_expected_amount_positive", sql`${table.expectedAmountUnits} > 0`),
    check("payment_intents_received_amount_non_negative", sql`${table.receivedAmountUnits} >= 0`),
    check("payment_intents_detected_amount_non_negative", sql`${table.detectedAmountUnits} >= 0`),
    check(
      "payment_intents_required_confirmations_range",
      sql`${table.requiredConfirmations} between ${sql.raw(String(MIN_REQUIRED_CONFIRMATIONS))} and ${sql.raw(String(MAX_REQUIRED_CONFIRMATIONS))}`,
    ),
    check(
      "payment_intents_expires_after_creation",
      sql`${table.expiresAt} > ${table.createdAt} and ${table.expiresAt} <= ${table.createdAt} + interval '7 days'`,
    ),
  ],
);

/** Chain evidence observed while reconciling an intent (ARCHITECTURE.md §4.2). */
export const matchedTransfers = pgTable(
  "matched_transfers",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    paymentIntentId: varchar("payment_intent_id", { length: 40 })
      .notNull()
      .references(() => paymentIntents.id, { onDelete: "restrict" }),
    txHash: varchar("tx_hash", { length: 66 }).notNull(),
    logIndex: integer("log_index").notNull(),
    blockNumber: blockNumber("block_number").notNull(),
    blockHash: varchar("block_hash", { length: 66 }).notNull(),
    fromAddress: varchar("from_address", { length: 42 }).notNull(),
    toAddress: varchar("to_address", { length: 42 }).notNull(),
    amountUnits: tokenUnits("amount_units").notNull(),
    blockTimestamp: timestamptz("block_timestamp").notNull(),
    association: transferAssociationEnum("association").notNull(),
    confirmations: integer("confirmations").notNull(),
    firstSeenAt: timestamptz("first_seen_at").notNull().defaultNow(),
    lastSeenAt: timestamptz("last_seen_at").notNull().defaultNow(),
  },
  (table) => [
    // Primary double-counting guard.
    uniqueIndex("matched_transfers_intent_tx_log_unique").on(
      table.paymentIntentId,
      table.txHash,
      table.logIndex,
    ),
    index("matched_transfers_intent_block_log_idx").on(
      table.paymentIntentId,
      table.blockNumber,
      table.logIndex,
    ),
    index("matched_transfers_tx_hash_idx").on(table.txHash),
    check("matched_transfers_amount_non_negative", sql`${table.amountUnits} >= 0`),
  ],
);

/** Operational history of reconciliation runs; no raw provider payloads (ARCHITECTURE.md §4.3). */
export const reconciliationAttempts = pgTable(
  "reconciliation_attempts",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    paymentIntentId: varchar("payment_intent_id", { length: 40 })
      .notNull()
      .references(() => paymentIntents.id, { onDelete: "restrict" }),
    requestId: varchar("request_id", { length: 64 }).notNull(),
    provider: varchar("provider", { length: 32 }).notNull(),
    fromBlock: blockNumber("from_block").notNull(),
    toBlock: blockNumber("to_block").notNull(),
    latestBlock: blockNumber("latest_block"),
    candidateCount: integer("candidate_count").notNull().default(0),
    resultStatus: paymentStatusEnum("result_status"),
    errorCode: varchar("error_code", { length: 64 }),
    startedAt: timestamptz("started_at").notNull(),
    completedAt: timestamptz("completed_at").notNull(),
    durationMs: integer("duration_ms").notNull(),
  },
  (table) => [
    index("reconciliation_attempts_intent_started_at_idx").on(
      table.paymentIntentId,
      table.startedAt.desc(),
    ),
  ],
);
