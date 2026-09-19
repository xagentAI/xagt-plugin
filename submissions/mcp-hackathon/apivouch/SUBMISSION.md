# APIVouch

## Capability

- **One-line description:** Route one agent goal across independent public APIs, reject invalid or disagreeing evidence, and return one verified outcome with a signed, tamper-evident receipt.
- **Who it helps:** Agents and automation systems that must use API-backed facts without trusting the first provider that responds.
- **Capability boundary:** APIVouch performs bounded read-only provider calls, validates schemas and constraints, requires cross-provider agreement, selects an eligible result, and exposes receipt verification through MCP. It does not settle payments, certify the truth of an upstream provider, supply private-provider credentials, or automatically execute state-changing API operations.

## Live API

- **API base URL:** https://apivouch.sklab.cc
- **Health-check URL:** https://apivouch.sklab.cc/health
- **Authentication:** None for the public review deployment.
- **Rate limits / known limits:** The service accepts two to five providers per outcome, limits MCP request bodies to 1 MiB, upstream responses to 1 MiB, redirects to three, retries to one, and application concurrency to 64. The live demo uses an 8-second per-provider latency constraint. There is no per-user quota or tenant isolation, so reviewers should avoid load testing.
- **API contract:** Live OpenAPI is at https://apivouch.sklab.cc/openapi.json and the submitted implementation is in `source/backend/app/`. Product MCP is `POST /mcp` with tools `apivouch_resolve_verified_outcome` and `apivouch_verify_receipt`.

## Source and reproducibility

- **Source repository:** https://github.com/sklabstudio/apivouch
- **Review commit:** `cead54a30bb3b7cc1e4b4e198d9da88cdc184ff9`
- **Source submitted in this PR:** `source/`
- **Run tests:** `python -m pip install -r backend/requirements-dev.txt && python -m pytest -q`
- **Run locally:** `docker compose up --build`, then open `http://localhost:8000`
- **Deploy:** Follow `source/docs/deployment.md`; the reviewed VPS stack is defined by `source/deploy/vps/docker-compose.yml` and `source/deploy/vps/Caddyfile`.
- **Version binding:** `GET /health`, `GET /ready`, signed receipts, the public signing-key document, and `GET /.well-known/xagent-verification.json` report or bind the exact deployed commit.

The deployed API exposes:

```json
{"status":"ok","service":"apivouch","version":"1.2.0","commit":"cead54a30bb3b7cc1e4b4e198d9da88cdc184ff9"}
```

```json
{"schemaVersion":1,"slug":"apivouch","commit":"cead54a30bb3b7cc1e4b4e198d9da88cdc184ff9"}
```

## Verification

Repeatable health, deployment-proof, live MCP, and safe-refusal calls are documented in `verification/README.md`.

- **Health-check result:** Public HTTPS returns HTTP 200, `status: ok`, and the exact review commit.
- **Capability call:** `POST /mcp` calls two independent public USD-to-EUR providers through `apivouch_resolve_verified_outcome`; the verified 2026-09-19 run returned `VERIFIED`, a signed receipt, two observations, and the exact deployment commit.
- **Expected error behavior:** Missing or invalid tool arguments return a structured MCP tool refusal without attempting provider calls. Provider disagreement, schema failure, origin collision, timeout, or budget failure returns an evidence-bearing `UNVERIFIED` result rather than inventing an answer.

## Security and data handling

- **Data collected:** Imported public API contracts, bounded project diagnostics, and outcome receipts containing redacted provider URLs, URL/content digests, resolved public origins, timing/status evidence, and bounded scalar previews. The review deployment is not intended for secrets or personal data.
- **Purpose and retention:** Data supports contract analysis and receipt verification. PostgreSQL persists review data; receipt storage is bounded to 1,000 records and project creation is bounded to 250 projects. No time-based deletion guarantee is offered.
- **Third parties / outbound network calls:** Calls go only to public provider URLs supplied in a request after URL, DNS, redirect, and private-network checks. The documented live example calls Frankfurter and ExchangeRate-API; the public live demo also attempts Floatrates.
- **Secrets:** No secrets are committed. Review access requires no credential. The Ed25519 private signing seed and database password exist only in the VPS runtime environment.
- **Known risks / restrictions:** The public review service has no authentication, project ownership, tenant isolation, or per-user rate limiting. Signed receipts authenticate the APIVouch deployment key, not the independent truth of upstream providers. The service reports prices but performs no payment or settlement. DNS pinning does not defend against host-level routing/NAT changes or a public upstream that proxies private resources.

## Support

- **Team / builder:** SKLab Studio (`@sklabstudio`)
- **Contact:** https://github.com/sklabstudio/apivouch/issues
- **License / rights:** First-party source is MIT licensed under `source/LICENSE`. SKLab Studio confirms authorization to submit the source and live service for program review and archival as stated in `RIGHTS.md`.
