import { getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { getEnvironmentScope } from "@/lib/env-scope.server";

const GIT_COMMIT =
  process.env.VERCEL_GIT_COMMIT_SHA ||
  process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA ||
  "c2a44bedd75a16f91da6e7a07787aec8340f40bb";

export async function GET(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const scope = getEnvironmentScope();

  return Response.json({
    status: "ok",
    service: "multipu",
    version: "1.0.0",
    commit: GIT_COMMIT,
    environment: {
      appPhase: scope.appPhase,
      network: scope.network,
    },
    supportedChains: [
      { id: "solana", name: "Solana", gas: "SOL" },
      { id: "bsc", name: "BNB Smart Chain", gas: "BNB" },
      { id: "robinhood", name: "Robinhood Chain", gas: "ETH" },
    ],
    mcp: {
      enabled: true,
      protocol: "2024-11-05",
      server: "multipu-mcp",
    },
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
  });
}
