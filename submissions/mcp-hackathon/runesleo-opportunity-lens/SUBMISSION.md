# Opportunity Lens API

## Capability

- **One-line description:** Convert a caller-supplied opportunity description into a deterministic cross-domain innovation profile, visible evidence gaps, signal maturity, and one bounded advisory validation action.
- **Who it helps:** Agents and operators triaging new APIs, products, grants, mechanisms, prediction-market infrastructure, and crypto or Bitcoin-native opportunities before deeper research.
- **Capability boundary:** The service classifies only text and evidence supplied by the caller. It does not fetch or verify external claims, access private systems, persist requests, operate wallets, trade, transfer funds, modify accounts, route tasks, send notifications, or publish content.

## Live API

- **API base URL:** https://opportunity-lens-api.leolabs.me
- **Health-check URL:** https://opportunity-lens-api.leolabs.me/health
- **Authentication:** None. The reviewed endpoints accept public, caller-supplied text only.
- **Rate limits / known limits:** 65,536-byte request body; 500-character headline; 2,000-character `why_now`; 12 evidence objects; 32-level JSON nesting; 10-second accepted-socket timeout; 32 default and 128 maximum application request threads. The Cloudflare edge and hosting environment may impose additional limits.
- **API contract:** The complete contract is documented in `source/README.md` and served live at https://opportunity-lens-api.leolabs.me/openapi.json.

## Source and reproducibility

- **Source repository:** https://github.com/runesleo/opportunity-lens-api
- **Review commit:** `8a441bd39b6899ca10af1f3a36b78f9376f5c01f`
- **Source submitted in this PR:** `source/`
- **Run tests:** `cd source && PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile app.py opportunity_lens.py tests/test_api.py && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`
- **Run locally:** `cd source && APP_COMMIT=8a441bd39b6899ca10af1f3a36b78f9376f5c01f APP_SLUG=runesleo-opportunity-lens HOST=127.0.0.1 PORT=8080 python3 app.py`
- **Deploy:** Build the included pinned non-root container with `docker build -t opportunity-lens-api .`, then run it behind managed HTTPS with `APP_COMMIT=8a441bd39b6899ca10af1f3a36b78f9376f5c01f` and `APP_SLUG=runesleo-opportunity-lens`. The reviewed public instance runs the same commit with Python 3.11 as a dedicated user service on localhost behind a dedicated Cloudflare Tunnel.
- **Version binding:** `APP_COMMIT` is validated as a 40-character hexadecimal commit and returned by both `/health` and the same-origin deployment-proof endpoint. `APP_SLUG` is returned by the deployment-proof endpoint.

The live API currently exposes:

```json
// GET https://opportunity-lens-api.leolabs.me/health
{"commit":"8a441bd39b6899ca10af1f3a36b78f9376f5c01f","status":"ok"}
```

```json
// GET https://opportunity-lens-api.leolabs.me/.well-known/xagent-verification.json
{"commit":"8a441bd39b6899ca10af1f3a36b78f9376f5c01f","schemaVersion":1,"slug":"runesleo-opportunity-lens"}
```

## Verification

The reproducible call instructions and observed responses are in `verification/README.md`.

- **Health-check result:** HTTP 200 with `status=ok` and the exact review commit.
- **Capability call:** `POST /v1/profile` with a non-sensitive hackathon/API opportunity description.
- **Expected error behavior:** Unknown fields fail closed with HTTP 400 and `INVALID_REQUEST`; malformed JSON, excessive body size, excessive nesting, unsupported content type, and incomplete bodies also return bounded errors.

## Security and data handling

- **Data collected:** Request fields `headline`, optional `why_now`, optional `candidate_class`, and up to 12 evidence objects containing optional `source_id`, `kind`, `first_party`, `url`, and `note`.
- **Purpose and retention:** These fields are processed in memory solely to generate the response. The application has no persistence layer and request logging is disabled by default.
- **Third parties / outbound network calls:** The application makes no outbound calls. The public service is delivered through Cloudflare edge and Cloudflare Tunnel; Cloudflare may process connection metadata under its own policies. GitHub hosts the public source repository.
- **Secrets:** No secrets are committed. No review credential is required.
- **Known risks / restrictions:** Classification is deterministic keyword inference rather than semantic or factual verification. The service trusts caller-supplied text, is unauthenticated, and must remain behind managed HTTPS, edge rate limiting, and platform resource limits. Users must not send secrets, personal data, private research, credentials, private keys, or private URLs.

## Support

- **Team / builder:** Leo, independent AI × crypto builder (`@runesleo` on GitHub)
- **Contact:** GitHub `@runesleo`; X `@runes_leo`; https://leolabs.me
- **License / rights:** MIT for the submitted project source. The submitter confirms authority to authorize review, archival, publication, and deployment of the submitted artifact under the program terms.
