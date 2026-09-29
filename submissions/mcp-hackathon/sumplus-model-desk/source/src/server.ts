import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { ensureCatalogue, type Offer, type Snapshot } from "./catalogue.js";
import { MAX_TOKENS } from "./plan.js";
import { usd } from "./pricing.js";
import {
  runCatalogue,
  runCatalogueDiff,
  runPlanCall,
  runQuote,
  runResolve,
} from "./operations.js";
import { handleMcpPayload, PARSE_ERROR_RESPONSE } from "./mcp.js";
import { TOOLS } from "./tools.js";

const HERE = dirname(fileURLToPath(import.meta.url));
export const SLUG = "sumplus-model-desk";

/**
 * The commit this build was cut from. It is injected at deploy time and
 * reported by /health and the verification document, which is how a reviewer
 * ties a running service to a line of source.
 */
const COMMIT = (process.env.REVIEW_COMMIT ?? "").trim();

/** The catalogue as it stood when this build was submitted. */
const SUBMITTED: Snapshot = JSON.parse(
  readFileSync(join(HERE, "..", "snapshots", "catalogue.json"), "utf8"),
) as Snapshot;

const RATE_LIMIT = Number(process.env.RATE_LIMIT ?? 60);
const hits = new Map<string, { count: number; resetAt: number }>();

function rateLimited(ip: string): { limited: boolean; remaining: number; resetAt: number } {
  const now = Date.now();
  const entry = hits.get(ip);
  if (!entry || entry.resetAt <= now) {
    const fresh = { count: 1, resetAt: now + 60_000 };
    hits.set(ip, fresh);
    if (hits.size > 5000) for (const [k, v] of hits) if (v.resetAt <= now) hits.delete(k);
    return { limited: false, remaining: RATE_LIMIT - 1, resetAt: fresh.resetAt };
  }
  entry.count += 1;
  return {
    limited: entry.count > RATE_LIMIT,
    remaining: Math.max(0, RATE_LIMIT - entry.count),
    resetAt: entry.resetAt,
  };
}

function send(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  const text = JSON.stringify(body, null, 2);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "access-control-allow-origin": "*",
    ...headers,
  });
  res.end(text);
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > 64_000) throw new Error("request body is too large");
    chunks.push(chunk as Buffer);
  }
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  if (!raw) return {};
  return JSON.parse(raw);
}

const INDEX = {
  service: "Sumplus Model Desk",
  what:
    "Prices one job against every offer in a live model catalogue, and says which offers can actually take it.",
  why:
    "A model id is not a price. The same id is sold on several lines at different prices, and an offer whose context or output ceiling is too small does not refuse the job, it truncates the answer and bills for it.",
  endpoints: [
    "GET  /health",
    "GET  /.well-known/xagent-verification.json",
    "GET  /v1/tools.json",
    "POST /v1/plan_call",
    "POST /v1/quote",
    "GET  /v1/resolve?modelId=gpt-5.5",
    "GET  /v1/catalogue",
    "GET  /v1/catalogue/diff",
    "POST /mcp",
  ],
  sideEffects: "None. Every endpoint is read-only, needs no credentials, and costs the caller nothing.",
  scope:
    "Procurement and pricing for model calls. It does not inspect wallets, transactions, contracts, or security posture.",
};

export async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const ip = (req.headers["x-forwarded-for"] as string)?.split(",")[0]?.trim() || req.socket.remoteAddress || "unknown";

  if (req.method === "OPTIONS") {
    return send(res, 204, null, { "access-control-allow-methods": "GET,POST,OPTIONS", "access-control-allow-headers": "content-type" });
  }

  // The verification document and health are never rate limited: a reviewer
  // checking whether the service is alive must not be turned away.
  if (path === "/.well-known/xagent-verification.json") {
    return send(res, 200, { schemaVersion: 1, slug: SLUG, commit: COMMIT });
  }

  if (path === "/health") {
    const state = await ensureCatalogue();
    return send(
      res,
      200,
      {
        status: "ok",
        commit: COMMIT,
        slug: SLUG,
        catalogue: {
          snapshotId: state.snapshot?.snapshotId ?? null,
          pricedAt: state.snapshot?.pricedAt ?? null,
          staleSeconds: state.staleSeconds,
          offers: state.snapshot?.offers.length ?? 0,
          cacheAgeSeconds: state.staleSeconds,
          refreshCount: state.refreshCount,
          servingShippedSnapshot: state.servingShippedSnapshot,
          lastRefreshAttemptAt: state.lastAttemptAt,
          lastRefreshError: state.lastError,
        },
      },
      { "x-source-commit": COMMIT },
    );
  }

  const limit = rateLimited(ip);
  const rateHeaders = {
    "x-ratelimit-limit": String(RATE_LIMIT),
    "x-ratelimit-remaining": String(limit.remaining),
    "x-ratelimit-reset": String(Math.ceil(limit.resetAt / 1000)),
  };
  if (limit.limited) {
    return send(
      res,
      429,
      {
        error: "rate_limited",
        message: `This desk answers ${RATE_LIMIT} requests a minute from one address.`,
        retryAfterSeconds: Math.ceil((limit.resetAt - Date.now()) / 1000),
      },
      { ...rateHeaders, "retry-after": String(Math.ceil((limit.resetAt - Date.now()) / 1000)) },
    );
  }

  if (path === "/") return send(res, 200, INDEX, rateHeaders);
  if (path === "/v1/tools.json") return send(res, 200, TOOLS, rateHeaders);

  const state = await ensureCatalogue();
  if (!state.snapshot) {
    return send(
      res,
      503,
      {
        error: "catalogue_unavailable",
        message: "This desk has not managed to read the catalogue yet, so it will not price anything.",
        lastAttemptAt: state.lastAttemptAt,
        lastError: state.lastError,
      },
      rateHeaders,
    );
  }
  const snapshot = state.snapshot;
  const staleSeconds = state.staleSeconds ?? 0;

  async function body(): Promise<Record<string, unknown> | null> {
    try {
      return (await readJson(req)) as Record<string, unknown>;
    } catch (err) {
      send(res, 400, {
        error: "invalid_request",
        message: err instanceof Error ? err.message : "unreadable body",
      }, rateHeaders);
      return null;
    }
  }

  if (path === "/v1/plan_call" && req.method === "POST") {
    const args = await body();
    if (!args) return;
    const out = runPlanCall(snapshot, staleSeconds, args);
    return send(res, out.status, out.body, rateHeaders);
  }

  if (path === "/v1/quote" && req.method === "POST") {
    const args = await body();
    if (!args) return;
    const out = runQuote(snapshot, staleSeconds, args);
    return send(res, out.status, out.body, rateHeaders);
  }

  if (path === "/v1/resolve" && req.method === "GET") {
    const out = runResolve(snapshot, staleSeconds, { modelId: url.searchParams.get("modelId") ?? "" });
    return send(res, out.status, out.body, rateHeaders);
  }

  if (path === "/v1/catalogue" && req.method === "GET") {
    const out = runCatalogue(snapshot, staleSeconds, {
      line: url.searchParams.get("line"),
      minContext: Number(url.searchParams.get("minContext") ?? 0),
      limit: Number(url.searchParams.get("limit") ?? 50),
    });
    return send(res, out.status, out.body, rateHeaders);
  }

  if (path === "/v1/catalogue/diff" && req.method === "GET") {
    const out = runCatalogueDiff(SUBMITTED, snapshot);
    return send(res, out.status, out.body, rateHeaders);
  }

  // JSON-RPC. The transport carries the answer; a refusal by a tool is a
  // result, and only a malformed request is an error object. The HTTP status
  // stays 200 for anything the protocol can describe itself.
  if (path === "/mcp" && req.method === "POST") {
    let payload: unknown;
    try {
      payload = await readJson(req);
    } catch (err) {
      return send(res, 400, PARSE_ERROR_RESPONSE(err instanceof Error ? err.message : "unreadable body"), rateHeaders);
    }
    const reply = handleMcpPayload(payload, { snapshot, staleSeconds, submitted: SUBMITTED });
    if (reply === null) {
      res.writeHead(202, { "access-control-allow-origin": "*" });
      res.end();
      return;
    }
    return send(res, 200, reply, rateHeaders);
  }

  return send(res, 404, {
    error: "not_found",
    message: `Nothing is served at ${path}.`,
    endpoints: INDEX.endpoints,
  }, rateHeaders);
}

const PORT = Number(process.env.PORT ?? 4400);

if (process.env.NODE_ENV !== "test") {
  createServer((req, res) => {
    handle(req, res).catch((err) => {
      send(res, 500, {
        error: "internal_error",
        message: err instanceof Error ? err.message : String(err),
      });
    });
  }).listen(PORT, () => {
    console.log(`model desk on ${PORT}, commit ${COMMIT || "(unset)"}, limit ${MAX_TOKENS} tokens`);
  });
}
