import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { Prisma } from "@prisma/client";
import { prisma } from "./prisma";

/**
 * Agent API keys for POST /api/capability/pay-by-email.
 *
 * An agent cannot complete Privy's interactive email login, so the capability
 * endpoint authenticates with a service credential instead. A key resolves to
 * exactly one company; the endpoint scopes every query to it.
 */

const KEY_PREFIX = "ark_";
const KEY_BYTES = 32;

export interface GeneratedKey {
  /** Shown to the operator exactly once. Never stored. */
  raw: string;
  hashed: string;
}

export function generateApiKey(): GeneratedKey {
  const raw = KEY_PREFIX + randomBytes(KEY_BYTES).toString("hex");
  return { raw, hashed: hashApiKey(raw) };
}

/**
 * SHA-256, deliberately — see the note on ApiKey.hashedKey in schema.prisma.
 * A key is 32 bytes of CSPRNG output, so there is no low-entropy secret for a
 * slow KDF to protect; bcrypt/argon2 would add per-request latency to a
 * payments endpoint and buy nothing.
 */
export function hashApiKey(raw: string): string {
  return createHash("sha256").update(raw).digest("hex");
}

/** Extracts a bearer token without revealing which part was malformed. */
function bearerToken(request: Request): string | null {
  const header = request.headers.get("authorization") ?? "";
  const [scheme, token] = header.split(" ");
  if (!/^Bearer$/i.test(scheme ?? "") || !token) return null;
  if (!token.startsWith(KEY_PREFIX)) return null;
  return token;
}

export interface AuthenticatedKey {
  keyId: string;
  companyId: string;
  label: string;
  maxAmountUsdc: number | null;
}

/**
 * Verifies a presented key.
 *
 * FAILS CLOSED. Absent, malformed, unknown and revoked keys are all a plain
 * null here and a uniform 401 at the route — same body, no hint about whether
 * the key ever existed or which company it belonged to.
 */
export async function authenticateApiKey(
  request: Request
): Promise<AuthenticatedKey | null> {
  const token = bearerToken(request);
  if (!token) return null;

  const hashed = hashApiKey(token);

  const record = await prisma.apiKey.findUnique({
    where: { hashedKey: hashed },
    select: {
      id: true,
      companyId: true,
      label: true,
      revokedAt: true,
      hashedKey: true,
      maxAmountUsdc: true,
    },
  });

  if (!record || record.revokedAt) return null;

  // The unique lookup already matched, so this is belt-and-braces against a
  // future non-unique lookup path rather than a hash collision.
  const a = Buffer.from(record.hashedKey, "hex");
  const b = Buffer.from(hashed, "hex");
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;

  return {
    keyId: record.id,
    companyId: record.companyId,
    label: record.label,
    maxAmountUsdc: record.maxAmountUsdc ? record.maxAmountUsdc.toNumber() : null,
  };
}

export interface RateLimitResult {
  allowed: boolean;
  /** Only meaningful when not allowed. */
  retryAfterSeconds: number;
  limit: number;
}

/**
 * FIXED window, not sliding — and deliberately so. Do not "fix" this.
 *
 * A window opens on a key's first call and resets wholesale 60s later, which
 * means a caller can burst the full budget, wait for the reset, and burst it
 * again: up to 2x the nominal limit across a 61-second boundary. That is a
 * known, bounded property, not an oversight. On the public reviewer key it
 * works out to 12 calls capped at 2 USDC each, and the per-payout ceiling —
 * not the rate limiter — is what actually bounds the money at risk.
 *
 * A sliding window would cost a second table (or a timestamp array per key)
 * and a second write per call, to tighten a bound that is already fine.
 */
const WINDOW_MS = 60_000;

/**
 * Counts this call against the key's per-minute budget, and stamps lastUsedAt
 * in the same row update — one write per authenticated call, not two.
 *
 * FAILS OPEN. If the database is unreachable (a cold Neon branch is the
 * expected case) the call is allowed and the failure logged. A reviewer must
 * never get a 503 because our rate limiter could not reach Postgres; the worst
 * case is an unmetered burst, which the per-payout cap already bounds.
 */
export async function consumeRateLimit(keyId: string): Promise<RateLimitResult> {
  const now = new Date();

  try {
    const key = await prisma.apiKey.findUnique({
      where: { id: keyId },
      select: { rateLimitPerMinute: true, windowStartedAt: true, windowCount: true },
    });

    if (!key) return { allowed: true, retryAfterSeconds: 0, limit: 0 };

    const windowAge = key.windowStartedAt
      ? now.getTime() - key.windowStartedAt.getTime()
      : Number.POSITIVE_INFINITY;
    const windowExpired = windowAge >= WINDOW_MS;
    const countSoFar = windowExpired ? 0 : key.windowCount;

    if (countSoFar >= key.rateLimitPerMinute) {
      return {
        allowed: false,
        retryAfterSeconds: Math.max(1, Math.ceil((WINDOW_MS - windowAge) / 1000)),
        limit: key.rateLimitPerMinute,
      };
    }

    await prisma.apiKey.update({
      where: { id: keyId },
      data: {
        lastUsedAt: now,
        ...(windowExpired
          ? { windowStartedAt: now, windowCount: 1 }
          : { windowCount: { increment: 1 } }),
      },
    });

    return { allowed: true, retryAfterSeconds: 0, limit: key.rateLimitPerMinute };
  } catch (err) {
    console.error("[api-key] rate limit check failed — allowing the call:", err);
    return { allowed: true, retryAfterSeconds: 0, limit: 0 };
  }
}

/** Creates a key for a company. Returns the raw value for one-time display. */
export async function createApiKey(
  companyId: string,
  label: string,
  options: { rateLimitPerMinute?: number; maxAmountUsdc?: number } = {}
): Promise<{ id: string; raw: string }> {
  const { raw, hashed } = generateApiKey();
  const created = await prisma.apiKey.create({
    data: {
      companyId,
      label: label.trim() || "Untitled key",
      hashedKey: hashed,
      ...(options.rateLimitPerMinute !== undefined
        ? { rateLimitPerMinute: options.rateLimitPerMinute }
        : {}),
      ...(options.maxAmountUsdc !== undefined
        ? { maxAmountUsdc: new Prisma.Decimal(options.maxAmountUsdc) }
        : {}),
    },
    select: { id: true },
  });
  return { id: created.id, raw };
}
