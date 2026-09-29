import { describe, expect, it } from "vitest";

import type { MatchedTransfer } from "@/domain/payment-intent";
import { AppError } from "@/lib/errors";
import {
  decodeEvidenceCursor,
  encodeEvidenceCursor,
  parseEvidenceQuery,
  toEvidenceItemResponse,
  toEvidenceResponse,
} from "@/validation/evidence";

const TX = `0x${"a".repeat(64)}`;

describe("evidence cursor", () => {
  it("round-trips an opaque, URL-safe cursor", () => {
    const cursor = { blockNumber: 51_450_000n, logIndex: 42, txHash: TX };
    const encoded = encodeEvidenceCursor(cursor);
    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeEvidenceCursor(encoded)).toEqual(cursor);
  });

  it("round-trips block numbers beyond Number.MAX_SAFE_INTEGER", () => {
    const cursor = { blockNumber: 9_007_199_254_740_993n, logIndex: 0, txHash: TX };
    expect(decodeEvidenceCursor(encodeEvidenceCursor(cursor)).blockNumber).toBe(9_007_199_254_740_993n);
  });

  it.each([
    "",
    "not-base64url!",
    Buffer.from("null").toString("base64url"),
    Buffer.from('["1",0]').toString("base64url"),
    Buffer.from('["1",-1,"' + TX + '"]').toString("base64url"),
    Buffer.from('["01",0,"' + TX + '"]').toString("base64url"),
    Buffer.from('["1",0,"0xshort"]').toString("base64url"),
    Buffer.from('["1","0","' + TX + '"]').toString("base64url"),
  ])("rejects malformed cursor %j with VALIDATION_ERROR", (value) => {
    try {
      decodeEvidenceCursor(value);
      expect.unreachable("expected rejection");
    } catch (error) {
      expect(error).toBeInstanceOf(AppError);
      expect((error as AppError).code).toBe("VALIDATION_ERROR");
    }
  });
});

describe("parseEvidenceQuery", () => {
  it("defaults to limit 50 and no cursor", () => {
    expect(parseEvidenceQuery(new URLSearchParams(""))).toEqual({ limit: 50, cursor: null });
    expect(parseEvidenceQuery(new URLSearchParams("limit=&cursor="))).toEqual({ limit: 50, cursor: null });
  });

  it("accepts limits 1..100 and a valid cursor", () => {
    const cursor = encodeEvidenceCursor({ blockNumber: 7n, logIndex: 1, txHash: TX });
    expect(parseEvidenceQuery(new URLSearchParams(`limit=100&cursor=${cursor}`))).toEqual({
      limit: 100,
      cursor: { blockNumber: 7n, logIndex: 1, txHash: TX },
    });
    expect(parseEvidenceQuery(new URLSearchParams("limit=1")).limit).toBe(1);
  });

  it.each(["0", "101", "-1", "1.5", "abc", "1e2", "9999"])("rejects limit=%s", (limit) => {
    expect(() => parseEvidenceQuery(new URLSearchParams(`limit=${limit}`))).toThrow(AppError);
  });

  it("ignores unknown query parameters", () => {
    expect(parseEvidenceQuery(new URLSearchParams("offset=10&page=2")).limit).toBe(50);
  });
});

describe("toEvidenceResponse", () => {
  const row: MatchedTransfer = {
    txHash: TX,
    logIndex: 42,
    blockNumber: 51_450_000n,
    blockHash: `0x${"b".repeat(64)}`,
    fromAddress: "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    toAddress: "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    amountUnits: 25_000_000n,
    blockTimestamp: new Date("2026-09-17T22:30:00.000Z"),
    association: "matched",
    confirmations: 7,
    firstSeenAt: new Date("2026-09-17T22:31:00.000Z"),
    lastSeenAt: new Date("2026-09-17T22:35:00.000Z"),
  };

  it("maps a row to the public shape with decimal amount, string block number and checksummed addresses", () => {
    expect(toEvidenceItemResponse(row)).toEqual({
      transactionHash: TX,
      logIndex: 42,
      blockNumber: "51450000",
      from: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
      to: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      amount: "25.00",
      confirmations: 7,
      blockTimestamp: "2026-09-17T22:30:00.000Z",
      association: "matched",
    });
  });

  it("never exposes internals and serializes without bigint", () => {
    const item = toEvidenceItemResponse(row) as unknown as Record<string, unknown>;
    for (const key of ["id", "paymentIntentId", "amountUnits", "blockHash", "firstSeenAt", "lastSeenAt"]) {
      expect(item).not.toHaveProperty(key);
    }
    expect(() => JSON.stringify(item)).not.toThrow();
  });

  it("encodes the next cursor or null", () => {
    expect(toEvidenceResponse({ items: [row], nextCursor: null })).toEqual({ evidence: [toEvidenceItemResponse(row)], nextCursor: null });
    const withNext = toEvidenceResponse({ items: [row], nextCursor: { blockNumber: 51_450_000n, logIndex: 42, txHash: TX } });
    expect(decodeEvidenceCursor(withNext.nextCursor as string)).toEqual({ blockNumber: 51_450_000n, logIndex: 42, txHash: TX });
  });
});
