import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
import { sessionOptions, SessionData } from "@/lib/session";
import { createAdminSupabase } from "@/lib/supabase/server";
import { assertTrustedOrigin } from "@/lib/request-security";

/**
 * POST /api/auth/demo
 *
 * Authenticates a mock user wallet for testing.
 * Bypasses cryptographic verification to set a secure iron-session cookie.
 *
 * Body: { walletAddress: string }
 */
export async function POST(request: Request) {
  try {
    const originError = assertTrustedOrigin(request);
    if (originError) {
      return Response.json({ error: originError }, { status: 403 });
    }

    if (process.env.NODE_ENV === "production" && process.env.ALLOW_DEMO_AUTH !== "true") {
      return Response.json(
        { error: "Demo authentication is disabled in production environments" },
        { status: 403 }
      );
    }

    const { walletAddress } = await request.json();

    if (!walletAddress) {
      return Response.json({ error: "Missing walletAddress" }, { status: 400 });
    }

    // Upsert demo user in database
    let sessionVersion = 1;
    try {
      const supabase = createAdminSupabase();
      const { data: user } = await supabase
        .from("users")
        .upsert(
          { wallet_address: walletAddress },
          { onConflict: "wallet_address" }
        )
        .select("session_version")
        .single();
      if (user) sessionVersion = user.session_version ?? 1;
    } catch (dbError) {
      console.warn("[AUTH] Supabase DB upsert skipped for demo wallet:", dbError);
    }

    // Create session
    const session = await getIronSession<SessionData>(
      await cookies(),
      sessionOptions
    );

    session.walletAddress = walletAddress;
    session.walletKind = walletAddress.startsWith("0x") ? "evm" : "solana";
    session.isLoggedIn = true;
    session.v = sessionVersion;

    await session.save();

    return Response.json({
      ok: true,
      walletAddress,
    });
  } catch (error) {
    console.error("[AUTH] Demo sign-in error:", error);
    return Response.json({ error: "Demo sign-in failed" }, { status: 500 });
  }
}
