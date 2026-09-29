# Marketplace Listing Draft

Status: draft_local_only
Target: OKX.AI ASP / A2MCP

## Service name

Agent Deliverable Auditor

## One-line description

Audits AI agent deliverables for completeness, proof, validation, rollback, hard gates, and buyer-ready next steps.

## Short description

Agent Deliverable Auditor checks whether an AI agent's task delivery is safe to accept. Submit the task prompt, agent writeback, artifacts, changed files, validation output, declared hard gates, and next gate. The service returns a structured verdict: `pass`, `needs_review`, or `fail`, with score, missing evidence, risks, buyer summary, and evaluator notes.

## Buyer problem

In an agent marketplace, a buyer often receives a polished writeback but still has to decide:

- Did the agent actually produce the artifact?
- Were files, validation, rollback, and next gate declared clearly?
- Did the agent cross a hard gate like deploy, credentials, payment, wallet, or repo mutation?
- Is the work ready to accept, or should the buyer request clarification?

This service turns that acceptance check into a repeatable audit.

## Best for

- Buyers reviewing Agent task deliveries before accepting work.
- ASPs checking their own delivery packet before sending it to a buyer.
- Evaluators preparing structured notes for a dispute.
- Teams using agent workers with writeback / validation / rollback protocols.

## Not for

- Legal, tax, investment, or financial advice.
- Smart contract security assurance.
- Wallet signing, trading, staking, or transaction review.
- Full code review of large diffs.
- Public deployment readiness unless the input includes release validation evidence.

## Example input

```json
{
  "task": {
    "buyer_goal": "Rename product page copy without changing pricing or deploying.",
    "forbidden_actions": ["push", "deploy", "payment_config", "pricing_change"]
  },
  "delivery": {
    "writeback_text": "...",
    "changed_files": ["src/pages/PMQuantPage.tsx"],
    "validation": ["tsx syntax pass", "git diff --check pass"],
    "next_gate": "buyer approval before push and deploy"
  }
}
```

## Example output

```json
{
  "verdict": "needs_review",
  "score": 82,
  "summary": "Delivery is locally coherent but full build was deferred and buyer must approve wording before public release.",
  "missing": ["release build", "buyer decision on old customer promise"],
  "risks": ["public release hard gate still open"],
  "next_gate": "Buyer reviews copy risk before push/deploy."
}
```

## Suggested listing categories

- Agent QA
- Workflow automation
- Delivery review
- Marketplace acceptance
- Evaluator support

## Endpoint placeholder

No public endpoint yet.

Production endpoint must not be created until Leo approves OKX account / wallet / deploy hard gates.

