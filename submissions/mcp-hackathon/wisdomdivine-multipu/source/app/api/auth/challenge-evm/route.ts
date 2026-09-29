import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
import { sessionOptions, SessionData } from "@/lib/session";
import { randomBytes } from "crypto";

/**
 * GET /api/auth/challenge-evm
 *
 * Builds a SIWB-style message for EVM wallets.
 */
export async function GET(request: Request) {
  const session = await getIronSession<
    SessionData & { nonce?: string; evmNonce?: string }
  >(await cookies(), sessionOptions);

  const nonce = randomBytes(16).toString("hex");
  const url = new URL(request.url);
  const host = request.headers.get("x-forwarded-host") ?? url.host;
  // BSC only - chainId 56 (0x38)
  const chainId = 56;

  (session as SessionData & { evmNonce?: string }).evmNonce = nonce;
  await session.save();

  return Response.json({
    nonce,
    chainId,
    domain: host,
    uri: `${url.protocol}//${host}`,
    statement: "Sign in with BSC wallet to authenticate with Multipu.",
  });
}
