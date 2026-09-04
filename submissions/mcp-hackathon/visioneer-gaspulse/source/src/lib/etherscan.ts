import type { EtherscanTx } from "../types.js";

const ETHERSCAN_BASE_URL = "https://api.etherscan.io/v2/api";
const CHAIN_ID_ETHEREUM_MAINNET = 1;
const REQUEST_TIMEOUT_MS = 8_000;
const MAX_TRANSACTIONS = 1000;

export class EtherscanError extends Error {
  constructor(
    message: string,
    public readonly kind: "rate_limited" | "unavailable",
  ) {
    super(message);
  }
}

interface EtherscanListResponse {
  status: string;
  message: string;
  result: EtherscanTx[] | string;
}

interface EtherscanGasOracleResult {
  SafeGasPrice: string;
  ProposeGasPrice: string;
  FastGasPrice: string;
}

interface EtherscanGasOracleResponse {
  status: string;
  message: string;
  result: EtherscanGasOracleResult | string;
}

export interface GasOraclePrices {
  safeGwei: number;
  standardGwei: number;
  fastGwei: number;
}

async function etherscanGet<T>(params: Record<string, string>): Promise<T> {
  const url = new URL(ETHERSCAN_BASE_URL);
  url.searchParams.set("chainid", String(CHAIN_ID_ETHEREUM_MAINNET));
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(url, { signal: controller.signal });
  } catch (error) {
    throw new EtherscanError(`Etherscan request failed: ${(error as Error).message}`, "unavailable");
  } finally {
    clearTimeout(timeout);
  }

  if (response.status === 429) {
    throw new EtherscanError("Etherscan rate limit exceeded", "rate_limited");
  }
  if (!response.ok) {
    throw new EtherscanError(`Etherscan responded with HTTP ${response.status}`, "unavailable");
  }

  return (await response.json()) as T;
}

export async function fetchGasOracle(apiKey: string): Promise<GasOraclePrices> {
  const body = await etherscanGet<EtherscanGasOracleResponse>({
    module: "gastracker",
    action: "gasoracle",
    apikey: apiKey,
  });

  if (body.status === "0" || typeof body.result === "string") {
    const message = typeof body.result === "string" ? body.result : body.message;
    if (/rate limit/i.test(message)) {
      throw new EtherscanError(message, "rate_limited");
    }
    throw new EtherscanError(message, "unavailable");
  }

  return {
    safeGwei: Number(body.result.SafeGasPrice),
    standardGwei: Number(body.result.ProposeGasPrice),
    fastGwei: Number(body.result.FastGasPrice),
  };
}

export async function fetchTransactions(address: string, apiKey: string): Promise<EtherscanTx[]> {
  const body = await etherscanGet<EtherscanListResponse>({
    module: "account",
    action: "txlist",
    address,
    startblock: "0",
    endblock: "99999999",
    page: "1",
    offset: String(MAX_TRANSACTIONS),
    sort: "desc",
    apikey: apiKey,
  });

  if (body.status === "0") {
    if (typeof body.result === "string" && /rate limit/i.test(body.result)) {
      throw new EtherscanError(body.result, "rate_limited");
    }
    return [];
  }
  return Array.isArray(body.result) ? body.result : [];
}
