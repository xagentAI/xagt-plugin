export async function GET() {
  return Response.json(
    {
      name: "Multipu API",
      version: "1.0.0",
      description:
        "Multipu is an autonomous decentralized execution engine that aggregates top launchpads like Pump.fun, Pons, and Meteora across Solana, BNB, and Robinhood to automate liquidity deployment, trade, and unify cross-chain creator earnings. It features an embedded copilot, Multipu AI, which uses OLAXbt telemetry and the X-Agent framework to turn a single prompt into an autonomous trading and arbitrage agent.",
      documentation: "https://www.multipu.fun",
      endpoints: {
        health: "/api/health",
        verification: "/.well-known/xagent-verification.json",
        exploreLaunches: "/api/launches/explore",
        trendingLaunches: "/api/launches/trending",
        tokenSearch: "/api/tokens/search",
        agents: "/api/agents",
        keeperhubAudit: "/api/keeperhub/audit/:id",
      },
      chains: ["solana", "bsc", "robinhood"],
    },
    {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=60, s-maxage=300",
      },
    }
  );
}
