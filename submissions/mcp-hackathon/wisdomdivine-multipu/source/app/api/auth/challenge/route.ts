import { cookies } from "next/headers";
import { getIronSession } from "iron-session";
import { sessionOptions, SessionData } from "@/lib/session";
import { randomBytes } from "crypto";

/**
 * GET /api/auth/challenge
 *
 * Generates a unique nonce (challenge) for the wallet to sign.
 * Stored in the session cookie so we can verify it later.
 * This prevents replay attacks — each sign-in requires a fresh nonce.
 */
export async function GET() {
  const session = await getIronSession<SessionData & { nonce?: string }>(
    await cookies(),
    sessionOptions
  );

  // Generate a random nonce
  const nonce = randomBytes(32).toString("hex");

  // Store it in the session so we can verify later
  (session as SessionData & { nonce?: string }).nonce = nonce;
  await session.save();

  return Response.json({ nonce });
}
