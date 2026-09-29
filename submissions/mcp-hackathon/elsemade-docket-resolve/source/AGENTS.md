# Docket agent instructions

## Mission

Build Docket into the settlement control plane for agent-to-agent work.

The product promise is:

> Docket reviews agent work and turns evidence into explainable, proportional settlements.

Proportional settlement is the defining feature. Do not bury it beneath implementation language such as “deterministic API,” “JSON evaluator,” or “MCP server.” Determinism is a trust mechanism under the product, not the headline.

## Current state

The repository currently contains Docket Resolve v0.1:

- a stateless Node.js settlement evaluator;
- strict agreement, evidence, and finding validation;
- confidence-weighted criterion scoring;
- critical-failure caps and evaluator-conflict escalation;
- proportional release and hold calculations;
- an HTTP API, OpenAPI document, and reviewer interface;
- 47 passing tests;
- a Gemini hosted AI review adapter with schema-constrained findings, plus a clearly labeled fixture test double;
- MCP tools over local stdio and authenticated Streamable HTTP;
- a persistent single-host case/event store with idempotent mutations and tenant isolation;
- bounded HTTPS evidence retrieval with digest verification;
- a local-only deterministic fixture evidence provider for the reviewer workspace, with explicit all-failed retrieval coverage;
- a responsive case workspace UI and production-like MCP workflow;
- no OAuth identity provider, shared multi-instance database, or payment authority yet.

The public hackathon submission is open at `xagentAI/xagt-plugin#74`. Do not push, deploy, amend the submission, change the rights declaration, or close the PR without explicit user approval after review.

## Product invariants

These rules are non-negotiable:

1. The settlement kernel is the only component allowed to calculate release and hold amounts.
2. AI may produce criterion findings, confidence, cited evidence, missing-evidence requests, and explanations. AI must not directly choose a payment amount.
3. Every positive or negative finding must cite supplied evidence for the same criterion.
4. No supporting evidence means no unsupported credit.
5. Materially conflicting findings, low confidence, missing critical evidence, provider failure, or schema-invalid AI output must fail closed to clarification or manual review.
6. Docket produces recommendations. It does not hold funds, sign transactions, expose wallet credentials, or execute payments.
7. Atomic asset amounts and decimal precision remain explicit. Never represent settlement authority with floating-point currency.
8. The original request, normalized evidence, AI findings, model/prompt provenance, policy version, and settlement result must be auditable together.
9. User-visible claims must reflect real behavior. Demo data must be clearly labeled.
10. Keep the core domain independent from HTTP, MCP, UI, database, and model-provider code.

## Target architecture

```text
Web app / agent / MCP client
            |
            v
HTTP and MCP boundaries
            |
            v
Case application service
  |         |          |
  v         v          v
Contract  Evidence   AI review
service   service    service
                       |
                       v
                 structured findings
                       |
                       v
              settlement kernel
                       |
                       v
        recommendation + criterion ledger
                       |
                       v
          case store + immutable events
```

The settlement kernel must remain usable as a pure function with no network or database dependency.

## Planned source boundaries

```text
src/
  domain/          agreements, evidence, findings, policies, settlement kernel
  application/     case workflows and orchestration
  ai/              provider interface, prompts, schemas, review pipeline
  mcp/             server factory, tools, resources, stdio and HTTP entrypoints
  persistence/     repositories and migrations
  http/            REST handlers, middleware and OpenAPI
  observability/   structured logs, metrics and trace context
  config/          validated environment configuration
public/            reviewer-facing web application
scripts/           reproducible demos, evals and operational checks
test/              unit, contract, integration, MCP and AI-eval fixtures
```

Do not move files mechanically until a phase requires the new boundary. Preserve behavior with tests during extraction.

## Implementation protocol

For every behavioral change:

1. Read the relevant specification in `docs/`.
2. Add or update a failing test first.
3. Implement the smallest complete behavior.
4. Run targeted tests, then the full suite.
5. Validate trust-boundary input and output.
6. Update OpenAPI, MCP schemas, examples, and documentation together.
7. Record any architectural decision that changes an invariant or external contract.
8. Stop for user review at the end of each production phase.

Do not combine a major UI redesign, domain-model rewrite, and protocol migration in one unreviewable change.

## AI implementation rules

- Use a provider interface. The first adapter may use OpenAI Responses with strict structured output, but domain code must not import a provider SDK.
- Set provider-side storage off where supported and document the actual retention behavior.
- Version every system prompt and output schema.
- Validate model output again locally. Structured output is not authorization.
- Require evidence IDs and criterion IDs to resolve against the case.
- Do not allow the model to create evidence, silently alter contract weights, or introduce requirements that were not agreed.
- Record provider, model identifier, prompt version, schema version, latency, token usage, and request correlation ID. Never log raw secrets or unrestricted evidence bodies.
- Bound timeouts and retries. At most one retry for transient provider failures; never retry refusals or schema-invalid findings without changing the request.
- Preserve a no-AI path: callers may submit trusted structured findings directly to the settlement kernel.

## MCP implementation rules

- Use the stable v2 official TypeScript SDK packages, pinned in the lockfile.
- Serve remote clients through stateless Streamable HTTP at `/mcp` using the current handler/factory API.
- Serve local clients through stdio from a separate entrypoint.
- Keep tools thin: validate input, authorize, call application services, and format structured output.
- Expose read-only case records as resources only after authorization is implemented.
- Use OAuth bearer-token resource-server behavior for production remote MCP. The public demo may expose a strictly limited anonymous sandbox, never production cases.
- Validate `Host` and `Origin` where applicable. Do not hand-roll protocol negotiation.
- Add a real SDK client integration test that discovers and invokes every tool.

## Reliability and security rules

- Every mutating operation requires an idempotency key.
- Case state transitions must be explicit and enforced server-side.
- Store immutable case events alongside current projections.
- Validate environment variables at startup and fail fast on invalid production configuration.
- Use request IDs across HTTP, MCP, AI-provider, and database operations.
- Keep API keys, database URLs, OAuth secrets, and model credentials server-side.
- Apply bounded request sizes, evidence counts, criterion counts, and per-tenant quotas.
- Evidence retrieval must use the implemented allowlist (mandatory in required-auth/production mode), HTTPS-only, private-host blocking, redirect rejection, byte limits, timeouts, and digest verification. Malware scanning and tenant-approved source integrations remain future hardening.
- Production errors must be actionable without exposing stack traces or evidence content.

## Required quality gates

Before a phase is called complete:

- unit and integration tests pass;
- type, lint, formatting, and dependency checks pass;
- REST and MCP contracts agree with domain schemas;
- loading, empty, success, partial-failure, retry, and hard-failure states are exercised;
- no secrets, private data, generated dependencies, or build output are committed;
- the production build succeeds;
- the critical path is manually exercised in the deployed preview;
- the user reviews the result before any public update.

## Current commands

```bash
npm ci
npm test
npm run check
npm run test:e2e
npm run test:mcp
npm run test:ai
npm run demo:mcp:production
npm start
```

Remaining release-gate commands such as `eval`, `lint`, `typecheck`, and `build` must not be documented as available until they exist and pass.

## Change authority

Allowed without additional approval:

- local planning and implementation;
- local tests and static analysis;
- local preview servers;
- reversible edits inside this repository.

Require explicit user approval:

- pushing commits;
- creating or updating a public deployment;
- changing the open hackathon PR;
- publishing screenshots, videos, posts, or submission copy;
- changing submitter identity, license, or rights language;
- enabling a paid model or other billable external service;
- adding payment or wallet authority.

## Source of truth

- `docs/production-plan.md` — execution order, milestones, ownership, and gates
- `docs/product-spec.md` — product behavior and user experience
- `docs/ai-adjudication-spec.md` — AI contract, provenance, and evaluation
- `docs/mcp-interface-spec.md` — MCP tools, resources, transports, and auth
- `docs/security-reliability.md` — threats, data handling, failure semantics, and operations
- `docs/test-release-plan.md` — test matrix, rollout, rollback, and release evidence
- `HANDOFF.md` — current status and next concrete actions
