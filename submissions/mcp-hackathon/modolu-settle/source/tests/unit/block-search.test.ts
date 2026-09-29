import { describe, expect, it } from "vitest";

import { findLastBlockAtOrBefore } from "@/integrations/chain/block-search";

/** Deterministic chain: block n has timestamp n * 2s; records every read. */
function chain(offsetMs = 0) {
  const reads: bigint[] = [];
  const read = async (blockNumber: bigint): Promise<Date> => {
    reads.push(blockNumber);
    return new Date(Number(blockNumber) * 2_000 + offsetMs);
  };
  return { reads, read };
}

describe("findLastBlockAtOrBefore", () => {
  it("returns the block whose timestamp equals the target", async () => {
    const { read } = chain();
    const outcome = await findLastBlockAtOrBefore(read, new Date(500 * 2_000), { fromBlock: 1n, toBlock: 1_000n });
    expect(outcome.blockNumber).toBe(500n);
  });

  it("returns the earlier block when the target lies between two block timestamps", async () => {
    const { read } = chain();
    const outcome = await findLastBlockAtOrBefore(read, new Date(500 * 2_000 + 1_999), { fromBlock: 1n, toBlock: 1_000n });
    expect(outcome.blockNumber).toBe(500n);
  });

  it("returns null when the first block of the range is already later than the target", async () => {
    const { read, reads } = chain();
    const outcome = await findLastBlockAtOrBefore(read, new Date(400 * 2_000), { fromBlock: 401n, toBlock: 1_000n });
    expect(outcome.blockNumber).toBeNull();
    expect(reads).toEqual([1_000n, 401n]);
  });

  it("returns the last block of the range when the target is after it", async () => {
    const { read, reads } = chain();
    const outcome = await findLastBlockAtOrBefore(read, new Date(5_000 * 2_000), { fromBlock: 1n, toBlock: 1_000n });
    expect(outcome.blockNumber).toBe(1_000n);
    expect(reads).toEqual([1_000n]);
  });

  it("handles the range boundaries themselves", async () => {
    const { read } = chain();
    expect((await findLastBlockAtOrBefore(read, new Date(1 * 2_000), { fromBlock: 1n, toBlock: 1_000n })).blockNumber).toBe(1n);
    expect((await findLastBlockAtOrBefore(read, new Date(999 * 2_000 + 1), { fromBlock: 1n, toBlock: 1_000n })).blockNumber).toBe(999n);
    expect((await findLastBlockAtOrBefore(read, new Date(7 * 2_000), { fromBlock: 7n, toBlock: 7n })).blockNumber).toBe(7n);
  });

  it("uses O(log n) reads and never reads a block twice", async () => {
    const { read, reads } = chain();
    const range = { fromBlock: 1n, toBlock: 302_400n }; // 7 days of Base blocks
    const outcome = await findLastBlockAtOrBefore(read, new Date(123_456 * 2_000 + 1_000), range);
    expect(outcome.blockNumber).toBe(123_456n);
    expect(outcome.reads).toBe(reads.length);
    expect(reads.length).toBeLessThanOrEqual(22);
    expect(new Set(reads).size).toBe(reads.length);
  });

  it("works on block numbers beyond Number.MAX_SAFE_INTEGER", async () => {
    const base = 9_007_199_254_740_993n;
    const read = async (blockNumber: bigint): Promise<Date> => new Date(Number(blockNumber - base) * 2_000);
    const outcome = await findLastBlockAtOrBefore(read, new Date(10 * 2_000), { fromBlock: base, toBlock: base + 100n });
    expect(outcome.blockNumber).toBe(base + 10n);
  });

  it("rejects an inverted range without reading", async () => {
    const { read, reads } = chain();
    await expect(findLastBlockAtOrBefore(read, new Date(), { fromBlock: 10n, toBlock: 9n })).rejects.toThrow(RangeError);
    expect(reads).toEqual([]);
  });
});
