import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import { FixtureReviewProvider } from "../src/ai/providers.js";
import { createRequestHandler } from "../src/http.js";

const commit = "c".repeat(40);

async function withServer(run, options = {}) {
  const server = createServer(
    createRequestHandler({
      commit,
      slug: "elsemade-docket-resolve",
      allowedOrigin: "*",
      reviewProvider: new FixtureReviewProvider(),
      ...options,
    }),
  );
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const origin = `http://127.0.0.1:${address.port}`;
  try {
    await run(origin);
  } finally {
    await new Promise((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
}

function agreement() {
  return {
    agreementId: "agreement_http_001",
    amountAtomic: 50_000_000,
    asset: { symbol: "USDC", decimals: 6 },
    criteria: [
      {
        id: "delivery",
        description: "The requested artifact was delivered.",
        weight: 100,
        critical: true,
        minimumEvidence: 1,
      },
    ],
    evidence: [
      {
        id: "e_delivery",
        criterionId: "delivery",
        kind: "receipt",
        uri: "https://example.com/receipt.json",
        digest: `sha256:${"d".repeat(64)}`,
        result: "pass",
      },
    ],
    findings: [
      {
        id: "f_delivery",
        criterionId: "delivery",
        evaluator: "reviewer-a",
        score: 100,
        confidence: 1,
        evidenceIds: ["e_delivery"],
        rationale: "Receipt matches the agreed artifact.",
      },
    ],
  };
}

test("health binds the deployment to the reviewed commit", async () => {
  await withServer(async (origin) => {
    const response = await fetch(`${origin}/health`);
    assert.equal(response.status, 200);
    assert.match(response.headers.get("x-request-id"), /^[a-f0-9-]{36}$/);
    assert.deepEqual(await response.json(), { status: "ok", commit });
  });
});

test("serves the X-Agent deployment proof from the same origin", async () => {
  await withServer(async (origin) => {
    const response = await fetch(
      `${origin}/.well-known/xagent-verification.json`,
    );
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      schemaVersion: 1,
      slug: "elsemade-docket-resolve",
      commit,
    });
  });
});

test("serves the controlled demo evidence as a reachable public fixture", async () => {
  await withServer(async (origin) => {
    const response = await fetch(`${origin}/fixtures/evidence/ev-smoke.txt`);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("content-type"), "text/plain; charset=utf-8");
    assert.match(await response.text(), /FIXTURE_SCORE: 100/);
  });
});

test("ships local example URLs that match the fixture evidence provider", async () => {
  await withServer(async (origin) => {
    const response = await fetch(`${origin}/app.js`);
    const source = await response.text();
    assert.equal(response.status, 200);
    assert.match(source, /https:\/\/evidence\.example\.test\/\$\{name\}\.txt/);
    assert.doesNotMatch(source, /evidence\.example\.test\/fixtures\/evidence/);
  });
});

test("evaluates a valid agreement over HTTP", async () => {
  await withServer(async (origin) => {
    const response = await fetch(`${origin}/v1/evaluations`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(agreement()),
    });
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.decision, "release_full");
    assert.equal(body.recommendedReleaseAtomic, 50_000_000);
  });
});

test("reviews evidence over HTTP without giving the reviewer payment authority", async () => {
  await withServer(async (origin) => {
    const input = agreement();
    input.findings = [];
    const response = await fetch(`${origin}/v1/reviews`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        agreement: input,
        evidenceContent: [{ id: "e_delivery", content: "The artifact is present." }],
      }),
    });
    const body = await response.json();

    assert.equal(response.status, 200);
    assert.equal(body.readyToResolve, true);
    assert.equal(body.findings[0].evidenceIds[0], "e_delivery");
    assert.equal("recommendedReleaseAtomic" in body, false);
  });
});

test("rate limits unauthenticated public review requests", async () => {
  await withServer(async (origin) => {
    const input = agreement();
    input.findings = [];
    const request = () => fetch(`${origin}/v1/reviews`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ agreement: input, evidenceContent: [{ id: "e_delivery", content: "The artifact is present." }] }),
    });

    assert.equal((await request()).status, 200);
    const limited = await fetch(`${origin}/v1/evaluations`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(agreement()),
    });
    assert.equal(limited.status, 429);
    assert.equal(limited.headers.get("retry-after"), "60");
    assert.equal((await limited.json()).error.code, "RATE_LIMITED");
  }, { publicRateLimitPerMinute: 1 });
});

test("returns structured errors for invalid agreements", async () => {
  await withServer(async (origin) => {
    const invalid = agreement();
    invalid.criteria[0].weight = 90;
    const response = await fetch(`${origin}/v1/evaluations`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(invalid),
    });
    const body = await response.json();

    assert.equal(response.status, 422);
    assert.equal(body.error.code, "INVALID_CRITERIA_WEIGHT_TOTAL");
    assert.equal(typeof body.error.requestId, "string");
  });
});

test("rejects malformed JSON without exposing internals", async () => {
  await withServer(async (origin) => {
    const response = await fetch(`${origin}/v1/evaluations`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{not-json",
    });
    const body = await response.json();

    assert.equal(response.status, 400);
    assert.deepEqual(Object.keys(body.error).sort(), [
      "code",
      "message",
      "requestId",
    ]);
    assert.equal(body.error.code, "INVALID_JSON");
  });
});

test("rejects oversized bodies with a structured response", async () => {
  await withServer(async (origin) => {
    const response = await fetch(`${origin}/v1/evaluations`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ padding: "x".repeat(256 * 1024) }),
    });
    const body = await response.json();

    assert.equal(response.status, 413);
    assert.equal(body.error.code, "PAYLOAD_TOO_LARGE");
  });
});

test("publishes an OpenAPI document and explicit 404s", async () => {
  await withServer(async (origin) => {
    const schemaResponse = await fetch(`${origin}/openapi.json`, { headers: { "x-forwarded-proto": "https" } });
    const schema = await schemaResponse.json();
    assert.equal(schemaResponse.status, 200);
    assert.equal(schema.openapi, "3.1.0");
    assert.ok(schema.paths["/v1/evaluations"]);
    assert.match(schema.servers[0].url, /^https:\/\//);

    const missingResponse = await fetch(`${origin}/missing`);
    const missing = await missingResponse.json();
    assert.equal(missingResponse.status, 404);
    assert.equal(missing.error.code, "NOT_FOUND");
  });
});

test("returns a structured error for malformed case identifiers", async () => {
  await withServer(async (origin) => {
    const response = await fetch(`${origin}/v1/cases/%E0%A4%A`);
    const body = await response.json();
    assert.equal(response.status, 400);
    assert.equal(body.error.code, "INVALID_CASE_ID");
  });
});

test("serves the reviewer-facing evaluation workspace", async () => {
  await withServer(async (origin) => {
    const response = await fetch(origin);
    const html = await response.text();

    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type"), /^text\/html/);
    assert.match(html, /Docket Resolve/);
    assert.match(html, /Open case/);
    assert.match(html, /Review evidence/);
    assert.match(html, /Retrieval failures/);
  });
});
