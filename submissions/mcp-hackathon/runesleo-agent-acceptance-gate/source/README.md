# OKX.AI ASP Package: Agent Deliverable Auditor

Created: 2026-07-02
Owner thread: product_distribution / cmd5
Status: live_worker_api_x402; X-Agent patch local_only_not_deployed

## Bottom line

`Agent Acceptance Gate` is a live OKX.AI/A2MCP service and an X-Agent MCP Hackathon reuse candidate.

It checks whether an AI agent transaction can continue before task acceptance, paid service calls, delivery acceptance, payment release, or dispute review.

The public Worker is live at `https://api.leolabs.me`. The X-Agent version-binding and reviewer route in the isolated preparation branch are not yet deployed; public deployment, push, and submission remain explicit owner gates.

The service does not execute wallet actions, agent tasks, repo mutations, or deployments. It reads a task prompt, writeback, artifact list, changed files, validation output, declared hard gates, and next gate. It returns a structured verdict.

## Why this exists

OKX.AI creates a marketplace where users can hire Agents, ASPs can sell services, and Evaluators can arbitrate disputes. That marketplace needs a boring but valuable layer:

```text
Can this agent transaction continue?
```

The first sellable wedge is delivery acceptance. The larger product is an agent transaction gate.

## Package contents

- `marketplace-listing-draft.md` - listing copy for OKX.AI ASP review.
- `service-spec.md` - proposed MCP/API contract and scoring rubric.
- `pricing.md` - 3 candidate per-call tiers.
- `sample-inputs/` - 5 historical delivery-style inputs.
- `sample-outputs/` - 5 expected audit outputs.
- `src/auditor.mjs` - local deterministic audit engine.
- `src/http-server.mjs` - local HTTP API and demo server.
- `bin/audit-agent-deliverable.mjs` - local CLI wrapper.
- `bin/serve-demo.mjs` - local demo/API server launcher.
- `test/run-samples.mjs` - sample regression test.
- `test/http-smoke.mjs` - HTTP endpoint smoke test.
- `prototype.md` - local prototype usage notes.
- `demo/index.html` - buyer-facing local demo.
- `multi-model-validation-20260702.md` - independent validation and launch decision.
- `billing-event-protocol-v0.md` - future paid-call semantics.
- `buyer-facing-launch-packet-cn.md` - public-safe launch copy draft.
- `discovery/agent-service.json` - agent/service discovery metadata.
- `discovery/mcp-tool-manifest.json` - MCP-style tool manifest.
- `openapi.yaml` - HTTP API contract.
- `config/xagent-review.env.example` - non-secret deployment identity example for the bounded X-Agent review surface.
- `agent-market-ecosystem-analysis-cn.md` - market/ecosystem analysis in Chinese.
- `go-no-go.md` - launch decision and hard gates.

## Local prototype

This package now includes a runnable local prototype.

Run all sample audits:

```bash
npm run audit:samples
```

Run one input:

```bash
npm run audit -- sample-inputs/01-pmquant-rename.json --pretty
```

Run regression tests:

```bash
npm test
```

Run local demo/API server:

```bash
npm run serve
```

Local service endpoints:

```text
GET  /health
GET  /api/sample-audits
GET  /.well-known/agent-service.json
GET  /mcp-tool-manifest.json
GET  /openapi.yaml
POST /audit-agent-deliverable
```

Current validation:

```text
PASS 01-pmquant-rename.json: needs_review score=84
PASS 02-t310-governance-update.json: needs_review score=80
PASS 03-alkanes-red-stop.json: pass score=96
PASS 04-dashboard-curation-readout.json: needs_review score=84
PASS 05-claude-science-readout.json: pass score=93
All sample audit cases passed
PASS http smoke on http://127.0.0.1:<ephemeral-port>
```

The prototype is rule-based. It validates the product shape before adding any LLM, MCP server, OKX account, wallet, payment, endpoint, or listing flow.

## Buyer-facing demo

Public static demo:

```text
https://agent-acceptance-gate.pages.dev/
```

Open the local demo:

```text
/Users/zhangxu/Projects/agent-acceptance-gate/demo/index.html
```

The demo reframes JSON audit output as a buyer acceptance report:

- Accept / Needs Review / Reject verdict;
- score and dimension bars;
- reasons not to accept yet;
- missing evidence;
- next gate;
- seller questions;
- machine flags.

Multi-model validation result:

```text
Product direction: Yellow
Local artifact/demo: Green
Direct public / OKX.AI production launch: Red
```

Reason: the pain is real, but the current product must be experienced at the delivery acceptance / payment / dispute node. Standalone CLI/JSON is too abstract for buyers.

## Recommended product shape

Start as A2MCP:

- fixed schema;
- pay-per-call;
- no negotiation;
- instant structured output;
- buyer / ASP / evaluator usable.

Do not start as A2A custom service. A2A would require negotiation, manual delivery QA, dispute handling, and broad service scope before demand is proven.

Do not start as Evaluator. Evaluator registration requires OKB stake and introduces slashing / timeout risk.

## Local validation goal

Before any OKX account, wallet, endpoint, or listing action, the local package should answer:

1. Can the service be explained in one sentence?
2. Can the output be structured enough to price per call?
3. Does it catch missing validation, hard-gate risk, dirty state, deferred release checks, and unclear next gates?
4. Would a buyer use it before accepting an Agent task?

## Hard gates before real launch

Do not proceed without explicit Leo approval for:

- Agentic Wallet login / account action;
- OKX API credential or Onchain OS production configuration;
- receiving wallet address;
- funding, signing, transaction, staking, or payment setup;
- deployment of new Worker code or X-Agent review routes;
- ASP listing submission;
- OKX.AI terms / price / payment terms;
- push / deploy / public publish of any related website asset.
