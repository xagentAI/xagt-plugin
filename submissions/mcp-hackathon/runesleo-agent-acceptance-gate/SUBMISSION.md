# Agent Acceptance Gate

## Capability

- **One-line description:** Deterministically audit an AI-agent delivery before acceptance and return a verdict, evidence gaps, risks, and the next safe gate.
- **Who it helps:** Agent marketplaces, buyers, evaluators, and orchestration systems that need a machine-readable acceptance gate.
- **Capability boundary:** Read-only evaluation of supplied evidence. It does not inspect a private repository, execute validation commands, sign, settle, pay, trade, mutate files, or change an account.
- **Track:** General Challenge (Open Innovation)

## Live API

- **API base URL:** https://api.leolabs.me
- **Capability URL:** https://api.leolabs.me/xagent/agent-delivery-acceptance-audit
- **Health-check URL:** https://api.leolabs.me/health
- **Deployment proof URL:** https://api.leolabs.me/.well-known/xagent-verification.json
- **Authentication:** None during the bounded reviewer window. The route is disabled unless `XAGENT_REVIEW_ENABLED=true` is explicitly deployed.
- **Rate limits / known limits:** Cloudflare Worker platform limits apply; JSON request bodies are capped at 1 MiB. The audit is deterministic and makes no outbound call on this route.
- **API contract:** `source/openapi.yaml`

## Source and reproducibility

- **Source repository:** https://github.com/runesleo/agent-acceptance-gate
- **Review commit:** `15c007b4a785a1263df989bb72c6e10e4b60ddf4`
- **Public branch:** `codex/xagent-mcp-hackathon-prep-20260917`
- **Source submitted in this PR:** `source/`
- **Setup:** `npm ci`
- **Run tests:** `npm test && npm run worker:check`
- **Run locally:** `npx wrangler dev --var XAGENT_GIT_COMMIT:15c007b4a785a1263df989bb72c6e10e4b60ddf4 --var XAGENT_PROJECT_SLUG:runesleo-agent-acceptance-gate --var XAGENT_REVIEW_ENABLED:true`
- **Deploy:** `npm run deploy:worker -- --var XAGENT_GIT_COMMIT:15c007b4a785a1263df989bb72c6e10e4b60ddf4 --var XAGENT_PROJECT_SLUG:runesleo-agent-acceptance-gate --var XAGENT_REVIEW_ENABLED:true`
- **Version binding:** The Worker returns `15c007b4a785a1263df989bb72c6e10e4b60ddf4` from `/health` and from the same-origin verification document. Missing or malformed deployment identity fails closed with HTTP 503.

Unrelated `research/demo-video-cn/` media is excluded. Worker implementation, tests, API contract, config example, and dependency lock are included.

## Verification

Repeatable commands and live response fixtures are in `verification/README.md`.

- **Offline health/proof contract:** Covered by `npm run test:xagent`.
- **Capability call:** `POST /xagent/agent-delivery-acceptance-audit` with `verification/request.json`.
- **Expected error behavior:** Missing `delivery_summary` returns HTTP 400; a disabled review route returns HTTP 404; missing deployment identity returns HTTP 503.

## Security and data handling

- **Data collected:** Request fields describing a task and delivery evidence. No wallet seed, signature, payment credential, or customer record is required.
- **Purpose and retention:** The reviewer route evaluates the body in memory and does not persist it.
- **Third parties / outbound network calls:** Cloudflare Workers hosts the API. This reviewer route makes no outbound call. Existing paid routes have separate x402/OKX behavior and are not changed by this review route.
- **Secrets:** No secrets are committed. Deployment values in `config/xagent-review.env.example` are non-secret bindings.
- **Known risks / restrictions:** The result is a deterministic evidence-quality judgment, not a security certification. It relies on caller-supplied evidence and intentionally preserves human approval gates.

## Support

- **Team / builder:** Leo / `runesleo`
- **Contact:** GitHub `@runesleo` via the source repository
- **License / rights:** See `RIGHTS.md`.
