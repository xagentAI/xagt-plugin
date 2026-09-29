import { expect, test } from "@playwright/test";

/** Request-level checks against the real server (no browser page needed). */
test.describe("public API hardening", () => {
  test("health and verification are uncacheable, hardened, and share the commit", async ({ request }) => {
    const health = await request.get("/health");
    expect(health.status()).toBe(200);
    expect(health.headers()["cache-control"]).toBe("no-store");
    expect(health.headers()["x-content-type-options"]).toBe("nosniff");
    expect(health.headers()["referrer-policy"]).toBe("no-referrer");
    const proof = await request.get("/.well-known/xagent-verification.json");
    expect(proof.status()).toBe(200);
    const body = (await proof.json()) as Record<string, unknown>;
    expect(Object.keys(body)).toEqual(["schemaVersion", "slug", "commit"]);
    expect(body).toMatchObject({ schemaVersion: 1, slug: "modolu-settle" });
    expect(body["commit"]).toBe(((await health.json()) as { commit: string }).commit);
    expect(body["commit"]).toMatch(/^[0-9a-f]{40}$/);
  });

  test("there is no way to list intents", async ({ request }) => {
    expect((await request.get("/v1/payment-intents")).status()).toBe(405);
  });

  test("malformed IDs are rejected with the stable envelope before any database access", async ({ request }) => {
    for (const path of ["/v1/payment-intents/nope", "/v1/payment-intents/nope/evidence"]) {
      const response = await request.get(path);
      expect(response.status()).toBe(400);
      expect(await response.json()).toEqual({
        error: { code: "VALIDATION_ERROR", message: "id must be a payment intent ID of the form pi_<32 url-safe characters>", retryable: false },
      });
      expect(response.headers()["cache-control"]).toBe("no-store");
    }
    expect((await request.post("/v1/payment-intents/nope/reconcile")).status()).toBe(400);
  });

  test("request bodies are bounded at 16 KiB and reconcile takes none", async ({ request }) => {
    const oversized = await request.post("/v1/payment-intents", {
      headers: { "content-type": "application/json" },
      data: `{"externalReference":"${"x".repeat(17_000)}"}`,
    });
    expect(oversized.status()).toBe(400);
    expect(((await oversized.json()) as { error: { message: string } }).error.message).toMatch(/must not exceed 16384 bytes/);

    const withBody = await request.post("/v1/payment-intents/pi_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/reconcile", {
      headers: { "content-type": "application/json" },
      data: "{}",
    });
    expect(withBody.status()).toBe(400);
    expect(((await withBody.json()) as { error: { message: string } }).error.message).toMatch(/does not accept a request body/);

    const wrongType = await request.post("/v1/payment-intents", { headers: { "content-type": "text/plain" }, data: "hello" });
    expect(wrongType.status()).toBe(400);
  });

  test("errors never come back as HTML or with CORS wildcards", async ({ request }) => {
    const response = await request.post("/v1/payment-intents", { headers: { "content-type": "application/json" }, data: "{not json" });
    expect(response.status()).toBe(400);
    expect(response.headers()["content-type"]).toContain("application/json");
    expect(response.headers()["access-control-allow-origin"]).toBeUndefined();
    expect(response.headers()["x-request-id"]).toMatch(/^req_/);
  });
});
