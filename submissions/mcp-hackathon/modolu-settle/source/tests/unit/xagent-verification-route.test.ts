import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/.well-known/xagent-verification.json/route";
import { GET as GET_HEALTH } from "@/app/health/route";
import { resetConfigCache } from "@/lib/config";
import { REQUEST_ID_HEADER } from "@/lib/http";

const SHA = "0123456789abcdef0123456789abcdef01234567";

function verification(): Promise<Response> {
  return GET(new Request("http://localhost/.well-known/xagent-verification.json"));
}

describe("GET /.well-known/xagent-verification.json", () => {
  beforeEach(() => {
    resetConfigCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    resetConfigCache();
  });

  it("returns exactly { schemaVersion: 1, slug: 'modolu-settle', commit } for a valid deployment", async () => {
    vi.stubEnv("XAGENT_SLUG", "modolu-settle");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", SHA);
    const response = await verification();
    expect(response.status).toBe(200);
    expect(response.headers.get(REQUEST_ID_HEADER)).toMatch(/^req_/);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toEqual({ schemaVersion: 1, slug: "modolu-settle", commit: SHA });
    expect(Object.keys(body)).toEqual(["schemaVersion", "slug", "commit"]);
  });

  it("reports the same commit as /health, from the same VERCEL_GIT_COMMIT_SHA", async () => {
    vi.stubEnv("XAGENT_SLUG", "modolu-settle");
    vi.stubEnv("VERCEL_ENV", "production");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", SHA);
    const health = (await (await GET_HEALTH(new Request("http://localhost/health"))).json()) as { commit: string };
    const proof = (await (await verification()).json()) as { commit: string };
    expect(proof.commit).toBe(SHA);
    expect(health.commit).toBe(proof.commit);
  });

  it("returns 500 rather than fabricated data when the slug is missing", async () => {
    vi.stubEnv("XAGENT_SLUG", "");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", SHA);
    const response = await verification();
    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: "INTERNAL_ERROR",
        message: "X-Agent verification is not configured: missing XAGENT_SLUG",
        retryable: false,
      },
    });
  });

  it("returns 500 when the configured slug is not modolu-settle", async () => {
    vi.stubEnv("XAGENT_SLUG", "settle");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", SHA);
    const response = await verification();
    expect(response.status).toBe(500);
    const body = (await response.json()) as { error: { code: string; message: string } };
    expect(body.error.code).toBe("INTERNAL_ERROR");
    expect(body.error.message).toContain('XAGENT_SLUG must be "modolu-settle"');
  });

  it("returns 500 rather than fabricated data when the commit is missing", async () => {
    vi.stubEnv("XAGENT_SLUG", "modolu-settle");
    vi.stubEnv("VERCEL_GIT_COMMIT_SHA", "");
    const response = await verification();
    expect(response.status).toBe(500);
    const body = (await response.json()) as { error: { code: string; message: string } };
    expect(body.error.code).toBe("INTERNAL_ERROR");
    expect(body.error.message).toContain("VERCEL_GIT_COMMIT_SHA");
  });

  it.each(["abc123", "0123456789ABCDEF0123456789ABCDEF01234567", `${SHA}0`, "not a sha"])(
    "returns 500 for a malformed commit %s (both routes share the validated value)",
    async (malformed) => {
      vi.stubEnv("XAGENT_SLUG", "modolu-settle");
      vi.stubEnv("VERCEL_GIT_COMMIT_SHA", malformed);
      const response = await verification();
      expect(response.status).toBe(500);
      const body = (await response.json()) as { error: { code: string } };
      expect(body.error.code).toBe("INTERNAL_ERROR");
      expect(JSON.stringify(body)).not.toContain(malformed);
      expect((await GET_HEALTH(new Request("http://localhost/health"))).status).toBe(500);
    },
  );
});
