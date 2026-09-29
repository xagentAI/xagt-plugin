/**
 * Binary search for the greatest block whose timestamp is `<= at`, assuming
 * non-decreasing block timestamps (true for Base). Provider-neutral: takes a
 * timestamp reader and memoizes every read for the duration of one search so
 * no block is fetched twice. Roughly `log2(toBlock - fromBlock) + 2` reads.
 */
import type { BlockRange } from "@/ports/chain-provider";

export type BlockTimestampReader = (blockNumber: bigint) => Promise<Date>;

export interface BlockSearchOutcome {
  /** Greatest block in range with `timestamp <= at`, or `null` when `fromBlock` is already later. */
  readonly blockNumber: bigint | null;
  /** Number of distinct blocks read. */
  readonly reads: number;
}

export async function findLastBlockAtOrBefore(
  read: BlockTimestampReader,
  at: Date,
  range: BlockRange,
): Promise<BlockSearchOutcome> {
  if (range.fromBlock > range.toBlock) {
    throw new RangeError(`invalid block range ${range.fromBlock}..${range.toBlock}`);
  }
  const target = at.getTime();
  const cache = new Map<bigint, number>();
  const timestampOf = async (blockNumber: bigint): Promise<number> => {
    const cached = cache.get(blockNumber);
    if (cached !== undefined) {
      return cached;
    }
    const value = (await read(blockNumber)).getTime();
    cache.set(blockNumber, value);
    return value;
  };

  // Common cases first: the whole range qualifies, or none of it does.
  if ((await timestampOf(range.toBlock)) <= target) {
    return { blockNumber: range.toBlock, reads: cache.size };
  }
  if ((await timestampOf(range.fromBlock)) > target) {
    return { blockNumber: null, reads: cache.size };
  }

  // Invariant: timestamp(low) <= target < timestamp(high).
  let low = range.fromBlock;
  let high = range.toBlock;
  while (high - low > 1n) {
    const mid = low + (high - low) / 2n;
    if ((await timestampOf(mid)) <= target) {
      low = mid;
    } else {
      high = mid;
    }
  }
  return { blockNumber: low, reads: cache.size };
}
