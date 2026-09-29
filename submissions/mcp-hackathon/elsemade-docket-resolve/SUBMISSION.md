# Docket Resolve

## Track

Open Innovation Challenge.

## Capability

Docket Resolve is an evidence-grounded dispute and settlement workflow for AI agents. It turns a frozen acceptance agreement into cited criterion findings, a review trail, and an explainable proportional release-or-hold recommendation.

The important output is proportional settlement: an agent does not have to choose between paying everything and paying nothing. If weighted work is partly complete, Docket calculates the earned share and keeps the remainder on hold. Uncertain, conflicting, or unsupported findings fail closed into human review.

The AI reviewer is Gemini, configured server-side. The model proposes structured, evidence-cited findings; local schema validation and the settlement kernel remain authoritative. Docket never moves funds and never gives the reviewer payment authority.

## Live service

- **API base URL:** https://docket-resolve.vercel.app/v1
- **Health-check URL:** https://docket-resolve.vercel.app/health
- **Deployment proof:** https://docket-resolve.vercel.app/.well-known/xagent-verification.json
- **Review commit:** `a05274938888c1ead7627900dc3ea45db23123b2`
- **Source repository:** https://github.com/ShalyX/docket-resolve

The public demo is callable without a bearer token. The same service supports `DOCKET_AUTH_MODE=required` with bearer-token-to-tenant profiles for remote MCP agents; tenant-scoped case reads and writes are covered by the included tests.

## Agent and MCP workflow

The persisted production sequence is:

1. `docket_create_case` freezes the agreement in a tenant-scoped case.
2. `docket_retrieve_evidence` fetches HTTPS references, checks the declared SHA-256 digest, and persists verified results or explicit failures.
3. `docket_review_persisted_case` sends bounded evidence to Gemini and saves cited findings.
4. `docket_resolve_case` runs the proportional settlement kernel and records a recommendation-only settlement.

The HTTP MCP endpoint is available at `POST/GET /mcp`. The source package also includes a stdio MCP entrypoint for trusted local agents. The API and MCP surfaces expose the same review boundary: AI suggests findings, while Docket validates citations and calculates the settlement.

## Reproducibility

From `source/`:

```bash
npm ci
npm test
npm run check
```

The suite contains 47 passing tests covering Gemini adapter validation, evidence retrieval and digest checks, all-failed retrieval handling, persistence, retry-safe model calls, authentication and MCP scope enforcement, tenant isolation, MCP discovery, the full case lifecycle, proportional settlement, manual review, and the reviewer workspace.

The controlled demo evidence is reachable from the deployed service at `/fixtures/evidence/ev-smoke.txt`, `/fixtures/evidence/ev-docs.txt`, and `/fixtures/evidence/ev-errors.txt`. These are sample evidence artifacts for repeatable verification; the AI review provider is Gemini, not a fixture provider. The all-failed evidence path remains an explicit regression test.

## Expected result

The example agreement weighs API delivery at 50%, documentation at 30%, and edge-case handling at 20%. Its declared findings score 100, 90, and 75, producing:

- **Decision:** `release_partial`
- **Agreed amount:** 250 USDC
- **Recommended release:** 230 USDC
- **Recommended hold:** 20 USDC
- **Settlement ratio:** 92%

## Safety and data handling

- Recommendations only: no wallet, escrow, or payment authority is present.
- Evidence is treated as untrusted input and must be cited by the model; invalid citations fail local validation.
- HTTPS retrieval uses bounded time and size limits, DNS/private-network checks, explicit production host allowlists, and SHA-256 verification.
- Prompt-injection text inside evidence is not treated as policy.
- Requests and evidence are not written to request logs.
- The Gemini credential is server-side only and is excluded from the submitted source.
- The included JSON file store is persistent for a single process or single-host deployment; a serverless or multi-instance launch should replace it with a transactional shared database.
- The public deployment is an anonymous hackathon sandbox with a best-effort per-process rate limit. It must not be used for private evidence or represented as a production tenant.

## Rights

See `RIGHTS.md`. The source package is complete and contains no credentials or private user data.
