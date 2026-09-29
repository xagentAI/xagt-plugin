/**
 * Chain read port. Services depend on this interface; the Alchemy adapter in
 * `src/integrations/chain/` is the only implementation that knows RPC details
 * (ARCHITECTURE.md §6). It is deliberately provider-neutral: no viem types
 * cross this boundary.
 */

/** One canonical native-USDC `Transfer` log, normalized for reconciliation. */
export interface ChainTransfer {
  readonly txHash: string;
  readonly logIndex: number;
  readonly blockNumber: bigint;
  readonly blockHash: string;
  /** Lowercase sender. */
  readonly from: string;
  /** Lowercase recipient. */
  readonly to: string;
  /** Exact USDC base units. */
  readonly amountUnits: bigint;
}

export interface UsdcTransferQuery {
  /** Inclusive block range; `fromBlock <= toBlock`. */
  readonly fromBlock: bigint;
  readonly toBlock: bigint;
  /** Lowercase recipient; always filtered at the log-query level. */
  readonly recipient: string;
  /** Lowercase payer; when present it is filtered at the log-query level too, otherwise every sender is returned. */
  readonly payer: string | null;
}

export interface BlockRange {
  readonly fromBlock: bigint;
  readonly toBlock: bigint;
}

export interface ChainProvider {
  /** Latest canonical Base block number. Throws `UPSTREAM_*` application errors on failure. */
  getLatestBlock(): Promise<bigint>;

  /**
   * Canonical native Base USDC transfers to `recipient` (from `payer` when
   * declared) within the block range. A query failure throws an `UPSTREAM_*`
   * error and is never reported as "no transfers".
   */
  getUsdcTransfers(query: UsdcTransferQuery): Promise<ChainTransfer[]>;

  /** Timestamp of the canonical block at `blockNumber`. */
  getBlockTimestamp(blockNumber: bigint): Promise<Date>;

  /**
   * Greatest block in `range` whose timestamp is `<= at`, or `null` when even
   * `range.fromBlock` is later than `at`. Returns `range.toBlock` when that
   * block itself is not later than `at`. The provider owns the search
   * mechanics (ARCHITECTURE.md §7.1).
   */
  findLastBlockAtOrBefore(at: Date, range: BlockRange): Promise<bigint | null>;
}
