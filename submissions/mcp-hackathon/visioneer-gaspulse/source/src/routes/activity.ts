import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { ETHERSCAN_API_KEY, CACHE_TTL_MS } from "../config.js";
import { fetchTransactions, EtherscanError } from "../lib/etherscan.js";
import { computeGasTrend } from "../lib/gasTrend.js";
import { computeActivityScore } from "../lib/activityScore.js";
import type { ActivityResponse, EtherscanTx } from "../types.js";

const paramsSchema = z.object({
  address: z.string().regex(/^0x[0-9a-fA-F]{40}$/),
});

const querySchema = z.object({
  windowDays: z.coerce.number().int().min(1).max(180).default(30),
});

const transactionCache = new Map<string, { expiresAt: number; transactions: EtherscanTx[] }>();

export async function registerActivityRoute(app: FastifyInstance): Promise<void> {
  app.get("/v1/address/:address/activity", async (request, reply) => {
    const paramsResult = paramsSchema.safeParse(request.params);
    if (!paramsResult.success) {
      return reply.code(400).send({
        error: {
          code: "invalid_address",
          message: "address must be a 0x-prefixed 40-hex-character Ethereum address",
        },
      });
    }

    const queryResult = querySchema.safeParse(request.query);
    if (!queryResult.success) {
      return reply.code(400).send({
        error: { code: "invalid_window", message: "windowDays must be an integer between 1 and 180" },
      });
    }

    const address = paramsResult.data.address.toLowerCase();
    const { windowDays } = queryResult.data;

    let transactions: EtherscanTx[];
    try {
      transactions = await getTransactions(address);
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

    const now = new Date();
    const windowStartMs = now.getTime() - windowDays * 86_400_000;
    const inWindow = transactions.filter((tx) => Number(tx.timeStamp) * 1000 >= windowStartMs);
    const gasTrend = computeGasTrend(transactions, windowDays, now);
    const activityScore = computeActivityScore(transactions, windowDays, now);

    const allTimestampsMs = transactions.map((tx) => Number(tx.timeStamp) * 1000);
    const response: ActivityResponse = {
      address,
      network: "ethereum-mainnet",
      windowDays,
      asOf: now.toISOString(),
      txCount: inWindow.length,
      firstSeen: allTimestampsMs.length > 0 ? new Date(Math.min(...allTimestampsMs)).toISOString() : null,
      lastSeen: allTimestampsMs.length > 0 ? new Date(Math.max(...allTimestampsMs)).toISOString() : null,
      gasTrend,
      activityScore,
      dataSource: "etherscan",
    };

    return response;
  });
}

async function getTransactions(address: string): Promise<EtherscanTx[]> {
  const cached = transactionCache.get(address);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.transactions;
  }
  const transactions = await fetchTransactions(address, ETHERSCAN_API_KEY);
  transactionCache.set(address, { expiresAt: Date.now() + CACHE_TTL_MS, transactions });
  return transactions;
}
