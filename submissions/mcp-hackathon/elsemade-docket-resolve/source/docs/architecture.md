# Architecture

## Current upgrade slice

The existing settlement kernel remains the financial authority. The new local slice adds two adapters around it:

```text
Authenticated agent / reviewer
             |
             v
     tenant + scope boundary
             |
             v
       durable case store <---- immutable lifecycle events
             |
             +---- bounded HTTPS evidence retrieval + SHA-256 verification
             |
             +---- AI review boundary -> cited findings
                                      |
                                      v
                           deterministic settlement kernel
                                      |
                                      v
                         release / hold / manual review
```

Gemini is the default hosted review provider and requests schema-constrained JSON through the Gemini API. The OpenAI Responses adapter remains an explicit alternative, while the fixture provider is retained only as a test double. All provider findings are validated locally before entering the kernel. No AI or MCP path can set financial fields directly.

```text
Agent or reviewer
      |
      | POST /v1/evaluations
      v
HTTP boundary
  - body limit
  - JSON parsing
  - request ID
  - structured errors
      |
      v
Agreement validator
  - unique IDs
  - weight total
  - evidence references
  - score and policy bounds
      |
      v
Deterministic evaluator
  - confidence-weighted scores
  - contradiction caps
  - conflict detection
  - proportional allocation
      |
      v
Explainable recommendation
  - decision
  - release / hold
  - criterion ledger
  - reason codes
  - stable evaluation ID
```

## Trust boundary

Docket validates the structure and internal consistency of a case. It does not download evidence or declare that third-party claims are true. Evidence authenticity and evaluator authority belong to the calling system. This boundary keeps the core deterministic and prevents a settlement recommendation from being mistaken for an oracle.

AI review adds a second boundary: model output is untrusted even when it matches a provider-side schema. Docket verifies criterion IDs, evidence IDs, citation presence, confidence thresholds, and the absence of financial authority before creating a kernel finding.

## State

The current upgrade slice persists cases, retrieved evidence metadata/content, review output,
recommendations, and immutable case events in the file-backed store at `DOCKET_STORAGE_PATH`.
Mutations accept idempotency keys and every read is scoped by the authenticated tenant. This is a
persistent single-host implementation for the hackathon slice; a shared transactional database,
optimistic concurrency, backups, and key management are still required before multi-instance launch.

## Failure behavior

- Invalid cases return `422` with a stable error code.
- Invalid JSON returns `400`.
- Unsupported media types return `415`.
- Bodies above 256 KiB return `413`.
- Material evaluator conflict returns `200` with `decision: manual_review` and null financial fields. This is a valid evaluation, not a transport failure.
- AI provider timeout, refusal, malformed output, unsupported evidence citation, or low confidence produces a recoverable review failure/manual-review state; it never creates an unsupported financial finding.

## MCP boundary

- Local clients connect through `npm run mcp` over stdio.
- Remote local-development clients connect to `/mcp` over Streamable HTTP.
- The current slice exposes stateless validation/review tools and persisted create, retrieve, review,
  get, and resolve tools.
- Production-like bearer authentication and tenant-scoped resources are enabled when
  `DOCKET_AUTH_MODE=required`; stdio inherits the trusted process identity.
