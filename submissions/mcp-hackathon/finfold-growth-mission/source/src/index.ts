import { authenticate, idempotencyKey } from "./auth";
import { AppError } from "./errors";
import { errorResponse, jsonResponse, readJsonBody, requestIdFrom } from "./http";
import { handleMcp } from "./mcp";
import { createMissionOperation, getMissionOperation, recordOutcomeOperation, recordTrackingClick } from "./mission";
import { openApiDocument } from "./openapi";
import { createMissionSchema, outcomeSchema } from "./schemas";

const SECURITY_HEADERS = {
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
  "permissions-policy": "camera=(), microphone=(), geolocation=()",
  "referrer-policy": "no-referrer",
  "x-frame-options": "DENY",
} as const;

function withSecurityHeaders(response: Response, requestId: string): Response {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value);
  headers.set("x-request-id", requestId);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function parseSchema<T>(result: { success: true; data: T } | { success: false; error: { issues: Array<{ path: PropertyKey[]; message: string }> } }): T {
  if (result.success) return result.data;
  throw new AppError("INVALID_REQUEST", "Request validation failed.", 400, {
    details: { issues: result.error.issues.map((issue) => ({ path: issue.path.join("."), message: issue.message })) },
  });
}

function isMissionId(value: string): boolean {
  return /^gm_[a-z0-9]{24}$/.test(value);
}

async function routeRequest(request: Request, env: Env, requestId: string): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (request.method === "GET" && path === "/health") {
    return jsonResponse({ status: "ok", commit: env.COMMIT_SHA });
  }
  if (request.method === "GET" && path === "/.well-known/xagent-verification.json") {
    return jsonResponse({ schemaVersion: 1, slug: "finfold-growth-mission", commit: env.COMMIT_SHA });
  }
  if (request.method === "GET" && path === "/openapi.json") {
    return jsonResponse(openApiDocument(env.APP_BASE_URL), 200, { "cache-control": "public, max-age=300" });
  }
  if (request.method === "GET" && path === "/v1/capability") {
    return jsonResponse({
      slug: "finfold-growth-mission",
      version: "1.0.0",
      unit: "one validated mission",
      input: "one public business URL plus one growth objective",
      output: "one evidence-bound mission, one content asset, one tracked CTA",
      supportedPlatforms: ["auto", "linkedin", "x", "reddit", "xiaohongshu", "wechat"],
      pricingBoundary: {
        model: "fixed_per_validated_mission",
        amount: "0.25",
        currency: "USD",
        settlement: "disabled_during_hackathon_review",
        x402: false,
      },
      retentionDays: 30,
      sideEffects: { autoPublish: false, externalAccountMutation: false },
    });
  }
  if (request.method === "GET" && path === "/") {
    return jsonResponse({
      name: "Finfold Growth Mission API",
      proposition: "One URL. One evidence-bound growth move. One measurable outcome loop.",
      mcp: `${env.APP_BASE_URL}/mcp`,
      openapi: `${env.APP_BASE_URL}/openapi.json`,
      support: env.SUPPORT_EMAIL,
      safety: { autoPublish: false, externalAccountMutation: false, sourcePolicy: "public HTML only" },
    });
  }

  const trackingMatch = path.match(/^\/r\/([a-z0-9]{36})$/);
  if (request.method === "GET" && trackingMatch?.[1]) {
    const destination = await recordTrackingClick(env, trackingMatch[1]);
    return new Response(null, {
      status: 302,
      headers: { location: destination, "cache-control": "no-store", "referrer-policy": "no-referrer" },
    });
  }

  if (path === "/v1/usage") {
    if (request.method !== "GET") throw new AppError("METHOD_NOT_ALLOWED", "This endpoint accepts GET only.", 405);
    const auth = await authenticate(request, env, "mission:read");
    const day = new Date().toISOString().slice(0, 10);
    const usage = await env.DB.prepare(
      `SELECT u.call_count, k.daily_limit, k.expires_at
       FROM api_keys k LEFT JOIN api_key_usage u ON u.api_key_id = k.id AND u.usage_day = ?
       WHERE k.id = ?`,
    )
      .bind(day, auth.apiKeyId)
      .first<{ call_count: number | null; daily_limit: number; expires_at: string }>();
    return jsonResponse({
      day,
      calls: Number(usage?.call_count ?? 0),
      dailyLimit: Number(usage?.daily_limit ?? 0),
      keyExpiresAt: usage?.expires_at,
      billableMissions: 0,
      billingEnabled: false,
    });
  }

  if (path === "/mcp") {
    if (request.method !== "POST") throw new AppError("METHOD_NOT_ALLOWED", "MCP accepts POST only.", 405);
    const body = await readJsonBody(request, 64_000);
    return handleMcp(request, env, body, requestId);
  }

  if (path === "/v1/missions") {
    if (request.method !== "POST") throw new AppError("METHOD_NOT_ALLOWED", "This endpoint accepts POST only.", 405);
    const auth = await authenticate(request, env, "mission:create");
    const key = idempotencyKey(request);
    const input = parseSchema(createMissionSchema.safeParse(await readJsonBody(request)));
    const result = await createMissionOperation(env, auth, input, key, requestId);
    return new Response(result.body, {
      status: result.status,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "idempotent-replayed": String(result.replayed),
      },
    });
  }

  const missionMatch = path.match(/^\/v1\/missions\/([^/]+)$/);
  if (missionMatch?.[1]) {
    if (request.method !== "GET") throw new AppError("METHOD_NOT_ALLOWED", "This endpoint accepts GET only.", 405);
    if (!isMissionId(missionMatch[1])) throw new AppError("INVALID_REQUEST", "Invalid mission ID.", 400);
    const auth = await authenticate(request, env, "mission:read");
    return jsonResponse(await getMissionOperation(env, auth, missionMatch[1]));
  }

  const outcomeMatch = path.match(/^\/v1\/missions\/([^/]+)\/outcomes$/);
  if (outcomeMatch?.[1]) {
    if (request.method !== "POST") throw new AppError("METHOD_NOT_ALLOWED", "This endpoint accepts POST only.", 405);
    if (!isMissionId(outcomeMatch[1])) throw new AppError("INVALID_REQUEST", "Invalid mission ID.", 400);
    const auth = await authenticate(request, env, "outcome:write");
    const key = idempotencyKey(request);
    const input = parseSchema(outcomeSchema.safeParse(await readJsonBody(request)));
    const result = await recordOutcomeOperation(env, auth, outcomeMatch[1], input, key);
    return new Response(result.body, {
      status: result.status,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
        "idempotent-replayed": String(result.replayed),
      },
    });
  }

  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: { allow: "GET, POST, OPTIONS" } });
  }
  throw new AppError("MISSION_NOT_FOUND", "Route not found.", 404);
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const started = Date.now();
    const requestId = requestIdFrom(request);
    let response: Response;
    try {
      response = await routeRequest(request, env, requestId);
    } catch (error) {
      response = errorResponse(error, requestId);
    }
    const secured = withSecurityHeaders(response, requestId);
    console.log(
      JSON.stringify({
        event: "request_complete",
        requestId,
        method: request.method,
        route: new URL(request.url).pathname,
        status: secured.status,
        durationMs: Date.now() - started,
      }),
    );
    return secured;
  },

  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const now = new Date().toISOString();
    ctx.waitUntil(
      env.DB.batch([
        env.DB.prepare("DELETE FROM idempotency_records WHERE expires_at <= ?").bind(now),
        env.DB.prepare("DELETE FROM missions WHERE expires_at <= ?").bind(now),
        env.DB.prepare("DELETE FROM api_key_usage WHERE usage_day < date('now', '-35 days')"),
      ]).then(() => {
        console.log(JSON.stringify({ event: "retention_cleanup", status: "complete" }));
      }),
    );
  },
} satisfies ExportedHandler<Env>;
