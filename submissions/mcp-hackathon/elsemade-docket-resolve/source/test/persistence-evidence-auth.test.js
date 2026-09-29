import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import { join } from "node:path";
import test from "node:test";

import { authenticate, createAuthConfig } from "../src/auth.js";
import {
  fixtureEvidenceAllowHosts,
  fixtureEvidenceFetcher,
  fixtureEvidenceResolver,
} from "../src/evidence/fixture.js";
import { EvidenceRetrievalError, retrieveAgreementEvidence, retrieveEvidenceItem } from "../src/evidence/retrieve.js";
import { CaseStore } from "../src/persistence/store.js";

function agreement() {
  return {
    agreementId: "persistent_case_001",
    amountAtomic: 100_000_000,
    asset: { symbol: "USDC", decimals: 6 },
    criteria: [{ id: "delivery", description: "Artifact delivered.", weight: 100, critical: true, minimumEvidence: 1 }],
    evidence: [{
      id: "e_delivery",
      criterionId: "delivery",
      kind: "artifact",
      uri: "https://evidence.example.test/delivery.txt",
      digest: `sha256:${"a".repeat(64)}`,
      result: "pass",
    }],
    findings: [],
  };
}

test("auth resolves a bearer token to one tenant and rejects unknown tokens", () => {
  const config = createAuthConfig({
    DOCKET_AUTH_MODE: "required",
    DOCKET_AUTH_TOKENS: JSON.stringify({
      "demo-agent-token-123": { tenantId: "tenant-a", subject: "agent-a", scopes: ["*"] },
    }),
  });
  const identity = authenticate({ headers: { authorization: "Bearer demo-agent-token-123" } }, config);
  assert.deepEqual(identity.tenantId, "tenant-a");
  assert.throws(
    () => authenticate({ headers: { authorization: "Bearer other-token-123" } }, config),
    (error) => error.code === "AUTH_INVALID",
  );
});

test("case store persists idempotent lifecycle events and isolates tenants", async () => {
  const directory = await mkdtemp(join(os.tmpdir(), "docket-store-"));
  const filePath = join(directory, "cases.json");
  try {
    const store = new CaseStore({ filePath });
    const first = await store.createCase({ tenantId: "tenant-a", subject: "agent-a", agreement: agreement(), idempotencyKey: "create-1" });
    const replay = await store.createCase({ tenantId: "tenant-a", subject: "agent-a", agreement: agreement(), idempotencyKey: "create-1" });
    assert.equal(first.case.caseId, replay.case.caseId);
    assert.equal(replay.replayed, true);
    await assert.rejects(
      store.createCase({ tenantId: "tenant-a", subject: "agent-a", agreement: { ...agreement(), agreementId: "different" }, idempotencyKey: "create-1" }),
      (error) => error.code === "IDEMPOTENCY_CONFLICT",
    );
    assert.equal(await store.getCase({ tenantId: "tenant-b", caseId: first.case.caseId }), null);

    await store.saveEvidenceRetrieval({
      tenantId: "tenant-a",
      caseId: first.case.caseId,
      subject: "agent-a",
      items: [{ id: "e_delivery", content: "Artifact delivered.", verified: true }],
      errors: [],
      idempotencyKey: "retrieve-1",
    });
    const reloaded = new CaseStore({ filePath });
    const persisted = await reloaded.getCase({ tenantId: "tenant-a", caseId: first.case.caseId });
    assert.equal(persisted.evidenceContent[0].verified, true);
    assert.equal(persisted.events.length, 2);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("evidence retrieval verifies HTTPS content against the declared digest", async () => {
  const content = "artifact delivered";
  const digest = `sha256:${createHash("sha256").update(content).digest("hex")}`;
  const item = { id: "e1", uri: "https://evidence.example.test/e1.txt", digest };
  const retrieved = await retrieveEvidenceItem(item, {
    fetchImpl: async () => new Response(content, { status: 200, headers: { "content-type": "text/plain" } }),
    allowHosts: ["evidence.example.test"],
    resolveHost: async () => [{ address: "93.184.216.34", family: 4 }],
  });
  assert.equal(retrieved.content, content);
  assert.equal(retrieved.verified, true);
  await assert.rejects(
    retrieveEvidenceItem({ ...item, digest: `sha256:${"b".repeat(64)}` }, {
      fetchImpl: async () => new Response(content, { status: 200 }),
      allowHosts: ["evidence.example.test"],
      resolveHost: async () => [{ address: "93.184.216.34", family: 4 }],
    }),
    (error) => error instanceof EvidenceRetrievalError && error.code === "EVIDENCE_DIGEST_MISMATCH",
  );
  await assert.rejects(
    retrieveEvidenceItem(item, { fetchImpl: async () => new Response(content), requireAllowlist: true }),
    (error) => error instanceof EvidenceRetrievalError && error.code === "EVIDENCE_ALLOWLIST_REQUIRED",
  );
  await assert.rejects(
    retrieveEvidenceItem(item, {
      fetchImpl: async () => new Response(content),
      allowHosts: ["evidence.example.test"],
      resolveHost: async () => [{ address: "10.0.0.8", family: 4 }],
    }),
    (error) => error instanceof EvidenceRetrievalError && error.code === "EVIDENCE_HOST_BLOCKED",
  );
  await assert.rejects(
    retrieveEvidenceItem({ ...item, uri: "https://[::1]/private.txt" }, { fetchImpl: async () => new Response(content), allowHosts: ["::1"] }),
    (error) => error instanceof EvidenceRetrievalError && error.code === "EVIDENCE_HOST_BLOCKED",
  );
  await assert.rejects(
    retrieveEvidenceItem({ ...item, uri: "https://user:password@evidence.example.test/private.txt" }, { fetchImpl: async () => new Response(content), allowHosts: ["evidence.example.test"] }),
    (error) => error instanceof EvidenceRetrievalError && error.code === "EVIDENCE_URL_UNSAFE",
  );
  await assert.rejects(
    retrieveEvidenceItem({ ...item, uri: "https://evidence.example.test:8443/private.txt" }, { fetchImpl: async () => new Response(content), allowHosts: ["evidence.example.test"] }),
    (error) => error instanceof EvidenceRetrievalError && error.code === "EVIDENCE_URL_UNSAFE",
  );
});

test("all-failed evidence retrieval remains an explicit failure-handling case", async () => {
  const retrieval = await retrieveAgreementEvidence({
    evidence: [
      { id: "ev-missing-a", uri: "https://evidence.example.test/missing-a.txt", digest: `sha256:${"a".repeat(64)}` },
      { id: "ev-missing-b", uri: "https://evidence.example.test/missing-b.txt", digest: `sha256:${"b".repeat(64)}` },
      { id: "ev-missing-c", uri: "https://evidence.example.test/missing-c.txt", digest: `sha256:${"c".repeat(64)}` },
    ],
  }, {
    fetchImpl: fixtureEvidenceFetcher,
    allowHosts: fixtureEvidenceAllowHosts,
    resolveHost: fixtureEvidenceResolver,
  });

  assert.deepEqual(retrieval.items, []);
  assert.equal(retrieval.errors.length, 3);
  assert.ok(retrieval.errors.every((error) => error.code === "EVIDENCE_FETCH_FAILED"));
});
