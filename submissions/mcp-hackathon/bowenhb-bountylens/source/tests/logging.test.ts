import { afterEach, describe, expect, it, vi } from "vitest";

import { buildApp } from "../src/app.js";
import type { AppConfig } from "../src/config.js";
import type { GitHubClient } from "../src/github/client.js";
import { GitHubApiError } from "../src/github/errors.js";
import type { NormalizedIssueContext } from "../src/github/normalize.js";
import { loadFixture } from "./fixture-loader.js";

const secretToken = "ghp_LOG_SECRET_MUST_NOT_APPEAR";
const upstreamBodyMarker = "FULL_PRIVATE_UPSTREAM_BODY_MUST_NOT_APPEAR";
const commentMarker = "PRIVATE_COMMENT_MUST_NOT_APPEAR";
const profileMarker = "PRIVATE_PROFILE_MUST_NOT_APPEAR";

const testConfig: AppConfig = {
  nodeEnv: "test",
  host: "127.0.0.1",
  port: 3_000,
  githubToken: secretToken,
  sourceCommit: "0".repeat(40),
  projectSlug: "bountylens",
  cacheTtlSeconds: 300,
  requestTimeoutMs: 50,
};

const openedApps: Awaited<ReturnType<typeof buildApp>>[] = [];

afterEach(async () => {
  await Promise.all(openedApps.splice(0).map((app) => app.close()));
});

function clientWithResult(result: NormalizedIssueContext | Error): GitHubClient {
  return {
    getIssueContext: vi.fn(async () => {
      if (result instanceof Error) throw result;
      return result;
    }),
  } as unknown as GitHubClient;
}

async function buildLoggingApp(result: NormalizedIssueContext | Error, logs: string[]) {
  const app = await buildApp(testConfig, {
    githubClient: clientWithResult(result),
    now: () => new Date("2026-09-19T00:00:00Z"),
    createRequestId: () => "req_logging_test",
    logStream: { write: (message) => logs.push(message) },
  });
  openedApps.push(app);
  return app;
}

function findEvaluationLog(logs: string[]): Record<string, unknown> {
  const entries = logs.map((line) => JSON.parse(line) as Record<string, unknown>);
  const entry = entries.find((candidate) => candidate.event === "evaluation.completed");
  if (entry === undefined) throw new Error("Expected an evaluation.completed log entry.");
  return entry;
}

describe("evaluation logging", () => {
  it("records correlation and timing fields without request or upstream secrets", async () => {
    const fixture = loadFixture("clear-reward-low-competition");
    fixture.context.issue.body = upstreamBodyMarker;
    fixture.context.comments = [
      {
        author: "anonymous-role",
        body: commentMarker,
        createdAt: "2026-09-18T00:00:00Z",
      },
    ];
    const logs: string[] = [];
    const app = await buildLoggingApp(fixture.context, logs);

    const response = await app.inject({
      method: "POST",
      url: "/v1/evaluate",
      headers: { authorization: "Bearer REQUEST_AUTH_SECRET" },
      payload: {
        issue_url: fixture.sourceUrl,
        developer_profile: { languages: [profileMarker] },
      },
    });

    expect(response.statusCode).toBe(200);
    expect(findEvaluationLog(logs)).toMatchObject({
      requestId: "req_logging_test",
      path: "/v1/evaluate",
      statusCode: 200,
      upstreamStatus: 200,
      upstreamCode: null,
    });
    expect(findEvaluationLog(logs).durationMs).toEqual(expect.any(Number));

    const serializedLogs = logs.join("");
    for (const secret of [
      secretToken,
      upstreamBodyMarker,
      commentMarker,
      profileMarker,
      "REQUEST_AUTH_SECRET",
    ]) {
      expect(serializedLogs).not.toContain(secret);
    }
  });

  it("records a safe GitHub status and code for upstream failures", async () => {
    const logs: string[] = [];
    const app = await buildLoggingApp(
      new GitHubApiError("GITHUB_RATE_LIMITED", "PRIVATE_UPSTREAM_MESSAGE", {
        status: 403,
        rateLimit: {
          limit: 60,
          remaining: 0,
          resetAt: null,
          retryAfterSeconds: 30,
        },
      }),
      logs,
    );

    const response = await app.inject({
      method: "POST",
      url: "/v1/evaluate",
      payload: { issue_url: "https://github.com/openai/example/issues/42" },
    });

    expect(response.statusCode).toBe(429);
    expect(findEvaluationLog(logs)).toMatchObject({
      requestId: "req_logging_test",
      path: "/v1/evaluate",
      statusCode: 429,
      upstreamStatus: 403,
      upstreamCode: "GITHUB_RATE_LIMITED",
    });
    expect(logs.join("")).not.toContain("PRIVATE_UPSTREAM_MESSAGE");
  });
});
