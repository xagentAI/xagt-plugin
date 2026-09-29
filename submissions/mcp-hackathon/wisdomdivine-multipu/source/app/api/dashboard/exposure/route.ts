import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";

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
    const { data: rows, error } = await supabase
      .from("exposure_timeline")
      .select("id, value, label, recorded_at")
      .eq("wallet_address", auth.walletAddress)
      .order("recorded_at", { ascending: true });

    if (error) {
      console.error("[API] GET /dashboard/exposure error:", error);
      return Response.json({ error: "Database error" }, { status: 500 });
    }

    const points = ((rows as any[]) ?? []).map((r) => ({
      date: r.label,
      value: Number(r.value),
      recordedAt: r.recorded_at,
    }));

    const startVal = points.length > 0 ? points[0].value : 0;
    const currentVal = points.length > 0 ? points[points.length - 1].value : 0;
    const changePct = startVal > 0 ? ((currentVal - startVal) / startVal) * 100 : 0;
    const changeFormatted = startVal > 0 ? `${changePct >= 0 ? "↑" : "↓"} ${Math.abs(changePct).toFixed(1)}%` : "0.0%";

    return Response.json({
      total: currentVal,
      formattedTotal: currentVal.toLocaleString(),
      changePct: Math.round(changePct * 10) / 10,
      changeFormatted,
      period: "last 30 days",
      points,
    });
  } catch (err) {
    console.error("[API] GET /dashboard/exposure error:", err);
    return Response.json({ error: "Internal error" }, { status: 500 });
  }
}
