import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import { join } from "node:path";
import test from "node:test";

import { FixtureReviewProvider } from "../src/ai/providers.js";
import { createAuthConfig } from "../src/auth.js";
import { createRequestHandler } from "../src/http.js";
import { CaseStore } from "../src/persistence/store.js";

test("authenticated HTTP case journey survives the full production lifecycle", async () => {
  const directory = await mkdtemp(join(os.tmpdir(), "docket-e2e-"));
  const content = "FIXTURE_SCORE: 80\nThe artifact is complete enough for a partial release.";
  const agreement = {
    agreementId: "http_e2e_001",
    amountAtomic: 100_000_000,
    asset: { symbol: "USDC", decimals: 6 },
    criteria: [{ id: "delivery", description: "The artifact was delivered.", weight: 100, critical: true, minimumEvidence: 1 }],
    evidence: [{ id: "e_delivery", criterionId: "delivery", kind: "artifact", uri: "https://evidence.example.test/e2e.txt", digest: `sha256:${createHash("sha256").update(content).digest("hex")}`, result: "pass" }],
    findings: [],
  };
  const fixtureProvider = new FixtureReviewProvider();
  let reviewCalls = 0;
  const reviewProvider = {
    name: fixtureProvider.name,
    model: fixtureProvider.model,
    promptVersion: fixtureProvider.promptVersion,
    schemaVersion: fixtureProvider.schemaVersion,
    reviewCriterion: async (...args) => {
      reviewCalls += 1;
      return fixtureProvider.reviewCriterion(...args);
    },
  };
  const server = createServer(createRequestHandler({
    commit: "a".repeat(40),
    slug: "elsemade-docket-resolve",
    auth: createAuthConfig({
      DOCKET_AUTH_MODE: "required",
      DOCKET_AUTH_TOKENS: JSON.stringify({
        "e2e-agent-token": { tenantId: "tenant-e2e", subject: "e2e-agent", scopes: ["*"] },
        "other-agent-token": { tenantId: "tenant-other", subject: "other-agent", scopes: ["*"] },
      }),
    }),
    store: new CaseStore({ filePath: join(directory, "cases.json") }),
    reviewProvider,
    evidenceFetcher: async () => new Response(content, { status: 200 }),
    evidenceAllowHosts: ["evidence.example.test"],
    evidenceResolver: async () => [{ address: "93.184.216.34", family: 4 }],
  }));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const headers = { authorization: "Bearer e2e-agent-token", "content-type": "application/json" };
  try {
    const unauthorized = await fetch(`${origin}/v1/cases`);
    assert.equal(unauthorized.status, 401);

    const preflight = await fetch(`${origin}/v1/cases`, { method: "OPTIONS", headers: { origin: "http://localhost:4173", "access-control-request-method": "POST", "access-control-request-headers": "authorization, content-type, idempotency-key" } });
    assert.equal(preflight.status, 204);
    assert.match(preflight.headers.get("access-control-allow-headers"), /authorization/);

    const missingIdempotency = await fetch(`${origin}/v1/cases`, { method: "POST", headers, body: JSON.stringify({ agreement }) });
    assert.equal(missingIdempotency.status, 400);
    assert.equal((await missingIdempotency.json()).error.code, "IDEMPOTENCY_KEY_REQUIRED");

    const createdResponse = await fetch(`${origin}/v1/cases`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-create" }, body: JSON.stringify({ agreement }) });
    assert.equal(createdResponse.status, 201);
    const created = await createdResponse.json();
    const caseId = created.case.caseId;

    const replayResponse = await fetch(`${origin}/v1/cases`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-create" }, body: JSON.stringify({ agreement }) });
    assert.equal((await replayResponse.json()).replayed, true);

    const retrievalResponse = await fetch(`${origin}/v1/cases/${caseId}/retrieve`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-retrieve" } });
    assert.equal((await retrievalResponse.json()).retrieval.items[0].verified, true);

    const reviewResponse = await fetch(`${origin}/v1/cases/${caseId}/review`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-review" } });
    const review = await reviewResponse.json();
    assert.equal(review.readyToResolve, true);
    assert.equal(reviewCalls, 1);

    const reviewReplayResponse = await fetch(`${origin}/v1/cases/${caseId}/review`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-review" } });
    const reviewReplay = await reviewReplayResponse.json();
    assert.equal(reviewReplay.replayed, true);
    assert.equal(reviewCalls, 1);

    const reviewedResponse = await fetch(`${origin}/v1/cases/${caseId}`, { headers: { authorization: "Bearer e2e-agent-token" } });
    assert.equal((await reviewedResponse.json()).evaluation, null);

    const resolutionResponse = await fetch(`${origin}/v1/cases/${caseId}/resolve`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-resolve" } });
    const resolution = await resolutionResponse.json();
    assert.equal(resolution.recommendedReleaseAtomic, 80_000_000);
    assert.equal(resolution.recommendedHoldAtomic, 20_000_000);
    assert.equal(resolution.fundsMoved, false);

    const resolutionReplayResponse = await fetch(`${origin}/v1/cases/${caseId}/resolve`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-resolve" } });
    const resolutionReplay = await resolutionReplayResponse.json();
    assert.equal(resolutionReplayResponse.status, 200);
    assert.equal(resolutionReplay.persisted.replayed, true);

    const duplicateResolutionResponse = await fetch(`${origin}/v1/cases/${caseId}/resolve`, { method: "POST", headers: { ...headers, "idempotency-key": "e2e-resolve-again" } });
    const duplicateResolution = await duplicateResolutionResponse.json();
    assert.equal(duplicateResolutionResponse.status, 409);
    assert.equal(duplicateResolution.error.code, "CASE_ALREADY_RESOLVED");

    const persisted = await fetch(`${origin}/v1/cases/${caseId}`, { headers: { authorization: "Bearer e2e-agent-token" } });
    const record = await persisted.json();
    assert.deepEqual(record.events.map((event) => event.type), ["case.created", "evidence.retrieved", "case.reviewed", "case.resolved"]);

    const crossTenant = await fetch(`${origin}/v1/cases/${caseId}`, { headers: { authorization: "Bearer other-agent-token" } });
    assert.equal(crossTenant.status, 404);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    await rm(directory, { recursive: true, force: true });
  }
});

test("HTTP resolution fails closed when review requires a human decision", async () => {
  const directory = await mkdtemp(join(os.tmpdir(), "docket-e2e-manual-"));
  const uncertainProvider = {
    name: "test-reviewer",
    model: "test-model",
    promptVersion: "test-v1",
    reviewCriterion: async ({ criterion }) => ({
      schemaVersion: 1,
      criterionId: criterion.id,
      verdict: "insufficient_evidence",
      score: null,
      confidence: 0.2,
      evidenceCitations: [],
      missingEvidence: ["A human needs to supply stronger evidence."],
      contradictions: [],
      rationale: "The supplied evidence is not sufficient for an automated decision.",
      requirementsApplied: [criterion.description],
      requirementsRejected: [],
    }),
  };
  const agreement = {
    agreementId: "http_e2e_manual_001",
    amountAtomic: 100_000_000,
    asset: { symbol: "USDC", decimals: 6 },
    criteria: [{ id: "delivery", description: "The artifact was delivered.", weight: 100, critical: true, minimumEvidence: 1 }],
    evidence: [{ id: "e_delivery", criterionId: "delivery", kind: "artifact", uri: "https://evidence.example.test/e2e.txt", digest: `sha256:${"a".repeat(64)}`, result: "pass" }],
    findings: [],
  };
  const server = createServer(createRequestHandler({
    commit: "b".repeat(40),
    slug: "elsemade-docket-resolve",
    auth: createAuthConfig({
      DOCKET_AUTH_MODE: "required",
      DOCKET_AUTH_TOKENS: JSON.stringify({ "manual-agent-token": { tenantId: "tenant-manual", subject: "manual-agent", scopes: ["*"] } }),
    }),
    store: new CaseStore({ filePath: join(directory, "cases.json") }),
    reviewProvider: uncertainProvider,
  }));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const headers = { authorization: "Bearer manual-agent-token", "content-type": "application/json" };
  try {
    const createdResponse = await fetch(`${origin}/v1/cases`, { method: "POST", headers: { ...headers, "idempotency-key": "manual-create" }, body: JSON.stringify({ agreement }) });
    const created = await createdResponse.json();
    const caseId = created.case.caseId;
    const reviewResponse = await fetch(`${origin}/v1/cases/${caseId}/review`, { method: "POST", headers: { ...headers, "idempotency-key": "manual-review" }, body: "{}" });
    const review = await reviewResponse.json();
    assert.equal(review.readyToResolve, false);

    const reviewedRecordResponse = await fetch(`${origin}/v1/cases/${caseId}`, { headers: { authorization: "Bearer manual-agent-token" } });
    assert.equal((await reviewedRecordResponse.json()).evaluation, null);

    const resolutionResponse = await fetch(`${origin}/v1/cases/${caseId}/resolve`, { method: "POST", headers: { ...headers, "idempotency-key": "manual-resolve" } });
    const resolution = await resolutionResponse.json();
    assert.equal(resolutionResponse.status, 409);
    assert.equal(resolution.error.code, "CASE_REVIEW_NOT_READY");
  } finally {
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    await rm(directory, { recursive: true, force: true });
  }
});
