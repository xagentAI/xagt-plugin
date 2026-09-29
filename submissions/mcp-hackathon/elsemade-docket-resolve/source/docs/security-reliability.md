# Security and reliability specification

## Security objective

Docket handles evidence and financial recommendations. It must prevent untrusted content, model output, replayed requests, or unauthorized agents from changing an agreement, crossing tenant boundaries, or creating misleading settlement authority.

The safest failure is an explicit clarification or manual-review state. Availability never justifies inventing findings or bypassing authorization.

## Trust boundaries

```text
Untrusted callers and MCP hosts
            |
            v
Authentication, authorization, quotas, schema validation
            |
            v
Application services and case-state rules
      |                 |
      v                 v
Untrusted evidence   Untrusted AI output
      |                 |
      +------validation-+
                |
                v
        settlement kernel
                |
                v
      recommendation record
```

Additional boundaries:

- browser to HTTP API;
- MCP transport to application services;
- application to the single-host case/event store (shared PostgreSQL remains the next migration);
- application to model provider;
- application to optional object storage;
- deployment environment to public internet;
- recommendation export to an external payment authority.

## Data classification

| Class | Examples | Controls |
| --- | --- | --- |
| Public | Demo agreements, public repository URLs, published API docs | Normal integrity controls |
| Internal | Case metadata, model usage, operational metrics | Authenticated access, tenant isolation |
| Confidential | Evidence bodies, private deliverables, dispute rationales | Encryption, minimization, scoped access, retention limits |
| Restricted | API keys, OAuth secrets, database credentials, signing material | Secret manager only; never model input, logs, browser, or MCP arguments |

Docket must not accept wallet seed phrases, private keys, or transaction signatures. If detected, reject and instruct the caller to rotate compromised material through the relevant wallet process.

## Authentication

### Web and REST

- Use an external identity provider.
- Validate issuer, audience, expiry, signature, and required claims server-side.
- Use short-lived access tokens.
- Do not store bearer tokens in logs or analytics.
- Session cookies, if used, are `HttpOnly`, `Secure`, and `SameSite` appropriate to the deployment.

### Remote MCP

- Operate as an OAuth bearer-token resource server.
- Publish protected-resource metadata.
- Enforce operation scopes and tenant membership.
- Support machine identities through client credentials or another approved non-user grant.
- Return 401 for invalid tokens and 403 for insufficient scope without leaking object existence.

### Local stdio

Local execution inherits the spawning process identity. Persistent remote data still requires an explicit access token or approved local credential provider; stdio is not an authentication bypass.

The current production-like profile implements opaque bearer tokens mapped server-side to a tenant,
subject, and scopes. It is suitable for the authenticated hackathon workflow, but it is not a
replacement for issuer/audience/signature validation through the approved OAuth resource server.

## Authorization model

Roles:

- `owner` — tenant administration and policy;
- `agreement_author` — create/edit drafts;
- `agreement_approver` — activate agreed versions;
- `evidence_submitter` — add evidence to allowed cases;
- `review_operator` — run review and inspect findings;
- `case_participant` — inspect and challenge assigned cases;
- `auditor` — read audit records without mutation;
- `service_agent` — explicit scopes only.

Authorization is evaluated inside application services, not only at routes or MCP handlers.

Rules:

- Every row is tenant-scoped.
- Object identifiers alone never grant access.
- Agreement activation requires an approver distinct from an untrusted worker agent when policy requires separation.
- Review providers are not principals and cannot mutate cases directly.
- Export does not imply payment execution permission.

## Financial integrity

- Amounts are positive integers in atomic units with explicit asset decimals.
- Use checked integer arithmetic and preserve the existing safe bound until a big-integer migration is designed and tested.
- Criterion allocations reconcile exactly to the agreement amount according to the documented rounding rule.
- Only the domain kernel calculates financial fields.
- AI inputs omit amount and weight during criterion scoring.
- Explanations are verified against the resulting ledger.
- Activated agreement versions and evaluations are immutable.
- Superseding a recommendation creates a new record and audit event.
- Recommendation exports include digests, versions, timestamps, and `recommendationOnly: true`.
- No code path constructs or submits a blockchain or payment transaction.

## Prompt injection and untrusted evidence

Evidence is data, never instructions.

Controls:

- Delimit evidence separately from system and policy instructions.
- Tell the model to ignore commands found inside evidence.
- Review one criterion with a bounded evidence set.
- Strip or neutralize active HTML and executable content during normalization.
- Do not execute uploaded code as part of AI review.
- Validate every evidence citation locally.
- Reject new requirements that do not match the frozen criterion.
- Include prompt-injection fixtures in every AI evaluation run.
- Treat model explanations as untrusted until ledger consistency checks pass.

## Evidence ingestion

Initial supported content:

- bounded UTF-8 text;
- structured test result JSON matching an explicit schema;
- metadata and digests for externally stored artifacts;
- selected image/PDF workflows only after scanning and provider/privacy review.

The current bounded fetcher supports HTTPS evidence references only when the deployment allowlist
permits the host. In required-auth/production mode, an explicit allowlist is mandatory. It checks
DNS-resolved addresses for private/local ranges, rejects private/local hosts and redirects,
enforces response time and byte limits, stores no cookies, and requires the fetched SHA-256 digest
to match the agreement before marking evidence verified. It does not yet provide malware scanning
or tenant-specific connector policies.

The preflight DNS check and the HTTP connection are separate operations in this reference fetcher.
Do not allow untrusted or attacker-controlled domains in a production allowlist; a hardened
multi-tenant deployment should use a connector or egress proxy that pins the approved address
through connection establishment and enforces the same policy on every request.

The reviewer workspace has a deterministic fixture evidence provider for local development. It is
selected only outside `NODE_ENV=production` and outside the required-auth profile, uses a synthetic
allowlisted host, and never makes a network call. Production configuration does not inject that
fetcher or resolver; unreachable and digest-mismatched references continue through the normal
explicit failure path.

Any production fetcher or connector must retain these controls and add:

- `https` only;
- DNS resolution and private/reserved IP rejection before every connection;
- redirect count and cross-origin redirect controls;
- explicit host allowlist or tenant-approved source integration;
- connection and total timeouts;
- response byte and decompression limits;
- MIME sniffing and allowlist;
- malware scanning;
- no ambient cloud credentials;
- no cookie forwarding;
- audit logs without sensitive bodies.

## Input and output validation

Validate at every boundary:

- REST request body and headers;
- MCP tool arguments;
- database records read from persistence;
- model-provider structured output;
- model-provider errors and usage metadata;
- environment variables;
- recommendation export;
- client-rendered content.

Client validation improves UX but never replaces server validation.

## Idempotency and concurrency

Mutations require a client-supplied idempotency key and canonical request digest.

Database transaction behavior:

1. authorize principal and tenant;
2. reserve or load idempotency key;
3. verify request digest;
4. check expected case version;
5. apply state transition and write immutable event;
6. update projection;
7. persist response;
8. commit atomically.

Use unique constraints to enforce one semantic operation where appropriate. Use optimistic concurrency for case updates. Do not hold a database transaction open across a model-provider call; create a review run, call the provider outside the transaction, then finalize against the expected version.

## Failure semantics

### User-visible states

- validation error — caller can fix input;
- permission error — caller needs access;
- version conflict — caller reloads and reconciles;
- evidence required — caller supplies named evidence;
- clarification required — caller answers a narrow question;
- manual review — a safe terminal review state until a human acts;
- provider delayed/unavailable — case remains recoverable;
- rate limited — include safe retry timing;
- internal failure — return request ID and preserve committed state.

### Retry policy

- No automatic retry for validation, authorization, refusal, manual-review, or schema-invalid model output.
- One bounded retry for transient model or network failure when the overall deadline permits.
- Database serialization/deadlock failures may retry a small bounded number with jitter if idempotency is in place.
- Clients may retry safe reads.
- Mutations may be retried only with the same idempotency key.
- Never use unbounded retry loops.

### Timeouts

Configure and test separate limits for:

- request body read;
- database query and transaction;
- model-provider connect and total response;
- MCP operation;
- browser request;
- graceful shutdown.

Propagate cancellation to provider and database operations where supported. A client disconnect must not leave an ambiguous committed mutation.

## Rate and cost limits

- Per-IP limit for anonymous demo traffic.
- Per-principal and per-tenant operation quotas.
- Separate AI-review concurrency and daily spend limits.
- Maximum cases, criteria, evidence items, evidence bytes, and review runs per case.
- Hard cap on model input/output tokens and reasoning budget.
- Circuit breaker for sustained provider failure.
- Operators can disable AI review without disabling deterministic validation and settlement.

## Secrets

- Store secrets in the deployment secret manager.
- Validate presence at startup only for enabled features.
- Keep model keys and database credentials server-side.
- Redact common token formats, authorization headers, cookies, and connection strings from logs.
- Never copy production secrets into preview environments or fixtures.
- Rotate secrets after suspected exposure and record the incident.
- Secret scanning runs before every public push.

## Browser security

- Strict Content Security Policy appropriate to actual assets.
- `frame-ancestors 'none'` unless embedding is explicitly required.
- `X-Content-Type-Options: nosniff`.
- Referrer policy minimizing evidence URL disclosure.
- Restrictive CORS; wildcard only for the isolated public sandbox if justified.
- CSRF protection for cookie-authenticated mutations.
- Output encoding and sanitized rendering for all evidence/model text.
- No raw HTML generated by models.
- Disable autocomplete for secret-bearing administrative fields.

## Database and audit

- PostgreSQL connections require TLS in production.
- Apply least-privilege database roles.
- Migrations are versioned, reviewed, and tested forward and backward where feasible.
- Backups are encrypted and restore drills are scheduled.
- Immutable case events contain event type, actor, tenant, object versions, request ID, timestamp, and safe metadata.
- Audit events never contain unrestricted evidence bodies or secrets.
- Administrative access is separately audited.

## Observability

### Structured logs

Include:

- timestamp and severity;
- request/trace ID;
- tenant and principal pseudonymous IDs;
- transport and operation;
- case/review/evaluation IDs;
- status and stable error code;
- duration;
- model/provider identifiers and token usage;
- deployment commit.

Exclude:

- authorization headers and cookies;
- API keys and connection strings;
- unrestricted evidence or prompt bodies;
- wallet or payment secrets;
- personal data unless explicitly required and protected.

### Metrics

- request count, latency, and error rate by REST/MCP operation;
- active and failed reviews;
- model latency, token usage, cost, refusal, and schema-failure rates;
- clarification/manual-review rate;
- idempotency replay/conflict rate;
- database pool and query health;
- case transition failures;
- recommendation generation and supersession rate.

### Alerts

Alert on:

- elevated 5xx or MCP internal errors;
- health/proof commit mismatch;
- model schema or citation failures above threshold;
- cross-tenant authorization failures suggesting probing;
- spending or quota anomalies;
- database saturation;
- recommendation invariant violation;
- secret-scanner or dependency-critical findings.

## Service objectives

Initial beta targets, reviewed after measurement:

- deterministic validation/settlement availability: 99.9 percent monthly;
- deterministic API p95 latency: under 500 ms excluding cold starts;
- MCP deterministic tool p95 latency: under 750 ms excluding client network;
- AI review p95 completion: under 30 seconds for the bounded standard fixture;
- recommendation invariant violations: zero;
- cross-tenant data exposure: zero;
- AI citation/reference validation: 100 percent;
- recovery point objective for case data: 15 minutes or better;
- recovery time objective: 4 hours or better.

Do not hide AI-provider downtime inside the deterministic service availability number.

## Deployment

Environments:

- local — fake provider by default, local database option;
- test — isolated database and provider mocks;
- preview — isolated data, explicit model budget, no production secrets;
- production — protected domain, production IdP, backups, alerts, and quotas.

Requirements:

- exact Git commit exposed by health and deployment proof;
- startup configuration validation;
- separate credentials and databases by environment;
- reproducible dependency lock;
- migration step with rollback/restore plan;
- smoke tests after deployment;
- manual product inspection;
- previous known-good deployment retained for rollback.

## Incident response

Severity examples:

- SEV-1: cross-tenant exposure, secret exposure, financial-invariant failure, unauthorized mutation;
- SEV-2: widespread inability to review or resolve cases, audit corruption, sustained provider runaway cost;
- SEV-3: isolated review failure, degraded UI, non-critical integration issue.

Response outline:

1. stop or isolate the affected capability;
2. preserve logs and audit evidence;
3. rotate exposed credentials;
4. assess affected tenants/cases;
5. invalidate or supersede suspect recommendations;
6. restore known-good service;
7. communicate accurately;
8. complete root-cause and corrective-action review.

## Security release gates

- Threat model reviewed for the changed surface.
- Authentication and authorization tests pass.
- Cross-tenant tests pass.
- Prompt-injection and evidence-reference tests pass.
- No AI-created financial fields accepted.
- Idempotency and concurrency tests pass.
- Secret and dependency scans pass with no unresolved critical issue.
- Security headers and CORS verified in deployment.
- Logs inspected for sensitive leakage.
- Backup/restore verified for persistence releases.
- Rollback rehearsed.
