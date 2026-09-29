import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
import { sessionOptions, SessionData, defaultSession } from "@/lib/session";
import { assertTrustedOrigin } from "@/lib/request-security";

/**
 * GET /api/auth/session
 *
 * Returns the current session data.
 * If not logged in, returns the default (empty) session.
 */
export async function GET() {
  const session = await getIronSession<SessionData>(
    await cookies(),
    sessionOptions
  );

  if (!session.isLoggedIn) {
    return Response.json(defaultSession);
  }

  return Response.json({
    walletAddress: session.walletAddress,
    walletKind: session.walletKind ?? "solana",
    isLoggedIn: session.isLoggedIn,
    v: session.v,
  });
}

/**
 * DELETE /api/auth/session
 *
 * Destroys the session (logs out).
 * The encrypted cookie is removed.
 */
export async function DELETE(request: Request) {
  const originError = assertTrustedOrigin(request);
  if (originError) {
    return Response.json({ error: originError }, { status: 403 });
  }

  const session = await getIronSession<SessionData>(
    await cookies(),
    sessionOptions
  );

  session.destroy();

  return Response.json({ ok: true });
}
