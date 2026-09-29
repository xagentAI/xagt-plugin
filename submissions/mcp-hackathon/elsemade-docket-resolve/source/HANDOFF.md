# Docket upgrade handoff

Updated: September 24, 2026

## Objective

Upgrade Docket Resolve from a stateless settlement calculator into an AI-assisted, MCP-native settlement control plane for agent-to-agent work.

The product story is:

> Docket reviews agent work and turns evidence into explainable, proportional settlements.

The memorable outcome is the proportional recommendation: for example, release 230 USDC and hold 20 USDC, with every amount traceable to an agreed acceptance criterion.

## Public state

- Source repository: https://github.com/ShalyX/docket-resolve
- Public deployment: https://docket-resolve.vercel.app
- Official submission PR: https://github.com/xagentAI/xagt-plugin/pull/74
- PR state at handoff: open, mergeable, automated receipt check passing, awaiting manual review
- Final hardening release: approved, published from the reviewed source, and ready for final submission metadata binding

Future public updates still require user review and explicit approval.

## Verified existing behavior

- Node.js 20+ ESM application with pinned MCP v2 and Zod runtime dependencies.
- `POST /v1/evaluations` validates an agreement and returns a settlement recommendation.
- Criterion weights must total 100.
- Evidence and findings must reference the same criterion.
- Each evaluator may submit at most one finding per criterion.
- Criterion scores are confidence-weighted.
- Missing passing evidence earns no value.
- Failed critical criteria apply a declared release cap.
- Material evaluator disagreement returns `manual_review` with null financial fields.
- Identical semantic input produces the same evaluation ID.
- `/health` and the X-Agent proof endpoint bind the deployment to its source commit.
- 47 automated tests and syntax checks pass.

## Current released upgrade slice

- A provider-neutral AI review boundary exists.
- The default hosted provider is Gemini `gemini-3.1-flash-lite`, using schema-constrained JSON and local validation before findings reach the settlement kernel.
- An optional OpenAI Responses adapter remains available; the deterministic fixture provider is retained only as an explicit test double.
- REST exposes `POST /v1/reviews`.
- MCP exposes `docket_validate_agreement`, `docket_review_case`, and `docket_resolve_case` over stdio and Streamable HTTP.
- `npm run demo:agent` executes the full validation → cited review → proportional resolution workflow through a real MCP stdio client.
- Persisted case lifecycle exists through HTTP and MCP: create, get, retrieve evidence, review, and resolve.
- Bearer-token authentication maps agents to tenants; case reads and writes are tenant-scoped.
- MCP tools enforce read and write scopes independently; read-only identities cannot mutate cases.
- Review and evidence-retrieval retries are idempotent before external model or network work, including same-process concurrent retries.
- Evidence retrieval is bounded to HTTPS, requires an explicit allowlist in required-auth/production mode, checks resolved addresses for private ranges, blocks private hosts, rejects redirects, enforces size/time limits, and verifies SHA-256 digests.
- The local reviewer workspace uses a deterministic, synthetic evidence fixture so its default “Retrieve & verify URLs” flow succeeds without public network dependencies; the all-failed retrieval state remains an explicit regression case, and production configuration never injects the fixture provider.
- The responsive case workspace shows the release/hold ledger, cited findings, review state, and audit events.
- `npm run demo:mcp:production` exercises the authenticated production-like MCP sequence and cross-tenant rejection.
- The canonical workflow returns 230 USDC release, 20 USDC hold, and `fundsMoved: false`.

This slice is implemented, verified, and published. It is a hackathon release,
not a claim that the full production plan is complete.

## Known limitations

- The persistent store is file-backed and single-host; it is not a durable shared database for serverless or multiple instances.
- Authentication is an opaque bearer-token map for the local production profile, not a full OAuth resource server or identity-provider integration.
- The public hackathon deployment is an anonymous sandbox. Its rate limit is a best-effort per-process guardrail, not a distributed production quota.
- Evidence retrieval does not yet perform malware scanning or tenant-approved connector integrations.
- The workspace supports local direct evidence notes; hosted evidence connectors and richer case navigation remain future work.
- There is no payment or wallet integration by design.

## Decisions already made

1. Proportional settlement is the hero feature.
2. The AI produces evidence-grounded findings; it never chooses the financial amount directly.
3. The settlement kernel remains deterministic, pure, and separately testable.
4. Low-confidence, missing-critical-evidence, or conflicting cases fail closed.
5. Docket remains recommendation-only. A separate authorized system decides whether to execute payment.
6. MCP supports local stdio plus authenticated Streamable HTTP for the persisted case lifecycle.
7. The first model integration uses a provider abstraction and strict structured output.
8. Production persistence uses a case record plus immutable event history; the hackathon demo may ship before multi-tenant persistence if the limitation is explicit.
9. Future pushes, deployments, and submission changes require user review of the phase output.

## First implementation slice

The AI/MCP, persistence, auth, evidence, MCP production-flow, and responsive workspace slices above are complete. The next implementation slice should be:

1. Move evaluator schemas and logic into `src/domain/` without changing behavior.
2. Add domain tests that prove output parity with v0.1 fixtures.
3. Replace the single-host store with a shared transactional database and migration/backup gates.
4. Replace opaque local tokens with the approved OAuth/resource-server identity model.
5. Add evidence connector integrations, malware scanning, and tenant-specific source policies.
6. Run the real hosted-model evaluation corpus with an approved model budget and CI browser E2E.

The AI-to-kernel boundary is now proven with the Gemini adapter and fixture test double and must remain intact while
the remaining slices are implemented.

## Required user reviews

Stop and present evidence after each checkpoint:

1. **Domain checkpoint:** schemas, boundaries, and unchanged settlement output.
2. **AI checkpoint:** real and adversarial example findings, model cost/latency, and failure behavior.
3. **MCP checkpoint:** tool list, client transcript, auth boundary, and structured outputs.
4. **Product checkpoint:** complete case workspace and the “why 230 of 250?” interaction.
5. **Release checkpoint:** production preview, tests, security review, revised submission copy, rights declaration, and exact PR diff.

## Open decisions requiring user input later

- Production identity provider and tenant model.
- Whether evidence bodies may be sent to a hosted model provider.
- Initial model/provider and spending ceiling.
- Whether durable case history is required for the hackathon update or follows immediately after it.
- The legal submitter identity in `RIGHTS.md`.
- Whether a payment-instruction export should target a specific wallet or escrow protocol in a later phase.

These decisions do not block local domain, MCP, fake-provider, or UI work.

## Validation commands

Current baseline:

```bash
npm ci
npm test
npm run check
npm run test:e2e
npm run test:mcp
npm run test:ai
npm run demo:mcp:production
```

After the upgrade, the repository must also provide and pass:

```bash
npm run typecheck
npm run lint
npm run test:mcp
npm run test:integration
npm run eval
npm run build
```

Do not add empty scripts to satisfy this list. Each command must execute a real gate.

## Handoff completion condition

Another agent should be able to read `AGENTS.md`, this file, and the specifications under `docs/`, implement the phases in order, and know exactly when to stop for user review.
