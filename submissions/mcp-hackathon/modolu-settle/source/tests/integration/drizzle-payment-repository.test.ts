/**
 * Database integration tests (ARCHITECTURE.md §13). They run only when
 * `TEST_DATABASE_URL` points at a dedicated Neon test/preview database —
 * never production. The migration in `drizzle/` is applied to that database
 * before the suite runs.
 *
 *   TEST_DATABASE_URL=postgres://... pnpm test tests/integration
 */
import { sql } from "drizzle-orm";
import { migrate } from "drizzle-orm/node-postgres/migrator";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { createDatabase, type DatabaseHandle } from "@/db/client";
import { paymentIntents } from "@/db/schema";
import { newPaymentIntentId } from "@/lib/ids";
import { createDrizzlePaymentRepository } from "@/repositories/drizzle-payment-repository";

const TEST_DATABASE_URL = process.env["TEST_DATABASE_URL"];

/** Drizzle wraps driver failures in `DrizzleQueryError`; the pg error with the constraint name is its `cause`. */
async function expectConstraintViolation(promise: Promise<unknown>, constraint: string): Promise<void> {
  let caught: unknown;
  try {
    await promise;
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(Error);
  const cause = (caught as Error).cause as { constraint?: string } | undefined;
  expect(cause?.constraint).toBe(constraint);
}

describe.skipIf(TEST_DATABASE_URL === undefined)("DrizzlePaymentRepository (Neon)", () => {
  let handle: DatabaseHandle;
  const createdIds: string[] = [];

  beforeAll(async () => {
    handle = createDatabase(TEST_DATABASE_URL as string);
    await migrate(handle.db, { migrationsFolder: "drizzle" });
  });

  afterAll(async () => {
    if (createdIds.length > 0) {
      await handle.db.execute(
        sql`delete from payment_intents where id in (${sql.join(
          createdIds.map((id) => sql`${id}`),
          sql`, `,
        )})`,
      );
    }
    await handle.pool.end();
  });

  function newIntent(overrides: Partial<Parameters<ReturnType<typeof createDrizzlePaymentRepository>["createPaymentIntent"]>[0]> = {}) {
    const id = newPaymentIntentId();
    createdIds.push(id);
    return {
      id,
      externalReference: "INV-204",
      expectedAmountUnits: 850_000_000n,
      recipientAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
      payerAddress: "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
      expiresAt: new Date(Date.now() + 60 * 60 * 1000),
      requiredConfirmations: 3,
      startBlock: 35_000_001n,
      ...overrides,
    };
  }

  it("applies the migration idempotently", async () => {
    await expect(migrate(handle.db, { migrationsFolder: "drizzle" })).resolves.toBeUndefined();
    const tables = await handle.db.execute<{ table_name: string }>(
      sql`select table_name from information_schema.tables where table_schema = 'public' order by table_name`,
    );
    const names = tables.rows.map((row) => row.table_name);
    expect(names).toEqual(expect.arrayContaining(["payment_intents", "matched_transfers", "reconciliation_attempts"]));
  });

  it("inserts a pending intent with the initial state and reads it back by ID", async () => {
    const repository = createDrizzlePaymentRepository(handle.db);
    const input = newIntent();

    const created = await repository.createPaymentIntent(input);
    expect(created).toMatchObject({
      id: input.id,
      status: "pending",
      chain: "base",
      asset: "USDC",
      tokenAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
      expectedAmountUnits: 850_000_000n,
      receivedAmountUnits: 0n,
      detectedAmountUnits: 0n,
      matchConfidence: "none",
      startBlock: 35_000_001n,
      expiryBlock: null,
      paidAt: null,
      lastReconciledBlock: null,
      lastReconciledAt: null,
      requiredConfirmations: 3,
    });
    expect(created.createdAt).toBeInstanceOf(Date);
    expect(created.expiresAt.getTime()).toBe(input.expiresAt.getTime());

    await expect(repository.getPaymentIntentById(input.id)).resolves.toEqual(created);
  });

  it("round-trips numeric(78,0) token units and bigint block numbers exactly", async () => {
    const repository = createDrizzlePaymentRepository(handle.db);
    const huge = 123_456_789_012_345_678_901_234_567_890_000_000n;
    const created = await repository.createPaymentIntent(
      newIntent({ expectedAmountUnits: huge, startBlock: 9_007_199_254_740_993n }),
    );
    const loaded = await repository.getPaymentIntentById(created.id);
    expect(loaded?.expectedAmountUnits).toBe(huge);
    expect(loaded?.startBlock).toBe(9_007_199_254_740_993n);
    expect(typeof loaded?.expectedAmountUnits).toBe("bigint");

    const tiny = await repository.createPaymentIntent(newIntent({ expectedAmountUnits: 1n }));
    expect((await repository.getPaymentIntentById(tiny.id))?.expectedAmountUnits).toBe(1n);
  });

  it("returns null for an unknown ID", async () => {
    const repository = createDrizzlePaymentRepository(handle.db);
    await expect(repository.getPaymentIntentById(newPaymentIntentId())).resolves.toBeNull();
  });

  it("stores a null payer", async () => {
    const repository = createDrizzlePaymentRepository(handle.db);
    const created = await repository.createPaymentIntent(newIntent({ payerAddress: null }));
    expect((await repository.getPaymentIntentById(created.id))?.payerAddress).toBeNull();
  });

  it("rejects invalid persisted states through CHECK constraints", async () => {
    const repository = createDrizzlePaymentRepository(handle.db);
    await expectConstraintViolation(
      repository.createPaymentIntent(newIntent({ expectedAmountUnits: 0n })),
      "payment_intents_expected_amount_positive",
    );
    await expectConstraintViolation(
      repository.createPaymentIntent(newIntent({ requiredConfirmations: 65 })),
      "payment_intents_required_confirmations_range",
    );
    await expectConstraintViolation(
      repository.createPaymentIntent(newIntent({ expiresAt: new Date(Date.now() - 1000) })),
      "payment_intents_expires_after_creation",
    );
    await expectConstraintViolation(
      repository.createPaymentIntent(newIntent({ expiresAt: new Date(Date.now() + 8 * 24 * 60 * 60 * 1000) })),
      "payment_intents_expires_after_creation",
    );
    await expectConstraintViolation(
      handle.db.insert(paymentIntents).values({
        ...newIntent(),
        chain: "ethereum",
        asset: "USDC",
        tokenAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
      }),
      "payment_intents_chain_check",
    );
    await expectConstraintViolation(
      handle.db.insert(paymentIntents).values({
        ...newIntent(),
        chain: "base",
        asset: "USDT",
        tokenAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
      }),
      "payment_intents_asset_check",
    );
  });

  it("rejects duplicate IDs", async () => {
    const repository = createDrizzlePaymentRepository(handle.db);
    const input = newIntent();
    await repository.createPaymentIntent(input);
    await expectConstraintViolation(repository.createPaymentIntent(input), "payment_intents_pkey");
  });
});

// ---------------------------------------------------------------------------
// Milestone 2: reconciliation application, evidence, attempts, pagination
// ---------------------------------------------------------------------------
import { and, eq } from "drizzle-orm";

import { matchedTransfers, reconciliationAttempts } from "@/db/schema";
import { reconcile, type ObservedTransfer } from "@/domain/reconciliation";
import type { ReconciliationObservation } from "@/ports/payment-repository";

const PAYER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045";
const RECIPIENT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";

describe.skipIf(TEST_DATABASE_URL === undefined)("DrizzlePaymentRepository — reconciliation (Neon)", () => {
  let handle: DatabaseHandle;
  const createdIds: string[] = [];

  beforeAll(async () => {
    handle = createDatabase(TEST_DATABASE_URL as string);
    await migrate(handle.db, { migrationsFolder: "drizzle" });
  });

  afterAll(async () => {
    for (const id of createdIds) {
      await handle.db.delete(reconciliationAttempts).where(eq(reconciliationAttempts.paymentIntentId, id));
      await handle.db.delete(matchedTransfers).where(eq(matchedTransfers.paymentIntentId, id));
      await handle.db.delete(paymentIntents).where(eq(paymentIntents.id, id));
    }
    await handle.pool.end();
  });

  function observedTransfer(overrides: Partial<ObservedTransfer> & { blockNumber: bigint; amountUnits: bigint }): ObservedTransfer {
    return {
      txHash: `0x${overrides.blockNumber.toString(16).padStart(64, "0")}`,
      logIndex: 0,
      blockHash: `0x${"b".repeat(64)}`,
      from: PAYER,
      to: RECIPIENT,
      blockTimestamp: new Date(Number(overrides.blockNumber) * 2_000),
      ...overrides,
    };
  }

  function observation(
    latestBlock: bigint,
    transfers: ObservedTransfer[],
    expected = 25_000_000n,
    requestId = "req_it",
    options: { payer?: string | null; toBlock?: bigint; expiryPassed?: boolean; expiryBlock?: bigint | null } = {},
  ): ReconciliationObservation {
    const startedAt = new Date();
    const window = { fromBlock: 1_000n, toBlock: options.toBlock ?? latestBlock };
    return {
      latestBlock,
      window,
      expiryBlock: options.expiryBlock ?? null,
      result: reconcile({
        expectedAmountUnits: expected,
        requiredConfirmations: 3,
        latestBlock,
        payer: options.payer === undefined ? PAYER : options.payer,
        window,
        expiryPassed: options.expiryPassed ?? false,
        transfers,
      }),
      attempt: { requestId, provider: "alchemy", fromBlock: 1_000n, toBlock: window.toBlock, candidateCount: transfers.length, startedAt, completedAt: new Date(startedAt.getTime() + 5) },
    };
  }

  async function seedIntent(expected = 25_000_000n) {
    const repository = createDrizzlePaymentRepository(handle.db);
    const id = newPaymentIntentId();
    createdIds.push(id);
    const intent = await repository.createPaymentIntent({
      id,
      externalReference: "INV-204",
      expectedAmountUnits: expected,
      recipientAddress: RECIPIENT,
      payerAddress: PAYER,
      expiresAt: new Date(Date.now() + 60 * 60 * 1000),
      requiredConfirmations: 3,
      startBlock: 1_000n,
    });
    return { repository, intent };
  }

  async function evidenceRows(id: string) {
    return handle.db
      .select()
      .from(matchedTransfers)
      .where(eq(matchedTransfers.paymentIntentId, id))
      .orderBy(matchedTransfers.blockNumber, matchedTransfers.logIndex, matchedTransfers.txHash);
  }

  it("inserts evidence, persists the domain state and records the attempt atomically", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    const outcome = await repository.applyReconciliation(intent.id, observation(1_100n, [transfer]));

    expect(outcome?.applied).toBe(true);
    expect(outcome?.intent).toMatchObject({
      status: "paid",
      receivedAmountUnits: 25_000_000n,
      detectedAmountUnits: 25_000_000n,
      matchConfidence: "exact_payer",
      lastReconciledBlock: 1_100n,
    });
    expect(outcome?.intent.paidAt?.getTime()).toBe(transfer.blockTimestamp.getTime());
    expect(outcome?.intent.lastReconciledAt).toBeInstanceOf(Date);

    const rows = await evidenceRows(intent.id);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      txHash: transfer.txHash,
      logIndex: 0,
      blockNumber: 1_050n,
      blockHash: transfer.blockHash,
      fromAddress: PAYER,
      toAddress: RECIPIENT,
      amountUnits: 25_000_000n,
      association: "matched",
      confirmations: 51,
    });
    expect(rows[0]?.blockTimestamp.getTime()).toBe(transfer.blockTimestamp.getTime());

    const attempts = await handle.db.select().from(reconciliationAttempts).where(eq(reconciliationAttempts.paymentIntentId, intent.id));
    expect(attempts).toHaveLength(1);
    expect(attempts[0]).toMatchObject({
      requestId: "req_it",
      provider: "alchemy",
      fromBlock: 1_000n,
      toBlock: 1_100n,
      latestBlock: 1_100n,
      candidateCount: 1,
      resultStatus: "paid",
      errorCode: null,
      durationMs: 5,
    });
  });

  it("re-observing the same transfer upserts (confirmations + last_seen_at) without duplicating or re-adding amounts", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });

    const first = await repository.applyReconciliation(intent.id, observation(1_050n, [transfer]));
    expect(first?.intent.status).toBe("detected");
    const [row1] = await evidenceRows(intent.id);
    expect(row1?.confirmations).toBe(1);

    const second = await repository.applyReconciliation(intent.id, observation(1_052n, [transfer]));
    expect(second?.intent.status).toBe("paid");
    expect(second?.intent.receivedAmountUnits).toBe(25_000_000n);
    const rows = await evidenceRows(intent.id);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.confirmations).toBe(3);
    expect(rows[0]?.firstSeenAt.getTime()).toBe(row1?.firstSeenAt.getTime());
    expect(rows[0]?.lastSeenAt.getTime()).toBeGreaterThanOrEqual(row1?.lastSeenAt.getTime() ?? 0);

    const third = await repository.applyReconciliation(intent.id, observation(1_052n, [transfer]));
    expect(third?.intent.receivedAmountUnits).toBe(25_000_000n); // never 50_000_000n
    expect(await evidenceRows(intent.id)).toHaveLength(1);
  });

  it("round-trips numeric(78,0) evidence amounts exactly", async () => {
    const huge = 123_456_789_012_345_678_901_234_567_890_000_000n;
    const { repository, intent } = await seedIntent(huge);
    await repository.applyReconciliation(intent.id, observation(1_100n, [observedTransfer({ blockNumber: 1_050n, amountUnits: huge })], huge));
    const [row] = await evidenceRows(intent.id);
    expect(row?.amountUnits).toBe(huge);
    expect((await repository.getPaymentIntentById(intent.id))?.receivedAmountUnits).toBe(huge);
  });

  it("records a failed attempt without touching intent state or evidence", async () => {
    const { repository, intent } = await seedIntent();
    await repository.recordReconciliationAttempt(intent.id, {
      requestId: "req_fail",
      provider: "alchemy",
      fromBlock: 1_000n,
      toBlock: 1_000n,
      latestBlock: null,
      candidateCount: 0,
      resultStatus: null,
      errorCode: "UPSTREAM_UNAVAILABLE",
      startedAt: new Date(),
      completedAt: new Date(),
    });
    const [attempt] = await handle.db.select().from(reconciliationAttempts).where(eq(reconciliationAttempts.paymentIntentId, intent.id));
    expect(attempt).toMatchObject({ errorCode: "UPSTREAM_UNAVAILABLE", latestBlock: null, resultStatus: null });
    expect(await repository.getPaymentIntentById(intent.id)).toEqual(intent);
    expect(await evidenceRows(intent.id)).toHaveLength(0);
  });

  it("does not let a stale (older latest block) observation overwrite newer intent state", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    const newer = await repository.applyReconciliation(intent.id, observation(1_100n, [transfer]));
    expect(newer?.intent.status).toBe("paid");

    const stale = await repository.applyReconciliation(intent.id, observation(1_040n, [], 25_000_000n, "req_stale"));
    expect(stale?.applied).toBe(false);
    expect(stale?.intent).toEqual(newer?.intent);
    expect((await repository.getPaymentIntentById(intent.id))?.lastReconciledBlock).toBe(1_100n);
    const [staleAttempt] = await handle.db
      .select()
      .from(reconciliationAttempts)
      .where(and(eq(reconciliationAttempts.paymentIntentId, intent.id), eq(reconciliationAttempts.requestId, "req_stale")));
    expect(staleAttempt).toMatchObject({ errorCode: "STALE_OBSERVATION", resultStatus: null, latestBlock: 1_040n });
  });

  it("serializes concurrent applications through the row lock: no duplicate evidence, consistent final state", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    const outcomes = await Promise.all(
      Array.from({ length: 6 }, (_, i) =>
        repository.applyReconciliation(intent.id, observation(1_100n + BigInt(i % 2), [transfer], 25_000_000n, `req_c${i}`)),
      ),
    );
    expect(outcomes.every((outcome) => outcome?.intent.receivedAmountUnits === 25_000_000n)).toBe(true);
    expect(await evidenceRows(intent.id)).toHaveLength(1);
    const final = await repository.getPaymentIntentById(intent.id);
    expect(final?.status).toBe("paid");
    expect(final?.lastReconciledBlock).toBe(1_101n);
    const attempts = await handle.db.select().from(reconciliationAttempts).where(eq(reconciliationAttempts.paymentIntentId, intent.id));
    expect(attempts).toHaveLength(6);
  });

  it("returns null when applying to an unknown intent", async () => {
    const repository = createDrizzlePaymentRepository(handle.db);
    await expect(repository.applyReconciliation(newPaymentIntentId(), observation(1n, []))).resolves.toBeNull();
  });

  it("pages evidence by (block_number, log_index, tx_hash) with a keyset cursor", async () => {
    const { repository, intent } = await seedIntent(1_000_000_000n);
    const transfers = [
      observedTransfer({ blockNumber: 1_020n, logIndex: 5, amountUnits: 1n, txHash: `0x${"b".repeat(64)}` }),
      observedTransfer({ blockNumber: 1_010n, logIndex: 9, amountUnits: 1n, txHash: `0x${"9".repeat(64)}` }),
      observedTransfer({ blockNumber: 1_020n, logIndex: 2, amountUnits: 1n, txHash: `0x${"c".repeat(64)}` }),
      observedTransfer({ blockNumber: 1_020n, logIndex: 2, amountUnits: 1n, txHash: `0x${"a".repeat(64)}` }),
      observedTransfer({ blockNumber: 1_030n, logIndex: 0, amountUnits: 1n, txHash: `0x${"d".repeat(64)}` }),
    ];
    await repository.applyReconciliation(intent.id, observation(1_100n, transfers, 1_000_000_000n));

    const key = (row: { blockNumber: bigint; logIndex: number; txHash: string }) => `${row.blockNumber}:${row.logIndex}:${row.txHash[2]}`;
    const page1 = await repository.getEvidencePage(intent.id, { limit: 2, cursor: null });
    expect(page1.items.map(key)).toEqual(["1010:9:9", "1020:2:a"]);
    expect(page1.nextCursor).toEqual({ blockNumber: 1_020n, logIndex: 2, txHash: `0x${"a".repeat(64)}` });

    const page2 = await repository.getEvidencePage(intent.id, { limit: 2, cursor: page1.nextCursor });
    expect(page2.items.map(key)).toEqual(["1020:2:c", "1020:5:b"]);

    const page3 = await repository.getEvidencePage(intent.id, { limit: 2, cursor: page2.nextCursor });
    expect(page3.items.map(key)).toEqual(["1030:0:d"]);
    expect(page3.nextCursor).toBeNull();

    const all = await repository.getEvidencePage(intent.id, { limit: 100, cursor: null });
    expect(all.items).toHaveLength(5);
    expect(all.nextCursor).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Milestone 3: canonical evidence (orphaning), associations, expiry block
// ---------------------------------------------------------------------------
const SENDER_B = "0x1111111111111111111111111111111111111111";

describe.skipIf(TEST_DATABASE_URL === undefined)("DrizzlePaymentRepository — canonical evidence (Neon)", () => {
  let handle: DatabaseHandle;
  const createdIds: string[] = [];

  beforeAll(async () => {
    handle = createDatabase(TEST_DATABASE_URL as string);
    await migrate(handle.db, { migrationsFolder: "drizzle" });
  });

  afterAll(async () => {
    for (const id of createdIds) {
      await handle.db.delete(reconciliationAttempts).where(eq(reconciliationAttempts.paymentIntentId, id));
      await handle.db.delete(matchedTransfers).where(eq(matchedTransfers.paymentIntentId, id));
      await handle.db.delete(paymentIntents).where(eq(paymentIntents.id, id));
    }
    await handle.pool.end();
  });

  function observedTransfer(overrides: Partial<ObservedTransfer> & { blockNumber: bigint; amountUnits: bigint }): ObservedTransfer {
    return {
      txHash: `0x${overrides.blockNumber.toString(16).padStart(64, "0")}`,
      logIndex: 0,
      blockHash: `0x${"b".repeat(64)}`,
      from: PAYER,
      to: RECIPIENT,
      blockTimestamp: new Date(Number(overrides.blockNumber) * 2_000),
      ...overrides,
    };
  }

  function observation(
    latestBlock: bigint,
    transfers: ObservedTransfer[],
    options: { payer?: string | null; toBlock?: bigint; expiryPassed?: boolean; expiryBlock?: bigint | null; expected?: bigint; requestId?: string } = {},
  ): ReconciliationObservation {
    const startedAt = new Date();
    const window = { fromBlock: 1_000n, toBlock: options.toBlock ?? latestBlock };
    return {
      latestBlock,
      window,
      expiryBlock: options.expiryBlock ?? null,
      result: reconcile({
        expectedAmountUnits: options.expected ?? 25_000_000n,
        requiredConfirmations: 3,
        latestBlock,
        payer: options.payer === undefined ? PAYER : options.payer,
        window,
        expiryPassed: options.expiryPassed ?? false,
        transfers,
      }),
      attempt: { requestId: options.requestId ?? "req_it", provider: "alchemy", fromBlock: 1_000n, toBlock: window.toBlock, candidateCount: transfers.length, startedAt, completedAt: startedAt },
    };
  }

  async function seedIntent(payer: string | null = PAYER, expected = 25_000_000n) {
    const repository = createDrizzlePaymentRepository(handle.db);
    const id = newPaymentIntentId();
    createdIds.push(id);
    const intent = await repository.createPaymentIntent({
      id,
      externalReference: null,
      expectedAmountUnits: expected,
      recipientAddress: RECIPIENT,
      payerAddress: payer,
      expiresAt: new Date(Date.now() + 60 * 60 * 1000),
      requiredConfirmations: 3,
      startBlock: 1_000n,
    });
    return { repository, intent };
  }

  async function rows(id: string) {
    return handle.db
      .select()
      .from(matchedTransfers)
      .where(eq(matchedTransfers.paymentIntentId, id))
      .orderBy(matchedTransfers.blockNumber, matchedTransfers.logIndex, matchedTransfers.txHash);
  }

  it("matched → orphaned when absent from a later complete scan; totals and status regress", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    expect((await repository.applyReconciliation(intent.id, observation(1_100n, [transfer])))?.intent.status).toBe("paid");

    const outcome = await repository.applyReconciliation(intent.id, observation(1_101n, []));
    expect(outcome?.intent).toMatchObject({ status: "pending", receivedAmountUnits: 0n, detectedAmountUnits: 0n, matchConfidence: "none", paidAt: null });
    const [row] = await rows(intent.id);
    expect(row?.association).toBe("orphaned");
    expect(await rows(intent.id)).toHaveLength(1);
  });

  it("orphaned → matched again when the identity is canonical again", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    await repository.applyReconciliation(intent.id, observation(1_100n, [transfer]));
    await repository.applyReconciliation(intent.id, observation(1_101n, []));
    expect((await rows(intent.id))[0]?.association).toBe("orphaned");

    const outcome = await repository.applyReconciliation(intent.id, observation(1_102n, [transfer]));
    expect(outcome?.intent.status).toBe("paid");
    const all = await rows(intent.id);
    expect(all).toHaveLength(1);
    expect(all[0]).toMatchObject({ association: "matched", confirmations: 53 });
  });

  it("block hash change: the same identity re-observed in another canonical block updates the row", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n, blockHash: `0x${"1".repeat(64)}` });
    await repository.applyReconciliation(intent.id, observation(1_100n, [transfer]));
    const moved = { ...transfer, blockNumber: 1_052n, blockHash: `0x${"2".repeat(64)}`, blockTimestamp: new Date(1_052 * 2_000) };
    await repository.applyReconciliation(intent.id, observation(1_101n, [moved]));
    const all = await rows(intent.id);
    expect(all).toHaveLength(1);
    expect(all[0]).toMatchObject({ blockNumber: 1_052n, blockHash: `0x${"2".repeat(64)}`, association: "matched", confirmations: 50 });
    expect(all[0]?.blockTimestamp.getTime()).toBe(1_052 * 2_000);
  });

  it("candidate rows never affect received/detected; candidate → orphaned and candidate → matched as ambiguity resolves", async () => {
    const { repository, intent } = await seedIntent(null);
    const a = observedTransfer({ blockNumber: 1_010n, amountUnits: 25_000_000n, from: SENDER_B });
    const b = observedTransfer({ blockNumber: 1_020n, amountUnits: 1n, from: PAYER });

    const ambiguous = await repository.applyReconciliation(intent.id, observation(1_100n, [a, b], { payer: null }));
    expect(ambiguous?.intent).toMatchObject({ status: "ambiguous", matchConfidence: "ambiguous", receivedAmountUnits: 0n, detectedAmountUnits: 0n });
    expect((await rows(intent.id)).map((row) => row.association)).toEqual(["candidate", "candidate"]);

    const resolved = await repository.applyReconciliation(intent.id, observation(1_101n, [a], { payer: null }));
    expect(resolved?.intent).toMatchObject({ status: "paid", matchConfidence: "single_sender", receivedAmountUnits: 25_000_000n });
    expect((await rows(intent.id)).map((row) => [row.txHash, row.association])).toEqual([
      [a.txHash, "matched"],
      [b.txHash, "orphaned"],
    ]);
  });

  it("a stale concurrent observation cannot re-match orphaned evidence, alter totals, or regress the expiry block", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    await repository.applyReconciliation(intent.id, observation(1_100n, [transfer]));
    const newest = await repository.applyReconciliation(intent.id, observation(1_120n, [], { toBlock: 1_060n, expiryPassed: true, expiryBlock: 1_060n }));
    expect(newest?.intent).toMatchObject({ status: "expired", expiryBlock: 1_060n, lastReconciledBlock: 1_120n });
    expect((await rows(intent.id))[0]?.association).toBe("orphaned");

    const stale = await repository.applyReconciliation(intent.id, observation(1_110n, [transfer], { expiryBlock: 1_070n, requestId: "req_stale" }));
    expect(stale?.applied).toBe(false);
    expect(stale?.intent).toEqual(newest?.intent);
    expect((await rows(intent.id))[0]?.association).toBe("orphaned");
    expect((await repository.getPaymentIntentById(intent.id))?.expiryBlock).toBe(1_060n);
  });

  it("persists the first resolved expiry block and never regresses or overwrites it", async () => {
    const { repository, intent } = await seedIntent();
    const first = await repository.applyReconciliation(intent.id, observation(1_100n, [], { toBlock: 1_050n, expiryPassed: true, expiryBlock: 1_050n }));
    expect(first?.intent.expiryBlock).toBe(1_050n);
    const second = await repository.applyReconciliation(intent.id, observation(1_101n, [], { toBlock: 1_050n, expiryPassed: true, expiryBlock: 1_049n }));
    expect(second?.intent.expiryBlock).toBe(1_050n);
    const third = await repository.applyReconciliation(intent.id, observation(1_102n, [], { toBlock: 1_050n, expiryPassed: true, expiryBlock: null }));
    expect(third?.intent.expiryBlock).toBe(1_050n);
  });

  it("does not orphan evidence outside the scanned window", async () => {
    const { repository, intent } = await seedIntent();
    const late = observedTransfer({ blockNumber: 1_080n, amountUnits: 25_000_000n });
    await repository.applyReconciliation(intent.id, observation(1_100n, [late]));
    const narrowed = await repository.applyReconciliation(intent.id, observation(1_101n, [], { toBlock: 1_050n, expiryPassed: true, expiryBlock: 1_050n }));
    expect(narrowed?.intent.status).toBe("expired");
    expect((await rows(intent.id))[0]?.association).toBe("matched");
  });

  it("never creates duplicate evidence rows across orphan/restore cycles", async () => {
    const { repository, intent } = await seedIntent();
    const transfer = observedTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    for (let i = 0; i < 4; i += 1) {
      await repository.applyReconciliation(intent.id, observation(1_100n + BigInt(i * 2), [transfer]));
      await repository.applyReconciliation(intent.id, observation(1_101n + BigInt(i * 2), []));
    }
    expect(await rows(intent.id)).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Milestone 5: all-or-nothing application under mid-transaction failure
// ---------------------------------------------------------------------------
describe.skipIf(TEST_DATABASE_URL === undefined)("DrizzlePaymentRepository — transaction atomicity (Neon)", () => {
  let handle: DatabaseHandle;
  const createdIds: string[] = [];

  beforeAll(async () => {
    handle = createDatabase(TEST_DATABASE_URL as string);
    await migrate(handle.db, { migrationsFolder: "drizzle" });
  });

  afterAll(async () => {
    for (const id of createdIds) {
      await handle.db.delete(reconciliationAttempts).where(eq(reconciliationAttempts.paymentIntentId, id));
      await handle.db.delete(matchedTransfers).where(eq(matchedTransfers.paymentIntentId, id));
      await handle.db.delete(paymentIntents).where(eq(paymentIntents.id, id));
    }
    await handle.pool.end();
  });

  function transferAt(blockNumber: bigint, amountUnits: bigint): ObservedTransfer {
    return {
      txHash: `0x${blockNumber.toString(16).padStart(64, "0")}`,
      logIndex: 0,
      blockNumber,
      blockHash: `0x${"b".repeat(64)}`,
      from: PAYER,
      to: RECIPIENT,
      amountUnits,
      blockTimestamp: new Date(Number(blockNumber) * 2_000),
    };
  }

  function observe(latestBlock: bigint, transfers: ObservedTransfer[], requestId = "req_atomic"): ReconciliationObservation {
    const window = { fromBlock: 1_000n, toBlock: latestBlock };
    const startedAt = new Date();
    return {
      latestBlock,
      window,
      expiryBlock: null,
      result: reconcile({ expectedAmountUnits: 25_000_000n, requiredConfirmations: 3, latestBlock, payer: PAYER, window, expiryPassed: false, transfers }),
      attempt: { requestId, provider: "alchemy", fromBlock: 1_000n, toBlock: latestBlock, candidateCount: transfers.length, startedAt, completedAt: startedAt },
    };
  }

  async function seed() {
    const repository = createDrizzlePaymentRepository(handle.db);
    const id = newPaymentIntentId();
    createdIds.push(id);
    await repository.createPaymentIntent({
      id,
      externalReference: null,
      expectedAmountUnits: 25_000_000n,
      recipientAddress: RECIPIENT,
      payerAddress: PAYER,
      expiresAt: new Date(Date.now() + 60 * 60 * 1000),
      requiredConfirmations: 3,
      startBlock: 1_000n,
    });
    const first = await repository.applyReconciliation(id, observe(1_100n, [transferAt(1_050n, 15_000_000n)]));
    expect(first?.intent.status).toBe("partial");
    return { repository, id, before: first?.intent };
  }

  async function snapshot(id: string) {
    const rows = await handle.db.select().from(matchedTransfers).where(eq(matchedTransfers.paymentIntentId, id));
    const attempts = await handle.db.select().from(reconciliationAttempts).where(eq(reconciliationAttempts.paymentIntentId, id));
    return { rows: rows.length, attempts: attempts.length };
  }

  it("a failure on the final attempt insert rolls back the evidence upserts and the intent update", async () => {
    const { repository, id, before } = await seed();
    const initial = await snapshot(id);
    // request_id is varchar(64): an oversized value fails the very last statement of the transaction.
    const poisoned = observe(1_101n, [transferAt(1_050n, 15_000_000n), transferAt(1_060n, 10_000_000n)], "r".repeat(65));
    await expect(repository.applyReconciliation(id, poisoned)).rejects.toThrow();
    expect(await snapshot(id)).toEqual(initial);
    expect(await repository.getPaymentIntentById(id)).toEqual(before);
  });

  it("a failure on the intent update rolls back evidence written earlier in the same transaction", async () => {
    const { repository, id, before } = await seed();
    const initial = await snapshot(id);
    const good = observe(1_101n, [transferAt(1_050n, 15_000_000n), transferAt(1_060n, 10_000_000n)]);
    // Violates payment_intents_received_amount_non_negative during the UPDATE, after the upserts ran.
    const poisoned: ReconciliationObservation = { ...good, result: { ...good.result, receivedAmountUnits: -1n } };
    await expect(repository.applyReconciliation(id, poisoned)).rejects.toThrow();
    expect(await snapshot(id)).toEqual(initial);
    expect(await repository.getPaymentIntentById(id)).toEqual(before);
    // The same observation, un-poisoned, then applies cleanly — nothing was left half-written.
    const applied = await repository.applyReconciliation(id, good);
    expect(applied?.intent.status).toBe("paid");
    expect((await snapshot(id)).rows).toBe(2);
  });

  it("a stale observation remains non-destructive even when it carries contradictory evidence", async () => {
    const { repository, id, before } = await seed();
    const stale = await repository.applyReconciliation(id, observe(1_090n, [], "req_stale_m5"));
    expect(stale?.applied).toBe(false);
    expect(await repository.getPaymentIntentById(id)).toEqual(before);
    expect((await snapshot(id)).rows).toBe(1);
  });
});
