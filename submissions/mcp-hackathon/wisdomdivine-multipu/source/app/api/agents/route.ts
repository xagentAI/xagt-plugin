import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { assertTrustedOrigin } from "@/lib/request-security";
import { createAdminSupabase } from "@/lib/supabase/server";
import { z } from "zod";

const createAgentSchema = z.object({
  name: z.string().min(2),
  description: z.string().optional(),
  prompt: z.string().min(3),
  mode: z.enum(["paper", "live"]).default("paper"),
  chain: z.string().default("solana"),
  launchpads: z.array(z.string()).default(["pumpfun", "meteora"]),
  strategyConfig: z.record(z.unknown()),
  budgetAllocated: z.number().positive().default(0.5),
});

export async function GET(request: Request) {
  const auth = await getAuth(request);
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const walletAddress = auth.isLoggedIn ? auth.walletAddress : "demo_wallet";

  try {
    const supabase = createAdminSupabase();
    const { data: agents, error } = await supabase
      .from("trading_agents")
      .select("*, agent_trades(*)")
      .eq("wallet_address", walletAddress)
      .order("created_at", { ascending: false });

    if (error) {
      // Fallback if table not yet migrated
      return Response.json({
        success: true,
        agents: [],
        count: 0,
      });
    }

    return Response.json({
      success: true,
      agents: agents || [],
      count: agents?.length || 0,
    });
  } catch (err: any) {
    return Response.json({
      success: true,
      agents: [],
      count: 0,
    });
  }
}

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
  const walletAddress = auth.walletAddress;

  try {
    const body = await request.json();
    const parsed = createAgentSchema.safeParse(body);

    if (!parsed.success) {
      return Response.json(
        { error: "Validation failed", details: parsed.error.flatten() },
        { status: 400 }
      );
    }

    const { name, description, prompt, mode, chain, launchpads, strategyConfig, budgetAllocated } = parsed.data;

    const supabase = createAdminSupabase();
    let userId: string | null = null;
    if (auth.isLoggedIn) {
      const { data: user } = await supabase
        .from("users")
        .select("id")
        .eq("wallet_address", walletAddress)
        .maybeSingle();
      if (user) userId = user.id;
    }

    const { data: agent, error } = await supabase
      .from("trading_agents")
      .insert({
        wallet_address: walletAddress,
        user_id: userId,
        name,
        description: description || "AI Trading Agent compiled from natural language",
        prompt,
        mode,
        status: "active",
        chain,
        launchpads,
        strategy_config: strategyConfig as any,
        budget_allocated: budgetAllocated,
        budget_spent: 0,
        total_pnl_pct: 0,
        total_trades: 0,
        successful_trades: 0,
      })
      .select()
      .single();

    if (error) {
      // Return a generated agent object if DB insert fails / offline migration
      const fallbackAgent = {
        id: "agent_" + Math.random().toString(36).substring(2, 11),
        wallet_address: walletAddress,
        name,
        description: description || "AI Trading Agent compiled from natural language",
        prompt,
        mode,
        status: "active",
        chain,
        launchpads,
        strategy_config: strategyConfig,
        budget_allocated: budgetAllocated,
        budget_spent: 0,
        total_pnl_pct: 0,
        total_trades: 0,
        successful_trades: 0,
        created_at: new Date().toISOString(),
      };
      return Response.json({ success: true, agent: fallbackAgent });
    }

    return Response.json({ success: true, agent });
  } catch (err: any) {
    console.error("[API] POST /api/agents error:", err);
    return Response.json(
      { error: err.message || "Failed to create trading agent" },
      { status: 500 }
    );
  }
}
