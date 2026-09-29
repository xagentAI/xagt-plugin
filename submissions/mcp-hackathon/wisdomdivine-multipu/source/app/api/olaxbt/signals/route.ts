import { fetchOlaXbtSignals } from "@/lib/olaxbt/client";
import { getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";

export async function GET(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol") || "GPU";

  const signal = await fetchOlaXbtSignals(symbol);

  return Response.json({
    success: true,
    protocol: "OlaXBT Nexus MCP",
    signal,
  });
}
