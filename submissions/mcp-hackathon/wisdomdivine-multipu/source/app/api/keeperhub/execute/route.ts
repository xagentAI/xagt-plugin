import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { assertTrustedOrigin } from "@/lib/request-security";
import { dryRunWorkflow, executeKeeperHubWorkflow } from "@/lib/keeperhub/client";
import { z } from "zod";

const executeSchema = z.object({
  chain: z.enum(["solana", "bsc", "robinhood"]),
  action: z.enum(["token_launch", "bonding_curve_swap", "liquidity_deposit"]),
  amount: z.number().positive(),
  data: z.record(z.unknown()).optional(),
  dryRun: z.boolean().default(false),
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
    const parsed = executeSchema.safeParse(body);

    if (!parsed.success) {
      return Response.json(
        { error: "Validation failed", details: parsed.error.flatten() },
        { status: 400 }
      );
    }

    const { chain, action, amount, data, dryRun } = parsed.data;

    if (dryRun) {
      const simulation = await dryRunWorkflow({
        chain,
        action,
        sender: auth.walletAddress,
        amount,
        data,
      });

      return Response.json({
        success: true,
        simulation,
        engine: "KeeperHub Deterministic Simulation",
      });
    }

    const result = await executeKeeperHubWorkflow({
      chain,
      action,
      sender: auth.walletAddress,
      amount,
      data,
    });

    if (result.status === "failed") {
      return Response.json(
        {
          success: false,
          error: result.error || "Workflow execution failed",
          result,
        },
        { status: 502 }
      );
    }

    return Response.json({
      success: result.status === "confirmed",
      result,
      engine: "KeeperHub Execution Layer",
    });
  } catch (err: any) {
    console.error("[API] POST /api/keeperhub/execute error:", err);
    return Response.json(
      { error: err.message || "Execution failed through KeeperHub" },
      { status: 500 }
    );
  }
}
