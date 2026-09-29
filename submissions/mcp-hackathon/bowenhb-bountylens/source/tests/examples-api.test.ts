import { afterEach, describe, expect, it } from "vitest";

import { buildApp } from "../src/app.js";
import type { AppConfig } from "../src/config.js";
import { exampleIds } from "../src/routes/examples.js";
import { errorResponseSchema } from "../src/schemas/error.js";
import { evaluateResponseSchema } from "../src/schemas/response.js";

const config: AppConfig = {
  nodeEnv: "test",
  host: "127.0.0.1",
  port: 3_000,
  githubToken: undefined,
  sourceCommit: "0".repeat(40),
  projectSlug: "bountylens",
  cacheTtlSeconds: 300,
  requestTimeoutMs: 10_000,
};

const openedApps: Awaited<ReturnType<typeof buildApp>>[] = [];

afterEach(async () => {
  await Promise.all(openedApps.splice(0).map((app) => app.close()));
});

async function buildTestApp() {
  let requestSequence = 0;
  const app = await buildApp(config, {
    createRequestId: () => `req_example_${++requestSequence}`,
  });
  openedApps.push(app);
  return app;
}

describe("GET /v1/examples/:exampleId", () => {
  it("serves all documented examples without GitHub access", async () => {
    const app = await buildTestApp();

    for (const exampleId of exampleIds) {
      const response = await app.inject({
        method: "GET",
        url: `/v1/examples/${exampleId}`,
      });
      expect(response.statusCode).toBe(200);
      expect(evaluateResponseSchema.parse(response.json()).issue.url).toMatch(
        /^https:\/\/github\.com\//,
      );
    }
  });

  it("returns the unified 404 response for an unknown example", async () => {
    const app = await buildTestApp();
    const response = await app.inject({
      method: "GET",
      url: "/v1/examples/unknown",
    });

    expect(response.statusCode).toBe(404);
    expect(errorResponseSchema.parse(response.json())).toMatchObject({
      error: { code: "EXAMPLE_NOT_FOUND", retryable: false },
    });
  });
});
