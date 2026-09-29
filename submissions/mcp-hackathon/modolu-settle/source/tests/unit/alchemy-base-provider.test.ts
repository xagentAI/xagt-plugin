import {
  HttpRequestError,
  InternalRpcError,
  InvalidParamsRpcError,
  LimitExceededRpcError,
  RpcRequestError,
  TimeoutError,
  encodeAbiParameters,
  encodeEventTopics,
} from "viem";
import { describe, expect, it } from "vitest";

import { ERC20_TRANSFER_EVENT_ABI, USDC_CONTRACT_ADDRESS } from "@/integrations/chain/base-usdc";
import {
  createAlchemyBaseProvider,
  redactProviderError,
  type BaseRpcClient,
} from "@/integrations/chain/alchemy-base-provider";
import { AppError } from "@/lib/errors";

const SECRET_URL = "https://base-mainnet.g.alchemy.com/v2/super-secret-api-key";
const PAYER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045";
const RECIPIENT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const OTHER = "0x1111111111111111111111111111111111111111";
const OTHER_TOKEN = "0x2222222222222222222222222222222222222222";
const BLOCK_HASH = `0x${"d".repeat(64)}`;

const unused = async (): Promise<never> => {
  throw new Error("not expected in this test");
};

async function captureAppError(promise: Promise<unknown>): Promise<AppError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(AppError);
    return error as AppError;
  }
  return expect.unreachable("expected an AppError");
}

// ---------------------------------------------------------------------------
// Fixture helpers: Transfers API pages and canonical receipts with real ABI-encoded logs
// ---------------------------------------------------------------------------

function tx(n: number): `0x${string}` {
  return `0x${n.toString(16).padStart(64, "0")}`;
}

interface LogSpec {
  address?: string;
  from?: string;
  to?: string;
  value?: bigint;
  logIndex: number;
  /** Emit an Approval-shaped log instead of Transfer. */
  approval?: boolean;
  removed?: boolean;
}

function transferLog(spec: LogSpec) {
  const from = spec.from ?? PAYER;
  const to = spec.to ?? RECIPIENT;
  const value = spec.value ?? 25_000_000n;
  const topics = spec.approval
    ? encodeEventTopics({
        abi: [{ type: "event", name: "Approval", inputs: [{ type: "address", name: "owner", indexed: true }, { type: "address", name: "spender", indexed: true }, { type: "uint256", name: "value" }] }],
        eventName: "Approval",
        args: { owner: from as `0x${string}`, spender: to as `0x${string}` },
      })
    : encodeEventTopics({ abi: ERC20_TRANSFER_EVENT_ABI, eventName: "Transfer", args: { from: from as `0x${string}`, to: to as `0x${string}` } });
  return {
    address: spec.address ?? USDC_CONTRACT_ADDRESS,
    topics,
    data: encodeAbiParameters([{ type: "uint256" }], [value]),
    logIndex: spec.logIndex,
    removed: spec.removed ?? false,
  };
}

function receipt(hash: `0x${string}`, blockNumber: bigint, logs: LogSpec[], overrides: Record<string, unknown> = {}) {
  return {
    transactionHash: hash,
    blockNumber,
    blockHash: BLOCK_HASH,
    status: "success",
    logs: logs.map(transferLog),
    ...overrides,
  };
}

/** A fake Alchemy client: `request` answers alchemy_getAssetTransfers pages, receipts come from a map. */
function fakeClient(options: {
  pages?: unknown[];
  receipts?: Record<string, unknown>;
  requestError?: (call: number) => Error | undefined;
  receiptError?: (hash: string) => Error | undefined;
}) {
  const requests: Array<{ method: string; params: unknown }> = [];
  const receiptCalls: string[] = [];
  let page = 0;
  const client: BaseRpcClient = {
    getBlockNumber: unused,
    getBlock: unused,
    request: (async (args: { method: string; params: unknown }) => {
      requests.push(args);
      const error = options.requestError?.(page);
      if (error !== undefined) {
        throw error;
      }
      const result = options.pages?.[page] ?? { transfers: [] };
      page += 1;
      return result;
    }) as unknown as BaseRpcClient["request"],
    getTransactionReceipt: (async ({ hash }: { hash: string }) => {
      receiptCalls.push(hash);
      const error = options.receiptError?.(hash);
      if (error !== undefined) {
        throw error;
      }
      const found = options.receipts?.[hash];
      if (found === undefined) {
        throw new Error(`no receipt fixture for ${hash}`);
      }
      return found;
    }) as unknown as BaseRpcClient["getTransactionReceipt"],
  };
  return { client, requests, receiptCalls };
}

const query = { fromBlock: 1_000n, toBlock: 1_100n, recipient: RECIPIENT, payer: PAYER };
const recipientOnly = { ...query, payer: null };

function provider(client: BaseRpcClient) {
  return createAlchemyBaseProvider({ rpcUrl: SECRET_URL, client });
}

// ---------------------------------------------------------------------------
// getUsdcTransfers — discovery + verification
// ---------------------------------------------------------------------------

describe("getUsdcTransfers — discovery request", () => {
  it("queries alchemy_getAssetTransfers with contract, recipient, payer, block range, erc20 category and max page size", async () => {
    const { client, requests } = fakeClient({ pages: [{ transfers: [] }] });
    await expect(provider(client).getUsdcTransfers(query)).resolves.toEqual([]);
    expect(requests).toHaveLength(1);
    expect(requests[0]?.method).toBe("alchemy_getAssetTransfers");
    expect(requests[0]?.params).toEqual([
      {
        fromBlock: "0x3e8",
        toBlock: "0x44c",
        toAddress: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        fromAddress: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        contractAddresses: [USDC_CONTRACT_ADDRESS],
        category: ["erc20"],
        order: "asc",
        withMetadata: false,
        excludeZeroValue: false,
        maxCount: "0x3e8",
      },
    ]);
  });

  it("omits fromAddress when no payer is declared", async () => {
    const { client, requests } = fakeClient({ pages: [{ transfers: [] }] });
    await provider(client).getUsdcTransfers(recipientOnly);
    const params = (requests[0]?.params as Record<string, unknown>[])[0] ?? {};
    expect(params).not.toHaveProperty("fromAddress");
    expect(params["toAddress"]).toBe("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913");
  });

  it("refuses an inverted block range before calling the provider", async () => {
    const { client, requests } = fakeClient({});
    await expect(provider(client).getUsdcTransfers({ ...query, fromBlock: 1_101n })).rejects.toThrow(/invalid block range/);
    expect(requests).toHaveLength(0);
  });
});

describe("getUsdcTransfers — verification from receipts", () => {
  it("returns the canonical transfer decoded from the receipt log, with an exact bigint amount", async () => {
    const huge = 123_456_789_012_345_678_901_234_567_890n;
    const { client, receiptCalls } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1), value: 0.000001 }] }], // human-readable value is never used
      receipts: { [tx(1)]: receipt(tx(1), 1_050n, [{ logIndex: 42, value: huge }]) },
    });
    const transfers = await provider(client).getUsdcTransfers(query);
    expect(receiptCalls).toEqual([tx(1)]);
    expect(transfers).toEqual([
      { txHash: tx(1), logIndex: 42, blockNumber: 1_050n, blockHash: BLOCK_HASH, from: PAYER, to: RECIPIENT, amountUnits: huge },
    ]);
    expect(typeof transfers[0]?.amountUnits).toBe("bigint");
  });

  it("recovers every sender for a payer-less query and leaves association to the domain", async () => {
    const { client } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }, { hash: tx(2) }] }],
      receipts: {
        [tx(1)]: receipt(tx(1), 1_010n, [{ logIndex: 3, from: PAYER, value: 1n }]),
        [tx(2)]: receipt(tx(2), 1_020n, [{ logIndex: 5, from: OTHER, value: 2n }]),
      },
    });
    const transfers = await provider(client).getUsdcTransfers(recipientOnly);
    expect(transfers.map((t) => [t.txHash, t.from, t.amountUnits])).toEqual([
      [tx(1), PAYER, 1n],
      [tx(2), OTHER, 2n],
    ]);
  });

  it("handles several USDC Transfer logs in one transaction as distinct (txHash, logIndex) identities, even with identical amounts", async () => {
    const { client, receiptCalls } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }, { hash: tx(1) }, { hash: tx(1) }] }], // Alchemy lists one entry per transfer
      receipts: {
        [tx(1)]: receipt(tx(1), 1_050n, [
          { logIndex: 7, value: 5_000_000n },
          { logIndex: 9, value: 5_000_000n },
          { logIndex: 12, value: 1n },
        ]),
      },
    });
    const transfers = await provider(client).getUsdcTransfers(query);
    expect(receiptCalls).toEqual([tx(1)]); // duplicate hashes fetch one receipt
    expect(transfers.map((t) => [t.logIndex, t.amountUnits])).toEqual([
      [7, 5_000_000n],
      [9, 5_000_000n],
      [12, 1n],
    ]);
  });

  it("ignores logs from other tokens, other recipients and (with a payer) other senders inside the same receipt", async () => {
    const { client } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }] }],
      receipts: {
        [tx(1)]: receipt(tx(1), 1_050n, [
          { logIndex: 1, address: OTHER_TOKEN, value: 999n }, // unrelated token
          { logIndex: 2, to: OTHER, value: 888n }, // unrelated recipient
          { logIndex: 3, from: OTHER, value: 777n }, // unrelated payer
          { logIndex: 4, approval: true }, // USDC Approval, not Transfer
          { logIndex: 5, value: 25_000_000n }, // the one that counts
        ]),
      },
    });
    const transfers = await provider(client).getUsdcTransfers(query);
    expect(transfers.map((t) => [t.logIndex, t.amountUnits])).toEqual([[5, 25_000_000n]]);
  });

  it("without a payer keeps logs from any sender but still drops other recipients and tokens", async () => {
    const { client } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }] }],
      receipts: {
        [tx(1)]: receipt(tx(1), 1_050n, [
          { logIndex: 1, address: OTHER_TOKEN },
          { logIndex: 2, to: OTHER },
          { logIndex: 3, from: OTHER, value: 3n },
          { logIndex: 4, from: PAYER, value: 4n },
        ]),
      },
    });
    const transfers = await provider(client).getUsdcTransfers(recipientOnly);
    expect(transfers.map((t) => [t.from, t.amountUnits])).toEqual([
      [OTHER, 3n],
      [PAYER, 4n],
    ]);
  });

  it("includes transactions exactly at both block boundaries and drops receipts outside the window", async () => {
    const { client } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }, { hash: tx(2) }, { hash: tx(3) }, { hash: tx(4) }] }],
      receipts: {
        [tx(1)]: receipt(tx(1), 1_000n, [{ logIndex: 0, value: 1n }]),
        [tx(2)]: receipt(tx(2), 1_100n, [{ logIndex: 0, value: 2n }]),
        [tx(3)]: receipt(tx(3), 999n, [{ logIndex: 0, value: 3n }]),
        [tx(4)]: receipt(tx(4), 1_101n, [{ logIndex: 0, value: 4n }]),
      },
    });
    const transfers = await provider(client).getUsdcTransfers(query);
    expect(transfers.map((t) => [t.blockNumber, t.amountUnits])).toEqual([
      [1_000n, 1n],
      [1_100n, 2n],
    ]);
  });

  it("ignores reverted transactions", async () => {
    const { client } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }] }],
      receipts: { [tx(1)]: receipt(tx(1), 1_050n, [{ logIndex: 0 }], { status: "reverted" }) },
    });
    await expect(provider(client).getUsdcTransfers(query)).resolves.toEqual([]);
  });
});

describe("getUsdcTransfers — pagination", () => {
  it("follows pageKey across multiple pages and merges every page's hashes", async () => {
    const { client, requests, receiptCalls } = fakeClient({
      pages: [
        { transfers: [{ hash: tx(1) }, { hash: tx(2) }], pageKey: "page-2" },
        { transfers: [{ hash: tx(3) }], pageKey: "page-3" },
        { transfers: [{ hash: tx(2) }, { hash: tx(4) }] }, // repeats a hash from page 1
      ],
      receipts: Object.fromEntries([1, 2, 3, 4].map((n) => [tx(n), receipt(tx(n), 1_000n + BigInt(n), [{ logIndex: n, value: BigInt(n) }])])),
    });
    const transfers = await provider(client).getUsdcTransfers(query);
    expect(requests.map((r) => (r.params as Record<string, unknown>[])[0]?.["pageKey"])).toEqual([undefined, "page-2", "page-3"]);
    expect(receiptCalls.sort()).toEqual([tx(1), tx(2), tx(3), tx(4)]);
    expect(transfers.map((t) => t.amountUnits)).toEqual([1n, 2n, 3n, 4n]);
  });

  it("fails the whole operation when a later page fails — no partial evidence", async () => {
    const { client, receiptCalls } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }], pageKey: "page-2" }],
      requestError: (page) => (page === 1 ? new HttpRequestError({ url: SECRET_URL, status: 503, body: { method: "alchemy_getAssetTransfers" } }) : undefined),
      receipts: { [tx(1)]: receipt(tx(1), 1_050n, [{ logIndex: 0 }]) },
    });
    const error = await captureAppError(provider(client).getUsdcTransfers(query));
    expect(error.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(error.retryable).toBe(true);
    expect(error.context).toMatchObject({ operation: "alchemy_getAssetTransfers" });
    expect(receiptCalls).toEqual([]); // nothing was verified, nothing returned
  });

  it("refuses a pagination that never terminates", async () => {
    const { client } = fakeClient({ pages: Array.from({ length: 2_000 }, () => ({ transfers: [], pageKey: "again" })) });
    const error = await captureAppError(provider(client).getUsdcTransfers(query));
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
  });
});

describe("getUsdcTransfers — failure safety", () => {
  it.each([
    ["Transfers API HTTP failure", () => new HttpRequestError({ url: SECRET_URL, status: 503, body: { method: "alchemy_getAssetTransfers" } }), "UPSTREAM_UNAVAILABLE", true],
    ["Transfers API timeout", () => new TimeoutError({ body: { method: "alchemy_getAssetTransfers" }, url: SECRET_URL }), "UPSTREAM_UNAVAILABLE", true],
    ["Transfers API JSON-RPC internal error", () => new InternalRpcError(new RpcRequestError({ body: {}, error: { code: -32603, message: `boom ${SECRET_URL}` }, url: SECRET_URL })), "UPSTREAM_UNAVAILABLE", true],
    ["Transfers API JSON-RPC invalid params", () => new InvalidParamsRpcError(new RpcRequestError({ body: {}, error: { code: -32602, message: `bad ${SECRET_URL}` }, url: SECRET_URL })), "UPSTREAM_UNAVAILABLE", false],
    ["Transfers API limit exceeded", () => new LimitExceededRpcError(new RpcRequestError({ body: {}, error: { code: -32005, message: "limit" }, url: SECRET_URL })), "UPSTREAM_UNAVAILABLE", false],
    ["connection failure", () => new TypeError(`fetch failed ${SECRET_URL}`), "UPSTREAM_UNAVAILABLE", true],
  ])("%s → %s (retryable=%s) without leaking the credential", async (_label, make, code, retryable) => {
    const { client } = fakeClient({ requestError: () => make() });
    const error = await captureAppError(provider(client).getUsdcTransfers(query));
    expect(error.code).toBe(code);
    expect(error.retryable).toBe(retryable);
    expect(JSON.stringify({ m: error.message, c: error.context, cause: error.cause ?? null, s: error.stack })).not.toContain("super-secret");
  });

  it.each([
    ["non-object result", "nope"],
    ["transfers not an array", { transfers: {} }],
    ["transfer entry not an object", { transfers: [1] }],
    ["malformed hash", { transfers: [{ hash: "0x1234" }] }],
    ["malformed pageKey", { transfers: [], pageKey: 7 }],
  ])("malformed Transfers API response (%s) → UPSTREAM_INVALID_RESPONSE", async (_label, page) => {
    const { client, receiptCalls } = fakeClient({ pages: [page] });
    const error = await captureAppError(provider(client).getUsdcTransfers(query));
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
    expect(error.retryable).toBe(false);
    expect(receiptCalls).toEqual([]);
  });

  it("receipt retrieval failure aborts the whole scan with a retryable upstream error", async () => {
    const { client } = fakeClient({
      pages: [{ transfers: [{ hash: tx(1) }, { hash: tx(2) }] }],
      receipts: { [tx(1)]: receipt(tx(1), 1_050n, [{ logIndex: 0 }]) },
      receiptError: (hash) => (hash === tx(2) ? new HttpRequestError({ url: SECRET_URL, status: 429, body: { method: "eth_getTransactionReceipt" } }) : undefined),
    });
    const error = await captureAppError(provider(client).getUsdcTransfers(query));
    expect(error.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(error.context).toMatchObject({ operation: "getTransactionReceipt" });
    expect(JSON.stringify(error.context)).not.toContain("super-secret");
  });

  it.each([
    ["receipt not an object", null],
    ["receipt hash malformed", { transactionHash: "0x12", blockNumber: 1_050n, blockHash: BLOCK_HASH, status: "success", logs: [] }],
    ["receipt block number not bigint", { transactionHash: tx(1), blockNumber: 1050, blockHash: BLOCK_HASH, status: "success", logs: [] }],
    ["receipt block hash malformed", { transactionHash: tx(1), blockNumber: 1_050n, blockHash: "0xzz", status: "success", logs: [] }],
    ["receipt logs malformed", { transactionHash: tx(1), blockNumber: 1_050n, blockHash: BLOCK_HASH, status: "success", logs: "none" }],
    ["USDC Transfer log with undecodable data", receipt(tx(1), 1_050n, [], { logs: [{ ...transferLog({ logIndex: 0 }), data: "0x12" }] })],
    ["USDC Transfer log with a bad log index", receipt(tx(1), 1_050n, [], { logs: [{ ...transferLog({ logIndex: 0 }), logIndex: -1 }] })],
    ["USDC Transfer log marked removed", receipt(tx(1), 1_050n, [{ logIndex: 0, removed: true }])],
  ])("malformed receipt/log (%s) → UPSTREAM_INVALID_RESPONSE", async (_label, bad) => {
    const { client } = fakeClient({ pages: [{ transfers: [{ hash: tx(1) }] }], receipts: { [tx(1)]: bad } });
    const error = await captureAppError(provider(client).getUsdcTransfers(query));
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
  });

  it("a failure on the last receipt of a batch discards everything already verified", async () => {
    const receipts: Record<string, unknown> = {};
    for (let n = 1; n <= 7; n += 1) {
      receipts[tx(n)] = receipt(tx(n), 1_000n + BigInt(n), [{ logIndex: 0, value: BigInt(n) }]);
    }
    const { client } = fakeClient({
      pages: [{ transfers: Array.from({ length: 7 }, (_, i) => ({ hash: tx(i + 1) })) }],
      receipts,
      receiptError: (hash) => (hash === tx(7) ? new TypeError("socket hang up") : undefined),
    });
    await expect(provider(client).getUsdcTransfers(query)).rejects.toMatchObject({ code: "UPSTREAM_UNAVAILABLE" });
  });
});

// ---------------------------------------------------------------------------
// getLatestBlock / getBlockTimestamp / findLastBlockAtOrBefore (unchanged behaviour)
// ---------------------------------------------------------------------------

function blockClient(getBlockNumber: () => Promise<unknown>, getBlock: (params: unknown) => Promise<unknown> = unused): BaseRpcClient {
  return {
    getBlockNumber: getBlockNumber as unknown as BaseRpcClient["getBlockNumber"],
    getBlock: getBlock as unknown as BaseRpcClient["getBlock"],
    getTransactionReceipt: unused as unknown as BaseRpcClient["getTransactionReceipt"],
    request: unused as unknown as BaseRpcClient["request"],
  };
}

describe("getLatestBlock", () => {
  it("returns the latest block as bigint", async () => {
    await expect(provider(blockClient(async () => 35_123_456n)).getLatestBlock()).resolves.toBe(35_123_456n);
  });

  it("maps HTTP failures to a retryable UPSTREAM_UNAVAILABLE without leaking the URL", async () => {
    const viemError = new HttpRequestError({ url: SECRET_URL, status: 429, body: { method: "eth_blockNumber" }, details: "Too Many Requests" });
    expect(viemError.message).toContain("super-secret-api-key"); // viem does include it
    const error = await captureAppError(provider(blockClient(async () => { throw viemError; })).getLatestBlock());
    expect(error.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(error.httpStatus).toBe(503);
    expect(error.retryable).toBe(true);
    expect(error.message).toBe("Blockchain provider is temporarily unavailable");
    expect(error.cause).toBeUndefined();
    expect(error.context).toEqual({
      provider: "alchemy",
      operation: "getBlockNumber",
      providerError: { name: "HttpRequestError", shortMessage: "HTTP request failed.", status: 429 },
    });
    expect(JSON.stringify({ message: error.message, context: error.context, stack: error.stack })).not.toContain("super-secret");
  });

  it("maps timeouts and non-viem errors to UPSTREAM_UNAVAILABLE", async () => {
    const timeout = new TimeoutError({ body: { method: "eth_blockNumber" }, url: SECRET_URL });
    const fromTimeout = await captureAppError(provider(blockClient(async () => { throw timeout; })).getLatestBlock());
    expect(fromTimeout.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(JSON.stringify(fromTimeout.context)).not.toContain("super-secret");
    const fromSocket = await captureAppError(provider(blockClient(async () => { throw new Error(`connect ECONNREFUSED ${SECRET_URL}`); })).getLatestBlock());
    expect(fromSocket.context).toEqual({ provider: "alchemy", operation: "getBlockNumber", providerError: { name: "Error", shortMessage: "Non-RPC error" } });
  });

  it.each([undefined, null, "0x1", 12, -1n])("maps an invalid block number %s to UPSTREAM_INVALID_RESPONSE", async (value) => {
    const error = await captureAppError(provider(blockClient(async () => value)).getLatestBlock());
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
    expect(error.httpStatus).toBe(502);
    expect(error.retryable).toBe(false);
  });

  it("uses a finite HTTP timeout and no automatic retries for the real transport", () => {
    const source = createAlchemyBaseProvider.toString();
    expect(source).toContain("retryCount: 0");
    expect(source).toMatch(/timeout: options\.timeoutMs \?\? DEFAULT_TIMEOUT_MS/);
  });
});

describe("getBlockTimestamp", () => {
  it("returns the block timestamp as a Date from the bigint seconds value", async () => {
    const client = blockClient(unused, async (params) => {
      expect(params).toEqual({ blockNumber: 1_050n, includeTransactions: false });
      return { number: 1_050n, timestamp: 1_789_685_400n, hash: BLOCK_HASH };
    });
    await expect(provider(client).getBlockTimestamp(1_050n)).resolves.toEqual(new Date("2026-09-17T22:50:00.000Z"));
  });

  it.each([
    ["mismatched number", { number: 1_051n, timestamp: 1_789_685_400n }],
    ["missing timestamp", { number: 1_050n }],
    ["number timestamp", { number: 1_050n, timestamp: 1_789_685_400 }],
    ["zero timestamp", { number: 1_050n, timestamp: 0n }],
    ["null block", null],
  ])("rejects %s as UPSTREAM_INVALID_RESPONSE", async (_label, block) => {
    const error = await captureAppError(provider(blockClient(unused, async () => block)).getBlockTimestamp(1_050n));
    expect(error.code).toBe("UPSTREAM_INVALID_RESPONSE");
  });

  it("maps a block fetch failure to a retryable upstream error", async () => {
    const error = await captureAppError(
      provider(blockClient(unused, async () => { throw new TimeoutError({ body: { method: "eth_getBlockByNumber" }, url: SECRET_URL }); })).getBlockTimestamp(1_050n),
    );
    expect(error.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(error.retryable).toBe(true);
    expect(error.context).toMatchObject({ operation: "getBlock" });
  });
});

describe("findLastBlockAtOrBefore", () => {
  it("searches through getBlock reads and returns the boundary block", async () => {
    const reads: bigint[] = [];
    const client = blockClient(unused, async (params) => {
      const { blockNumber } = params as { blockNumber: bigint };
      reads.push(blockNumber);
      return { number: blockNumber, timestamp: blockNumber * 2n, hash: BLOCK_HASH };
    });
    await expect(provider(client).findLastBlockAtOrBefore(new Date(500 * 2_000 + 1_000), { fromBlock: 1n, toBlock: 1_000n })).resolves.toBe(500n);
    expect(reads.length).toBeLessThanOrEqual(12);
    await expect(provider(client).findLastBlockAtOrBefore(new Date(0), { fromBlock: 1n, toBlock: 1_000n })).resolves.toBeNull();
  });

  it("propagates a block-read failure as a retryable upstream error", async () => {
    const client = blockClient(unused, async () => { throw new TimeoutError({ body: { method: "eth_getBlockByNumber" }, url: SECRET_URL }); });
    const error = await captureAppError(provider(client).findLastBlockAtOrBefore(new Date(), { fromBlock: 1n, toBlock: 10n }));
    expect(error.code).toBe("UPSTREAM_UNAVAILABLE");
    expect(JSON.stringify(error.context)).not.toContain("super-secret");
  });
});

describe("redactProviderError", () => {
  it("redacts unknown thrown values", () => {
    expect(redactProviderError("boom")).toEqual({ name: "UnknownError", shortMessage: "Non-error value thrown" });
  });
});
