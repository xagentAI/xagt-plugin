import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
import { sessionOptions, SessionData } from "@/lib/session";
import { PublicKey } from "@solana/web3.js";
import nacl from "tweetnacl";
import bs58 from "bs58";
import { createAdminSupabase } from "@/lib/supabase/server";
import { authLimiter } from "@/lib/rate-limit";
import { getClientIp } from "@/lib/auth";
import { assertTrustedOrigin } from "@/lib/request-security";

/**
 * POST /api/auth/verify
 *
 * Verifies a wallet signature against the stored nonce.
 * If valid, creates an authenticated session (encrypted httpOnly cookie).
 *
 * Body: { walletAddress: string, signature: string }
 *
 * Flow:
 * 1. Client called GET /api/auth/challenge → got a nonce
 * 2. Client signed the nonce with their wallet
 * 3. Client sends walletAddress + signature here
 * 4. Server verifies the signature using the wallet's public key
 * 5. If valid → session created → httpOnly cookie set
 */
export async function POST(request: Request) {
  try {
    const originError = assertTrustedOrigin(request);
    if (originError) {
      return Response.json({ error: originError }, { status: 403 });
    }

    // Rate limit auth attempts
    const ip = getClientIp(request);
    if (!authLimiter.check(ip)) {
      return Response.json(
        { error: "Too many attempts. Try again later." },
        { status: 429, headers: authLimiter.headers(ip) }
      );
    }

    const { walletAddress, signature } = await request.json();

    if (!walletAddress || !signature) {
      return Response.json(
        { error: "Missing walletAddress or signature" },
        { status: 400 }
      );
    }

    // Get the session (which has the nonce stored from /challenge)
    const session = await getIronSession<SessionData & { nonce?: string }>(
      await cookies(),
      sessionOptions
    );

    const nonce = (session as SessionData & { nonce?: string }).nonce;

    if (!nonce) {
      return Response.json(
        { error: "No challenge found. Request a new one." },
        { status: 400 }
      );
    }

    // Verify the signature
    // The message that was signed is the nonce string
    const message = new TextEncoder().encode(nonce);
    const signatureBytes = bs58.decode(signature);
    const publicKeyBytes = new PublicKey(walletAddress).toBytes();

    const isValid = nacl.sign.detached.verify(
      message,
      signatureBytes,
      publicKeyBytes
    );

    if (!isValid) {
      return Response.json({ error: "Invalid signature" }, { status: 401 });
    }

    // Signature is valid — upsert user in database
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
      // Database optional — don't block auth if Supabase isn't configured
      console.warn("[AUTH] DB upsert skipped:", dbError);
    }

    // Create the authenticated session
    session.walletAddress = walletAddress;
    session.walletKind = "solana";
    session.isLoggedIn = true;
    session.v = sessionVersion;

    // Clear the nonce so it can't be reused
    delete (session as SessionData & { nonce?: string }).nonce;

    await session.save();

    return Response.json({
      ok: true,
      walletAddress,
    });
  } catch (error) {
    console.error("[AUTH] Verify error:", error);
    return Response.json({ error: "Verification failed" }, { status: 500 });
  }
}
