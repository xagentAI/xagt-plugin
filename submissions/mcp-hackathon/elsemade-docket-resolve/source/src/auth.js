import { timingSafeEqual } from "node:crypto";

export class AuthError extends Error {
  constructor(code, message, status = 401) {
    super(message);
    this.name = "AuthError";
    this.code = code;
    this.status = status;
  }
}

function normalizeProfile(profile, token) {
  if (!profile || typeof profile !== "object") return null;
  if (typeof profile.tenantId !== "string" || !profile.tenantId.trim()) return null;
  const subject = typeof profile.subject === "string" && profile.subject.trim()
    ? profile.subject
    : "agent";
  const scopes = Array.isArray(profile.scopes) && profile.scopes.length > 0
    ? profile.scopes.filter((scope) => typeof scope === "string")
    : ["*"];
  return { tenantId: profile.tenantId, subject, scopes, tokenId: profile.tokenId ?? token.slice(0, 8) };
}

function parseTokenProfiles(raw) {
  if (!raw) return new Map();
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("DOCKET_AUTH_TOKENS must be valid JSON.");
  }

  const entries = Array.isArray(parsed)
    ? parsed
        .filter((item) => item && typeof item.token === "string")
        .map((item) => [item.token, item])
    : Object.entries(parsed ?? {});
  const tokens = new Map();
  for (const [token, profile] of entries) {
    if (typeof token !== "string" || token.length < 12) {
      throw new Error("Configured auth tokens must be at least 12 characters.");
    }
    const normalized = normalizeProfile(profile, token);
    if (!normalized) throw new Error("Each auth token needs a tenantId.");
    tokens.set(token, normalized);
  }
  return tokens;
}

export function createAuthConfig(environment = process.env) {
  const mode = environment.DOCKET_AUTH_MODE;
  if (mode && mode !== "off" && mode !== "required") {
    throw new Error("DOCKET_AUTH_MODE must be either off or required.");
  }
  const tokens = parseTokenProfiles(environment.DOCKET_AUTH_TOKENS);
  const legacyToken = environment.DOCKET_AUTH_TOKEN;
  if (legacyToken) {
    if (legacyToken.length < 12) {
      throw new Error("DOCKET_AUTH_TOKEN must be at least 12 characters.");
    }
    tokens.set(legacyToken, normalizeProfile({
      tenantId: environment.DOCKET_AUTH_TENANT ?? "tenant-local",
      subject: environment.DOCKET_AUTH_SUBJECT ?? "local-agent",
      scopes: ["*"],
    }, legacyToken));
  }
  const explicitlyPublic = environment.DOCKET_AUTH_MODE === "off";
  const required = !explicitlyPublic && (environment.DOCKET_AUTH_MODE === "required" || environment.NODE_ENV === "production");
  if (required && tokens.size === 0) {
    throw new Error("Authenticated production mode requires at least one configured bearer token.");
  }
  return {
    required,
    tokens,
  };
}

function constantTimeEqual(left, right) {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  if (leftBytes.length !== rightBytes.length) return false;
  return timingSafeEqual(leftBytes, rightBytes);
}

function findProfile(token, tokens) {
  for (const [configuredToken, profile] of tokens.entries()) {
    if (constantTimeEqual(token, configuredToken)) return profile;
  }
  return null;
}

export function authenticate(request, config = { required: false, tokens: new Map() }) {
  const header = request.headers?.authorization ?? request.headers?.Authorization;
  if (!header) {
    if (!config.required) {
      return { tenantId: "public", subject: "anonymous", scopes: ["*"], authenticated: false };
    }
    throw new AuthError("AUTH_REQUIRED", "Bearer authentication is required.");
  }
  const match = /^Bearer\s+(.+)$/i.exec(header);
  if (!match) throw new AuthError("AUTH_INVALID", "Use an Authorization: Bearer token.");
  const profile = findProfile(match[1], config.tokens);
  if (!profile) throw new AuthError("AUTH_INVALID", "The bearer token is invalid.");
  return { ...profile, authenticated: true };
}

export function requireScope(identity, scope) {
  if (identity.scopes.includes("*") || identity.scopes.includes(scope)) return;
  throw new AuthError("AUTH_FORBIDDEN", `The token lacks the ${scope} scope.`, 403);
}
