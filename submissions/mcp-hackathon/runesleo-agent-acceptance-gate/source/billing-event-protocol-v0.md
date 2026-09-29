# Billing Event Protocol v0

Status: local_only_design

## Purpose

Multi-model validation found that per-call pricing only works if the charge event is explicit.

This protocol defines the minimum billing semantics for a future OKX.AI / A2MCP launch. It is not active and does not connect to payments.

## Current launch decision

Do not charge users yet.

Use this only as a design constraint for the future payment integration.

## Billable event

Recommended billable event:

```text
valid_audit_generated
```

Do not bill on raw request receipt. Bill only when:

1. request JSON is valid;
2. required fields are present;
3. audit verdict is generated;
4. response is returned or durably stored for retry.

## Non-billable events

No charge for:

- invalid JSON;
- missing required fields;
- server error before audit generation;
- duplicate retry with the same idempotency key;
- health checks;
- sample/demo calls.

## Required request fields before paid launch

Future paid endpoint should require:

```json
{
  "idempotency_key": "buyer-task-id-or-client-generated-key",
  "mode": "quick | full | evaluator",
  "task": {},
  "delivery": {},
  "context": {}
}
```

## Pricing mapping

Start narrow:

- `quick`: simple acceptance check;
- `full`: complete buyer-ready report;
- `evaluator`: not launched until dispute demand exists.

Do not launch dynamic pricing until usage data exists.

## Refund / retry rule

If the service returns a syntactically valid audit, the call is billable.

If the user claims the audit quality is bad, handle through support or credits, not automatic refund. Automatic refund requires a separate quality SLA that does not exist yet.

## Hard gates before activation

- OKX.AI account / Agentic Wallet;
- receiving wallet address;
- payment middleware or reverse proxy;
- endpoint deploy;
- idempotency storage;
- public terms;
- privacy statement;
- abuse/rate-limit policy.

