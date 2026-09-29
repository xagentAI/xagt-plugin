import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, type HealthResponse } from "@/app/health/route";
import { resetConfigCache } from "@/lib/config";
import { REQUEST_ID_HEADER } from "@/lib/http";

const SHA = "0123456789abcdef0123456789abcdef01234567";

describe("GET /health", () => {
  beforeEach(() => {
    resetConfigCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    resetConfigCache();
  });

  it("reports ok with a null commit outside a deployment", async () => {
    vi.stubEnv("VERCEL_ENV", "");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "");
    const response = await GET(new Request("http://localhost/health"));
    expect(response.status).toBe(200);
    expect(response.headers.get(REQUEST_ID_HEADER)).toMatch(/^req_/);
    expect(response.headers.get("cache-control")).toBe("no-store");

    const body = (await response.json()) as HealthResponse;
    expect(body).toEqual({
      status: "ok",
      service: "settle",
      environment: "test",
      commit: null,
      timestamp: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/) as string,
    });
  });

  it("exposes the exact deployed commit and environment on Vercel", async () => {
    vi.stubEnv("VERCEL_ENV", "production");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", SHA);
    const response = await GET(new Request("http://localhost/health"));
    const body = (await response.json()) as HealthResponse;
    expect(body.commit).toBe(SHA);
    expect(body.environment).toBe("production");
  });

  it("returns a 500 error envelope when configuration is invalid", async () => {
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "not-a-sha");
    const response = await GET(new Request("http://localhost/health"));
    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({
      error: { code: "INTERNAL_ERROR", message: "Server configuration is invalid", retryable: false },
    });
  });
});
