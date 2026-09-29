import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  Client,
  InMemoryTransport,
  StreamableHTTPClientTransport,
} from "@modelcontextprotocol/client";

import { FixtureReviewProvider } from "../src/ai/providers.js";
import { createAuthConfig } from "../src/auth.js";
import { createRequestHandler } from "../src/http.js";
import { createDocketMcpServer } from "../src/mcp/server.js";
import { CaseStore } from "../src/persistence/store.js";

function agreement() {
  return {
    agreementId: "mcp_case_001",
    amountAtomic: 250_000_000,
    asset: { symbol: "USDC", decimals: 6 },
    policy: { conflictSpread: 35, criticalFailureCapPercent: 20 },
    criteria: [
      {
        id: "delivery",
        description: "The agreed artifact was delivered.",
        weight: 100,
        critical: true,
        minimumEvidence: 1,
      },
    ],
    evidence: [
      {
        id: "e_delivery",
        criterionId: "delivery",
        kind: "artifact",
        uri: "https://example.com/artifact",
        digest: `sha256:${"b".repeat(64)}`,
        result: "pass",
      },
    ],
    findings: [
      {
        id: "f_delivery",
        criterionId: "delivery",
        evaluator: "review-agent",
        score: 100,
        confidence: 1,
        evidenceIds: ["e_delivery"],
        rationale: "The artifact evidence supports delivery.",
      },
    ],
  };
}

async function connectedClient(options = {}) {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const server = createDocketMcpServer({ reviewProvider: new FixtureReviewProvider(), ...options });
  await server.connect(serverTransport);
  const client = new Client({ name: "docket-test-client", version: "1.0.0" });
  await client.connect(clientTransport);
  return { client, server };
}

async function connectedHttpClient() {
  const server = createServer(
    createRequestHandler({
      commit: "d".repeat(40),
      slug: "elsemade-docket-resolve",
      allowedOrigin: "*",
      reviewProvider: new FixtureReviewProvider(),
    }),
  );
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const origin = `http://127.0.0.1:${address.port}`;
  const client = new Client({ name: "docket-http-test-client", version: "1.0.0" });
  await client.connect(new StreamableHTTPClientTransport(new URL(`${origin}/mcp`)));
  return { client, server };
}

test("MCP client discovers Docket tools and resolves a proportional recommendation", async () => {
  const { client, server } = await connectedClient();
  try {
    const tools = await client.listTools();
    const names = tools.tools.map((tool) => tool.name).sort();
    assert.deepEqual(names, [
      "docket_create_case",
      "docket_get_case",
      "docket_resolve_case",
      "docket_retrieve_evidence",
      "docket_review_case",
      "docket_review_persisted_case",
      "docket_validate_agreement",
    ]);

    const validated = await client.callTool({
      name: "docket_validate_agreement",
      arguments: { agreement: agreement() },
    });
    assert.equal(validated.isError, undefined);
    assert.equal(validated.structuredContent.valid, true);

    const resolved = await client.callTool({
      name: "docket_resolve_case",
      arguments: { agreement: agreement() },
    });
    assert.equal(resolved.structuredContent.recommendedReleaseAtomic, 250_000_000);
    assert.equal(resolved.structuredContent.recommendedHoldAtomic, 0);
    assert.equal(resolved.structuredContent.recommendationOnly, true);
    assert.equal(resolved.structuredContent.fundsMoved, false);
  } finally {
    await client.close();
    await server.close();
  }
});

test("MCP review exposes cited findings and a safe review boundary", async () => {
  const { client, server } = await connectedClient();
  try {
    const reviewed = await client.callTool({
      name: "docket_review_case",
      arguments: {
        agreement: agreement(),
        evidenceContent: [{ id: "e_delivery", content: "Artifact is present." }],
      },
    });
    assert.equal(reviewed.structuredContent.readyToResolve, true);
    assert.equal(reviewed.structuredContent.findings[0].evidenceIds[0], "e_delivery");
    assert.equal("recommendedReleaseAtomic" in reviewed.structuredContent, false);
  } finally {
    await client.close();
    await server.close();
  }
});

test("MCP write tools reject a read-only identity", async () => {
  const { client, server } = await connectedClient({ scopes: ["cases:read"] });
  try {
    const created = await client.callTool({
      name: "docket_create_case",
      arguments: { agreement: agreement(), idempotencyKey: "read-only-create" },
    });
    assert.equal(created.isError, true);
    assert.equal(created.structuredContent.error.code, "AUTH_FORBIDDEN");

    const validated = await client.callTool({
      name: "docket_validate_agreement",
      arguments: { agreement: agreement() },
    });
    assert.equal(validated.structuredContent.valid, true);
  } finally {
    await client.close();
    await server.close();
  }
});

test("MCP Streamable HTTP endpoint serves the same tools", async () => {
  const { client, server } = await connectedHttpClient();
  try {
    const tools = await client.listTools();
    assert.equal(tools.tools.some((tool) => tool.name === "docket_resolve_case"), true);
    const result = await client.callTool({
      name: "docket_resolve_case",
      arguments: { agreement: agreement() },
    });
    assert.equal(result.structuredContent.recommendedReleaseAtomic, 250_000_000);
  } finally {
    await client.close();
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  }
});

test("production-mode MCP flow authenticates agents, persists a case, retrieves evidence, and isolates tenants", async () => {
  const directory = await mkdtemp(join(os.tmpdir(), "docket-mcp-production-"));
  const content = "The production artifact is present and matches the acceptance brief.";
  const digest = `sha256:${createHash("sha256").update(content).digest("hex")}`;
  const input = agreement();
  input.agreementId = "mcp_production_001";
  input.findings = [];
  input.evidence[0].uri = "https://evidence.example.test/production.txt";
  input.evidence[0].digest = digest;
  const auth = createAuthConfig({
    DOCKET_AUTH_MODE: "required",
    DOCKET_AUTH_TOKENS: JSON.stringify({
      "agent-a-production-token": { tenantId: "tenant-a", subject: "agent-a", scopes: ["*"] },
      "agent-b-production-token": { tenantId: "tenant-b", subject: "agent-b", scopes: ["cases:read"] },
    }),
  });
  const store = new CaseStore({ filePath: join(directory, "cases.json") });
  const server = createServer(createRequestHandler({
    commit: "e".repeat(40),
    slug: "elsemade-docket-resolve",
    auth,
    store,
    reviewProvider: new FixtureReviewProvider(),
    evidenceFetcher: async () => new Response(content, { status: 200, headers: { "content-type": "text/plain" } }),
    evidenceAllowHosts: ["evidence.example.test"],
    evidenceResolver: async () => [{ address: "93.184.216.34", family: 4 }],
  }));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const client = new Client({ name: "production-agent-a", version: "1.0.0" });
  const otherClient = new Client({ name: "production-agent-b", version: "1.0.0" });
  try {
    await client.connect(new StreamableHTTPClientTransport(new URL(`${origin}/mcp`), {
      authProvider: { token: async () => "agent-a-production-token" },
    }));
    await otherClient.connect(new StreamableHTTPClientTransport(new URL(`${origin}/mcp`), {
      authProvider: { token: async () => "agent-b-production-token" },
    }));

    const created = await client.callTool({ name: "docket_create_case", arguments: { agreement: input, idempotencyKey: "create-production-1" } });
    assert.equal(created.isError, undefined);
    const caseId = created.structuredContent.case.caseId;
    const replay = await client.callTool({ name: "docket_create_case", arguments: { agreement: input, idempotencyKey: "create-production-1" } });
    assert.equal(replay.structuredContent.case.caseId, caseId);
    assert.equal(replay.structuredContent.replayed, true);

    const retrieved = await client.callTool({ name: "docket_retrieve_evidence", arguments: { caseId, idempotencyKey: "retrieve-production-1" } });
    assert.equal(retrieved.structuredContent.retrieval.items[0].verified, true);

    const reviewed = await client.callTool({ name: "docket_review_persisted_case", arguments: { caseId, idempotencyKey: "review-production-1" } });
    assert.equal(reviewed.structuredContent.readyToResolve, true);
    assert.equal(reviewed.structuredContent.findings[0].evidenceIds[0], "e_delivery");

    const resolved = await client.callTool({ name: "docket_resolve_case", arguments: { caseId, idempotencyKey: "resolve-production-1" } });
    assert.equal(resolved.structuredContent.recommendedReleaseAtomic, 250_000_000);
    assert.equal(resolved.structuredContent.recommendationOnly, true);
    assert.equal(resolved.structuredContent.fundsMoved, false);

    const crossTenant = await otherClient.callTool({ name: "docket_get_case", arguments: { caseId } });
    assert.equal(crossTenant.isError, true);
    assert.equal(crossTenant.structuredContent.error.code, "CASE_NOT_FOUND");

    const forbiddenWrite = await otherClient.callTool({ name: "docket_create_case", arguments: { agreement: input, idempotencyKey: "reader-create-1" } });
    assert.equal(forbiddenWrite.isError, true);
    assert.equal(forbiddenWrite.structuredContent.error.code, "AUTH_FORBIDDEN");
  } finally {
    await client.close();
    await otherClient.close();
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    await rm(directory, { recursive: true, force: true });
  }
});
