import { SessionOptions } from "iron-session";

/**
 * Session data shape — what we store in the encrypted cookie.
 * Contains wallet address and a version counter for revocation.
 */
export interface SessionData {
  walletAddress: string;
  walletKind: "solana" | "evm";
  v: number; // token version — increment in DB to revoke all sessions
  isLoggedIn: boolean;
}

/**
 * Iron-session configuration.
 * The cookie is encrypted + signed, httpOnly, secure, SameSite=Lax.
 * No JS can read it. No DB needed per request. Revocable via version counter.
 */
function getSessionSecret(): string {
  const secret = process.env.SESSION_SECRET;
  if (!secret) {
    if (process.env.NODE_ENV === "production") {
      throw new Error("CRITICAL: SESSION_SECRET is not configured in production environment.");
    }
    return "dev_mode_only_session_secret_min_32_characters_long";
  }
  return secret;
}

export const sessionOptions: SessionOptions = {
  password: getSessionSecret(),
  cookieName: "multipu_session",
  cookieOptions: {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    maxAge: 60 * 60 * 24 * 7, // 7 days
    path: "/",
  },
};

/**
 * Default (empty) session — used when no session exists.
 */
export const defaultSession: SessionData = {
  walletAddress: "",
  walletKind: "solana",
  v: 0,
  isLoggedIn: false,
};
