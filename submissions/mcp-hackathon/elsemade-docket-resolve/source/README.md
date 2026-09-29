# Docket Resolve

Docket is the settlement control plane for agent-to-agent work. It turns evidence against pre-agreed acceptance criteria into an explainable, proportional release and hold recommendation.

## AI + MCP product

Docket combines a provider-neutral AI evidence reviewer, a local settlement kernel, persisted case workflows, and an MCP interface. The public hackathon build is available at [docket-resolve.vercel.app](https://docket-resolve.vercel.app), and its source is reviewed through the [official X-Agent submission PR](https://github.com/xagentAI/xagt-plugin/pull/74).

- [Production plan](docs/production-plan.md)
- [Product specification](docs/product-spec.md)
- [AI adjudication specification](docs/ai-adjudication-spec.md)
- [MCP interface specification](docs/mcp-interface-spec.md)
- [Security and reliability specification](docs/security-reliability.md)
- [Test and release plan](docs/test-release-plan.md)
- [Agent instructions](AGENTS.md)
- [Current handoff](HANDOFF.md)

It does one job: given an agreed amount in explicitly denominated atomic units, weighted acceptance criteria, evidence references, and evaluator findings, return how much should be released, how much should remain on hold, and why.

The service does not move funds, fetch private data, or pretend to verify evidence it cannot see. It produces a recommendation that another agent, marketplace, or human can inspect before acting.

## Why agents need it

Agent marketplaces can automate task assignment and payment, but disputes still collapse into an all-or-nothing choice. Docket makes the acceptance contract machine-readable and preserves the reasoning behind a proportional outcome.

Typical callers include:

- an orchestrator checking a subcontractor's deliverables;
- a marketplace preparing an escrow release proposal;
- a review agent comparing independent findings;
- a human operator who needs an auditable case record.

## Run locally

Requirements: Node.js 20 or newer.

```bash
npm ci
npm test
npm run check
cp .env.example .env.local
# Add a server-side GEMINI_API_KEY to .env.local.
npm start
```

Open `http://localhost:3000` for the interactive workspace.

For a local MCP process:

```bash
npm run mcp
```

For the reproducible agent workflow:

```bash
npm run demo:agent
npm run demo:mcp:production
```

The local default uses Gemini review with schema-constrained findings and local-only fixture evidence, so the reviewer workspace can complete “Retrieve & verify URLs” without depending on public evidence endpoints. Set `GEMINI_API_KEY` server-side; the default model is `gemini-3.1-flash-lite`. Hosted review is never enabled from an ambient credential alone.

The fixture evidence is never enabled when `NODE_ENV=production` or when authentication is required. Production agents must supply real HTTPS evidence references, a matching SHA-256 digest, and an explicit host allowlist or connector policy. Gemini free-tier usage is appropriate for public demo evidence only because Google states that free-tier content may be used to improve its products. The missing/unreachable evidence path remains covered by an explicit all-failed regression test.

`demo:mcp:production` exercises the authenticated agent path with single-host persisted storage, tenant
isolation, idempotent retries, bounded evidence retrieval, digest verification, AI review, and
recommendation-only resolution. The reproducible test workflow uses explicit evidence and review
test doubles, so it does not make a network or model call and is not the runtime review provider.

### Public demo boundary

The hosted hackathon deployment is an anonymous sandbox, not a private production tenant. Do not submit sensitive or private evidence to it. Its unauthenticated request limit is a best-effort, per-process demo guardrail; multi-instance production requires a shared rate limiter. The file-backed case store is appropriate for the local and single-host reference workflow, but serverless instances do not provide a durable shared database. A real deployment must enable required authentication, use tenant-specific tokens or OAuth, configure an evidence-host allowlist, and replace the store and rate limiter with shared transactional infrastructure.

## API

### Evaluate an agreement

```bash
curl -X POST http://localhost:3000/v1/evaluations \
  -H "content-type: application/json" \
  --data-binary @examples/agreement.json
```

The complete machine-readable contract is available at `GET /openapi.json`.

### MCP tools

The same domain is available through MCP at `http://localhost:3000/mcp` or through the local stdio command. The first vertical slice exposes:

- `docket_validate_agreement`
- `docket_review_case`
- `docket_resolve_case`
- `docket_create_case`
- `docket_get_case`
- `docket_retrieve_evidence`
- `docket_review_persisted_case`

AI review produces cited findings and confidence. The settlement kernel alone calculates release and hold amounts.

Production agents should use the persisted sequence:

1. `docket_create_case` with an `Idempotency-Key`.
2. `docket_retrieve_evidence` to fetch HTTPS references and verify SHA-256 digests.
3. `docket_review_persisted_case` to save evidence-grounded findings.
4. `docket_resolve_case` to calculate the proportional recommendation.

The HTTP MCP endpoint requires a bearer token when `DOCKET_AUTH_MODE=required`. Tokens resolve
to a tenant and subject on the server; a case ID from another tenant returns `CASE_NOT_FOUND`.

### Verification endpoints

```text
GET /health
GET /.well-known/xagent-verification.json
```

Production deployments must set `XAGT_COMMIT` to the exact 40-character reviewed Git commit and `XAGT_SLUG` to the submission directory slug. The endpoints deliberately expose those values so reviewers can bind the running service to its source.

## Decision model

1. Criterion weights must total 100.
2. Every finding must cite evidence for the same criterion.
3. Each evaluator may submit at most one finding per criterion.
4. Findings are aggregated by confidence-weighted score.
5. A criterion with no passing evidence earns nothing; failed evidence also marks it contradicted.
6. A failed critical criterion applies the agreement's declared release cap.
7. A score spread at or above the declared conflict threshold routes the case to manual review and suppresses the financial recommendation.
8. Otherwise, each criterion earns its weighted share of the agreement amount and the shares are summed.

The `evaluationId` is derived from a canonical SHA-256 digest of the input. Identical input produces the same result and identifier.

## Safety boundaries

- Recommendations only. No wallet, escrow, or payment authority is present.
- AI review is advisory and is validated locally before findings reach the settlement kernel.
- HTTPS evidence references and SHA-256 digests are required. Production retrieval also requires an explicit host allowlist and checks resolved addresses, but the API still does not claim that a referenced artifact is truthful.
- Conflicting evaluators fail closed into manual review.
- Invalid references, duplicate IDs, malformed JSON, and oversized bodies return structured errors.
- Cases, review results, retrieval metadata, and immutable lifecycle events are persisted in the
  file-backed store configured by `DOCKET_STORAGE_PATH`. This is persistent for a single process or
  single-host deployment; multi-instance production should replace it with a transactional shared
  database before launch.
- Request logs never include agreement bodies or evidence content.

See [docs/verification.md](docs/verification.md) for repeatable reviewer checks and [docs/architecture.md](docs/architecture.md) for the system boundary.

## Environment

| Variable | Purpose | Default |
| --- | --- | --- |
| `PORT` | HTTP port | `3000` |
| `HOST` | Bind address | `0.0.0.0` |
| `XAGT_COMMIT` | Exact reviewed Git commit | `development` |
| `XAGT_SLUG` | X-Agent submission slug | `elsemade-docket-resolve` |
| `ALLOWED_ORIGIN` | CORS origin | `*` |
| `DOCKET_AUTH_MODE` | `off` or `required` | `off` |
| `DOCKET_AUTH_TOKENS` | JSON bearer-token-to-tenant map | unset |
| `DOCKET_STORAGE_PATH` | Durable case/event store path | `data/docket-store.json` |
| `DOCKET_EVIDENCE_ALLOW_HOSTS` | Comma-separated HTTPS evidence host allowlist | empty |
| `DOCKET_EVIDENCE_REQUIRE_ALLOWLIST` | Require the evidence allowlist even outside required auth mode | `false` |
| `DOCKET_PUBLIC_RATE_LIMIT_PER_MINUTE` | Per-process limit for unauthenticated POST requests | `30` |
| `DOCKET_EVIDENCE_FIXTURE` | Enable local-only deterministic evidence fixtures | `true` in local fixture mode; never in production |
| `DOCKET_AI_PROVIDER` | `gemini`, `openai`, or explicit `fixture` test double | `gemini` |
| `DOCKET_AI_MODEL` | Hosted review model | `gemini-3.1-flash-lite` |
| `GEMINI_API_KEY` | Server-only Gemini API credential | unset |
| `GEMINI_BASE_URL` | Gemini API base URL | `https://generativelanguage.googleapis.com/v1beta` |
| `OPENAI_API_KEY` | Server-only hosted review credential | unset |
| `OPENAI_BASE_URL` | OpenAI-compatible Responses API base | `https://api.openai.com/v1` |

## Repository map

```text
api/            Vercel function entrypoint
docs/           architecture and verification evidence
examples/       reproducible request and expected response
public/         interactive reviewer workspace
src/            domain evaluator, AI review, MCP, HTTP adapter and server
scripts/        reproducible agent workflow
test/           domain, AI, MCP and live HTTP contract tests
```
