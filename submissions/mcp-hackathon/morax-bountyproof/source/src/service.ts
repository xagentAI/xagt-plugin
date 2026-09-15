import { analyzeBounty, parseIssueUrl, type AnalyzeInput } from "./analyzer.js";
import { TtlCache } from "./cache.js";
import { fetchIssueEvidence, GitHubApiError } from "./github.js";
import { openApiDocument } from "./openapi.js";
import type { BountyPreflight } from "./types.js";

const MAX_BODY_BYTES = 16 * 1024;
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type",
  "access-control-max-age": "86400",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

export interface ServiceConfig {
  reviewCommit: string;
  sourceRepository: string;
  githubApiToken?: string;
}

export interface ServiceDependencies {
  fetchEvidence?: typeof fetchIssueEvidence;
  cache?: TtlCache<BountyPreflight>;
  now?: () => Date;
  randomUUID?: () => string;
}

class RequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "RequestError";
  }
}

function json(value: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return Response.json(value, { status, headers: { ...JSON_HEADERS, ...extraHeaders } });
}

async function readJsonObject(request: Request): Promise<Record<string, unknown>> {
  const contentType = request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (contentType !== "application/json") {
    throw new RequestError(415, "CONTENT_TYPE_REQUIRED", "Use content-type: application/json.");
  }
  const declaredLength = Number.parseInt(request.headers.get("content-length") ?? "0", 10);
  if (Number.isFinite(declaredLength) && declaredLength > MAX_BODY_BYTES) {
    throw new RequestError(413, "REQUEST_TOO_LARGE", `Request body exceeds ${MAX_BODY_BYTES} bytes.`);
  }
  if (!request.body) throw new RequestError(400, "EMPTY_BODY", "Request body is required.");

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_BODY_BYTES) {
      await reader.cancel("request body too large");
      throw new RequestError(413, "REQUEST_TOO_LARGE", `Request body exceeds ${MAX_BODY_BYTES} bytes.`);
    }
    chunks.push(value);
  }

  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }

  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  } catch {
    throw new RequestError(400, "INVALID_JSON", "Request body must be valid UTF-8 JSON.");
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new RequestError(400, "OBJECT_REQUIRED", "Request body must be a JSON object.");
  }
  return value as Record<string, unknown>;
}

function parseAnalyzeInput(body: Record<string, unknown>): AnalyzeInput {
  const allowed = new Set(["issueUrl", "expectedRewardUsd", "expectedPlatform"]);
  const unknown = Object.keys(body).filter((key) => !allowed.has(key));
  if (unknown.length) throw new RequestError(400, "UNKNOWN_FIELDS", `Unknown field(s): ${unknown.join(", ")}.`);
  if (typeof body.issueUrl !== "string" || body.issueUrl.length > 300) {
    throw new RequestError(400, "INVALID_ISSUE_URL", "issueUrl must be a canonical GitHub issue URL.");
  }
  try {
    parseIssueUrl(body.issueUrl);
  } catch {
    throw new RequestError(400, "INVALID_ISSUE_URL", "issueUrl must be a canonical public GitHub issue URL.");
  }

  if (
    body.expectedRewardUsd !== undefined &&
    body.expectedRewardUsd !== null &&
    typeof body.expectedRewardUsd !== "number"
  ) {
    throw new RequestError(400, "INVALID_EXPECTED_REWARD", "expectedRewardUsd must be a number or null.");
  }
  if (
    typeof body.expectedRewardUsd === "number" &&
    (!Number.isFinite(body.expectedRewardUsd) || body.expectedRewardUsd <= 0 || body.expectedRewardUsd > 10_000_000)
  ) {
    throw new RequestError(
      400,
      "INVALID_EXPECTED_REWARD",
      "expectedRewardUsd must be positive and no greater than 10000000.",
    );
  }
  if (
    body.expectedPlatform !== undefined &&
    body.expectedPlatform !== null &&
    typeof body.expectedPlatform !== "string"
  ) {
    throw new RequestError(400, "INVALID_EXPECTED_PLATFORM", "expectedPlatform must be a string or null.");
  }
  if (typeof body.expectedPlatform === "string" && body.expectedPlatform.length > 80) {
    throw new RequestError(400, "INVALID_EXPECTED_PLATFORM", "expectedPlatform must not exceed 80 characters.");
  }

  const input: AnalyzeInput = { issueUrl: body.issueUrl };
  if (body.expectedRewardUsd !== undefined) {
    input.expectedRewardUsd = body.expectedRewardUsd as number | null;
  }
  if (body.expectedPlatform !== undefined) {
    input.expectedPlatform = body.expectedPlatform as string | null;
  }
  return input;
}

function cacheKey(input: AnalyzeInput): string {
  const parsed = parseIssueUrl(input.issueUrl);
  return JSON.stringify([
    parsed.canonicalUrl.toLowerCase(),
    input.expectedRewardUsd ?? null,
    input.expectedPlatform?.trim().toLowerCase() ?? null,
  ]);
}

export function createService(config: ServiceConfig, dependencies: ServiceDependencies = {}) {
  const evidenceFetcher = dependencies.fetchEvidence ?? fetchIssueEvidence;
  const cache = dependencies.cache ?? new TtlCache<BountyPreflight>();
  const currentTime = dependencies.now ?? (() => new Date());
  const randomUUID = dependencies.randomUUID ?? (() => crypto.randomUUID());

  return async function handleRequest(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const requestId = request.headers.get("x-request-id")?.slice(0, 100) || randomUUID();

    try {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: JSON_HEADERS });

      if (request.method === "GET" && url.pathname === "/") {
        return json({
          name: "BountyProof",
          description: "Evidence-first GitHub bounty preflight for humans and agents.",
          version: "0.1.0",
          commit: config.reviewCommit,
          source: config.sourceRepository,
          documentation: `${url.origin}/openapi.json`,
          capability: `${url.origin}/v1/check`,
          limits: { requestBytes: MAX_BODY_BYTES, cacheSeconds: 300 },
        });
      }

      if (request.method === "GET" && url.pathname === "/health") {
        return json({
          status: "ok",
          service: "bountyproof",
          version: "0.1.0",
          commit: config.reviewCommit,
          checkedAt: currentTime().toISOString(),
        }, 200, { "cache-control": "no-store", "x-source-commit": config.reviewCommit });
      }

      if (request.method === "GET" && url.pathname === "/.well-known/xagent-verification.json") {
        return json({
          schemaVersion: 1,
          slug: "morax-bountyproof",
          commit: config.reviewCommit,
        }, 200, { "cache-control": "no-store", "x-source-commit": config.reviewCommit });
      }

      if (request.method === "GET" && url.pathname === "/openapi.json") {
        return json(openApiDocument(url.origin), 200, { "cache-control": "public, max-age=300" });
      }

      if (request.method === "POST" && url.pathname === "/v1/check") {
        const input = parseAnalyzeInput(await readJsonObject(request));
        const key = cacheKey(input);
        const cached = cache.get(key);
        if (cached) {
          return json({ ...cached, requestId }, 200, {
            "cache-control": "public, max-age=300",
            "x-bountyproof-cache": "HIT",
            "x-request-id": requestId,
          });
        }

        const evidence = await evidenceFetcher(input.issueUrl, config.githubApiToken);
        const result = analyzeBounty(input, evidence, currentTime(), requestId);
        cache.set(key, result);
        return json(result, 200, {
          "cache-control": "public, max-age=300",
          "x-bountyproof-cache": "MISS",
          "x-request-id": requestId,
        });
      }

      throw new RequestError(404, "ROUTE_NOT_FOUND", "Route not found.");
    } catch (error) {
      if (error instanceof RequestError) {
        return json({ error: { code: error.code, message: error.message, requestId } }, error.status, {
          "cache-control": "no-store",
          "x-request-id": requestId,
        });
      }
      if (error instanceof GitHubApiError) {
        const status = error.upstreamCode === "GITHUB_NOT_FOUND"
          ? 404
          : error.upstreamCode === "GITHUB_RATE_LIMITED"
            ? 429
            : 502;
        return json({ error: { code: error.upstreamCode, message: error.message, requestId } }, status, {
          "cache-control": "no-store",
          "x-request-id": requestId,
        });
      }
      const message = error instanceof Error ? error.message : "Internal service error.";
      console.error(JSON.stringify({ level: "error", event: "request_failed", requestId, message }));
      return json({ error: { code: "INTERNAL_ERROR", message: "Internal service error.", requestId } }, 500, {
        "cache-control": "no-store",
        "x-request-id": requestId,
      });
    }
  };
}
