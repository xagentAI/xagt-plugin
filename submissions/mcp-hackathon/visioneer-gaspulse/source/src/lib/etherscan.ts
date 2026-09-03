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

export async function fetchTransactions(address: string, apiKey: string): Promise<EtherscanTx[]> {
  const url = new URL(ETHERSCAN_BASE_URL);
  url.searchParams.set("chainid", String(CHAIN_ID_ETHEREUM_MAINNET));
  url.searchParams.set("module", "account");
  url.searchParams.set("action", "txlist");
  url.searchParams.set("address", address);
  url.searchParams.set("startblock", "0");
  url.searchParams.set("endblock", "99999999");
  url.searchParams.set("page", "1");
  url.searchParams.set("offset", String(MAX_TRANSACTIONS));
  url.searchParams.set("sort", "desc");
  url.searchParams.set("apikey", apiKey);

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

  const body = (await response.json()) as EtherscanListResponse;
  if (body.status === "0") {
    if (typeof body.result === "string" && /rate limit/i.test(body.result)) {
      throw new EtherscanError(body.result, "rate_limited");
    }
    return [];
  }
  return Array.isArray(body.result) ? body.result : [];
}
