import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import type { LaunchpadId } from "@/lib/supabase/database.types";
import { getEnvironmentScope } from "@/lib/env-scope.server";

/**
 * GET /api/earnings — Get the current user's earnings with breakdowns.
 *
 * Query params:
 *   ?period=24h|7d|30d|all (default: all)
 *   ?launchpad=meteora|bags|pumpfun (optional filter)
 */
export async function GET(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { searchParams } = new URL(request.url);
    const period = searchParams.get("period") || "all";
    const launchpadFilter = searchParams.get("launchpad");

    const supabase = createAdminSupabase();
    const scope = getEnvironmentScope();

    // Build query
    let query = supabase
      .from("earnings")
      .select("*, tokens(name, symbol), launches(launchpad, pool_address)")
      .eq("wallet_address", auth.walletAddress)
      .eq("app_phase", scope.appPhase)
      .order("recorded_at", { ascending: false });

    // Period filter
    if (period !== "all") {
      const intervals: Record<string, string> = {
        "24h": new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
        "7d": new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
        "30d": new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
      };
      if (intervals[period]) {
        query = query.gte("recorded_at", intervals[period]);
      }
    }

    // Launchpad filter
    if (launchpadFilter) {
      query = query.eq("launchpad", launchpadFilter as LaunchpadId);
    }

    const { data: rawEarnings, error } = await query;
    if (error) throw error;

    const earningsList = (rawEarnings ?? []) as { amount_sol: number; launchpad: string; [key: string]: unknown }[];

    // Aggregate totals
    const totalSol = earningsList.reduce(
      (sum, e) => sum + Number(e.amount_sol),
      0
    );

    // Group by launchpad
    const byLaunchpad: Record<string, number> = {};
    for (const e of earningsList) {
      byLaunchpad[e.launchpad] =
        (byLaunchpad[e.launchpad] || 0) + Number(e.amount_sol);
    }

    return Response.json({
      earnings: earningsList,
      summary: {
        total: Math.round(totalSol * 1e9) / 1e9,
        byLaunchpad,
        count: earningsList.length,
      },
    });
  } catch (err) {
    console.error("[API] GET /earnings error:", err);
    return Response.json(
      { error: "Failed to fetch earnings" },
      { status: 500 }
    );
  }
}
