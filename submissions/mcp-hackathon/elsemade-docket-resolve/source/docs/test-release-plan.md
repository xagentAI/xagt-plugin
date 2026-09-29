# Test and release plan

## Purpose

This document defines the evidence required to call the Docket AI + MCP upgrade complete and the process for releasing it without weakening the existing settlement guarantees.

## Test strategy

### Unit tests

Target pure behavior:

- agreement validation;
- allocation and rounding;
- evidence/finding reference rules;
- confidence-weighted scoring;
- critical-failure caps;
- conflict detection;
- case-state transitions;
- idempotency digesting;
- explanation numeric-consistency checks;
- AI output local validation;
- error mapping.

Unit tests must not require network, model credentials, or a database.

### Golden contract tests

Freeze representative v0.1 requests and complete responses for:

- full release;
- canonical 230/20 partial release;
- complete hold;
- critical-failure cap;
- evaluator conflict/manual review;
- malformed and invalid input.

Domain extraction must preserve these outputs unless an explicitly reviewed API version changes.

### Property and invariant tests

Generate bounded agreements and verify:

- release plus hold equals agreement amount;
- release and hold are never negative;
- settlement ratio is within zero to 10,000 basis points;
- criterion earned plus held equals criterion allocation;
- criterion totals reconcile with agreement amount;
- manual review has null financial recommendation fields;
- equivalent canonical input yields the same evaluation identity;
- adding unsupported evidence cannot increase value;
- AI output cannot inject unknown criterion or evidence IDs.

### Persistence integration tests

Run against a real ephemeral PostgreSQL instance:

- migration from empty database;
- agreement version immutability;
- append-only case events;
- idempotent mutation replay;
- idempotency-key conflict;
- optimistic concurrency conflict;
- transaction rollback after failure;
- tenant isolation;
- recommendation supersession;
- audit replay;
- backup and restore fixture.

### HTTP contract tests

- OpenAPI matches implemented routes and schemas.
- Valid and invalid requests return documented statuses.
- Request size, content type, CORS, and security headers are enforced.
- Authentication and authorization semantics are stable.
- Request IDs appear in responses and logs.
- Timeouts and cancellation are bounded.
- Health and deployment proof report the exact source commit.

### MCP tests

Use the official client SDK:

- in-memory transport for fast tool behavior tests;
- stdio process test for local integration;
- Streamable HTTP test for remote integration;
- discovery and protocol negotiation;
- tool and resource listing;
- structured output validation;
- canonical proportional settlement call;
- manual-review outcome;
- auth/scopes and tenant isolation;
- idempotency replay;
- malformed input and state conflicts;
- cancellation and shutdown;
- no stdout log pollution in stdio mode.

### AI evaluation tests

Run the versioned corpus in `docs/ai-adjudication-spec.md` against:

- deterministic fake provider on every CI run;
- recorded redacted provider fixtures on every CI run;
- the selected live model in a controlled pre-release evaluation job.

Record:

- schema validity;
- evidence citation validity;
- unsupported requirements;
- correct insufficient-evidence behavior;
- prompt-injection resistance;
- designated manual-review recall;
- score agreement within tolerance;
- explanation-to-ledger numeric consistency;
- latency, token usage, and cost.

A live-model eval result is tied to provider, model, prompt, schema, corpus, and commit versions.

### UI tests

Component tests:

- settlement summary formatting;
- criterion allocation ledger;
- evidence and finding states;
- manual-review warnings;
- permission and provider errors;
- numeric formatting for asset decimals.

Browser end-to-end tests:

- create/approve agreement;
- submit evidence;
- run review;
- inspect 230/20 recommendation;
- challenge a finding;
- see superseded recommendation;
- reconnect/refresh without data loss;
- prevent double submission;
- operate keyboard-only;
- responsive layouts.

Visual QA scenarios:

- empty workspace;
- partial settlement;
- failed critical criterion;
- evaluator conflict;
- AI running;
- AI unavailable;
- long rationale/evidence labels;
- narrow viewport;
- high zoom and reduced motion.

### Security tests

- missing, expired, wrong-audience, and insufficient-scope tokens;
- cross-tenant ID probing;
- CSRF where cookies are used;
- XSS in task briefs, evidence, findings, and model output;
- prompt injection inside evidence;
- oversized/decompression payloads;
- duplicate/replayed mutations;
- secret patterns in logs and client bundles;
- unsafe CORS, Host, and Origin behavior;
- SSRF tests if any fetcher is introduced;
- dependency and secret scanning.

### Performance and resilience tests

- deterministic settlement throughput and p95 latency;
- MCP tool latency and concurrent connections;
- AI-review bounded concurrency;
- database pool saturation;
- provider timeout, 429, 5xx, refusal, and malformed output;
- process restart during a review;
- client disconnect and cancellation;
- deployment cold start;
- circuit breaker and recovery;
- rate-limit enforcement.

## CI gates

Every pull request:

1. dependency lock consistency;
2. formatting;
3. lint;
4. typecheck;
5. unit and golden tests;
6. property/invariant tests;
7. fake-provider AI tests;
8. MCP in-memory tests;
9. secret scan;
10. dependency vulnerability scan;
11. production build.

Protected integration job:

- PostgreSQL integration tests;
- HTTP and MCP process tests;
- browser smoke tests;
- migration verification.

Pre-release job:

- live-model evaluation under a hard spending cap;
- full browser suite;
- performance smoke/load tests;
- deployment preview smoke tests;
- manual security and product review.

No CI job may expose model or deployment secrets to untrusted fork code.

## Manual acceptance script

### Agreement

- Create the canonical 250 USDC agreement.
- Confirm weights total 100 and allocations total 250 USDC.
- Activate the agreement.
- Attempt to edit weights and confirm rejection/versioning behavior.

### Evidence and AI

- Submit the three canonical evidence items.
- Run the AI review.
- Confirm every finding cites valid evidence.
- Confirm the resulting scores are 100, 90, and 75 for the controlled demo fixture or fall within the approved live-model tolerance.
- Insert a prompt-injection sentence into evidence and confirm it is ignored.
- Remove required evidence and confirm Docket requests it rather than inventing support.

### Settlement

- Resolve the case.
- Confirm release is 230,000,000 atomic units.
- Confirm hold is 20,000,000 atomic units.
- Confirm ratio is 9,200 basis points.
- Confirm criterion ledger sums exactly.
- Confirm the explanation names the held value without changing numbers.
- Confirm “recommendation only” and “no funds moved” are visible.

### Conflict

- Add a materially conflicting independent finding.
- Confirm manual review and null financial fields.
- Confirm no export implies payment execution.

### MCP

- Connect a real SDK client through stdio.
- Discover tools.
- Validate the agreement.
- Review and resolve the canonical case.
- Repeat over the preview HTTP endpoint with approved credentials.
- Confirm structured output matches REST/domain output.

### Persistence

- Refresh the browser and reconnect the MCP client.
- Confirm case history remains intact.
- Retry a mutation with the same idempotency key and confirm one effect.
- Attempt a stale-version update and confirm conflict.

## Release environments

### Local

- Fake AI provider by default.
- Real provider only through explicit local secret configuration.
- No production data.

### Preview

- Per-branch deployment and isolated database.
- Strict model spending cap.
- Test identities only.
- Public access disabled unless a review flow explicitly requires it.
- Source commit exposed in health.

### Production

- Protected domain and OAuth.
- Production database, backups, alerts, and quotas.
- Model credentials scoped to production.
- Exact reviewed commit in health and proof.
- Anonymous demo separated from tenant data and mutation endpoints.

## Rollout sequence

### Stage 0 — Local only

Complete domain extraction, fake-provider AI, and MCP tests. No external changes.

### Stage 1 — Private preview

Deploy isolated preview after user approval. Run automated and manual acceptance. No hackathon PR update.

### Stage 2 — Controlled beta

Enable selected identities and strict quotas. Monitor model quality, manual-review rate, errors, and cost.

### Stage 3 — Production release

Promote the exact approved commit after release gates pass. Run smoke tests and manual product inspection immediately.

### Stage 4 — Submission update

Only after the user reviews the final product and public materials:

- update source repository;
- update deployment binding;
- package the exact source snapshot;
- rerun official offline and online validators;
- update PR #74.

## Rollback plan

Triggers:

- financial invariant violation;
- cross-tenant authorization issue;
- schema/citation failure beyond threshold;
- deployment health/proof mismatch;
- data corruption or failed migration;
- severe provider cost or availability regression;
- critical UI or MCP path unavailable.

Actions:

1. Disable AI review through a server-side feature flag if the deterministic service remains safe.
2. Stop new mutations if persistence integrity is uncertain.
3. Roll traffic back to the previous known-good deployment.
4. Roll back application code before database schema only when backward compatibility is verified.
5. Restore database from backup only under an incident plan; do not casually overwrite newer audit records.
6. Mark suspect recommendations superseded or under review.
7. Verify health, deterministic settlement, auth, and tenant isolation after rollback.

The previous v0.1 stateless evaluator remains a useful emergency reference but is not a substitute for persisted production cases.

## Release evidence package

Store for each release:

- Git commit and dependency lock digest;
- build result;
- test and coverage report;
- AI eval report with provider/model/prompt/schema/corpus versions;
- MCP client transcript;
- migration plan and result;
- security and dependency scan result;
- deployed health/proof responses;
- browser screenshots for critical states;
- manual acceptance checklist;
- known limitations;
- rollback target and verification;
- user approval for public release/submission changes.

## Final release checklist

- [ ] Product copy leads with proportional settlement.
- [ ] AI cannot produce authoritative financial fields.
- [ ] Domain, REST, MCP, UI, and persistence schemas agree.
- [ ] Golden and invariant tests pass.
- [ ] AI zero-tolerance evaluation gates pass.
- [ ] MCP stdio and HTTP client tests pass.
- [ ] Authentication, scopes, and tenant isolation pass.
- [ ] Idempotency and concurrency pass.
- [ ] Production build succeeds.
- [ ] Preview critical path passes.
- [ ] Logs contain no sensitive evidence or secrets.
- [ ] Quotas, alerts, backups, and rollback are configured.
- [ ] Known limitations are documented accurately.
- [ ] User reviewed the product and exact public claims.
- [ ] User explicitly approved deployment and PR update.
