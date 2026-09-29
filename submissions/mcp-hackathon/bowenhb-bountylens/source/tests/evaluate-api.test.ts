import { afterEach, describe, expect, it, vi } from "vitest";

import { buildApp, requestBodyLimitBytes } from "../src/app.js";
import type { AppConfig } from "../src/config.js";
import type { GitHubClient } from "../src/github/client.js";
import { GitHubApiError } from "../src/github/errors.js";
import type { NormalizedIssueContext } from "../src/github/normalize.js";
import { errorResponseSchema } from "../src/schemas/error.js";
import { evaluateResponseSchema } from "../src/schemas/response.js";
import { loadFixture } from "./fixture-loader.js";

const testConfig: AppConfig = {
  nodeEnv: "test",
  host: "127.0.0.1",
  port: 3_000,
  githubToken: "server-secret-token",
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

async function appWithClient(client: GitHubClient) {
  const app = await buildApp(testConfig, {
    githubClient: client,
    now: () => new Date("2026-09-17T00:00:00Z"),
    createRequestId: () => "req_test_001",
  });
  openedApps.push(app);
  return app;
}

describe("POST /v1/evaluate success contract", () => {
  it("runs the complete pipeline and returns a validated, redacted response", async () => {
    const fixture = loadFixture("clear-reward-low-competition");
    const client = clientWithResult(fixture.context);
    const app = await appWithClient(client);

    const response = await app.inject({
      method: "POST",
      url: "/v1/evaluate",
      payload: {
        issue_url: fixture.sourceUrl,
        developer_profile: {
          languages: ["TypeScript", "Python"],
          hourly_rate_usd: 30,
          max_hours: 12,
        },
      },
    });

    expect(response.statusCode).toBe(200);
    expect(response.headers["x-request-id"]).toBe("req_test_001");
    const body = evaluateResponseSchema.parse(response.json());
    expect(body).toMatchObject({
      request_id: "req_test_001",
      issue: {
        url: fixture.sourceUrl,
        repository: fixture.context.repository.fullName,
        number: 9562,
        state: "open",
      },
      decision: "investigate",
      reward: { amount: 50, currency: "USD" },
    });
    expect(client.getIssueContext).toHaveBeenCalledWith(
      expect.objectContaining({ owner: "QubesOS", repo: "qubes-issues", issueNumber: 9562 }),
      { requestId: "req_test_001" },
    );

    const serialized = response.body;
    expect(serialized).not.toContain(fixture.context.issue.body);
    expect(serialized).not.toContain("server-secret-token");
    expect(serialized).not.toContain("GITHUB_TOKEN");
  });

  it("works without a developer profile and declares the limitation", async () => {
    const fixture = loadFixture("no-explicit-reward");
    const app = await appWithClient(clientWithResult(fixture.context));
    const response = await app.inject({
      method: "POST",
      url: "/v1/evaluate",
      payload: { issue_url: fixture.sourceUrl },
    });

    expect(response.statusCode).toBe(200);
    const body = evaluateResponseSchema.parse(response.json());
    expect(body.dimensions.technical_fit).toBe(50);
    expect(body.limitations.join(" ")).toContain("neutral score");
  });
});

describe("POST /v1/evaluate validation and limits", () => {
  it.each([
    [{}, "INVALID_REQUEST"],
    [{ issue_url: "https://example.com/repo/issues/1" }, "INVALID_ISSUE_URL"],
    [
      { issue_url: "https://github.com/a/b/issues/1", unexpected: true },
      "INVALID_REQUEST",
    ],
  ])("rejects invalid input with a stable error: %o", async (payload, code) => {
    const fixture = loadFixture("no-explicit-reward");
    const app = await appWithClient(clientWithResult(fixture.context));
    const response = await app.inject({ method: "POST", url: "/v1/evaluate", payload });

    expect(response.statusCode).toBe(400);
    const body = errorResponseSchema.parse(response.json());
    expect(body.request_id).toBe("req_test_001");
    expect(body.error.code).toBe(code);
    expect(body.error.retryable).toBe(false);
  });

  it("rejects a body above the configured byte limit", async () => {
    const fixture = loadFixture("no-explicit-reward");
    const app = await appWithClient(clientWithResult(fixture.context));
    const response = await app.inject({
      method: "POST",
      url: "/v1/evaluate",
      payload: JSON.stringify({ issue_url: "x".repeat(requestBodyLimitBytes + 1) }),
      headers: { "content-type": "application/json" },
    });

    expect(response.statusCode).toBe(413);
    expect(errorResponseSchema.parse(response.json()).error.code).toBe("REQUEST_TOO_LARGE");
  });

  it("returns the unified error contract for malformed JSON", async () => {
    const fixture = loadFixture("no-explicit-reward");
    const app = await appWithClient(clientWithResult(fixture.context));
    const response = await app.inject({
      method: "POST",
      url: "/v1/evaluate",
      payload: '{"issue_url":',
      headers: { "content-type": "application/json" },
    });

    expect(response.statusCode).toBe(400);
    expect(errorResponseSchema.parse(response.json())).toMatchObject({
      request_id: "req_test_001",
      error: { code: "INVALID_REQUEST", retryable: false },
    });
  });
});

describe("POST /v1/evaluate upstream error mapping", () => {
  it.each([
    [new GitHubApiError("GITHUB_NOT_FOUND", "private detail"), 404, "ISSUE_NOT_FOUND", false],
    [
      new GitHubApiError("GITHUB_RATE_LIMITED", "private detail", {
        rateLimit: {
          limit: 60,
          remaining: 0,
          resetAt: null,
          retryAfterSeconds: 30,
        },
      }),
      429,
      "GITHUB_RATE_LIMITED",
      true,
    ],
    [new GitHubApiError("GITHUB_TIMEOUT", "private detail"), 504, "UPSTREAM_TIMEOUT", true],
    [new GitHubApiError("GITHUB_UPSTREAM_ERROR", "private detail"), 500, "EVALUATION_FAILED", false],
    [new Error("server-secret-token"), 500, "EVALUATION_FAILED", false],
  ] as const)("maps an upstream error to HTTP %i and %s", async (error, status, code, retryable) => {
    const app = await appWithClient(clientWithResult(error));
    const response = await app.inject({
      method: "POST",
      url: "/v1/evaluate",
      payload: { issue_url: "https://github.com/openai/example/issues/42" },
    });

    expect(response.statusCode).toBe(status);
    const body = errorResponseSchema.parse(response.json());
    expect(body).toMatchObject({ error: { code, retryable } });
    expect(response.body).not.toContain("private detail");
    expect(response.body).not.toContain("server-secret-token");
    if (status === 429) expect(response.headers["retry-after"]).toBe("30");
  });
});
