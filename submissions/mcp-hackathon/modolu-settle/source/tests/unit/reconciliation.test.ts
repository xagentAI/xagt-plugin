import { describe, expect, it } from "vitest";

import type { PaymentStatus } from "@/domain/payment-intent";
import {
  STATUS_PRECEDENCE,
  compareTransfers,
  confirmationDepth,
  isInWindow,
  reconcile,
  resolveStatus,
  type ObservedTransfer,
  type ReconciliationInput,
  type StatusFacts,
} from "@/domain/reconciliation";

const PAYER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045";
const SENDER_B = "0x1111111111111111111111111111111111111111";
const SENDER_C = "0x2222222222222222222222222222222222222222";
const RECIPIENT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";

let txCounter = 0;
function transfer(overrides: Partial<ObservedTransfer> & { blockNumber: bigint; amountUnits: bigint }): ObservedTransfer {
  txCounter += 1;
  return {
    txHash: `0x${txCounter.toString(16).padStart(64, "0")}`,
    logIndex: 0,
    blockHash: `0x${"b".repeat(64)}`,
    from: PAYER,
    to: RECIPIENT,
    blockTimestamp: new Date(Number(overrides.blockNumber) * 2_000),
    ...overrides,
  };
}

/** Latest block 1000; required confirmations 3 → blocks <= 998 are confirmed. */
function input(overrides: Partial<ReconciliationInput> = {}): ReconciliationInput {
  return {
    expectedAmountUnits: 100_000_000n,
    requiredConfirmations: 3,
    latestBlock: 1_000n,
    payer: PAYER,
    window: { fromBlock: 1n, toBlock: 1_000n },
    expiryPassed: false,
    transfers: [],
    ...overrides,
  };
}

const CONFIRMED_BLOCK = 500n;
const UNCONFIRMED_BLOCK = 1_000n; // exactly 1 confirmation

describe("confirmationDepth", () => {
  it("is latest - block + 1, exactly, as bigint", () => {
    expect(confirmationDepth(1_000n, 1_000n)).toBe(1n);
    expect(confirmationDepth(998n, 1_000n)).toBe(3n);
    expect(confirmationDepth(0n, 51_446_899n)).toBe(51_446_900n);
    expect(typeof confirmationDepth(1n, 2n)).toBe("bigint");
  });

  it("gives a block above the latest zero confirmations", () => {
    expect(confirmationDepth(1_001n, 1_000n)).toBe(0n);
  });
});

describe("compareTransfers", () => {
  it("orders by blockNumber, then logIndex, then txHash", () => {
    const rows = [
      { blockNumber: 10n, logIndex: 5, txHash: "0xbb" },
      { blockNumber: 9n, logIndex: 9, txHash: "0xzz" },
      { blockNumber: 10n, logIndex: 2, txHash: "0xcc" },
      { blockNumber: 10n, logIndex: 2, txHash: "0xaa" },
    ];
    expect([...rows].sort(compareTransfers)).toEqual([
      { blockNumber: 9n, logIndex: 9, txHash: "0xzz" },
      { blockNumber: 10n, logIndex: 2, txHash: "0xaa" },
      { blockNumber: 10n, logIndex: 2, txHash: "0xcc" },
      { blockNumber: 10n, logIndex: 5, txHash: "0xbb" },
    ]);
  });
});

describe("status precedence", () => {
  it("is exactly the ARCHITECTURE.md §7.4 order", () => {
    expect(STATUS_PRECEDENCE).toEqual(["ambiguous", "overpaid", "paid", "partial", "detected", "expired", "pending"]);
  });

  const base: StatusFacts = {
    expectedAmountUnits: 100n,
    detectedAmountUnits: 0n,
    receivedAmountUnits: 0n,
    ambiguous: false,
    expiryPassed: false,
  };

  it.each<[string, Partial<StatusFacts>, PaymentStatus]>([
    ["nothing observed", {}, "pending"],
    ["under-confirmed evidence only", { detectedAmountUnits: 40n }, "detected"],
    ["confirmed below expected", { detectedAmountUnits: 60n, receivedAmountUnits: 60n }, "partial"],
    ["confirmed 60 + under-confirmed 40", { detectedAmountUnits: 100n, receivedAmountUnits: 60n }, "partial"],
    ["confirmed equals expected", { detectedAmountUnits: 100n, receivedAmountUnits: 100n }, "paid"],
    ["confirmed above expected", { detectedAmountUnits: 130n, receivedAmountUnits: 130n }, "overpaid"],
    ["expired, no evidence", { expiryPassed: true }, "expired"],
    ["expired, confirmed 60 and nothing pending", { expiryPassed: true, detectedAmountUnits: 60n, receivedAmountUnits: 60n }, "expired"],
    ["expired, confirmed 60 + under-confirmed 10 (cannot satisfy)", { expiryPassed: true, detectedAmountUnits: 70n, receivedAmountUnits: 60n }, "expired"],
    ["expired, confirmed 60 + under-confirmed 40 (can satisfy)", { expiryPassed: true, detectedAmountUnits: 100n, receivedAmountUnits: 60n }, "partial"],
    ["expired, only under-confirmed 100 (can satisfy)", { expiryPassed: true, detectedAmountUnits: 100n }, "detected"],
    ["expired, only under-confirmed 10 (cannot satisfy)", { expiryPassed: true, detectedAmountUnits: 10n }, "expired"],
    ["expired but confirmed equals expected", { expiryPassed: true, detectedAmountUnits: 100n, receivedAmountUnits: 100n }, "paid"],
    ["expired but confirmed above expected", { expiryPassed: true, detectedAmountUnits: 150n, receivedAmountUnits: 150n }, "overpaid"],
    ["ambiguous with no totals", { ambiguous: true }, "ambiguous"],
    ["ambiguous outranks expired", { ambiguous: true, expiryPassed: true }, "ambiguous"],
    ["ambiguous outranks paid-looking totals", { ambiguous: true, detectedAmountUnits: 100n, receivedAmountUnits: 100n }, "ambiguous"],
  ])("%s → %s", (_label, facts, expected) => {
    expect(resolveStatus({ ...base, ...facts })).toBe(expected);
  });
});

describe("reconcile — exact payer", () => {
  it("zero transfers → pending, confidence none, no evidence", () => {
    expect(reconcile(input())).toEqual({
      status: "pending",
      detectedAmountUnits: 0n,
      receivedAmountUnits: 0n,
      matchConfidence: "none",
      paidAt: null,
      transfers: [],
    });
  });

  it("an unconfirmed exact transfer → detected with 1 confirmation", () => {
    const result = reconcile(input({ transfers: [transfer({ blockNumber: UNCONFIRMED_BLOCK, amountUnits: 100_000_000n })] }));
    expect(result).toMatchObject({ status: "detected", detectedAmountUnits: 100_000_000n, receivedAmountUnits: 0n, matchConfidence: "exact_payer", paidAt: null });
    expect(result.transfers[0]).toMatchObject({ confirmations: 1n, confirmed: false, association: "matched" });
  });

  it("confirmations one below the threshold → detected; exactly at threshold → paid", () => {
    const below = reconcile(input({ transfers: [transfer({ blockNumber: 999n, amountUnits: 100_000_000n })] }));
    expect(below.transfers[0]?.confirmations).toBe(2n);
    expect(below.status).toBe("detected");

    const at = reconcile(input({ transfers: [transfer({ blockNumber: 998n, amountUnits: 100_000_000n })] }));
    expect(at.transfers[0]?.confirmations).toBe(3n);
    expect(at.status).toBe("paid");
    expect(at.paidAt).toEqual(new Date(998 * 2_000));
  });

  it("confirmed amount below expected → partial with remaining computable", () => {
    const result = reconcile(input({ transfers: [transfer({ blockNumber: CONFIRMED_BLOCK, amountUnits: 60_000_000n })] }));
    expect(result).toMatchObject({ status: "partial", receivedAmountUnits: 60_000_000n, detectedAmountUnits: 60_000_000n, paidAt: null });
  });

  it("confirmed 60 + under-confirmed 40 → partial; detected exceeds received", () => {
    const result = reconcile(
      input({
        transfers: [
          transfer({ blockNumber: CONFIRMED_BLOCK, amountUnits: 60_000_000n }),
          transfer({ blockNumber: UNCONFIRMED_BLOCK, amountUnits: 40_000_000n }),
        ],
      }),
    );
    expect(result).toMatchObject({ status: "partial", receivedAmountUnits: 60_000_000n, detectedAmountUnits: 100_000_000n, paidAt: null });
  });

  it("confirmed amount equal to expected → paid", () => {
    const result = reconcile(input({ transfers: [transfer({ blockNumber: CONFIRMED_BLOCK, amountUnits: 100_000_000n })] }));
    expect(result).toMatchObject({ status: "paid", receivedAmountUnits: 100_000_000n, paidAt: new Date(500 * 2_000) });
  });

  it("confirmed amount above expected → overpaid, paidAt from the threshold-crossing transfer, not the excess", () => {
    const result = reconcile(
      input({
        expectedAmountUnits: 25_000_000n,
        transfers: [
          transfer({ blockNumber: 300n, amountUnits: 10_000_000n }),
          transfer({ blockNumber: 400n, amountUnits: 15_000_000n }), // crosses 25 here
          transfer({ blockNumber: 500n, amountUnits: 5_000_000n }), // excess
        ],
      }),
    );
    expect(result).toMatchObject({ status: "overpaid", receivedAmountUnits: 30_000_000n, paidAt: new Date(400 * 2_000) });
  });

  it("overpaid with partial intermediate transfers → overpaid", () => {
    const result = reconcile(
      input({
        transfers: [
          transfer({ blockNumber: 100n, amountUnits: 30_000_000n }),
          transfer({ blockNumber: 200n, amountUnits: 30_000_000n }),
          transfer({ blockNumber: 300n, amountUnits: 30_000_000n }),
          transfer({ blockNumber: 400n, amountUnits: 30_000_000n }),
        ],
      }),
    );
    expect(result.status).toBe("overpaid");
    expect(result.receivedAmountUnits).toBe(120_000_000n);
    expect(result.paidAt).toEqual(new Date(400 * 2_000));
  });

  it("multiple transfers aggregate, and paidAt is the threshold-crossing transfer in canonical order", () => {
    const result = reconcile(
      input({
        transfers: [
          transfer({ blockNumber: 300n, amountUnits: 40_000_000n }),
          transfer({ blockNumber: 100n, amountUnits: 60_000_000n }),
          transfer({ blockNumber: 400n, amountUnits: 5_000_000n }),
        ],
      }),
    );
    expect(result.status).toBe("overpaid");
    expect(result.transfers.map((t) => t.blockNumber)).toEqual([100n, 300n, 400n]);
    expect(result.paidAt).toEqual(new Date(300 * 2_000));
  });

  it("uses logIndex then txHash order within one block for paidAt", () => {
    const result = reconcile(
      input({
        expectedAmountUnits: 30_000_000n,
        transfers: [
          transfer({ blockNumber: 700n, logIndex: 9, amountUnits: 20_000_000n, blockTimestamp: new Date(9_000) }),
          transfer({ blockNumber: 700n, logIndex: 2, amountUnits: 20_000_000n, blockTimestamp: new Date(2_000) }),
        ],
      }),
    );
    expect(result.transfers.map((t) => t.logIndex)).toEqual([2, 9]);
    expect(result.paidAt).toEqual(new Date(9_000));
  });

  it("counts a duplicated (txHash, logIndex) identity exactly once", () => {
    const same = transfer({ blockNumber: CONFIRMED_BLOCK, amountUnits: 100_000_000n });
    const result = reconcile(input({ transfers: [same, { ...same }, { ...same }] }));
    expect(result.transfers).toHaveLength(1);
    expect(result.status).toBe("paid");
  });

  it("keeps money and depth as bigint without precision loss", () => {
    const huge = 123_456_789_012_345_678_901_234_567_890n;
    const result = reconcile(
      input({
        expectedAmountUnits: huge,
        latestBlock: 9_007_199_254_740_993n,
        window: { fromBlock: 1n, toBlock: 9_007_199_254_740_993n },
        transfers: [transfer({ blockNumber: 9_007_199_254_740_990n, amountUnits: huge })],
      }),
    );
    expect(typeof result.receivedAmountUnits).toBe("bigint");
    expect(result.receivedAmountUnits).toBe(huge);
    expect(result.transfers[0]?.confirmations).toBe(4n);
    expect(result.status).toBe("paid");
  });

  it("never introduces ambiguity for a declared payer, whatever the senders look like", () => {
    // The service guarantees `from === payer`; the engine must not re-group by sender.
    const result = reconcile(
      input({
        transfers: [
          transfer({ blockNumber: 100n, amountUnits: 50_000_000n, from: PAYER }),
          transfer({ blockNumber: 200n, amountUnits: 50_000_000n, from: PAYER.toUpperCase().replace("0X", "0x") }),
        ],
      }),
    );
    expect(result.matchConfidence).toBe("exact_payer");
    expect(result.status).toBe("paid");
  });
});

describe("reconcile — expiry", () => {
  it("expiry passed with nothing observed → expired", () => {
    expect(reconcile(input({ expiryPassed: true, window: { fromBlock: 1n, toBlock: 900n } }))).toMatchObject({ status: "expired", matchConfidence: "none" });
  });

  it("expiry passed with an incomplete confirmed payment → expired, amounts still exposed", () => {
    const result = reconcile(
      input({ expiryPassed: true, window: { fromBlock: 1n, toBlock: 900n }, transfers: [transfer({ blockNumber: 500n, amountUnits: 60_000_000n })] }),
    );
    expect(result).toMatchObject({ status: "expired", receivedAmountUnits: 60_000_000n, detectedAmountUnits: 60_000_000n, matchConfidence: "exact_payer", paidAt: null });
  });

  it("paid before expiry but confirmed after expiry → paid (confirmation time is not payment time)", () => {
    // Boundary at block 900; transfer mined in 900 (1 confirmation at expiry); now latest is 1000.
    const result = reconcile(
      input({ expiryPassed: true, window: { fromBlock: 1n, toBlock: 900n }, transfers: [transfer({ blockNumber: 900n, amountUnits: 100_000_000n })] }),
    );
    expect(result.transfers[0]?.confirmations).toBe(101n);
    expect(result.status).toBe("paid");
  });

  it("partial + expired with no pending eligible evidence → expired", () => {
    const result = reconcile(
      input({
        expiryPassed: true,
        window: { fromBlock: 1n, toBlock: 900n },
        transfers: [transfer({ blockNumber: 100n, amountUnits: 30_000_000n }), transfer({ blockNumber: 200n, amountUnits: 30_000_000n })],
      }),
    );
    expect(result.status).toBe("expired");
    expect(result.receivedAmountUnits).toBe(60_000_000n);
  });

  it("partial + pre-expiry under-confirmed transfer capable of satisfying the balance → partial, not expired", () => {
    // Latest is 901: the block-900 transfer has 2 confirmations, below the threshold of 3.
    const result = reconcile(
      input({
        latestBlock: 901n,
        expiryPassed: true,
        window: { fromBlock: 1n, toBlock: 900n },
        transfers: [transfer({ blockNumber: 100n, amountUnits: 60_000_000n }), transfer({ blockNumber: 900n, amountUnits: 40_000_000n })],
      }),
    );
    expect(result.transfers[1]?.confirmations).toBe(2n);
    expect(result).toMatchObject({ status: "partial", receivedAmountUnits: 60_000_000n, detectedAmountUnits: 100_000_000n });
  });

  it("only a pre-expiry under-confirmed transfer that can satisfy → detected, not expired", () => {
    const result = reconcile(
      input({ latestBlock: 901n, expiryPassed: true, window: { fromBlock: 1n, toBlock: 900n }, transfers: [transfer({ blockNumber: 900n, amountUnits: 100_000_000n })] }),
    );
    expect(result.status).toBe("detected");
  });

  it("a pre-expiry under-confirmed transfer that cannot satisfy the balance → expired immediately", () => {
    const result = reconcile(
      input({
        latestBlock: 901n,
        expiryPassed: true,
        window: { fromBlock: 1n, toBlock: 900n },
        transfers: [transfer({ blockNumber: 100n, amountUnits: 60_000_000n }), transfer({ blockNumber: 900n, amountUnits: 10_000_000n })],
      }),
    );
    expect(result.status).toBe("expired");
  });

  it("transfers after the expiry boundary are ignored even if the provider returned them", () => {
    const result = reconcile(
      input({ expiryPassed: true, window: { fromBlock: 1n, toBlock: 900n }, transfers: [transfer({ blockNumber: 901n, amountUnits: 100_000_000n })] }),
    );
    expect(result.status).toBe("expired");
    expect(result.transfers).toHaveLength(0);
  });

  it("a transfer at the expiry block is eligible", () => {
    const result = reconcile(
      input({ expiryPassed: true, window: { fromBlock: 1n, toBlock: 900n }, transfers: [transfer({ blockNumber: 900n, amountUnits: 100_000_000n })] }),
    );
    expect(result.status).toBe("paid");
  });
});

describe("reconcile — window defence", () => {
  it("ignores transfers before startBlock and after toBlock, whatever the provider returned", () => {
    const result = reconcile(
      input({
        window: { fromBlock: 500n, toBlock: 800n },
        transfers: [
          transfer({ blockNumber: 499n, amountUnits: 100_000_000n }), // pre-intent
          transfer({ blockNumber: 801n, amountUnits: 100_000_000n }), // beyond the scanned end
          transfer({ blockNumber: 500n, amountUnits: 1_000_000n }),
          transfer({ blockNumber: 800n, amountUnits: 1_000_000n }),
        ],
      }),
    );
    expect(result.transfers.map((t) => t.blockNumber)).toEqual([500n, 800n]);
    expect(result.detectedAmountUnits).toBe(2_000_000n);
    expect(result.status).toBe("partial");
  });

  it("an empty window yields no evidence", () => {
    expect(isInWindow(5n, { fromBlock: 6n, toBlock: 5n })).toBe(false);
    const result = reconcile(input({ window: { fromBlock: 6n, toBlock: 5n }, transfers: [transfer({ blockNumber: 5n, amountUnits: 1n })] }));
    expect(result.transfers).toHaveLength(0);
    expect(result.status).toBe("pending");
  });
});

describe("reconcile — payer-less association", () => {
  const noPayer = (overrides: Partial<ReconciliationInput> = {}) => input({ payer: null, ...overrides });

  it("no sender → pending, confidence none", () => {
    expect(reconcile(noPayer())).toMatchObject({ status: "pending", matchConfidence: "none" });
  });

  it("one sender, one transfer → matched, single_sender, aggregates like a declared payer", () => {
    const result = reconcile(noPayer({ transfers: [transfer({ blockNumber: CONFIRMED_BLOCK, amountUnits: 100_000_000n, from: SENDER_B })] }));
    expect(result).toMatchObject({ status: "paid", matchConfidence: "single_sender", receivedAmountUnits: 100_000_000n, paidAt: new Date(500 * 2_000) });
    expect(result.transfers[0]?.association).toBe("matched");
  });

  it("one sender, multiple transfers → aggregate to overpaid with the crossing paidAt", () => {
    const result = reconcile(
      noPayer({
        transfers: [
          transfer({ blockNumber: 100n, amountUnits: 60_000_000n, from: SENDER_B }),
          transfer({ blockNumber: 200n, amountUnits: 40_000_000n, from: SENDER_B }),
          transfer({ blockNumber: 300n, amountUnits: 1_000_000n, from: SENDER_B }),
        ],
      }),
    );
    expect(result).toMatchObject({ status: "overpaid", matchConfidence: "single_sender", receivedAmountUnits: 101_000_000n, paidAt: new Date(200 * 2_000) });
  });

  it("two senders → ambiguous; every transfer is a candidate and totals stay zero", () => {
    const result = reconcile(
      noPayer({
        transfers: [
          transfer({ blockNumber: 100n, amountUnits: 100_000_000n, from: SENDER_B }),
          transfer({ blockNumber: 200n, amountUnits: 5_000_000n, from: SENDER_C }),
        ],
      }),
    );
    expect(result).toMatchObject({ status: "ambiguous", matchConfidence: "ambiguous", detectedAmountUnits: 0n, receivedAmountUnits: 0n, paidAt: null });
    expect(result.transfers).toHaveLength(2);
    expect(result.transfers.every((t) => t.association === "candidate")).toBe(true);
    expect(result.transfers.map((t) => t.confirmations)).toEqual([901n, 801n]);
  });

  it("three senders → ambiguous", () => {
    const result = reconcile(
      noPayer({
        transfers: [
          transfer({ blockNumber: 100n, amountUnits: 1n, from: PAYER }),
          transfer({ blockNumber: 200n, amountUnits: 1n, from: SENDER_B }),
          transfer({ blockNumber: 300n, amountUnits: 1n, from: SENDER_C }),
        ],
      }),
    );
    expect(result.status).toBe("ambiguous");
    expect(result.transfers.filter((t) => t.association === "candidate")).toHaveLength(3);
  });

  it("different address casing normalizes to one sender group", () => {
    const result = reconcile(
      noPayer({
        transfers: [
          transfer({ blockNumber: 100n, amountUnits: 50_000_000n, from: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045" }),
          transfer({ blockNumber: 200n, amountUnits: 50_000_000n, from: "0xD8DA6BF26964AF9D7EED9E03E53415D37AA96045" }),
        ],
      }),
    );
    expect(result.matchConfidence).toBe("single_sender");
    expect(result.status).toBe("paid");
    expect(result.transfers.every((t) => t.from === PAYER)).toBe(true);
  });

  it("one sender exactly matches expected but another candidate exists → ambiguous, never paid", () => {
    const result = reconcile(
      noPayer({
        transfers: [
          transfer({ blockNumber: 100n, amountUnits: 100_000_000n, from: SENDER_B }),
          transfer({ blockNumber: 900n, amountUnits: 1n, from: SENDER_C }),
        ],
      }),
    );
    expect(result.status).toBe("ambiguous");
    expect(result.receivedAmountUnits).toBe(0n);
  });

  it("ambiguous outranks expiry", () => {
    const result = reconcile(
      noPayer({
        expiryPassed: true,
        window: { fromBlock: 1n, toBlock: 900n },
        transfers: [transfer({ blockNumber: 100n, amountUnits: 1n, from: SENDER_B }), transfer({ blockNumber: 200n, amountUnits: 1n, from: SENDER_C })],
      }),
    );
    expect(result.status).toBe("ambiguous");
  });

  it("single sender with only under-confirmed evidence → detected", () => {
    const result = reconcile(noPayer({ transfers: [transfer({ blockNumber: UNCONFIRMED_BLOCK, amountUnits: 100_000_000n, from: SENDER_B })] }));
    expect(result).toMatchObject({ status: "detected", matchConfidence: "single_sender" });
  });
});
