import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import { getEnvironmentScope } from "@/lib/env-scope.server";

/**
 * GET /api/dashboard — Aggregated dashboard stats for the current user.
 *
 * Returns: {
 *   totalTokens, activeLaunches, totalEarnings, earningsToday,
 *   tokens (with launches), recentEarnings
 * }
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
    const supabase = createAdminSupabase();
    const wallet = auth.walletAddress;
    const scope = getEnvironmentScope();

    // Run queries in parallel for performance
    const [tokensRes, launchesRes, earningsRes, recentEarningsRes, exposureRes] =
      await Promise.all([
        supabase
          .from("tokens")
          .select("*, launches(id, launchpad, status, pool_address)")
          .eq("wallet_address", wallet)
          .eq("app_phase", scope.appPhase)
          .order("created_at", { ascending: false }),

        supabase
          .from("launches")
          .select("id, status, launchpad, created_at")
          .eq("wallet_address", wallet)
          .eq("app_phase", scope.appPhase),

        supabase
          .from("earnings")
          .select("amount_sol, recorded_at, launchpad")
          .eq("wallet_address", wallet)
          .eq("app_phase", scope.appPhase),

        supabase
          .from("earnings")
          .select(
            "amount_sol, fee_type, recorded_at, launchpad, tokens(name, symbol)"
          )
          .eq("wallet_address", wallet)
          .eq("app_phase", scope.appPhase)
          .order("recorded_at", { ascending: false })
          .limit(10),

        supabase
          .from("exposure_timeline")
          .select("id, value, label, recorded_at")
          .eq("wallet_address", wallet)
          .order("recorded_at", { ascending: true }),
      ]);

    const tokens = tokensRes.data ?? [];
    const launches: { id: string; status: string; launchpad?: string; created_at?: string }[] =
      (launchesRes.data ?? []) as { id: string; status: string; launchpad?: string; created_at?: string }[];
    const earnings: { amount_sol: number; recorded_at: string; launchpad: string }[] =
      (earningsRes.data ?? []) as { amount_sol: number; recorded_at: string; launchpad: string }[];
    const recentEarnings = recentEarningsRes.data ?? [];
    const exposureRows = exposureRes.data ?? [];

    const totalEarnings = earnings.reduce(
      (sum, e) => sum + Number(e.amount_sol),
      0
    );

    const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

    const earningsToday = earnings
      .filter((e) => e.recorded_at > oneDayAgo)
      .reduce((sum, e) => sum + Number(e.amount_sol), 0);

    const earningsLast30d = earnings
      .filter((e) => e.recorded_at >= thirtyDaysAgo)
      .reduce((sum, e) => sum + Number(e.amount_sol), 0);
    const earningsChange = earningsLast30d > 0 ? `+${earningsLast30d.toFixed(2)} SOL` : "0.00 SOL";
    const earningsChangeColor = earningsLast30d > 0 ? "text-emerald-400" : "text-neutral-400";

    const tokensLast30d = tokens.filter((t: any) => t.created_at && t.created_at >= thirtyDaysAgo).length;
    const tokensChange = tokensLast30d > 0 ? `+${tokensLast30d} new` : "none";
    const tokensChangeColor = tokensLast30d > 0 ? "text-emerald-400" : "text-neutral-400";

    const launchesLast30d = launches.filter((l) => l.created_at && l.created_at >= thirtyDaysAgo).length;
    const launchesChange = launchesLast30d > 0 ? `${launchesLast30d} launched` : "no launches";
    const launchesChangeColor = launchesLast30d > 0 ? "text-emerald-400" : "text-neutral-400";

    // Launchpads used (distinct)
    const launchpadsUsed = [
      ...new Set(launches.map((l) => l.launchpad).filter(Boolean)),
    ];
    const launchpadsChange = launchpadsUsed.length > 0 ? `${launchpadsUsed.length} venues` : "none";
    const launchpadsChangeColor = launchpadsUsed.length > 0 ? "text-emerald-400" : "text-neutral-400";

    const exposurePoints = ((exposureRows as any[]) ?? []).map((r) => ({
      date: r.label,
      value: Number(r.value),
    }));

    const startVal = exposurePoints.length > 0 ? exposurePoints[0].value : 0;
    const currentVal = exposurePoints.length > 0 ? exposurePoints[exposurePoints.length - 1].value : 0;
    const changePct = startVal > 0 ? ((currentVal - startVal) / startVal) * 100 : 0;
    const changeFormatted = startVal > 0 ? `${changePct >= 0 ? "↑" : "↓"} ${Math.abs(changePct).toFixed(1)}%` : "0.0%";

    return Response.json({
      stats: {
        totalTokens: tokens.length,
        tokensChange,
        tokensChangeColor,
        activeLaunches: launches.filter((l) => l.status === "live").length,
        launchesChange,
        launchesChangeColor,
        totalEarnings: Math.round(totalEarnings * 1e9) / 1e9,
        earningsChange,
        earningsChangeColor,
        earningsToday: Math.round(earningsToday * 1e9) / 1e9,
        launchpadsUsed,
        launchpadsChange,
        launchpadsChangeColor,
      },
      exposure: {
        total: currentVal.toLocaleString(),
        change: changeFormatted,
        period: "last 30 days",
        points: exposurePoints,
      },
      tokens,
      recentEarnings,
    });
  } catch (err) {
    console.error("[API] GET /dashboard error:", err);
    return Response.json(
      { error: "Failed to fetch dashboard" },
      { status: 500 }
    );
  }
}
