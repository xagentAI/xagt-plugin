import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
import { sessionOptions, SessionData, defaultSession } from "./session";

import { createAdminSupabase } from "@/lib/supabase/server";

/**
 * Server-side auth helper.
 *
 * Usage in API routes:
 *   const auth = await getAuth(request);
 *   if (!auth.isLoggedIn) return Response.json({ error: "Unauthorized" }, { status: 401 });
 *   // auth.walletAddress is now safe to use
 */
export async function getAuth(request?: Request): Promise<SessionData> {
  // 1. Try checking for an API key in the headers first (if request is passed)
  if (request) {
    const apiKey = request.headers.get("x-api-key");
    if (apiKey) {
      try {
        const supabase = createAdminSupabase();
        const { data, error } = await supabase
          .from("developer_api_keys")
          .select("wallet_address, user_id, users(session_version)")
          .eq("api_key", apiKey)
          .eq("revoked", false)
          .single();

        if (data && !error) {
          const isEvm = data.wallet_address.startsWith("0x");
          return {
            walletAddress: data.wallet_address,
            walletKind: isEvm ? "evm" : "solana",
            isLoggedIn: true,
            v: (data.users as any)?.session_version ?? 1,
          };
        }
      } catch (err) {
        console.error("[AUTH] API key verification failed:", err);
      }
    }
  }

  // 2. Fall back to standard session cookie check
  try {
    const session = await getIronSession<SessionData>(
      await cookies(),
      sessionOptions
    );
    if (!session.isLoggedIn || !session.walletAddress) {
      return defaultSession;
    }
    return {
      walletAddress: session.walletAddress,
      walletKind: session.walletKind ?? "solana",
      isLoggedIn: session.isLoggedIn,
      v: session.v,
    };
  } catch {
    return defaultSession;
  }
}

/**
 * Helper to extract client IP from request headers.
 * Works on Vercel, Cloudflare, and direct connections.
 */
export function getClientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  const real = request.headers.get("x-real-ip");
  if (real) return real;
  return "unknown";
}
