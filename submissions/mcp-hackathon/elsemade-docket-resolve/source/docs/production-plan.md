# Docket AI + MCP production plan

## 1. Executive outcome

Docket will become an AI-assisted settlement control plane for agent-to-agent work.

It will turn a task agreement, submitted evidence, and reviewer input into:

- evidence-grounded criterion findings;
- missing-evidence and conflict detection;
- an explainable proportional release and hold recommendation;
- a replayable audit record;
- MCP tools that other agents can call safely.

The primary product claim is proportional settlement, not generic AI review:

> Docket reviews agent work and turns evidence into explainable, proportional settlements.

## 1.1 Current execution status

The AI/MCP vertical slice and final hackathon hardening candidate are implemented and reviewable. They
include the provider-neutral AI review boundary, a Gemini adapter, a labeled fixture test double, an optional
structured-output OpenAI adapter, persistent single-host tenant-scoped cases/events, idempotent mutations,
bounded HTTPS evidence retrieval with digest verification, authenticated MCP tools over stdio and
Streamable HTTP, an authenticated HTTP E2E test, a responsive case workspace, and an end-to-end
MCP client demo that produces the canonical 230 USDC release / 20 USDC hold recommendation.

The settlement kernel remains the only component that calculates financial fields. Shared
multi-instance storage, a full OAuth resource-server integration, malware scanning/source
connectors, and a live hosted-model evaluation corpus remain outside this hackathon slice. The final
candidate still requires user approval before its source, deployment, and official submission are updated.

## 2. Success criteria

The upgrade succeeds when a reviewer can:

1. create or load a weighted acceptance agreement;
2. submit representative evidence for delivered work;
3. ask Docket's AI reviewer to assess every criterion;
4. inspect citations, confidence, missing evidence, and disagreements;
5. receive a proportional release and hold recommendation from the settlement kernel;
6. understand exactly why the result is not zero or 100 percent;
7. reproduce the same settlement from the recorded structured findings;
8. complete the same workflow through a real MCP client;
9. see uncertain or conflicting cases stop for clarification or manual review;
10. verify that Docket never executes payment.

Production readiness additionally requires authenticated tenants, durable case history, idempotent mutations, bounded failures, observability, deployment validation, and rollback evidence.

## 3. Scope

### In scope

- Agreement drafting from a task brief, with user approval before activation.
- Structured evidence ingestion and normalization.
- AI-assisted evidence review against agreed criteria.
- Proportional settlement using the existing kernel.
- Conflict, confidence, and missing-evidence gates.
- Plain-language settlement explanations grounded in the ledger.
- MCP tools over stdio and remote Streamable HTTP.
- A reviewer-facing case workspace.
- Durable cases and immutable audit events.
- Authentication, tenant isolation, quotas, observability, and operational controls.
- Reproducible demos, model evaluations, and submission documentation.

### Explicitly out of scope

- Custody of user funds.
- Signing or broadcasting transactions.
- Automatic payment execution.
- Treating AI output as legal arbitration.
- Arbitrary server-side fetching of untrusted URLs.
- Secret collection through MCP tool arguments.
- Training models on customer case data.
- Hidden requirements added after an agreement is activated.

## 4. Critical user path

```text
Draft agreement
  -> approve weighted criteria
  -> activate agreement
  -> submit evidence
  -> run AI review
  -> resolve gaps/conflicts
  -> calculate proportional settlement
  -> inspect explanation
  -> export unsigned recommendation
```

Important alternate states:

- invalid agreement;
- agreement awaiting approval;
- insufficient evidence;
- AI unavailable;
- AI refusal;
- schema-invalid AI output;
- low-confidence finding;
- evaluator conflict;
- critical criterion failed;
- manual review required;
- settlement superseded after new evidence;
- unauthorized or cross-tenant access.

## 5. Target system

### Domain layer

Owns agreements, criteria, evidence metadata, findings, review policy, case state transitions, proportional allocation, reason codes, and evaluation identity. It contains no network, model-provider, protocol, UI, or database imports.

### Application layer

Coordinates use cases:

- draft agreement;
- approve and activate agreement;
- attach evidence;
- request AI review;
- accept or challenge findings;
- calculate settlement;
- supersede a recommendation when evidence changes;
- export a recommendation.

It enforces authorization, idempotency, state transitions, and audit events through interfaces.

### AI review layer

Converts allowed evidence content into schema-valid findings. It uses versioned prompts, a provider adapter, local output validation, evidence-reference verification, confidence policy, and bounded retries. It cannot call the settlement calculator with modified weights or amounts.

### MCP layer

Registers application use cases as agent tools and case snapshots as authorized resources. Use the stable v2 official TypeScript SDK. The remote endpoint uses the current handler/factory API in stateless Streamable HTTP mode. Local integrations use stdio. MCP code does not duplicate domain logic.

### Persistence layer

Use PostgreSQL for production records. Recommended tables:

- `tenants`
- `principals`
- `agreements`
- `agreement_versions`
- `criteria`
- `cases`
- `evidence`
- `review_runs`
- `findings`
- `evaluations`
- `case_events`
- `idempotency_keys`

Financial amounts remain integer atomic units. Agreement versions become immutable when activated. Case events are append-only. Current-state tables are projections, not the only audit record.

### Artifact storage

The first production version accepts bounded text evidence and metadata for external artifacts. Binary uploads require object storage, signed upload URLs, MIME verification, size limits, malware scanning, and retention controls. Do not proxy arbitrary URLs through the application.

### Web application

The UI becomes a case workspace rather than a JSON playground. The advanced JSON view remains available for reviewers and developers.

## 6. Delivery phases

### Phase 0 — Baseline and contract freeze

Purpose: protect working behavior before structural changes.

Tasks:

- Tag or record the current public commit.
- Snapshot canonical full, partial, critical-failure, and conflict fixtures.
- Add golden parity tests for the current evaluation response.
- Document current performance and payload limits.
- Add TypeScript migration decision and tooling spike without changing runtime behavior.
- Confirm current public PR and deployment remain untouched.

Exit gates:

- Existing 18 tests pass.
- Golden fixtures reproduce exactly.
- No public artifact changes.

### Phase 1 — Domain extraction and shared schemas

Purpose: create one trustworthy contract for REST, MCP, AI, persistence, and UI.

Tasks:

- Move evaluator code into `src/domain/` through behavior-preserving commits.
- Define runtime schemas for agreement, criterion, evidence, finding, policy, evaluation, and reason code.
- Add `CaseState` and explicit transition rules.
- Separate input normalization from settlement calculation.
- Define application ports for clock, ID generation, repositories, and review provider.
- Generate or derive OpenAPI and MCP schemas from the same domain definitions where practical.
- Preserve stable v1 response fields or introduce an explicit versioned endpoint.

Exit gates:

- Golden parity tests pass.
- Domain package runs without network or database dependencies.
- Invalid state transitions have tests.
- HTTP contract remains backward compatible.

User review: architecture boundaries and revised schemas.

### Phase 2 — AI adjudication vertical slice

Purpose: prove that AI can produce useful evidence-grounded findings without controlling money.

Tasks:

- Add a provider-neutral `ReviewProvider` interface.
- Add a deterministic fake provider for tests.
- Add the first hosted-model adapter behind server-only configuration.
- Define strict JSON schemas for review findings and settlement explanations.
- Implement evidence packaging with size/token budgets and redaction hooks.
- Require criterion IDs, evidence IDs, rationale, score, confidence, missing evidence, and contradiction flags.
- Reject unknown IDs, uncited claims, duplicate findings, impossible scores, and contract modifications.
- Add one bounded retry for transient upstream errors.
- Add review-run provenance: provider, model, prompt version, schema version, latency, usage, and correlation ID.
- Add an evaluation corpus covering complete, partial, missing, contradictory, adversarial, and irrelevant evidence.

Exit gates:

- AI findings pass local schema and reference validation.
- The model cannot directly set release or hold amounts.
- Provider timeout/refusal/error leaves the case recoverable.
- Low confidence and critical gaps route to clarification or manual review.
- Evaluation thresholds in `docs/ai-adjudication-spec.md` pass.

User review: findings, explanations, costs, latency, and adversarial results.

### Phase 3 — MCP-native workflow

Purpose: let real agents complete the case workflow.

Tasks:

- Add the stable official MCP v2 server and client packages with exact lockfile versions.
- Implement a shared MCP server factory.
- Add local stdio entrypoint.
- Add remote `/mcp` entrypoint using stateless Streamable HTTP and compatibility support provided by the official handler.
- Implement the tool surface in `docs/mcp-interface-spec.md`.
- Return structured tool output plus concise text summaries.
- Add MCP resources for authorized case snapshots and evaluation reports.
- Implement production bearer-token resource-server auth and scope checks.
- Add Host/Origin protection and request-size limits.
- Build an SDK-client integration suite for discovery, success, invalid input, unauthorized access, timeout, and manual-review responses.
- Add configuration examples for supported agent hosts.

Exit gates:

- A real client discovers and invokes every tool over stdio and HTTP.
- Tool output validates against the same schemas as REST.
- Cross-tenant resource reads fail.
- No tool has payment authority.

User review: tool descriptions, transcript, permissions, and agent ergonomics.

### Phase 4 — Durable case workflow

Purpose: make case history auditable and recoverable.

Tasks:

- Add PostgreSQL migrations and repository implementations.
- Add immutable agreement versions and append-only case events.
- Add idempotency keys for all mutations.
- Add optimistic concurrency/version checks for case updates.
- Store evidence metadata separately from optional evidence bodies.
- Add recommendation supersession when new evidence or findings are accepted.
- Add tenant quotas and retention configuration.
- Add backup/restore and migration rollback procedures.

Exit gates:

- Duplicate requests cannot create duplicate evidence, reviews, or evaluations.
- Refresh/reconnect preserves committed state.
- Concurrent changes are detected rather than overwritten.
- Audit replay reconstructs the visible case history.
- Tenant isolation tests pass.

### Phase 5 — Product experience

Purpose: make the proportional outcome obvious and trustworthy.

Build the workspace defined in `docs/product-spec.md`:

- agreement composer and approval;
- evidence inbox;
- AI review status and findings;
- criterion allocation ledger;
- dominant release/hold recommendation;
- “Why this amount?” explanation;
- missing-evidence and dispute panels;
- activity trace and provenance;
- MCP connection panel;
- advanced JSON view;
- full, partial, critical-failure, and conflict demos.

Required UX states:

- loading;
- empty case;
- draft agreement;
- evidence required;
- review running;
- partial review failure;
- clarification required;
- manual review;
- recommendation ready;
- superseded recommendation;
- permission denied;
- service unavailable.

Exit gates:

- A first-time reviewer understands why a settlement is proportional without reading JSON.
- Long-running AI work shows progress and can recover from failure.
- Mutating controls prevent accidental double submission.
- Accessibility and responsive-layout checks pass.

User review: complete product walkthrough and visual QA.

### Phase 6 — Production hardening

Purpose: make the deployed system safe and operable.

Tasks:

- Validate all production environment variables at startup.
- Add authentication, tenant roles, and MCP scopes.
- Add structured logs, metrics, traces, audit events, and alerts.
- Add per-tenant rate limits, model spending limits, and circuit breakers.
- Add request deadlines, cancellation propagation, and bounded retries.
- Add CSP, strict CORS, security headers, dependency scanning, and secret scanning.
- Add privacy controls, retention jobs, and evidence deletion behavior consistent with immutable audit requirements.
- Load-test the settlement and MCP paths.
- Run threat modeling and focused security review.
- Verify production build and deployed critical path.

Exit gates are specified in `docs/security-reliability.md` and `docs/test-release-plan.md`.

### Phase 7 — Submission update

Purpose: update the public artifact only after approval.

Tasks:

- Rewrite positioning around AI-assisted proportional settlement.
- Record a real MCP client workflow.
- Update architecture, API, MCP, data, security, and limitation disclosures.
- Re-run source tests, AI evals, production checks, and official submission validators.
- Produce the exact source snapshot tied to the deployed commit.
- Show the user the product, copy, rights declaration, commit, deployment, and PR diff.
- Push and update the existing PR only after explicit approval.

## 7. Release slices

### Slice A — Reviewable intelligence

Domain extraction plus AI findings, runnable locally with fake and real providers. No public release.

### Slice B — Agent-callable Docket

MCP stdio and HTTP, end-to-end client transcript, stateless case input. Suitable for a reviewed hackathon update if time is constrained.

### Slice C — Durable production beta

Authentication, tenant isolation, case persistence, idempotency, audit history, quotas, and production UI.

Do not label Slice A or B “production-ready.”

## 8. Dependencies and configuration

Expected categories, selected and pinned during implementation:

- official MCP v2 server and client packages;
- a runtime schema validator;
- TypeScript and test/build tooling;
- official model-provider SDK for the first adapter;
- PostgreSQL client and migration tooling;
- structured logging and telemetry exporters;
- browser test tooling.

Production configuration will include:

- database URL;
- model provider and server-side API key;
- model and prompt versions;
- AI timeout, retry, token, and spending limits;
- OAuth issuer, audience, JWKS, and allowed scopes;
- allowed hosts and origins;
- evidence and request limits;
- retention policy;
- deployment commit and submission slug.

No secret may use a `PUBLIC_`-style client-exposed variable.

## 9. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| AI invents evidence | Require supplied evidence IDs, local reference validation, and fail closed |
| AI changes the agreement | Activated agreement versions are immutable; reject unknown requirements or weights |
| AI output is inconsistent | Strict schema, evaluation corpus, provider/model pinning, provenance, and human-review thresholds |
| Settlement appears legally authoritative | Use recommendation language, visible limits, and separate payment authority |
| Model outage blocks cases | Preserve direct structured findings, retries bounded to one, manual-review fallback |
| Evidence leaks to a provider | Explicit consent, minimization, redaction, `store: false` where supported, retention disclosure |
| MCP endpoint is abused | OAuth resource-server auth, scopes, quotas, payload limits, Host/Origin checks |
| Duplicate agent calls mutate twice | Idempotency keys and unique constraints |
| New evidence silently rewrites history | Append-only events and superseded evaluations |
| Product story becomes generic AI review | Keep release/hold amount and criterion allocation central in copy and UI |
| Public submission changes without review | Mandatory user checkpoint before push, deployment, rights, or PR changes |

## 10. Definition of done

The upgrade is complete only when:

- the critical workflow works through both the web product and a real MCP client;
- AI findings are grounded, schema-valid, versioned, and evaluated;
- the settlement kernel independently computes every amount;
- all important mutations are authenticated, authorized, idempotent, and audited;
- cases survive retry, refresh, reconnect, provider outage, and process restart;
- tenant isolation and security tests pass;
- production logs and metrics diagnose failures without leaking evidence;
- the production build and deployment are verified manually;
- rollback is tested;
- the user approves the final product, public copy, rights language, deployment, and PR diff.
