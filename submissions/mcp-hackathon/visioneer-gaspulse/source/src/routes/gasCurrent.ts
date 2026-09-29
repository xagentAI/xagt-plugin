import type { FastifyInstance } from "fastify";
import { ETHERSCAN_API_KEY, GAS_ORACLE_CACHE_TTL_MS } from "../config.js";
import { fetchGasOracle, EtherscanError, type GasOraclePrices } from "../lib/etherscan.js";
import type { GasOracleResponse } from "../types.js";

let cache: { expiresAt: number; prices: GasOraclePrices } | null = null;

/** Test-only: clears the module-level cache so each test hits the mocked fetch. */
export function resetGasOracleCache(): void {
  cache = null;
}

export async function registerGasCurrentRoute(app: FastifyInstance): Promise<void> {
  app.get("/v1/gas/current", async (request, reply) => {
    let prices: GasOraclePrices;
    try {
      prices = await getGasOracle();
    } catch (error) {
      if (error instanceof EtherscanError && error.kind === "rate_limited") {
        return reply.code(429).send({
          error: { code: "upstream_rate_limited", message: "Etherscan rate limit exceeded, retry shortly" },
        });
      }
      request.log.error(error);
      return reply.code(502).send({
        error: { code: "upstream_unavailable", message: "the upstream data source is unavailable" },
      });
    }

    const response: GasOracleResponse = {
      network: "ethereum-mainnet",
      asOf: new Date().toISOString(),
      ...prices,
      dataSource: "etherscan",
    };
    return response;
  });
}

async function getGasOracle(): Promise<GasOraclePrices> {
  if (cache && cache.expiresAt > Date.now()) {
    return cache.prices;
  }
  const prices = await fetchGasOracle(ETHERSCAN_API_KEY);
  cache = { expiresAt: Date.now() + GAS_ORACLE_CACHE_TTL_MS, prices };
  return prices;
}
