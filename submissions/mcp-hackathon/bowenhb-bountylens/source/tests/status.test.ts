import { afterEach, describe, expect, it } from "vitest";

import { buildApp } from "../src/app.js";
import { loadConfig, type AppConfig } from "../src/config.js";
import {
  healthResponseSchema,
  verificationResponseSchema,
} from "../src/schemas/status.js";

const temporaryCommit = "0123456789abcdef0123456789abcdef01234567";
const openedApps: Awaited<ReturnType<typeof buildApp>>[] = [];

afterEach(async () => {
  await Promise.all(openedApps.splice(0).map((app) => app.close()));
});

describe("SOURCE_COMMIT configuration", () => {
  it("reads an explicit 40-character commit in production", () => {
    expect(
      loadConfig({ NODE_ENV: "production", SOURCE_COMMIT: temporaryCommit }).sourceCommit,
    ).toBe(temporaryCommit);
  });

  it("uses Render's immutable deploy commit when SOURCE_COMMIT is absent", () => {
    expect(
      loadConfig({ NODE_ENV: "production", RENDER_GIT_COMMIT: temporaryCommit })
        .sourceCommit,
    ).toBe(temporaryCommit);
  });

  it("prefers an explicit SOURCE_COMMIT over platform metadata", () => {
    const explicitCommit = "abcdef0123456789abcdef0123456789abcdef01";

    expect(
      loadConfig({
        NODE_ENV: "production",
        SOURCE_COMMIT: explicitCommit,
        RENDER_GIT_COMMIT: temporaryCommit,
      }).sourceCommit,
    ).toBe(explicitCommit);
  });

  it.each(["abc", "g".repeat(40), "0".repeat(39), "0".repeat(41)])(
    "rejects an invalid production commit: %s",
    (sourceCommit) => {
      expect(() =>
        loadConfig({ NODE_ENV: "production", SOURCE_COMMIT: sourceCommit }),
      ).toThrow();
    },
  );

  it("rejects the development placeholder in production", () => {
    expect(() => loadConfig({ NODE_ENV: "production" })).toThrow(
      /reviewed source commit/i,
    );
  });

  it("keeps the all-zero placeholder available outside production", () => {
    expect(loadConfig({ NODE_ENV: "development" }).sourceCommit).toBe("0".repeat(40));
  });
});

describe("public status endpoints", () => {
  it("returns the same configured commit from health and verification", async () => {
    const config: AppConfig = {
      nodeEnv: "test",
      host: "127.0.0.1",
      port: 3_000,
      githubToken: undefined,
      sourceCommit: temporaryCommit,
      projectSlug: "bountylens",
      cacheTtlSeconds: 300,
      requestTimeoutMs: 10_000,
    };
    const app = await buildApp(config, { createRequestId: () => "req_status_test" });
    openedApps.push(app);

    const [healthResult, verificationResult] = await Promise.all([
      app.inject({ method: "GET", url: "/health" }),
      app.inject({ method: "GET", url: "/.well-known/xagent-verification.json" }),
    ]);

    expect(healthResult.statusCode).toBe(200);
    expect(verificationResult.statusCode).toBe(200);
    expect(healthResult.headers["content-type"]).toContain("application/json");
    expect(verificationResult.headers["content-type"]).toContain("application/json");
    expect(healthResult.headers["x-request-id"]).toBe("req_status_test");
    expect(verificationResult.headers["x-request-id"]).toBe("req_status_test");

    const health = healthResponseSchema.parse(healthResult.json());
    const verification = verificationResponseSchema.parse(verificationResult.json());
    expect(health).toEqual({ status: "ok", commit: temporaryCommit });
    expect(verification).toEqual({
      schemaVersion: 1,
      slug: "bountylens",
      commit: temporaryCommit,
    });
    expect(health.commit).toBe(verification.commit);
  });
});
