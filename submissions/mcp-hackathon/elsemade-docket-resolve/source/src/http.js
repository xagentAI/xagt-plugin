import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { toNodeHandler } from "@modelcontextprotocol/node";

import { EvaluationError, evaluateAgreement } from "./evaluate.js";
import { createReviewProvider } from "./ai/providers.js";
import { ReviewValidationError, reviewAgreement } from "./ai/review.js";
import { authenticate, AuthError, requireScope } from "./auth.js";
import { retrieveAgreementEvidence } from "./evidence/retrieve.js";
import { fixtureEvidenceContent } from "./evidence/fixture.js";
import { createDocketMcpHandler } from "./mcp/server.js";
import { createOpenApiDocument } from "./openapi.js";
import { CaseStore, CaseStoreError } from "./persistence/store.js";

const MAX_BODY_BYTES = 256 * 1024;
const DEFAULT_PUBLIC_RATE_LIMIT_PER_MINUTE = 30;
const PUBLIC_FILES = new Map([
  ["/", { contentType: "text/html; charset=utf-8", body: readFileSync(new URL("../public/index.html", import.meta.url)) }],
  ["/app.js", { contentType: "text/javascript; charset=utf-8", body: readFileSync(new URL("../public/app.js", import.meta.url)) }],
  ["/retrieval-status.js", { contentType: "text/javascript; charset=utf-8", body: readFileSync(new URL("../public/retrieval-status.js", import.meta.url)) }],
  ["/styles.css", { contentType: "text/css; charset=utf-8", body: readFileSync(new URL("../public/styles.css", import.meta.url)) }],
  ["/favicon.svg", { contentType: "image/svg+xml", body: readFileSync(new URL("../public/favicon.svg", import.meta.url)) }],
]);
const PUBLIC_EVIDENCE_FILES = new Map([
  ["/fixtures/evidence/ev-smoke.txt", "https://evidence.example.test/ev-smoke.txt"],
  ["/fixtures/evidence/ev-docs.txt", "https://evidence.example.test/ev-docs.txt"],
  ["/fixtures/evidence/ev-errors.txt", "https://evidence.example.test/ev-errors.txt"],
].map(([path, uri]) => [path, {
  contentType: "text/plain; charset=utf-8",
  body: Buffer.from(fixtureEvidenceContent(uri), "utf8"),
}]));

function readJsonBody(request, { optional = false } = {}) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let tooLarge = false;

    request.on("data", (chunk) => {
      if (tooLarge) return;
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        tooLarge = true;
        chunks.length = 0;
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (tooLarge) {
        const error = new Error("Request body exceeds 256 KiB.");
        error.code = "PAYLOAD_TOO_LARGE";
        reject(error);
        return;
      }
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(optional && raw.trim() === "" ? {} : JSON.parse(raw));
      } catch {
        const error = new Error("Request body is not valid JSON.");
        error.code = "INVALID_JSON";
        reject(error);
      }
    });
    request.on("error", reject);
  });
}

function sendJson(response, status, body, requestId, allowedOrigin, extraHeaders = {}) {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "access-control-allow-headers": "content-type, authorization, idempotency-key",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-origin": allowedOrigin,
    "cache-control": "no-store",
    "content-length": Buffer.byteLength(payload),
    "content-type": "application/json; charset=utf-8",
    "x-content-type-options": "nosniff",
    "x-request-id": requestId,
    ...extraHeaders,
  });
  response.end(payload);
}

function sendPublicFile(response, file, requestId) {
  response.writeHead(200, {
    "cache-control": file.contentType.startsWith("text/html")
      ? "no-cache"
      : "public, max-age=3600",
    "content-length": file.body.length,
    "content-security-policy":
      "default-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    "content-type": file.contentType,
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "x-request-id": requestId,
  });
  response.end(file.body);
}

function errorBody(code, message, requestId, details = undefined) {
  const error = { code, message, requestId };
  if (details !== undefined) {
    error.details = details;
  }
  return { error };
}

class HttpRequestError extends Error {
  constructor(code, message, status = 400) {
    super(message);
    this.name = "HttpRequestError";
    this.code = code;
    this.status = status;
  }
}

function idempotencyKey(request, { required = false } = {}) {
  const value = request.headers["idempotency-key"];
  if (typeof value !== "string" || !value.trim()) {
    if (required) throw new HttpRequestError("IDEMPOTENCY_KEY_REQUIRED", "Mutating production requests require an Idempotency-Key header.");
    return undefined;
  }
  const normalized = value.trim();
  if (normalized.length > 200 || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(normalized)) {
    throw new HttpRequestError("IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must be 1–200 characters using letters, numbers, dot, underscore, colon, or hyphen.");
  }
  return normalized;
}

function routeCaseId(pathname) {
  const match = /^\/v1\/cases\/([^/]+)(?:\/(retrieve|review|resolve))?$/.exec(pathname);
  if (!match) return null;
  let caseId;
  try {
    caseId = decodeURIComponent(match[1]);
  } catch {
    return { invalid: true };
  }
  return /^[A-Za-z0-9_-]{1,128}$/.test(caseId)
    ? { caseId, action: match[2] ?? null }
    : { invalid: true };
}

function evaluationOutput(evaluation) {
  return {
    ...evaluation,
    recommendationOnly: true,
    fundsMoved: false,
    source: "docket-settlement-kernel",
  };
}

function createRateLimiter(limitPerMinute) {
  const buckets = new Map();
  const windowMs = 60_000;
  const limit = Number.isInteger(limitPerMinute) && limitPerMinute > 0
    ? limitPerMinute
    : DEFAULT_PUBLIC_RATE_LIMIT_PER_MINUTE;

  return {
    consume(key) {
      const now = Date.now();
      const previous = buckets.get(key);
      const bucket = previous && now - previous.startedAt < windowMs
        ? previous
        : { startedAt: now, count: 0 };
      if (bucket.count >= limit) return false;
      bucket.count += 1;
      buckets.set(key, bucket);
      if (buckets.size > 10_000) {
        for (const [bucketKey, value] of buckets) {
          if (now - value.startedAt >= windowMs) buckets.delete(bucketKey);
        }
      }
      return true;
    },
  };
}

export function createRequestHandler({
  commit,
  slug,
  allowedOrigin = "*",
  reviewProvider = createReviewProvider(),
  auth = { required: false, tokens: new Map() },
  store,
  storagePath = "data/docket-store.json",
  evidenceFetcher = globalThis.fetch,
  evidenceAllowHosts = [],
  evidenceRequireAllowlist = false,
  evidenceResolver,
  publicRateLimitPerMinute = DEFAULT_PUBLIC_RATE_LIMIT_PER_MINUTE,
}) {
  const caseStore = store ?? new CaseStore({ filePath: storagePath });
  const requireEvidenceAllowlist = evidenceRequireAllowlist || auth.required;
  const publicRateLimiter = createRateLimiter(publicRateLimitPerMinute);
  return async function requestHandler(request, response) {
    const requestId = randomUUID();
    const forwardedProtocol = String(request.headers["x-forwarded-proto"] ?? "").split(",")[0].trim().toLowerCase();
    const protocol = forwardedProtocol === "https" || forwardedProtocol === "http"
      ? forwardedProtocol
      : request.socket?.encrypted ? "https" : "http";
    const origin = `${protocol}://${request.headers.host ?? "localhost"}`;
    const url = new URL(request.url ?? "/", origin);
    const protectedRequest = url.pathname === "/mcp" || url.pathname.startsWith("/v1/");
    let identity = null;

    if (protectedRequest && request.method !== "OPTIONS") {
      try {
        identity = authenticate(request, auth);
      } catch (error) {
        if (error instanceof AuthError) {
          sendJson(response, error.status, errorBody(error.code, error.message, requestId), requestId, allowedOrigin);
          return;
        }
        throw error;
      }
    }

    if (request.method === "OPTIONS") {
      response.writeHead(204, {
        "access-control-allow-headers": "content-type, authorization, idempotency-key",
        "access-control-allow-methods": "GET,POST,OPTIONS",
        "access-control-allow-origin": allowedOrigin,
        "x-request-id": requestId,
      });
      response.end();
      return;
    }

    const publicMutation = Boolean(
      identity
      && !identity.authenticated
      && request.method === "POST"
      && (url.pathname === "/mcp" || url.pathname.startsWith("/v1/")),
    );
    if (publicMutation && !publicRateLimiter.consume(request.socket?.remoteAddress ?? "unknown")) {
      sendJson(
        response,
        429,
        errorBody("RATE_LIMITED", "The public demo rate limit was reached. Retry in one minute.", requestId),
        requestId,
        allowedOrigin,
        { "retry-after": "60" },
      );
      return;
    }

    if (url.pathname === "/mcp") {
      try {
        const handler = toNodeHandler(createDocketMcpHandler({
          reviewProvider,
          store: caseStore,
          tenantId: identity.tenantId,
          subject: identity.subject,
          evidenceFetcher,
          evidenceAllowHosts,
          evidenceRequireAllowlist: requireEvidenceAllowlist,
          evidenceResolver,
          requireIdempotency: auth.required,
          scopes: identity.scopes,
        }));
        await handler(request, response);
      } catch (error) {
        if (!response.headersSent) {
          sendJson(response, 500, errorBody("MCP_FAILED", "The MCP request failed safely.", requestId), requestId, allowedOrigin);
        }
      }
      return;
    }

    const publicFile = request.method === "GET"
      ? PUBLIC_FILES.get(url.pathname) ?? PUBLIC_EVIDENCE_FILES.get(url.pathname)
      : null;
    if (publicFile) {
      sendPublicFile(response, publicFile, requestId);
      return;
    }

    if (request.method === "GET" && url.pathname === "/health") {
      sendJson(response, 200, { status: "ok", commit }, requestId, allowedOrigin);
      return;
    }

    if (
      request.method === "GET" &&
      url.pathname === "/.well-known/xagent-verification.json"
    ) {
      sendJson(
        response,
        200,
        { schemaVersion: 1, slug, commit },
        requestId,
        allowedOrigin,
      );
      return;
    }

    if (request.method === "GET" && url.pathname === "/openapi.json") {
      sendJson(
        response,
        200,
        createOpenApiDocument({ origin }),
        requestId,
        allowedOrigin,
      );
      return;
    }

    if (request.method === "GET" && url.pathname === "/v1/cases") {
      try {
        requireScope(identity, "cases:read");
        sendJson(response, 200, { cases: await caseStore.listCases({ tenantId: identity.tenantId }) }, requestId, allowedOrigin);
      } catch (error) {
        if (error instanceof AuthError || error instanceof CaseStoreError) {
          sendJson(response, error.status, errorBody(error.code, error.message, requestId), requestId, allowedOrigin);
          return;
        }
        console.error(JSON.stringify({ level: "error", requestId, code: "CASE_LIST_FAILED", message: error.message }));
        sendJson(response, 500, errorBody("CASE_LIST_FAILED", "Cases could not be loaded.", requestId), requestId, allowedOrigin);
      }
      return;
    }

    if (request.method === "POST" && url.pathname === "/v1/cases") {
      try {
        requireScope(identity, "cases:write");
        const body = await readJsonBody(request);
        if (!body || typeof body !== "object" || Array.isArray(body) || !body.agreement || typeof body.agreement !== "object") {
          sendJson(response, 422, errorBody("INVALID_CASE_REQUEST", "Case requests must include an agreement object.", requestId), requestId, allowedOrigin);
          return;
        }
        const agreement = {
          ...body.agreement,
          findings: Array.isArray(body.agreement.findings) ? body.agreement.findings : [],
        };
        evaluateAgreement(agreement);
        const created = await caseStore.createCase({
          tenantId: identity.tenantId,
          subject: identity.subject,
          agreement,
          idempotencyKey: idempotencyKey(request, { required: auth.required }),
        });
        sendJson(response, created.replayed ? 200 : 201, created, requestId, allowedOrigin);
      } catch (error) {
        if (error instanceof AuthError || error instanceof CaseStoreError || error instanceof EvaluationError || error instanceof HttpRequestError) {
          sendJson(response, error.status ?? 422, errorBody(error.code, error.message, requestId, error.details), requestId, allowedOrigin);
          return;
        }
        if (error?.code === "INVALID_JSON") {
          sendJson(response, 400, errorBody(error.code, error.message, requestId), requestId, allowedOrigin);
          return;
        }
        if (error?.code === "PAYLOAD_TOO_LARGE") {
          sendJson(response, 413, errorBody(error.code, error.message, requestId), requestId, allowedOrigin);
          return;
        }
        console.error(JSON.stringify({ level: "error", requestId, code: "CASE_CREATE_FAILED", message: error.message }));
        sendJson(response, 500, errorBody("CASE_CREATE_FAILED", "The case could not be created.", requestId), requestId, allowedOrigin);
      }
      return;
    }

    const caseRoute = routeCaseId(url.pathname);
    if (caseRoute?.invalid) {
      sendJson(response, 400, errorBody("INVALID_CASE_ID", "The case ID is malformed.", requestId), requestId, allowedOrigin);
      return;
    }
    if (caseRoute && request.method === "GET" && !caseRoute.action) {
      try {
        requireScope(identity, "cases:read");
        const record = await caseStore.getCase({ tenantId: identity.tenantId, caseId: caseRoute.caseId });
        if (!record) {
          sendJson(response, 404, errorBody("CASE_NOT_FOUND", "The case was not found.", requestId), requestId, allowedOrigin);
          return;
        }
        sendJson(response, 200, record, requestId, allowedOrigin);
      } catch (error) {
        if (error instanceof AuthError) sendJson(response, error.status, errorBody(error.code, error.message, requestId), requestId, allowedOrigin);
        else sendJson(response, 500, errorBody("CASE_READ_FAILED", "The case could not be loaded.", requestId), requestId, allowedOrigin);
      }
      return;
    }

    if (caseRoute && request.method === "POST") {
      try {
        const mutationKey = idempotencyKey(request, { required: auth.required });
        requireScope(identity, "cases:write");
        let record = await caseStore.getCase({ tenantId: identity.tenantId, caseId: caseRoute.caseId });
        if (!record) {
          sendJson(response, 404, errorBody("CASE_NOT_FOUND", "The case was not found.", requestId), requestId, allowedOrigin);
          return;
        }

        if (caseRoute.action === "retrieve") {
          const retrievalRequest = { caseId: caseRoute.caseId };
          const saved = await caseStore.runIdempotent({
            tenantId: identity.tenantId,
            operation: "retrieve-evidence",
            scope: caseRoute.caseId,
            idempotencyKey: mutationKey,
            request: retrievalRequest,
          }, async () => {
            const retrieval = await retrieveAgreementEvidence(record.agreement, {
              fetchImpl: evidenceFetcher,
              allowHosts: evidenceAllowHosts,
              requireAllowlist: requireEvidenceAllowlist,
              resolveHost: evidenceResolver,
            });
            return caseStore.saveEvidenceRetrieval({
              tenantId: identity.tenantId,
              caseId: caseRoute.caseId,
              subject: identity.subject,
              items: retrieval.items,
              errors: retrieval.errors,
              idempotencyKey: mutationKey,
              request: retrievalRequest,
            });
          });
          sendJson(response, 200, saved, requestId, allowedOrigin);
          return;
        }

        if (caseRoute.action === "review") {
          const body = await readJsonBody(request, { optional: true });
          const reviewRequest = {
            caseId: caseRoute.caseId,
            retrieveEvidence: Boolean(body?.retrieveEvidence),
            evidenceContent: Array.isArray(body?.evidenceContent) ? body.evidenceContent : null,
          };
          const saved = await caseStore.runIdempotent({
            tenantId: identity.tenantId,
            operation: "review-case",
            scope: caseRoute.caseId,
            idempotencyKey: mutationKey,
            request: reviewRequest,
          }, async () => {
            if (body?.retrieveEvidence) {
              const retrieval = await retrieveAgreementEvidence(record.agreement, {
                fetchImpl: evidenceFetcher,
                allowHosts: evidenceAllowHosts,
                requireAllowlist: requireEvidenceAllowlist,
                resolveHost: evidenceResolver,
              });
              await caseStore.saveEvidenceRetrieval({
                tenantId: identity.tenantId,
                caseId: caseRoute.caseId,
                subject: identity.subject,
                items: retrieval.items,
                errors: retrieval.errors,
                idempotencyKey: `${mutationKey ?? "review"}:retrieve`,
              });
              record = await caseStore.getCase({ tenantId: identity.tenantId, caseId: caseRoute.caseId });
            }
            const reviewEvidenceContent = Array.isArray(body?.evidenceContent) ? body.evidenceContent : record.evidenceContent;
            const review = await reviewAgreement({
              agreement: record.agreement,
              evidenceContent: reviewEvidenceContent,
              provider: reviewProvider,
            });
            return caseStore.saveReview({
              tenantId: identity.tenantId,
              caseId: caseRoute.caseId,
              subject: identity.subject,
              review,
              evidenceContent: reviewEvidenceContent,
              idempotencyKey: mutationKey,
              request: reviewRequest,
            });
          });
          sendJson(response, 200, saved, requestId, allowedOrigin);
          return;
        }

        if (caseRoute.action === "resolve") {
          if (!record.review) {
            sendJson(response, 409, errorBody("CASE_NOT_REVIEWED", "Review the case before resolving it.", requestId), requestId, allowedOrigin);
            return;
          }
          if (!record.review.readyToResolve) {
            sendJson(response, 409, errorBody("CASE_REVIEW_NOT_READY", "The case requires human review before it can be resolved.", requestId), requestId, allowedOrigin);
            return;
          }
          const evaluation = evaluationOutput(evaluateAgreement({ ...record.agreement, findings: record.review.findings }));
          const saved = await caseStore.saveResolution({
            tenantId: identity.tenantId,
            caseId: caseRoute.caseId,
            subject: identity.subject,
            evaluation,
            idempotencyKey: mutationKey,
          });
          sendJson(response, 200, { ...evaluation, persisted: saved }, requestId, allowedOrigin);
          return;
        }
      } catch (error) {
        if (error instanceof AuthError || error instanceof CaseStoreError || error instanceof EvaluationError || error instanceof ReviewValidationError || error instanceof HttpRequestError) {
          sendJson(response, error.status ?? 422, errorBody(error.code, error.message, requestId, error.details), requestId, allowedOrigin);
          return;
        }
        if (error?.code === "INVALID_JSON") {
          sendJson(response, 400, errorBody(error.code, error.message, requestId), requestId, allowedOrigin);
          return;
        }
        if (error?.code === "PAYLOAD_TOO_LARGE") {
          sendJson(response, 413, errorBody(error.code, error.message, requestId), requestId, allowedOrigin);
          return;
        }
        console.error(JSON.stringify({ level: "error", requestId, code: error?.code ?? "CASE_ACTION_FAILED", message: error.message }));
        sendJson(response, 500, errorBody(error?.code ?? "CASE_ACTION_FAILED", "The case action failed safely.", requestId), requestId, allowedOrigin);
      }
      return;
    }

    if (request.method === "POST" && url.pathname === "/v1/evaluations") {
      const contentType = request.headers["content-type"] ?? "";
      if (!contentType.toLowerCase().startsWith("application/json")) {
        sendJson(
          response,
          415,
          errorBody(
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type must be application/json.",
            requestId,
          ),
          requestId,
          allowedOrigin,
        );
        return;
      }

      try {
        const agreement = await readJsonBody(request);
        const evaluation = evaluateAgreement(agreement);
        sendJson(response, 200, evaluation, requestId, allowedOrigin);
      } catch (error) {
        if (error instanceof EvaluationError) {
          sendJson(
            response,
            422,
            errorBody(error.code, error.message, requestId, error.details),
            requestId,
            allowedOrigin,
          );
          return;
        }
        if (error?.code === "INVALID_JSON") {
          sendJson(
            response,
            400,
            errorBody("INVALID_JSON", error.message, requestId),
            requestId,
            allowedOrigin,
          );
          return;
        }
        if (error?.code === "PAYLOAD_TOO_LARGE") {
          if (!response.headersSent) {
            sendJson(
              response,
              413,
              errorBody("PAYLOAD_TOO_LARGE", error.message, requestId),
              requestId,
              allowedOrigin,
            );
          }
          return;
        }

        console.error(JSON.stringify({
          level: "error",
          requestId,
          code: "INTERNAL_ERROR",
          message: error instanceof Error ? error.message : "Unknown error",
        }));
        sendJson(
          response,
          500,
          errorBody("INTERNAL_ERROR", "The evaluation failed.", requestId),
          requestId,
          allowedOrigin,
        );
      }
      return;
    }

    if (request.method === "POST" && url.pathname === "/v1/reviews") {
      const contentType = request.headers["content-type"] ?? "";
      if (!contentType.toLowerCase().startsWith("application/json")) {
        sendJson(
          response,
          415,
          errorBody(
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type must be application/json.",
            requestId,
          ),
          requestId,
          allowedOrigin,
        );
        return;
      }

      try {
        const body = await readJsonBody(request);
        if (
          body === null ||
          typeof body !== "object" ||
          Array.isArray(body) ||
          body.agreement === null ||
          typeof body.agreement !== "object" ||
          Array.isArray(body.agreement)
        ) {
          sendJson(
            response,
            422,
            errorBody(
              "INVALID_REVIEW_REQUEST",
              "Review requests must include an agreement object.",
              requestId,
            ),
            requestId,
            allowedOrigin,
          );
          return;
        }
        const review = await reviewAgreement({
          agreement: body.agreement,
          evidenceContent: Array.isArray(body.evidenceContent)
            ? body.evidenceContent
            : [],
          provider: reviewProvider,
        });
        sendJson(response, 200, review, requestId, allowedOrigin);
      } catch (error) {
        if (error instanceof EvaluationError || error instanceof ReviewValidationError) {
          sendJson(
            response,
            422,
            errorBody(error.code, error.message, requestId, error.details),
            requestId,
            allowedOrigin,
          );
          return;
        }
        if (error?.code === "INVALID_JSON") {
          sendJson(
            response,
            400,
            errorBody("INVALID_JSON", error.message, requestId),
            requestId,
            allowedOrigin,
          );
          return;
        }
        if (error?.code === "PAYLOAD_TOO_LARGE") {
          sendJson(
            response,
            413,
            errorBody("PAYLOAD_TOO_LARGE", error.message, requestId),
            requestId,
            allowedOrigin,
          );
          return;
        }
        console.error(JSON.stringify({
          level: "error",
          requestId,
          code: error?.code ?? "AI_REVIEW_FAILED",
          message: error instanceof Error ? error.message : "Unknown review error",
        }));
        sendJson(
          response,
          503,
          errorBody("AI_REVIEW_FAILED", "The evidence review is unavailable.", requestId),
          requestId,
          allowedOrigin,
        );
      }
      return;
    }

    sendJson(
      response,
      404,
      errorBody("NOT_FOUND", "No route matches this request.", requestId),
      requestId,
      allowedOrigin,
    );
  };
}
