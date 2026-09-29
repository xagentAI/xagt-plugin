# OKX AI Genesis Hackathon Submission Packet

Status: draft_not_submitted
Project: Agent Acceptance Gate

## One-liner

Agent Acceptance Gate is a transaction gate for agent commerce: before an agent accepts a task, spends budget, submits delivery, releases payment, or votes on a dispute, it checks whether the transaction can continue safely.

## Problem

Agent marketplaces create a new failure mode:

```text
Agents can transact faster than humans can verify.
```

This causes:

- unclear task scope;
- unnecessary paid tool calls;
- incomplete deliveries;
- unsafe release/deploy actions;
- payment disputes;
- evaluator overload.

## Solution

Agent Acceptance Gate provides a machine-callable check:

```text
Can this agent transaction continue?
```

Current prototype focuses on delivery acceptance:

- pass / needs_review / fail;
- missing evidence;
- hard-gate risks;
- buyer summary;
- evaluator notes;
- next gate.

Expanded roadmap covers:

- pre-hire gate;
- pre-call budget gate;
- delivery acceptance gate;
- dispute/evaluator gate.

## Why OKX.AI

OKX.AI is building A2A / A2MCP agent commerce.

The more agents transact, the more the market needs:

- acceptance standards;
- evidence packets;
- escrow release checks;
- dispute-ready facts;
- seller reputation signals.

Agent Acceptance Gate is designed as infrastructure for that market.

## Demo

Static demo:

```text
https://agent-acceptance-gate.pages.dev/
```

Local API draft:

```text
POST /audit-agent-deliverable
GET /.well-known/agent-service.json
GET /mcp-tool-manifest.json
GET /openapi.yaml
```

## Current artifacts

- Public static demo.
- Local HTTP prototype.
- Deterministic audit engine.
- OpenAPI 3.1 draft.
- MCP-style tool manifest.
- Agent discovery metadata.
- 5 sample audits.
- Revenue route map.
- Billing event protocol.

## What is not live yet

- No OKX.AI listing.
- No public API endpoint.
- No wallet.
- No payment middleware.
- No receiving address.
- No production auth/rate limit.

## Hackathon positioning

Do not pitch as:

```text
another auditor
```

Pitch as:

```text
the acceptance and transaction gate for agent commerce
```

## Evaluation criteria fit

### Solves real problems

Agent commerce needs trust checks before money and external state move.

### Generates real usage

Potential call points:

- every task posting;
- every paid service call;
- every delivery;
- every payment release;
- every dispute.

### Uses OKX.AI design

Designed for:

- ASPs;
- buyer agents;
- seller agents;
- evaluator agents;
- A2MCP call surface;
- future payment/escrow flow.

## Immediate submission gap

Need before submission:

1. public API endpoint or hosted mock endpoint;
2. short demo video / screenshots;
3. 10 real usage examples;
4. pricing mode;
5. privacy / terms boundary;
6. OKX.AI ASP registration path, if submitting formally.

## Proposed category

```text
Agent Commerce Infrastructure
```

Tags:

- agent marketplace;
- A2MCP;
- escrow safety;
- delivery acceptance;
- budget guard;
- dispute support;
- evaluator tooling.

