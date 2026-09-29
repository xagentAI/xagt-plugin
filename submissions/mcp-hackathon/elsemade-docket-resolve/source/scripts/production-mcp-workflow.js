import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import { join } from "node:path";

import { Client, StreamableHTTPClientTransport } from "@modelcontextprotocol/client";

import { FixtureReviewProvider } from "../src/ai/providers.js";
import { createAuthConfig } from "../src/auth.js";
import { createRequestHandler } from "../src/http.js";
import { CaseStore } from "../src/persistence/store.js";

const TOKEN = "agent-production-demo-token";
const tenantId = "tenant-production-demo";
const evidenceByUri = new Map();

function evidence(id, criterionId, content) {
  const uri = `https://evidence.example.test/${id}.txt`;
  const digest = `sha256:${createHash("sha256").update(content).digest("hex")}`;
  evidenceByUri.set(uri, content);
  return { id, criterionId, kind: "artifact", uri, digest, result: "pass" };
}

const agreement = {
  agreementId: "production-mcp-demo-001",
  amountAtomic: 250_000_000,
  asset: { symbol: "USDC", decimals: 6 },
  policy: { conflictSpread: 35, criticalFailureCapPercent: 20 },
  criteria: [
    { id: "api-live", description: "Production API is reachable.", weight: 50, critical: true, minimumEvidence: 1 },
    { id: "docs", description: "A new agent can reproduce one real call.", weight: 30, critical: false, minimumEvidence: 1 },
    { id: "edge-cases", description: "Invalid inputs fail safely.", weight: 20, critical: false, minimumEvidence: 1 },
  ],
  evidence: [
    evidence("ev-api-live", "api-live", "FIXTURE_SCORE: 100\nSmoke test passed."),
    evidence("ev-docs", "docs", "FIXTURE_SCORE: 90\nThe documented call reproduced."),
    evidence("ev-edge-cases", "edge-cases", "FIXTURE_SCORE: 75\nMalformed inputs fail safely."),
  ],
  findings: [],
};

const directory = await mkdtemp(join(os.tmpdir(), "docket-mcp-demo-"));
const server = createServer(createRequestHandler({
  commit: "f".repeat(40),
  slug: "elsemade-docket-resolve",
  auth: createAuthConfig({
    DOCKET_AUTH_MODE: "required",
    DOCKET_AUTH_TOKENS: JSON.stringify({
      [TOKEN]: { tenantId, subject: "production-demo-agent", scopes: ["*"] },
    }),
  }),
  store: new CaseStore({ filePath: join(directory, "cases.json") }),
  reviewProvider: new FixtureReviewProvider(),
  evidenceFetcher: async (url) => new Response(evidenceByUri.get(url.toString()), {
    status: 200,
    headers: { "content-type": "text/plain" },
  }),
  evidenceAllowHosts: ["evidence.example.test"],
  evidenceResolver: async () => [{ address: "93.184.216.34", family: 4 }],
}));

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const client = new Client({ name: "docket-production-demo-agent", version: "1.0.0" });

try {
  await client.connect(new StreamableHTTPClientTransport(new URL(`${origin}/mcp`), {
    authProvider: { token: async () => TOKEN },
  }));
  const created = await client.callTool({
    name: "docket_create_case",
    arguments: { agreement, idempotencyKey: "demo-create-1" },
  });
  const caseId = created.structuredContent.case.caseId;
  const retrieved = await client.callTool({
    name: "docket_retrieve_evidence",
    arguments: { caseId, idempotencyKey: "demo-retrieve-1" },
  });
  const reviewed = await client.callTool({
    name: "docket_review_persisted_case",
    arguments: { caseId, idempotencyKey: "demo-review-1" },
  });
  const resolved = await client.callTool({
    name: "docket_resolve_case",
    arguments: { caseId, idempotencyKey: "demo-resolve-1" },
  });
  const stored = await client.callTool({ name: "docket_get_case", arguments: { caseId } });

  console.log(JSON.stringify({
    mode: "production-like",
    authenticatedTenant: tenantId,
    caseId,
    evidenceVerified: retrieved.structuredContent.retrieval.items.map((item) => item.id),
    reviewReady: reviewed.structuredContent.readyToResolve,
    decision: resolved.structuredContent.decision,
    recommendedReleaseAtomic: resolved.structuredContent.recommendedReleaseAtomic,
    recommendedHoldAtomic: resolved.structuredContent.recommendedHoldAtomic,
    recommendationOnly: resolved.structuredContent.recommendationOnly,
    fundsMoved: resolved.structuredContent.fundsMoved,
    eventTypes: stored.structuredContent.events.map((event) => event.type),
  }, null, 2));
} finally {
  await client.close();
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  await rm(directory, { recursive: true, force: true });
}
