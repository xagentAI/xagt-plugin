/**
 * `ChainProvider` implementation backed by an Alchemy Base mainnet JSON-RPC
 * endpoint through viem. This is the only module that creates a viem RPC
 * client or knows the transport URL (ARCHITECTURE.md §6).
 *
 * Transfer discovery uses Alchemy's `alchemy_getAssetTransfers` (filtered by
 * contract, recipient and optional sender over the whole window, paginated),
 * and every discovered transaction is then verified from its canonical
 * receipt: the native USDC `Transfer` logs are decoded with viem and
 * re-filtered, and only receipt/log data becomes evidence. The Transfers API
 * is never trusted for amounts. This keeps reconciliation independent of the
 * `eth_getLogs` block-range limit of the Alchemy plan (ARCHITECTURE.md §7.2).
 *
 * The RPC URL embeds the provider credential. viem error messages can contain
 * that URL, so provider errors are never re-thrown or attached as `cause`;
 * only a redacted summary reaches the application error.
 */
import "server-only";

import {
  BaseError,
  InvalidParamsRpcError,
  LimitExceededRpcError,
  createPublicClient,
  getAddress,
  http,
  isAddress,
  parseEventLogs,
  toEventSelector,
  type PublicClient,
} from "viem";

import { AppError } from "@/lib/errors";
import type { BlockRange, ChainProvider, ChainTransfer, UsdcTransferQuery } from "@/ports/chain-provider";

import { BASE_CHAIN, ERC20_TRANSFER_EVENT_ABI, USDC_CONTRACT_ADDRESS } from "./base-usdc";
import { findLastBlockAtOrBefore } from "./block-search";

/** The subset of a viem public client the provider uses; injectable for tests. */
export type BaseRpcClient = Pick<PublicClient, "getBlockNumber" | "getBlock" | "getTransactionReceipt" | "request">;

export interface AlchemyBaseProviderOptions {
  readonly rpcUrl: string;
  /** Per-request timeout; defaults to 10 seconds. */
  readonly timeoutMs?: number;
  /** Test seam; when omitted a viem HTTP client is created from `rpcUrl`. */
  readonly client?: BaseRpcClient;
}

const DEFAULT_TIMEOUT_MS = 10_000;
const USDC_CONTRACT_LOWERCASE = USDC_CONTRACT_ADDRESS.toLowerCase();
const TRANSFER_TOPIC = toEventSelector(ERC20_TRANSFER_EVENT_ABI[0]).toLowerCase();
const HASH_32 = /^0x[0-9a-f]{64}$/;
/** Alchemy's documented per-page maximum for `alchemy_getAssetTransfers`. */
const TRANSFERS_PAGE_SIZE = 1000;
/** Safety cap on pagination so a misbehaving provider cannot loop forever. */
const MAX_TRANSFER_PAGES = 1000;
/** Receipts are fetched a few at a time: fast enough, gentle on provider rate limits. */
const RECEIPT_CONCURRENCY = 4;

/** Summary of a provider failure that is safe to log: never includes the URL or payloads. */
export interface RedactedProviderError {
  readonly name: string;
  readonly shortMessage: string;
  readonly status?: number;
  readonly rpcCode?: number;
}

export function redactProviderError(error: unknown): RedactedProviderError {
  if (error instanceof BaseError) {
    const summary: { name: string; shortMessage: string; status?: number; rpcCode?: number } = {
      name: error.name,
      shortMessage: error.shortMessage,
    };
    if ("status" in error && typeof error.status === "number") {
      summary.status = error.status;
    }
    if ("code" in error && typeof error.code === "number") {
      summary.rpcCode = error.code;
    }
    return summary;
  }
  if (error instanceof Error) {
    return { name: error.name, shortMessage: "Non-RPC error" };
  }
  return { name: "UnknownError", shortMessage: "Non-error value thrown" };
}

/**
 * Maps a thrown provider error to the stable upstream error. Explicit
 * range/response-size rejections (Alchemy answers those with -32602 or
 * -32005) are still `UPSTREAM_UNAVAILABLE` but flagged non-retryable, since
 * repeating the same query cannot succeed; nothing is ever truncated to fit.
 */
function toUpstreamError(operation: string, error: unknown): AppError {
  const providerError = redactProviderError(error);
  const isQueryLimit = error instanceof LimitExceededRpcError || error instanceof InvalidParamsRpcError;
  return new AppError(
    "UPSTREAM_UNAVAILABLE",
    isQueryLimit
      ? "Blockchain provider could not serve the requested block range"
      : "Blockchain provider is temporarily unavailable",
    {
      retryable: !isQueryLimit,
      context: { provider: "alchemy", operation, providerError },
    },
  );
}

function invalidResponse(operation: string, reason: string): AppError {
  return new AppError("UPSTREAM_INVALID_RESPONSE", "Blockchain provider returned an invalid response", {
    context: { provider: "alchemy", operation, reason },
  });
}

/** One entry of an `alchemy_getAssetTransfers` page — only the hash is used, for discovery. */
interface AssetTransfersPage {
  readonly transfers: readonly { readonly hash?: unknown }[];
  readonly pageKey?: unknown;
}

function parseAssetTransfersPage(result: unknown): AssetTransfersPage {
  if (typeof result !== "object" || result === null) {
    throw invalidResponse("alchemy_getAssetTransfers", "result is not an object");
  }
  const page = result as { transfers?: unknown; pageKey?: unknown };
  if (!Array.isArray(page.transfers)) {
    throw invalidResponse("alchemy_getAssetTransfers", "transfers is not an array");
  }
  if (page.pageKey !== undefined && page.pageKey !== null && typeof page.pageKey !== "string") {
    throw invalidResponse("alchemy_getAssetTransfers", "pageKey malformed");
  }
  for (const transfer of page.transfers) {
    if (typeof transfer !== "object" || transfer === null) {
      throw invalidResponse("alchemy_getAssetTransfers", "transfer entry is not an object");
    }
  }
  return page as AssetTransfersPage;
}

/**
 * Converts the canonical USDC `Transfer` logs of one receipt into
 * `ChainTransfer`s that match the query. Logs from other contracts, other
 * recipients, or (when declared) other payers are ignored; anything that is
 * present but malformed is an invalid provider response.
 */
function transfersFromReceipt(receipt: unknown, query: UsdcTransferQuery): ChainTransfer[] {
  if (typeof receipt !== "object" || receipt === null) {
    throw invalidResponse("getTransactionReceipt", "receipt is not an object");
  }
  const candidate = receipt as {
    transactionHash?: unknown;
    blockNumber?: unknown;
    blockHash?: unknown;
    status?: unknown;
    logs?: unknown;
  };
  if (typeof candidate.transactionHash !== "string" || !HASH_32.test(candidate.transactionHash.toLowerCase())) {
    throw invalidResponse("getTransactionReceipt", "receipt transaction hash malformed");
  }
  if (typeof candidate.blockNumber !== "bigint") {
    throw invalidResponse("getTransactionReceipt", "receipt block number malformed");
  }
  if (typeof candidate.blockHash !== "string" || !HASH_32.test(candidate.blockHash.toLowerCase())) {
    throw invalidResponse("getTransactionReceipt", "receipt block hash malformed");
  }
  if (!Array.isArray(candidate.logs)) {
    throw invalidResponse("getTransactionReceipt", "receipt logs malformed");
  }
  // A discovered transaction outside the window (reorg between calls) is simply not evidence for it.
  if (candidate.blockNumber < query.fromBlock || candidate.blockNumber > query.toBlock) {
    return [];
  }
  if (candidate.status !== "success") {
    return [];
  }

  // Only native-USDC `Transfer` logs matter; other USDC events (e.g. Approval) and other contracts are ignored.
  const usdcLogs = candidate.logs.filter((log) => {
    const { address, topics } = log as { address?: unknown; topics?: unknown };
    const topic0 = Array.isArray(topics) && typeof topics[0] === "string" ? topics[0].toLowerCase() : null;
    return typeof address === "string" && address.toLowerCase() === USDC_CONTRACT_LOWERCASE && topic0 === TRANSFER_TOPIC;
  });

  let decoded: readonly { args: unknown; logIndex: unknown; removed?: unknown }[];
  try {
    decoded = parseEventLogs({
      abi: ERC20_TRANSFER_EVENT_ABI,
      eventName: "Transfer",
      logs: usdcLogs as Parameters<typeof parseEventLogs>[0]["logs"],
      strict: true,
    });
  } catch {
    throw invalidResponse("getTransactionReceipt", "USDC log could not be decoded");
  }
  // strict: true drops logs whose topics/data do not decode; every USDC log must decode.
  if (decoded.length !== usdcLogs.length) {
    throw invalidResponse("getTransactionReceipt", "USDC log could not be decoded");
  }

  const transfers: ChainTransfer[] = [];
  for (const log of decoded) {
    const { from, to, value } = (log.args ?? {}) as { from?: unknown; to?: unknown; value?: unknown };
    if (typeof from !== "string" || !isAddress(from) || typeof to !== "string" || !isAddress(to) || typeof value !== "bigint" || value < 0n) {
      throw invalidResponse("getTransactionReceipt", "decoded Transfer arguments malformed");
    }
    if (typeof log.logIndex !== "number" || !Number.isInteger(log.logIndex) || log.logIndex < 0) {
      throw invalidResponse("getTransactionReceipt", "log index malformed");
    }
    if (log.removed === true) {
      throw invalidResponse("getTransactionReceipt", "log marked removed");
    }
    const sender = from.toLowerCase();
    if (to.toLowerCase() !== query.recipient || (query.payer !== null && sender !== query.payer)) {
      continue;
    }
    transfers.push({
      txHash: candidate.transactionHash.toLowerCase(),
      logIndex: log.logIndex,
      blockNumber: candidate.blockNumber,
      blockHash: candidate.blockHash.toLowerCase(),
      from: sender,
      to: to.toLowerCase(),
      amountUnits: value,
    });
  }
  return transfers;
}

export function createAlchemyBaseProvider(options: AlchemyBaseProviderOptions): ChainProvider {
  const client: BaseRpcClient =
    options.client ??
    createPublicClient({
      chain: BASE_CHAIN,
      transport: http(options.rpcUrl, {
        timeout: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
        retryCount: 0,
      }),
      // The latest block fixes an intent's matching boundary; never serve a cached value.
      cacheTime: 0,
    });

  const provider: ChainProvider = {
    async getLatestBlock(): Promise<bigint> {
      let result: unknown;
      try {
        result = await client.getBlockNumber({ cacheTime: 0 });
      } catch (error) {
        throw toUpstreamError("getBlockNumber", error);
      }
      if (typeof result !== "bigint" || result < 0n) {
        throw invalidResponse("getBlockNumber", `block number is ${typeof result}`);
      }
      return result;
    },

    async getUsdcTransfers(query: UsdcTransferQuery): Promise<ChainTransfer[]> {
      if (query.fromBlock > query.toBlock || query.fromBlock < 0n) {
        throw new Error(`invalid block range ${query.fromBlock}..${query.toBlock}`);
      }

      // 1. Discovery: every USDC transfer to the recipient (from the payer, when declared)
      //    in the window, paginated through pageKey. Only transaction hashes are kept.
      const hashes = new Set<string>();
      let pageKey: string | undefined;
      for (let pages = 0; ; pages += 1) {
        if (pages >= MAX_TRANSFER_PAGES) {
          throw invalidResponse("alchemy_getAssetTransfers", "pagination did not terminate");
        }
        const params: Record<string, unknown> = {
          fromBlock: `0x${query.fromBlock.toString(16)}`,
          toBlock: `0x${query.toBlock.toString(16)}`,
          toAddress: getAddress(query.recipient),
          contractAddresses: [USDC_CONTRACT_ADDRESS],
          category: ["erc20"],
          order: "asc",
          withMetadata: false,
          excludeZeroValue: false,
          maxCount: `0x${TRANSFERS_PAGE_SIZE.toString(16)}`,
        };
        if (query.payer !== null) {
          params["fromAddress"] = getAddress(query.payer);
        }
        if (pageKey !== undefined) {
          params["pageKey"] = pageKey;
        }
        let result: unknown;
        try {
          result = await client.request({
            method: "alchemy_getAssetTransfers" as never,
            params: [params] as never,
          });
        } catch (error) {
          throw toUpstreamError("alchemy_getAssetTransfers", error);
        }
        const page = parseAssetTransfersPage(result);
        for (const transfer of page.transfers) {
          if (typeof transfer.hash !== "string" || !HASH_32.test(transfer.hash.toLowerCase())) {
            throw invalidResponse("alchemy_getAssetTransfers", "transfer hash malformed");
          }
          hashes.add(transfer.hash.toLowerCase());
        }
        if (typeof page.pageKey !== "string") {
          break;
        }
        pageKey = page.pageKey;
      }

      // 2. Verification: canonical receipts, decoded USDC Transfer logs, re-filtered.
      //    Any failure aborts the whole operation — never a partial result.
      const ordered = [...hashes];
      const transfers: ChainTransfer[] = [];
      for (let index = 0; index < ordered.length; index += RECEIPT_CONCURRENCY) {
        const batch = ordered.slice(index, index + RECEIPT_CONCURRENCY);
        const receipts = await Promise.all(
          batch.map(async (hash) => {
            try {
              return await client.getTransactionReceipt({ hash: hash as `0x${string}` });
            } catch (error) {
              throw toUpstreamError("getTransactionReceipt", error);
            }
          }),
        );
        for (const receipt of receipts) {
          transfers.push(...transfersFromReceipt(receipt, query));
        }
      }

      // Identity is (txHash, logIndex); a hash discovered twice yields one receipt, but be explicit.
      const unique = new Map<string, ChainTransfer>();
      for (const transfer of transfers) {
        unique.set(`${transfer.txHash}:${transfer.logIndex}`, transfer);
      }
      return [...unique.values()];
    },

    async getBlockTimestamp(blockNumber: bigint): Promise<Date> {
      let block: unknown;
      try {
        block = await client.getBlock({ blockNumber, includeTransactions: false });
      } catch (error) {
        throw toUpstreamError("getBlock", error);
      }
      const header = (block ?? {}) as { number?: unknown; timestamp?: unknown };
      if (header.number !== blockNumber) {
        throw invalidResponse("getBlock", "block number does not match the request");
      }
      if (typeof header.timestamp !== "bigint" || header.timestamp <= 0n || header.timestamp > 253_402_300_799n) {
        throw invalidResponse("getBlock", "block timestamp malformed");
      }
      // Seconds since epoch fit a JavaScript number exactly up to year 9999.
      return new Date(Number(header.timestamp) * 1000);
    },

    async findLastBlockAtOrBefore(at: Date, range: BlockRange): Promise<bigint | null> {
      const outcome = await findLastBlockAtOrBefore((blockNumber) => provider.getBlockTimestamp(blockNumber), at, range);
      return outcome.blockNumber;
    },
  };
  return provider;
}
