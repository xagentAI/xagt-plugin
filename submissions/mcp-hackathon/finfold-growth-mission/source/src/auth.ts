import { sha256Hex, timingSafeHexEqual } from "./crypto";
import type { ApiKeyRow } from "./db";
import { AppError } from "./errors";

export type Scope = "mission:create" | "mission:read" | "outcome:write";
export type AuthContext = { apiKeyId: string; label: string; scopes: Set<Scope> };

function bearerToken(request: Request): string {
  const authorization = request.headers.get("authorization");
  if (!authorization) throw new AppError("AUTH_REQUIRED", "Bearer authentication is required.", 401);
  const match = authorization.match(/^Bearer\s+([^\s]+)$/i);
  if (!match?.[1]) throw new AppError("AUTH_INVALID", "The Authorization header is invalid.", 401);
  return match[1];
}

export async function authenticate(request: Request, env: Env, requiredScope?: Scope): Promise<AuthContext> {
  const tokenHash = await sha256Hex(bearerToken(request));
  const row = await env.DB.prepare(
    "SELECT id, token_hash, label, scopes, daily_limit, expires_at FROM api_keys WHERE token_hash = ?",
  )
    .bind(tokenHash)
    .first<ApiKeyRow>();
  if (!row || !timingSafeHexEqual(row.token_hash, tokenHash)) {
    throw new AppError("AUTH_INVALID", "The review key is invalid.", 401);
  }
  if (Date.parse(row.expires_at) <= Date.now()) {
    throw new AppError("KEY_EXPIRED", "The review key has expired.", 401);
  }
  const scopes = new Set(row.scopes.split(" ").filter(Boolean) as Scope[]);
  if (requiredScope && !scopes.has(requiredScope)) {
    throw new AppError("SCOPE_DENIED", `The key does not grant ${requiredScope}.`, 403);
  }

  const day = new Date().toISOString().slice(0, 10);
  const usage = await env.DB.prepare(
    `INSERT INTO api_key_usage (api_key_id, usage_day, call_count) VALUES (?, ?, 1)
     ON CONFLICT(api_key_id, usage_day) DO UPDATE SET call_count = call_count + 1
     WHERE call_count < ?`,
  )
    .bind(row.id, day, row.daily_limit)
    .run();
  if (usage.meta.changes !== 1) {
    const resetsAt = new Date();
    resetsAt.setUTCDate(resetsAt.getUTCDate() + 1);
    resetsAt.setUTCHours(0, 0, 0, 0);
    throw new AppError("RATE_LIMITED", "The review key has reached its daily limit.", 429, {
      retryable: true,
      details: { dailyLimit: row.daily_limit, resetsAt: resetsAt.toISOString() },
    });
  }
  return { apiKeyId: row.id, label: row.label, scopes };
}

export function idempotencyKey(request: Request): string {
  const key = request.headers.get("idempotency-key")?.trim();
  if (!key) throw new AppError("IDEMPOTENCY_REQUIRED", "Idempotency-Key is required for mutations.", 400);
  if (!/^[A-Za-z0-9._:-]{8,128}$/.test(key)) {
    throw new AppError("INVALID_REQUEST", "Idempotency-Key must be 8-128 safe characters.", 400);
  }
  return key;
}
