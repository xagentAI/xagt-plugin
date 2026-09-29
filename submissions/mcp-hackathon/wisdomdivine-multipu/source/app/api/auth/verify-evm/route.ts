import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
import { getAddress, verifyMessage } from "ethers";
import { createAdminSupabase } from "@/lib/supabase/server";
import { authLimiter } from "@/lib/rate-limit";
import { getClientIp } from "@/lib/auth";
import { sessionOptions, SessionData } from "@/lib/session";
import { assertTrustedOrigin } from "@/lib/request-security";

interface VerifyEvmBody {
  walletAddress?: string;
  signature?: string;
  message?: string;
}

/**
 * POST /api/auth/verify-evm
 *
 * Verifies an EVM wallet signature (SIWB) and creates the same app session.
 */
export async function POST(request: Request) {
  const originError = assertTrustedOrigin(request);
  if (originError) {
    return Response.json({ error: originError }, { status: 403 });
  }

  const ip = getClientIp(request);
  if (!authLimiter.check(ip)) {
    return Response.json(
      { error: "Too many attempts. Try again later." },
      { status: 429, headers: authLimiter.headers(ip) }
    );
  }

  try {
    const body = (await request.json()) as VerifyEvmBody;
    if (!body.walletAddress || !body.signature || !body.message) {
      return Response.json(
        { error: "Missing walletAddress, message, or signature" },
        { status: 400 }
      );
    }

    const session = await getIronSession<SessionData & { evmNonce?: string }>(
      await cookies(),
      sessionOptions
    );
    const nonce = (session as SessionData & { evmNonce?: string }).evmNonce;
    if (!nonce) {
      return Response.json(
        { error: "No EVM challenge found. Request a new one." },
        { status: 400 }
      );
    }

    if (!body.message.includes(nonce)) {
      return Response.json({ error: "Invalid challenge nonce" }, { status: 401 });
    }

    const recovered = verifyMessage(body.message, body.signature);
    if (getAddress(recovered) !== getAddress(body.walletAddress)) {
      return Response.json({ error: "Invalid signature" }, { status: 401 });
    }

    let sessionVersion = 1;
    try {
      const supabase = createAdminSupabase();
      const { data: user } = await supabase
        .from("users")
        .upsert(
          { wallet_address: getAddress(body.walletAddress) },
          { onConflict: "wallet_address" }
        )
        .select("session_version")
        .single();
      if (user) sessionVersion = user.session_version ?? 1;
    } catch (dbError) {
      console.warn("[AUTH] EVM DB upsert skipped:", dbError);
    }

    session.walletAddress = getAddress(body.walletAddress);
    session.walletKind = "evm";
    session.isLoggedIn = true;
    session.v = sessionVersion;

    delete (session as SessionData & { evmNonce?: string }).evmNonce;
    await session.save();

    return Response.json({
      ok: true,
      walletAddress: session.walletAddress,
      walletKind: session.walletKind,
    });
  } catch (error) {
    console.error("[AUTH] EVM verify error:", error);
    return Response.json({ error: "Verification failed" }, { status: 500 });
  }
}
