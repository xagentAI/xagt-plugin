"use client";

import { getAccessToken } from "@privy-io/react-auth";

/**
 * fetch() for our own API, with the Privy access token attached.
 *
 * Every guarded route reads `Authorization: Bearer <token>`; this is the one
 * place that header is set, so no call site can forget it. The token is read
 * fresh per request rather than cached — Privy rotates it, and a stale token
 * is a 401 the user experiences as a random logout.
 */
export async function apiFetch(
  input: string,
  init: RequestInit = {}
): Promise<Response> {
  const token = await getAccessToken();

  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(input, { ...init, headers });
}

export interface SessionInfo {
  status: "employer" | "payee" | "needs-company";
  role: "EMPLOYER" | "PAYEE" | null;
  email: string | null;
  company: { id: string; name: string } | null;
  /** Has a company — what actually grants the dashboard. */
  canUseDashboard: boolean;
  /** Has been paid by someone — what actually grants /claim. */
  canUseClaim: boolean;
  /** Where to land by default. Never a restriction on the other surface. */
  destination: string;
}

/**
 * Asks the server who this identity is. The answer is derived from stored
 * records and the verified email — never from which button was clicked.
 */
export async function resolveSession(): Promise<SessionInfo | null> {
  const res = await apiFetch("/api/session");
  if (!res.ok) return null;
  return (await res.json()) as SessionInfo;
}
