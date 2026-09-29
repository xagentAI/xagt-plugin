import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";

const projectRoot = fileURLToPath(new URL("..", import.meta.url));
const agreement = JSON.parse(
  await readFile(resolve(projectRoot, "examples/agreement.json"), "utf8"),
);

const evidenceContent = agreement.evidence.map((evidence) => {
  const finding = agreement.findings.find((item) => item.criterionId === evidence.criterionId);
  return {
    id: evidence.id,
    content: `Controlled demo evidence for ${evidence.criterionId}. FIXTURE_SCORE: ${finding?.score ?? 0}`,
  };
});

const transport = new StdioClientTransport({
  command: process.execPath,
  args: [resolve(projectRoot, "src/mcp/stdio.js")],
  env: { ...process.env, DOCKET_AI_PROVIDER: "fixture" },
});
const client = new Client({ name: "docket-agent-demo", version: "1.0.0" });

try {
  await client.connect(transport);
  const validation = await client.callTool({
    name: "docket_validate_agreement",
    arguments: { agreement },
  });
  const review = await client.callTool({
    name: "docket_review_case",
    arguments: { agreement: { ...agreement, findings: [] }, evidenceContent },
  });
  const reviewedAgreement = {
    ...agreement,
    findings: review.structuredContent.findings,
  };
  const resolution = await client.callTool({
    name: "docket_resolve_case",
    arguments: { agreement: reviewedAgreement },
  });

  const output = {
    workflow: [
      "commissioning_agent.validated_agreement",
      "review_agents.submitted_cited_findings",
      "docket.calculated_proportional_settlement",
    ],
    valid: validation.structuredContent.valid,
    reviewReady: review.structuredContent.readyToResolve,
    decision: resolution.structuredContent.decision,
    asset: resolution.structuredContent.asset,
    recommendedReleaseAtomic: resolution.structuredContent.recommendedReleaseAtomic,
    recommendedHoldAtomic: resolution.structuredContent.recommendedHoldAtomic,
    settlementRatioBps: resolution.structuredContent.settlementRatioBps,
    recommendationOnly: resolution.structuredContent.recommendationOnly,
    fundsMoved: resolution.structuredContent.fundsMoved,
  };
  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
} finally {
  await client.close();
}
