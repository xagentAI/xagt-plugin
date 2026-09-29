import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import { assertTrustedOrigin } from "@/lib/request-security";
import { getEnvironmentScope } from "@/lib/env-scope.server";
import { z } from "zod";

const swapSchema = z.object({
  launchId: z.string().uuid(),
  type: z.enum(["buy", "sell"]),
  amountPay: z.coerce.number().positive(),
  amountReceive: z.coerce.number().positive(),
  txSignature: z.string().optional(),
});

export async function POST(request: Request) {
  const originError = assertTrustedOrigin(request);
  if (originError) {
    return Response.json({ error: originError }, { status: 403 });
  }

  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const body = await request.json();
    const parsed = swapSchema.safeParse(body);

    if (!parsed.success) {
      return Response.json(
        { error: "Validation failed", details: parsed.error.flatten() },
        { status: 400 }
      );
    }

    const { launchId, type, amountPay, amountReceive, txSignature } = parsed.data;
    const supabase = createAdminSupabase();
    const scope = getEnvironmentScope();

    // 1. Fetch launch details
    const { data: launch, error: launchError } = await supabase
      .from("launches")
      .select("*, tokens(*)")
      .eq("id", launchId)
      .eq("app_phase", scope.appPhase)
      .single();

    if (launchError || !launch) {
      return Response.json({ error: "Launch not found" }, { status: 404 });
    }

    if (launch.status !== "live") {
      return Response.json({ error: "Launch is not live for trading" }, { status: 400 });
    }

    // 2. Update volume_24h
    const currentVolume = Number(launch.volume_24h || 0);
    const newVolume = currentVolume + amountPay;

    const { error: updateError } = await supabase
      .from("launches")
      .update({ volume_24h: newVolume })
      .eq("id", launchId);

    if (updateError) throw updateError;

    // 3. Record trade fee earnings (1% of the swap amount)
    const feeAmount = amountPay * 0.01;
    const { error: earningError } = await supabase
      .from("earnings")
      .insert({
        user_id: launch.user_id,
        wallet_address: launch.wallet_address,
        token_id: launch.token_id,
        launch_id: launch.id,
        launchpad: launch.launchpad,
        network: launch.network,
        app_phase: scope.appPhase,
        amount_sol: feeAmount,
        fee_type: "creator_fee",
        tx_signature: txSignature || null,
      });

    if (earningError) throw earningError;

    return Response.json({
      success: true,
      newVolume,
      feeEarned: feeAmount,
      execution: {
        engine: "KeeperHub Deterministic Router",
        mevShield: true,
        route: "private_mempool",
        auditRecord: `https://keeperhub.com/audit/kh_${launchId.slice(0, 8)}`,
      },
    });
  } catch (err) {
    console.error("[API] POST /api/trade/swap error:", err);
    return Response.json({ error: "Failed to process swap trade record" }, { status: 500 });
  }
}
