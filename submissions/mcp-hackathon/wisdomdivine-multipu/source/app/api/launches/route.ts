import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import { createLaunchSchema, confirmLaunchSchema } from "@/lib/validations";
import { assertTrustedOrigin } from "@/lib/request-security";
import { getEvmLaunchPolicyError, getLaunchPolicyError } from "@/lib/runtime-config.server";
import { verifyLaunchConfirmationOnChain } from "@/lib/solana/server";
import { getEnvironmentScope } from "@/lib/env-scope.server";
import { getLaunchControls } from "@/lib/launch-controls";
import { isEvmLaunchpad, isSolanaLaunchpad, getLaunchpadChainNetwork } from "@/lib/launchpad-network";
import { verifyEvmLaunchTransaction } from "@/lib/evm/server";

/**
 * GET /api/launches — List the current user's launches.
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
    const scope = getEnvironmentScope();
    const { data: launches, error } = await supabase
      .from("launches")
      .select("*, tokens(name, symbol, mint_address, image_url)")
      .eq("wallet_address", auth.walletAddress)
      .eq("app_phase", scope.appPhase)
      .order("created_at", { ascending: false });

    if (error) throw error;
    return Response.json({ launches: launches ?? [] });
  } catch (err) {
    console.error("[API] GET /launches error:", err);
    return Response.json({ error: "Failed to fetch launches" }, { status: 500 });
  }
}

/**
 * POST /api/launches — Create a launch record (before on-chain deployment).
 *
 * Body: { tokenId, launchpad, initialLiquidity? }
 * Returns: { launch } with status: pending.
 */
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
    const parsed = createLaunchSchema.safeParse(body);
    const walletKind = String(auth.walletKind ?? "solana");

    if (!parsed.success) {
      return Response.json(
        { error: "Validation failed", details: parsed.error.flatten() },
        { status: 400 }
      );
    }

    if (isSolanaLaunchpad(parsed.data.launchpad) && walletKind !== "solana") {
      return Response.json(
        { error: "Solana launchpads require a Solana-authenticated wallet." },
        { status: 400 }
      );
    }

    if (isEvmLaunchpad(parsed.data.launchpad) && walletKind !== "evm") {
      return Response.json(
        { error: "EVM launchpads require an EVM-authenticated wallet (SIWB)." },
        { status: 400 }
      );
    }

    if (isSolanaLaunchpad(parsed.data.launchpad)) {
      const launchPolicyError = getLaunchPolicyError();
      if (launchPolicyError) {
        return Response.json({ error: launchPolicyError }, { status: 403 });
      }
    } else {
      const evmPolicyError = getEvmLaunchPolicyError();
      if (evmPolicyError) {
        return Response.json({ error: evmPolicyError }, { status: 403 });
      }
    }

    const supabase = createAdminSupabase();
    const scope = getEnvironmentScope();
    const controls = await getLaunchControls();
    const launchNetwork =
      getLaunchpadChainNetwork(parsed.data.launchpad) ?? scope.network;

    if (controls.launchesPaused) {
      return Response.json(
        { error: "Launches are currently paused by admin policy" },
        { status: 403 }
      );
    }

    if (!controls.launchpadsEnabled[parsed.data.launchpad]) {
      return Response.json(
        { error: `Launchpad ${parsed.data.launchpad} is currently disabled` },
        { status: 403 }
      );
    }

    if (
      controls.allowlistMode &&
      !controls.allowedWallets.includes(auth.walletAddress)
    ) {
      return Response.json(
        { error: "Wallet is not allowlisted for launches in current phase" },
        { status: 403 }
      );
    }

    // Verify the token belongs to this user and is minted
    const { data: token } = await supabase
      .from("tokens")
      .select("id, user_id, status, network, app_phase")
      .eq("id", parsed.data.tokenId)
      .eq("wallet_address", auth.walletAddress)
      .eq("app_phase", scope.appPhase)
      .single();

    if (!token) {
      return Response.json({ error: "Token not found" }, { status: 404 });
    }

    if (token.status !== "active") {
      return Response.json(
        { error: "Token must be minted before launching" },
        { status: 400 }
      );
    }

    // Check for duplicate launch
    const { data: existing } = await supabase
      .from("launches")
      .select("id")
      .eq("token_id", parsed.data.tokenId)
      .eq("launchpad", parsed.data.launchpad)
      .eq("app_phase", scope.appPhase)
      .single();

    if (existing) {
      return Response.json(
        { error: "Token already launched on this launchpad" },
        { status: 409 }
      );
    }

    const { data: launch, error } = await supabase
      .from("launches")
      .insert({
        token_id: parsed.data.tokenId,
        user_id: token.user_id,
        wallet_address: auth.walletAddress,
        launchpad: parsed.data.launchpad,
        initial_liquidity: parsed.data.initialLiquidity || null,
        network: launchNetwork,
        app_phase: scope.appPhase,
        status: "pending",
      })
      .select()
      .single();

    if (error) throw error;
    return Response.json({ launch }, { status: 201 });
  } catch (err) {
    console.error("[API] POST /launches error:", err);
    return Response.json({ error: "Failed to create launch" }, { status: 500 });
  }
}

/**
 * PATCH /api/launches — Confirm an on-chain launch.
 *
 * Body: { launchId, poolAddress, launchTx, initialLiquidity? }
 */
export async function PATCH(request: Request) {
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
    const normalizedBody = {
      launchId: body.launchId || body.id,
      poolAddress: body.poolAddress,
      launchTx: body.launchTx || body.txSignature,
      initialLiquidity: body.initialLiquidity,
    };
    const parsed = confirmLaunchSchema.safeParse(normalizedBody);
    const walletKind = String(auth.walletKind ?? "solana");

    if (!parsed.success) {
      return Response.json(
        { error: "Validation failed", details: parsed.error.flatten() },
        { status: 400 }
      );
    }

    const supabase = createAdminSupabase();
    const scope = getEnvironmentScope();

    // Verify ownership
    const { data: launch } = await supabase
      .from("launches")
      .select("id, launchpad, network")
      .eq("id", parsed.data.launchId)
      .eq("wallet_address", auth.walletAddress)
      .eq("app_phase", scope.appPhase)
      .single();

    if (!launch) {
      return Response.json({ error: "Launch not found" }, { status: 404 });
    }

    if (isSolanaLaunchpad(launch.launchpad) && walletKind !== "solana") {
      return Response.json(
        { error: "Solana launch confirmations require a Solana-authenticated wallet." },
        { status: 400 }
      );
    }
    if (isEvmLaunchpad(launch.launchpad) && walletKind !== "evm") {
      return Response.json(
        { error: "EVM launch confirmations require an EVM-authenticated wallet." },
        { status: 400 }
      );
    }

    if (isSolanaLaunchpad(launch.launchpad)) {
      const launchPolicyError = getLaunchPolicyError();
      if (launchPolicyError) {
        return Response.json({ error: launchPolicyError }, { status: 403 });
      }
      await verifyLaunchConfirmationOnChain({
        walletAddress: auth.walletAddress,
        signature: parsed.data.launchTx,
      });
    } else {
      const evmPolicyError = getEvmLaunchPolicyError();
      if (evmPolicyError) {
        return Response.json({ error: evmPolicyError }, { status: 403 });
      }
      const evmNetwork = getLaunchpadChainNetwork(launch.launchpad);
      if (!evmNetwork) {
        return Response.json(
          { error: "Unable to determine EVM network for launchpad." },
          { status: 400 }
        );
      }
      await verifyEvmLaunchTransaction({
        network: evmNetwork,
        walletAddress: auth.walletAddress,
        txHash: parsed.data.launchTx,
      });
    }

    const { data: updated, error } = await supabase
      .from("launches")
      .update({
        pool_address: parsed.data.poolAddress,
        launch_tx: parsed.data.launchTx,
        initial_liquidity: parsed.data.initialLiquidity || null,
        status: "live",
        launched_at: new Date().toISOString(),
      })
      .eq("id", parsed.data.launchId)
      .select()
      .single();

    if (error) throw error;
    return Response.json({ launch: updated });
  } catch (err) {
    console.error("[API] PATCH /launches error:", err);
    return Response.json({ error: "Failed to confirm launch" }, { status: 500 });
  }
}

export const PUT = PATCH;
