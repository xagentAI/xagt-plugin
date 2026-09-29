import { describe, expect, it } from "vitest";

import { AppError } from "@/lib/errors";
import { newPaymentIntentId } from "@/lib/ids";
import type { ChainTransfer } from "@/ports/chain-provider";
import { reconcilePaymentIntent } from "@/services/reconcile-payment-intent";

import { FakeChainProvider, InMemoryPaymentRepository, type FakeChainState } from "./fakes";

const PAYER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045";
const RECIPIENT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const OTHER = "0x1111111111111111111111111111111111111111";
const START_BLOCK = 1_000n;

function chainTransfer(overrides: Partial<ChainTransfer> & { blockNumber: bigint; amountUnits: bigint }): ChainTransfer {
  return {
    txHash: `0x${overrides.blockNumber.toString(16).padStart(64, "0")}`,
    logIndex: 0,
    blockHash: `0x${"b".repeat(64)}`,
    from: PAYER,
    to: RECIPIENT,
    ...overrides,
  };
}

interface SetupOptions {
  payerAddress?: string | null;
  expectedAmountUnits?: bigint;
  requiredConfirmations?: number;
  expiresAt?: Date;
  /** Wall clock used by the service; defaults to well before the intent's expiry. */
  now?: () => Date;
}

/** Fake chain time: block n is mined at n * 2 s after the epoch. */
const blockTime = (blockNumber: bigint) => new Date(Number(blockNumber) * 2_000);

async function setup(chain: FakeChainState, options: SetupOptions = {}) {
  const chainProvider = new FakeChainProvider(chain);
  const paymentRepository = new InMemoryPaymentRepository();
  const expiresAt = options.expiresAt ?? new Date(Date.now() + 60 * 60 * 1000);
  const intent = await paymentRepository.createPaymentIntent({
    id: newPaymentIntentId(),
    externalReference: "INV-204",
    expectedAmountUnits: options.expectedAmountUnits ?? 25_000_000n,
    recipientAddress: RECIPIENT,
    payerAddress: options.payerAddress === undefined ? PAYER : options.payerAddress,
    expiresAt,
    requiredConfirmations: options.requiredConfirmations ?? 3,
    startBlock: START_BLOCK,
  });
  const now = options.now ?? (() => new Date(expiresAt.getTime() - 1_000));
  const reconcile = (requestId = "req_test") =>
    reconcilePaymentIntent(intent.id, { chainProvider, paymentRepository, requestId, now });
  return { chainProvider, paymentRepository, intent, reconcile };
}

async function captureAppError(promise: Promise<unknown>): Promise<AppError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(AppError);
    return error as AppError;
  }
  return expect.unreachable("expected an AppError");
}

describe("reconcilePaymentIntent — query window", () => {
  it("queries exactly [intent.startBlock, latestBlock] for payer → recipient", async () => {
    const { chainProvider, reconcile } = await setup({ latestBlock: 1_500n, transfers: [] });
    await reconcile();
    expect(chainProvider.transferQueries).toEqual([
      { fromBlock: START_BLOCK, toBlock: 1_500n, recipient: RECIPIENT, payer: PAYER },
    ]);
  });

  it("skips the log query when the window is empty (latest block below startBlock) and records a pending observation", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 999n, transfers: [] });
    const outcome = await reconcile();
    expect(chainProvider.transferQueries).toEqual([]);
    expect(outcome.intent.status).toBe("pending");
    expect(outcome.intent.lastReconciledBlock).toBe(999n);
    expect(paymentRepository.attempts).toEqual([
      expect.objectContaining({ paymentIntentId: intent.id, fromBlock: START_BLOCK, toBlock: 999n, latestBlock: 999n, candidateCount: 0, resultStatus: "pending" }),
    ]);
  });

  it("calculates confirmation depth from the same latest-block observation used for the query", async () => {
    const { reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_010n,
      transfers: [chainTransfer({ blockNumber: 1_010n, amountUnits: 25_000_000n })],
    });
    const outcome = await reconcile();
    expect(outcome.latestBlock).toBe(1_010n);
    expect(outcome.intent.status).toBe("detected");
    expect(paymentRepository.evidenceRows(intent.id)[0]?.confirmations).toBe(1);
  });

  it("fetches each distinct block timestamp once and maps it to every transfer in that block", async () => {
    const timestamps = new Map<bigint, Date>([
      [1_100n, new Date("2026-09-17T10:00:00.000Z")],
      [1_200n, new Date("2026-09-17T11:00:00.000Z")],
    ]);
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_300n,
      timestamps,
      transfers: [
        chainTransfer({ blockNumber: 1_100n, logIndex: 1, amountUnits: 5_000_000n, txHash: `0x${"1".repeat(64)}` }),
        chainTransfer({ blockNumber: 1_100n, logIndex: 7, amountUnits: 5_000_000n, txHash: `0x${"2".repeat(64)}` }),
        chainTransfer({ blockNumber: 1_200n, logIndex: 0, amountUnits: 15_000_000n, txHash: `0x${"3".repeat(64)}` }),
        chainTransfer({ blockNumber: 1_100n, logIndex: 9, amountUnits: 1n, txHash: `0x${"4".repeat(64)}` }),
      ],
    });
    const outcome = await reconcile();
    expect([...chainProvider.timestampRequests].sort()).toEqual([1_100n, 1_200n]);
    const rows = paymentRepository.evidenceRows(intent.id);
    expect(rows.map((row) => row.blockTimestamp.toISOString())).toEqual([
      "2026-09-17T10:00:00.000Z",
      "2026-09-17T10:00:00.000Z",
      "2026-09-17T10:00:00.000Z",
      "2026-09-17T11:00:00.000Z",
    ]);
    // 5 + 5 + 0.000001 + 15 = 25.000001 > 25: overpaid, crossing transfer is the block-1200 one.
    expect(outcome.intent.status).toBe("overpaid");
    expect(outcome.intent.paidAt).toEqual(new Date("2026-09-17T11:00:00.000Z"));
  });
});

describe("reconcilePaymentIntent — state and idempotency", () => {
  it("Test A: one confirmed matching transfer → paid, received = X, evidence persisted once", async () => {
    const { reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    const outcome = await reconcile();
    expect(outcome).toMatchObject({ applied: true, candidateCount: 1, latestBlock: 1_100n });
    expect(outcome.intent).toMatchObject({
      status: "paid",
      receivedAmountUnits: 25_000_000n,
      detectedAmountUnits: 25_000_000n,
      matchConfidence: "exact_payer",
      lastReconciledBlock: 1_100n,
    });
    expect(outcome.intent.paidAt).toEqual(new Date(1_050 * 2_000));
    expect(paymentRepository.evidenceRows(intent.id)).toHaveLength(1);
    expect(paymentRepository.evidenceRows(intent.id)[0]).toMatchObject({ association: "matched", confirmations: 51, amountUnits: 25_000_000n });
  });

  it("Test B: reconciling the same provider result again leaves received = X and the evidence count unchanged", async () => {
    const { reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    const first = await reconcile("req_1");
    const second = await reconcile("req_2");
    const third = await reconcile("req_3");
    for (const outcome of [first, second, third]) {
      expect(outcome.intent.receivedAmountUnits).toBe(25_000_000n);
      expect(outcome.intent.detectedAmountUnits).toBe(25_000_000n);
      expect(outcome.intent.status).toBe("paid");
    }
    expect(paymentRepository.evidenceRows(intent.id)).toHaveLength(1);
    expect(paymentRepository.attempts).toHaveLength(3);
    expect(second.intent.paidAt).toEqual(first.intent.paidAt);
  });

  it("Test C: a transfer gaining confirmations updates the existing evidence row instead of duplicating it", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_050n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    const detected = await reconcile();
    expect(detected.intent.status).toBe("detected");
    const [row] = paymentRepository.evidenceRows(intent.id);
    expect(row?.confirmations).toBe(1);

    chainProvider.state.latestBlock = 1_052n;
    const paid = await reconcile();
    expect(paid.intent.status).toBe("paid");
    const rows = paymentRepository.evidenceRows(intent.id);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.confirmations).toBe(3);
    expect(rows[0]?.firstSeenAt).toEqual(row?.firstSeenAt);
  });

  it("Test D: provider failure leaves status and evidence unchanged and surfaces the retryable upstream error", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    const before = await reconcile("req_ok");
    expect(before.intent.status).toBe("paid");

    const upstream = new AppError("UPSTREAM_UNAVAILABLE", "Blockchain provider is temporarily unavailable");
    chainProvider.state.failTransfers = upstream;
    chainProvider.state.latestBlock = 1_200n;
    const error = await captureAppError(reconcile("req_fail"));
    expect(error).toBe(upstream);
    expect(error.retryable).toBe(true);

    const after = await paymentRepository.getPaymentIntentById(intent.id);
    expect(after).toEqual(before.intent);
    expect(paymentRepository.evidenceRows(intent.id)).toHaveLength(1);
    expect(paymentRepository.attempts.at(-1)).toMatchObject({
      requestId: "req_fail",
      errorCode: "UPSTREAM_UNAVAILABLE",
      resultStatus: null,
      latestBlock: 1_200n,
      candidateCount: 0,
    });
  });

  it("Test D (latest block failure): nothing is queried or written except a failed attempt", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 0n, transfers: [] });
    chainProvider.state.failLatestBlock = new AppError("UPSTREAM_UNAVAILABLE", "down");
    await captureAppError(reconcile());
    expect(chainProvider.transferQueries).toEqual([]);
    expect((await paymentRepository.getPaymentIntentById(intent.id))?.lastReconciledBlock).toBeNull();
    expect(paymentRepository.attempts).toEqual([expect.objectContaining({ errorCode: "UPSTREAM_UNAVAILABLE", latestBlock: null })]);
  });

  it("Test D (timestamp failure): evidence is not written when block timestamps cannot be fetched", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    chainProvider.state.failTimestamps = new AppError("UPSTREAM_UNAVAILABLE", "down");
    await captureAppError(reconcile());
    expect(paymentRepository.evidenceRows(intent.id)).toHaveLength(0);
    expect((await paymentRepository.getPaymentIntentById(intent.id))?.status).toBe("pending");
  });

  it("Test E: an older latest-block observation arriving after a newer one does not overwrite intent state", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    const newer = await reconcile("req_newer");
    expect(newer.intent.status).toBe("paid");

    // A lagging node answers with an older head and, consequently, no transfers.
    chainProvider.state.latestBlock = 1_040n;
    chainProvider.state.transfers = [];
    const stale = await reconcile("req_stale");
    expect(stale.applied).toBe(false);
    expect(stale.intent).toEqual(newer.intent);
    expect((await paymentRepository.getPaymentIntentById(intent.id))?.lastReconciledBlock).toBe(1_100n);
    expect(paymentRepository.attempts.at(-1)).toMatchObject({ requestId: "req_stale", errorCode: "STALE_OBSERVATION", resultStatus: null });
  });

  it("the provider's unexpected non-upstream error propagates without recording a misleading attempt", async () => {
    const { chainProvider, reconcile, paymentRepository } = await setup({ latestBlock: 1_100n, transfers: [] });
    chainProvider.state.failTransfers = new Error("bug in adapter");
    await expect(reconcile()).rejects.toThrow("bug in adapter");
    expect(paymentRepository.attempts).toEqual([]);
  });
});

describe("reconcilePaymentIntent — guards", () => {
  it("throws INTENT_NOT_FOUND for an unknown ID", async () => {
    const { chainProvider, paymentRepository } = await setup({ latestBlock: 1n, transfers: [] });
    const error = await captureAppError(
      reconcilePaymentIntent(newPaymentIntentId(), { chainProvider, paymentRepository, requestId: "req_x" }),
    );
    expect(error.code).toBe("INTENT_NOT_FOUND");
    expect(chainProvider.calls).toBe(0);
  });

  it("rejects a transfer the provider returns outside the payer/recipient filter", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 1_100n, transfers: [] });
    chainProvider.getUsdcTransfers = async () => [chainTransfer({ blockNumber: 1_050n, amountUnits: 1n, from: OTHER })];
    const paymentRepository = new InMemoryPaymentRepository();
    const intent = await paymentRepository.createPaymentIntent({
      id: newPaymentIntentId(),
      externalReference: null,
      expectedAmountUnits: 1n,
      recipientAddress: RECIPIENT,
      payerAddress: PAYER,
      expiresAt: new Date(Date.now() + 60_000),
      requiredConfirmations: 1,
      startBlock: START_BLOCK,
    });
    const error = await captureAppError(reconcilePaymentIntent(intent.id, { chainProvider, paymentRepository, requestId: "r" }));
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
    expect(paymentRepository.evidenceRows(intent.id)).toHaveLength(0);
  });

});

describe("reconcilePaymentIntent — window defence (§18)", () => {
  it("rejects evidence before startBlock or after the window end from a faulty provider, without touching state", async () => {
    for (const blockNumber of [START_BLOCK - 1n, 1_101n]) {
      const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 1_100n, transfers: [] });
      chainProvider.getUsdcTransfers = async () => [chainTransfer({ blockNumber, amountUnits: 25_000_000n })];
      const error = await captureAppError(reconcile());
      expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
      expect(error.context).toMatchObject({ outsideWindow: true });
      const after = await paymentRepository.getPaymentIntentById(intent.id);
      expect(after?.status).toBe("pending");
      expect(after?.lastReconciledBlock).toBeNull();
      expect(paymentRepository.evidenceRows(intent.id)).toHaveLength(0);
    }
  });

  it("an API-shaped intent (startBlock = latest + 1) is never satisfied by a transfer mined before it", async () => {
    // The transfer exists on the fake chain one block before the intent's window opens.
    const { reconcile, paymentRepository, intent, chainProvider } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: START_BLOCK - 1n, amountUnits: 25_000_000n })],
    });
    const outcome = await reconcile();
    expect(chainProvider.transferQueries[0]?.fromBlock).toBe(START_BLOCK);
    expect(outcome.intent.status).toBe("pending");
    expect(outcome.intent.paidAt).toBeNull();
    expect(paymentRepository.evidenceRows(intent.id)).toHaveLength(0);
  });
});

describe("reconcilePaymentIntent — final statuses", () => {
  it("confirmed below expected → partial with remaining amount", async () => {
    const { reconcile } = await setup({ latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 15_000_000n })] });
    const outcome = await reconcile();
    expect(outcome.intent).toMatchObject({ status: "partial", receivedAmountUnits: 15_000_000n, detectedAmountUnits: 15_000_000n, paidAt: null });
  });

  it("confirmed above expected → overpaid, paidAt from the crossing transfer", async () => {
    const { reconcile } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_010n, amountUnits: 25_000_000n }), chainTransfer({ blockNumber: 1_020n, amountUnits: 5_000_000n })],
    });
    const outcome = await reconcile();
    expect(outcome.intent).toMatchObject({ status: "overpaid", receivedAmountUnits: 30_000_000n, paidAt: blockTime(1_010n) });
  });
});

describe("reconcilePaymentIntent — expiry boundary", () => {
  // Chain time: block n at n*2s. Intent window starts at block 1000 (t=2000s).
  const expiresAt = blockTime(1_050n); // exactly block 1050's timestamp
  const afterExpiry = () => new Date(expiresAt.getTime() + 60_000);

  it("before expiresAt the window runs to the latest block and no search happens", async () => {
    const { chainProvider, reconcile } = await setup({ latestBlock: 1_100n, transfers: [] }, { expiresAt, now: () => new Date(expiresAt.getTime() - 1) });
    await reconcile();
    expect(chainProvider.searchRequests).toEqual([]);
    expect(chainProvider.transferQueries[0]).toMatchObject({ fromBlock: START_BLOCK, toBlock: 1_100n });
  });

  it("after expiresAt resolves and persists the expiry block (timestamp == expiresAt → that block is included)", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 1_100n, transfers: [] }, { expiresAt, now: afterExpiry });
    const outcome = await reconcile();
    expect(chainProvider.searchRequests).toEqual([{ at: expiresAt, range: { fromBlock: START_BLOCK, toBlock: 1_100n } }]);
    expect(chainProvider.transferQueries[0]).toMatchObject({ fromBlock: START_BLOCK, toBlock: 1_050n });
    expect(outcome.intent.expiryBlock).toBe(1_050n);
    expect(outcome.intent.status).toBe("expired");
    expect((await paymentRepository.getPaymentIntentById(intent.id))?.expiryBlock).toBe(1_050n);
    expect(paymentRepository.attempts[0]).toMatchObject({ fromBlock: START_BLOCK, toBlock: 1_050n, latestBlock: 1_100n, resultStatus: "expired" });
  });

  it("expiry between two block timestamps → the earlier block is the boundary", async () => {
    const between = new Date(blockTime(1_050n).getTime() + 1_000);
    const { reconcile } = await setup({ latestBlock: 1_100n, transfers: [] }, { expiresAt: between, now: () => new Date(between.getTime() + 60_000) });
    expect((await reconcile()).intent.expiryBlock).toBe(1_050n);
  });

  it("a persisted expiryBlock is reused without repeating the search", async () => {
    const { chainProvider, reconcile } = await setup({ latestBlock: 1_100n, transfers: [] }, { expiresAt, now: afterExpiry });
    await reconcile("req_1");
    chainProvider.state.latestBlock = 1_200n;
    await reconcile("req_2");
    expect(chainProvider.searchRequests).toHaveLength(1);
    expect(chainProvider.transferQueries[1]).toMatchObject({ fromBlock: START_BLOCK, toBlock: 1_050n });
  });

  it("a transfer one block after the expiry block is excluded; one at the expiry block is eligible", async () => {
    const excluded = await setup({ latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_051n, amountUnits: 25_000_000n })] }, { expiresAt, now: afterExpiry });
    const first = await excluded.reconcile();
    expect(first.intent.status).toBe("expired");
    expect(first.candidateCount).toBe(0);

    const eligible = await setup({ latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })] }, { expiresAt, now: afterExpiry });
    const second = await eligible.reconcile();
    expect(second.intent.status).toBe("paid");
    expect(second.intent.paidAt).toEqual(blockTime(1_050n));
  });

  it("expiry before the start block's timestamp → empty window, expired, persisted as startBlock - 1", async () => {
    const early = blockTime(START_BLOCK - 5n);
    const { chainProvider, reconcile, paymentRepository, intent } = await setup(
      { latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_001n, amountUnits: 25_000_000n })] },
      { expiresAt: early, now: () => new Date(early.getTime() + 60_000) },
    );
    const outcome = await reconcile();
    expect(chainProvider.transferQueries).toEqual([]); // no invalid log range is ever requested
    expect(outcome.intent.status).toBe("expired");
    expect(outcome.intent.expiryBlock).toBe(START_BLOCK - 1n);
    expect((await paymentRepository.getPaymentIntentById(intent.id))?.expiryBlock).toBe(START_BLOCK - 1n);
  });

  it("wall clock past expiry but the latest block not yet past it → window to latest, nothing persisted, not expired", async () => {
    // latest block 1040 is mined at t=2080s, before expiresAt (t=2100s); the boundary is not on chain yet.
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 1_040n, transfers: [] }, { expiresAt, now: afterExpiry });
    const outcome = await reconcile();
    expect(chainProvider.searchRequests).toHaveLength(1);
    expect(chainProvider.transferQueries[0]).toMatchObject({ toBlock: 1_040n });
    expect(outcome.intent.status).toBe("pending");
    expect((await paymentRepository.getPaymentIntentById(intent.id))?.expiryBlock).toBeNull();
  });

  it("payment mined before expiry but confirmed after expiry → paid", async () => {
    // Mined in block 1050 (the boundary). At block 1051 it has 2 confirmations → detected; at 1053 → paid.
    const { chainProvider, reconcile } = await setup(
      { latestBlock: 1_051n, transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })] },
      { expiresAt, now: afterExpiry },
    );
    const detected = await reconcile("req_1");
    expect(detected.intent.status).toBe("detected");
    expect(detected.intent.expiryBlock).toBe(1_050n);

    chainProvider.state.latestBlock = 1_053n;
    const paid = await reconcile("req_2");
    expect(paid.intent.status).toBe("paid");
    expect(paid.intent.paidAt).toEqual(blockTime(1_050n));
  });

  it("partial at expiry with an under-confirmed pre-expiry transfer that can satisfy the balance stays partial, then pays", async () => {
    const { chainProvider, reconcile } = await setup(
      {
        latestBlock: 1_051n,
        transfers: [chainTransfer({ blockNumber: 1_010n, amountUnits: 15_000_000n }), chainTransfer({ blockNumber: 1_050n, amountUnits: 10_000_000n })],
      },
      { expiresAt, now: afterExpiry },
    );
    expect((await reconcile("req_1")).intent.status).toBe("partial");
    chainProvider.state.latestBlock = 1_060n;
    const paid = await reconcile("req_2");
    expect(paid.intent.status).toBe("paid");
    expect(paid.intent.paidAt).toEqual(blockTime(1_050n));
  });

  it("partial at expiry with nothing pending → expired, amounts retained", async () => {
    const { reconcile } = await setup(
      { latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_010n, amountUnits: 15_000_000n })] },
      { expiresAt, now: afterExpiry },
    );
    const outcome = await reconcile();
    expect(outcome.intent).toMatchObject({ status: "expired", receivedAmountUnits: 15_000_000n, paidAt: null });
  });
});

describe("reconcilePaymentIntent — payer-less intents", () => {
  const noPayer = { payerAddress: null } as const;

  it("queries the recipient without a sender filter", async () => {
    const { chainProvider, reconcile } = await setup({ latestBlock: 1_100n, transfers: [] }, noPayer);
    await reconcile();
    expect(chainProvider.transferQueries).toEqual([{ fromBlock: START_BLOCK, toBlock: 1_100n, recipient: RECIPIENT, payer: null }]);
  });

  it("no sender → pending", async () => {
    const { reconcile } = await setup({ latestBlock: 1_100n, transfers: [] }, noPayer);
    expect((await reconcile()).intent).toMatchObject({ status: "pending", matchConfidence: "none" });
  });

  it("one sender → single_sender and normal aggregation", async () => {
    const { reconcile, paymentRepository, intent } = await setup(
      { latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_010n, amountUnits: 10_000_000n, from: OTHER }), chainTransfer({ blockNumber: 1_020n, amountUnits: 15_000_000n, from: OTHER })] },
      noPayer,
    );
    const outcome = await reconcile();
    expect(outcome.intent).toMatchObject({ status: "paid", matchConfidence: "single_sender", receivedAmountUnits: 25_000_000n, paidAt: blockTime(1_020n) });
    expect(paymentRepository.evidenceRows(intent.id).every((row) => row.association === "matched")).toBe(true);
  });

  it("two senders → ambiguous; evidence stored as candidates; totals untouched", async () => {
    const { reconcile, paymentRepository, intent } = await setup(
      { latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_010n, amountUnits: 25_000_000n, from: OTHER }), chainTransfer({ blockNumber: 1_020n, amountUnits: 1n, from: PAYER })] },
      noPayer,
    );
    const outcome = await reconcile();
    expect(outcome.intent).toMatchObject({ status: "ambiguous", matchConfidence: "ambiguous", receivedAmountUnits: 0n, detectedAmountUnits: 0n, paidAt: null });
    const rows = paymentRepository.evidenceRows(intent.id);
    expect(rows).toHaveLength(2);
    expect(rows.every((row) => row.association === "candidate")).toBe(true);
  });
});

describe("reconcilePaymentIntent — canonical evidence and reorgs", () => {
  it("A: a transfer that disappears from a later complete scan is orphaned and the state regresses", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    expect((await reconcile("req_1")).intent.status).toBe("paid");

    chainProvider.state.transfers = [];
    chainProvider.state.latestBlock = 1_101n;
    const outcome = await reconcile("req_2");
    expect(outcome.intent).toMatchObject({ status: "pending", receivedAmountUnits: 0n, detectedAmountUnits: 0n, matchConfidence: "none", paidAt: null });
    const rows = paymentRepository.evidenceRows(intent.id);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.association).toBe("orphaned");
  });

  it("A′: an orphaned identity seen canonically again returns to matched and counts again", async () => {
    const transfer = chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n });
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 1_100n, transfers: [transfer] });
    await reconcile("req_1");
    chainProvider.state.transfers = [];
    chainProvider.state.latestBlock = 1_101n;
    expect((await reconcile("req_2")).intent.status).toBe("pending");
    chainProvider.state.transfers = [transfer];
    chainProvider.state.latestBlock = 1_102n;
    const outcome = await reconcile("req_3");
    expect(outcome.intent.status).toBe("paid");
    expect(paymentRepository.evidenceRows(intent.id)).toEqual([expect.objectContaining({ association: "matched", confirmations: 53 })]);
  });

  it("B: the same identity re-observed in a different canonical block updates the stored block details", async () => {
    const transfer = chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n, blockHash: `0x${"1".repeat(64)}` });
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 1_100n, transfers: [transfer] });
    await reconcile("req_1");
    chainProvider.state.transfers = [{ ...transfer, blockNumber: 1_052n, blockHash: `0x${"2".repeat(64)}` }];
    chainProvider.state.latestBlock = 1_101n;
    await reconcile("req_2");
    const rows = paymentRepository.evidenceRows(intent.id);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ blockNumber: 1_052n, blockHash: `0x${"2".repeat(64)}`, association: "matched", confirmations: 50 });
    expect(rows[0]?.blockTimestamp).toEqual(blockTime(1_052n));
  });

  it("C: ambiguous scan, then one sender disappears → candidate orphaned, remaining sender becomes single_sender", async () => {
    const a = chainTransfer({ blockNumber: 1_010n, amountUnits: 25_000_000n, from: OTHER });
    const b = chainTransfer({ blockNumber: 1_020n, amountUnits: 1n, from: PAYER });
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({ latestBlock: 1_100n, transfers: [a, b] }, { payerAddress: null });
    expect((await reconcile("req_1")).intent.status).toBe("ambiguous");

    chainProvider.state.transfers = [a];
    chainProvider.state.latestBlock = 1_101n;
    const outcome = await reconcile("req_2");
    expect(outcome.intent).toMatchObject({ status: "paid", matchConfidence: "single_sender", receivedAmountUnits: 25_000_000n });
    const rows = paymentRepository.evidenceRows(intent.id);
    expect(rows.map((row) => [row.txHash, row.association])).toEqual([
      [a.txHash, "matched"],
      [b.txHash, "orphaned"],
    ]);
  });

  it("D: a failed scan orphans nothing and leaves state unchanged", async () => {
    const { chainProvider, reconcile, paymentRepository, intent } = await setup({
      latestBlock: 1_100n,
      transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 25_000_000n })],
    });
    const before = await reconcile("req_1");
    expect(before.intent.status).toBe("paid");

    chainProvider.state.failTransfers = new AppError("UPSTREAM_UNAVAILABLE", "down");
    chainProvider.state.transfers = [];
    chainProvider.state.latestBlock = 1_200n;
    await captureAppError(reconcile("req_2"));
    expect(await paymentRepository.getPaymentIntentById(intent.id)).toEqual(before.intent);
    expect(paymentRepository.evidenceRows(intent.id)).toEqual([expect.objectContaining({ association: "matched" })]);
  });

  it("does not orphan evidence outside the scanned window (expiry narrows the window)", async () => {
    // Milestone-2-style row beyond the expiry boundary must stay untouched by a narrower scan.
    const expiresAt = blockTime(1_050n);
    const late = chainTransfer({ blockNumber: 1_060n, amountUnits: 25_000_000n });
    const { chainProvider, reconcile, paymentRepository, intent } = await setup(
      { latestBlock: 1_100n, transfers: [late] },
      { expiresAt, now: () => new Date(expiresAt.getTime() - 1) },
    );
    // Simulate a pre-expiry full scan that legitimately included block 1060: the wall clock was before expiresAt.
    // (On the fake chain block 1060 is after expiresAt, so this mirrors a lagging clock; the row exists either way.)
    await reconcile("req_1");
    expect(paymentRepository.evidenceRows(intent.id)[0]?.association).toBe("matched");

    // Now the clock passes expiry: window becomes [1000, 1050]; the row at 1060 is outside it.
    const repo2 = paymentRepository;
    const later = reconcilePaymentIntent(intent.id, {
      chainProvider,
      paymentRepository: repo2,
      requestId: "req_2",
      now: () => new Date(expiresAt.getTime() + 60_000),
    });
    const outcome = await later;
    expect(outcome.intent.status).toBe("expired");
    expect(outcome.intent.receivedAmountUnits).toBe(0n);
    expect(paymentRepository.evidenceRows(intent.id)[0]?.association).toBe("matched"); // outside window: untouched, uncounted
  });
});

describe("reconcilePaymentIntent — failure invariants (Milestone 5)", () => {
  /** A partial intent with one persisted matched transfer, reconciled once successfully. */
  async function partialIntent() {
    const fixture = await setup({ latestBlock: 1_100n, transfers: [chainTransfer({ blockNumber: 1_050n, amountUnits: 15_000_000n })] });
    const before = await fixture.reconcile("req_ok");
    expect(before.intent.status).toBe("partial");
    expect(fixture.paymentRepository.evidenceRows(fixture.intent.id)).toHaveLength(1);
    return { ...fixture, before };
  }

  async function expectUnchanged(fixture: Awaited<ReturnType<typeof partialIntent>>) {
    const after = await fixture.paymentRepository.getPaymentIntentById(fixture.intent.id);
    expect(after).toEqual(fixture.before.intent);
    const rows = fixture.paymentRepository.evidenceRows(fixture.intent.id);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.association).toBe("matched");
  }

  it("provider unavailable: upstream error, status stays partial, evidence untouched, nothing orphaned", async () => {
    const fixture = await partialIntent();
    fixture.chainProvider.state.failTransfers = new AppError("UPSTREAM_UNAVAILABLE", "Blockchain provider is temporarily unavailable");
    fixture.chainProvider.state.transfers = []; // a failed scan must never read as "the transfer is gone"
    fixture.chainProvider.state.latestBlock = 1_200n;
    const error = await captureAppError(fixture.reconcile("req_fail"));
    expect(error.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(error.retryable).toBe(true);
    await expectUnchanged(fixture);
    expect(fixture.paymentRepository.attempts.at(-1)).toMatchObject({ requestId: "req_fail", errorCode: "UPSTREAM_UNAVAILABLE", resultStatus: null });
  });

  it("provider timeout: same guarantees", async () => {
    const fixture = await partialIntent();
    fixture.chainProvider.state.failLatestBlock = new AppError("UPSTREAM_UNAVAILABLE", "timeout");
    await captureAppError(fixture.reconcile("req_timeout"));
    await expectUnchanged(fixture);
  });

  it("provider malformed response: UPSTREAM_INVALID_RESPONSE and no payment-state mutation", async () => {
    const fixture = await partialIntent();
    fixture.chainProvider.state.failTransfers = new AppError("UPSTREAM_INVALID_RESPONSE", "bad data");
    const error = await captureAppError(fixture.reconcile("req_malformed"));
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
    await expectUnchanged(fixture);
  });

  it("out-of-filter evidence from a faulty provider: rejected before any state or evidence changes", async () => {
    const fixture = await partialIntent();
    fixture.chainProvider.getUsdcTransfers = async () => [chainTransfer({ blockNumber: 1_060n, amountUnits: 10_000_000n, from: OTHER })];
    const error = await captureAppError(fixture.reconcile("req_bad_filter"));
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
    await expectUnchanged(fixture);
  });

  it("block timestamp lookup failure after logs were fetched: no evidence applied, no status mutation", async () => {
    const fixture = await partialIntent();
    fixture.chainProvider.state.transfers.push(chainTransfer({ blockNumber: 1_060n, amountUnits: 10_000_000n }));
    fixture.chainProvider.state.failTimestamps = new AppError("UPSTREAM_UNAVAILABLE", "block lookup failed");
    await captureAppError(fixture.reconcile("req_ts"));
    await expectUnchanged(fixture); // the second transfer was never persisted
  });

  it("database failure while applying: error propagates, no attempt is fabricated, state unchanged", async () => {
    const fixture = await partialIntent();
    fixture.chainProvider.state.transfers.push(chainTransfer({ blockNumber: 1_060n, amountUnits: 10_000_000n }));
    const attemptsBefore = fixture.paymentRepository.attempts.length;
    fixture.paymentRepository.applyReconciliation = async () => {
      throw new Error("connection terminated unexpectedly");
    };
    await expect(fixture.reconcile("req_db")).rejects.toThrow("connection terminated unexpectedly");
    await expectUnchanged(fixture);
    expect(fixture.paymentRepository.attempts).toHaveLength(attemptsBefore);
  });

  it("a failed scan is never interpreted as canonical absence: the transfer stays matched and counted", async () => {
    const fixture = await partialIntent();
    fixture.chainProvider.state.transfers = [];
    fixture.chainProvider.state.failTransfers = new AppError("UPSTREAM_UNAVAILABLE", "down");
    await captureAppError(fixture.reconcile("req_scan_fail"));
    await expectUnchanged(fixture);
    // Once the provider is healthy again and still returns the transfer, nothing has been lost.
    fixture.chainProvider.state.failTransfers = undefined as unknown as Error;
    delete fixture.chainProvider.state.failTransfers;
    fixture.chainProvider.state.transfers = [chainTransfer({ blockNumber: 1_050n, amountUnits: 15_000_000n })];
    const recovered = await fixture.reconcile("req_recovered");
    expect(recovered.intent.status).toBe("partial");
    expect(fixture.paymentRepository.evidenceRows(fixture.intent.id)).toHaveLength(1);
  });
});
