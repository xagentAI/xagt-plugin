import cors from "@fastify/cors";
import { randomUUID } from "node:crypto";
import Fastify, { type FastifyInstance } from "fastify";

import { loadConfig, type AppConfig } from "./config.js";
import { GitHubRestClient, type GitHubClient } from "./github/client.js";
import { registerEvaluateRoute } from "./routes/evaluate.js";
import { registerExampleRoutes } from "./routes/examples.js";
import { registerStatusRoutes } from "./routes/status.js";
import { createErrorResponse } from "./schemas/error.js";

export const requestBodyLimitBytes = 16_384;

type LogStream = {
  write(message: string): void;
};

export type AppDependencies = {
  githubClient?: GitHubClient;
  now?: () => Date;
  createRequestId?: () => string;
  logStream?: LogStream;
};

function hasErrorCode(error: unknown, code: string): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === code
  );
}

/**
 * Build the Fastify application without opening a network port.
 *
 * Accepting config as an argument keeps tests deterministic and lets deployment
 * settings be validated separately from route behavior.
 */
export async function buildApp(
  config: AppConfig = loadConfig(),
  dependencies: AppDependencies = {},
): Promise<FastifyInstance> {
  const createRequestId = dependencies.createRequestId ?? (() => `req_${randomUUID()}`);
  const app = Fastify({
    logger:
      dependencies.logStream === undefined
        ? config.nodeEnv !== "test"
        : {
            level: "info",
            stream: dependencies.logStream,
            redact: ["req.headers.authorization", "req.headers.cookie"],
          },
    requestTimeout: config.requestTimeoutMs,
    bodyLimit: requestBodyLimitBytes,
    genReqId: () => createRequestId(),
  });

  // BountyLens is an API-first service intended for agents and lightweight web
  // clients. Authentication and a stricter origin policy can be added later.
  await app.register(cors, {
    origin: true,
    methods: ["GET", "POST", "OPTIONS"],
  });

  // Return the same correlation identifier used by response bodies and logs.
  app.addHook("onRequest", async (request, reply) => {
    reply.header("x-request-id", request.id);
  });

  // Both public status routes receive the same immutable config object, which
  // prevents health and verification from reporting different source commits.
  registerStatusRoutes(app, config);
  registerExampleRoutes(app);

  const githubClient =
    dependencies.githubClient ??
    new GitHubRestClient(
      config.githubToken === undefined
        ? {
            timeoutMs: config.requestTimeoutMs,
            cacheTtlMs: config.cacheTtlSeconds * 1_000,
          }
        : {
            token: config.githubToken,
            timeoutMs: config.requestTimeoutMs,
            cacheTtlMs: config.cacheTtlSeconds * 1_000,
          },
    );

  registerEvaluateRoute(app, {
    githubClient,
    now: dependencies.now ?? (() => new Date()),
  });

  app.setErrorHandler((error, request, reply) => {
    if (hasErrorCode(error, "FST_ERR_CTP_BODY_TOO_LARGE")) {
      return reply
        .code(413)
        .send(
          createErrorResponse(
            request.id,
            "REQUEST_TOO_LARGE",
            `Request body exceeds the ${requestBodyLimitBytes}-byte limit.`,
            false,
          ),
        );
    }

    if (hasErrorCode(error, "FST_ERR_CTP_INVALID_JSON_BODY")) {
      return reply
        .code(400)
        .send(
          createErrorResponse(
            request.id,
            "INVALID_REQUEST",
            "Request body must contain valid JSON.",
            false,
          ),
        );
    }

    request.log.error(
      { requestId: request.id, errorName: error instanceof Error ? error.name : "UnknownError" },
      "Unhandled request error",
    );
    return reply
      .code(500)
      .send(
        createErrorResponse(
          request.id,
          "EVALUATION_FAILED",
          "The request could not be completed.",
          false,
        ),
      );
  });

  return app;
}
