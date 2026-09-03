# MCP Doctor

## Capability

- **One-line description:** Turn any OpenAPI-described API into a tested, normalized, agent-ready tool with a before/after readiness score.
- **Who it helps:** Developers and AI agents that need strict schemas, predictable outputs, and standardized failures from third-party APIs.
- **Capability boundary:** Does API discovery, live safe-method testing, deterministic quality scoring, declarative response normalization, proxying, and tool-JSON generation. Does NOT modify upstream APIs, does NOT do security auditing, penetration testing, or risk scoring.

## Live API

- **API base URL:** `https://belts-raymond-advertisements-radical.trycloudflare.com/api` (local verified: `http://localhost:8000/api`)
- **Health-check URL:** `https://belts-raymond-advertisements-radical.trycloudflare.com/health`
- **Authentication:** none
- **Rate limits / known limits:** No auth limits; upstream calls timeout 10s, max 2 retries, 1MB response cap. Auto-test covers GET/HEAD/OPTIONS only.
- **API contract:** `source/examples/broken-demo-api/openapi-demo.json` + live OpenAPI at `/openapi.json`; endpoint docs in `source/docs/api.md`.

## Source and reproducibility

- **Source repository:** `https://github.com/ShahadatTest/mcp-doctor`
- **Review commit:** `3ce175fb14a0e176a9b29a2c213d78d4fab91bad`
- **Source submitted in this PR:** `source/`
- **Run tests:** `cd source/backend && pip install -r requirements.txt && python -m pytest tests/ -q` (8 passed)
- **Run locally:** `cd source && docker-compose up --build` (frontend :3000, backend :8000, demo :8001)
- **Deploy:** build `source/backend/Dockerfile`, set `GIT_COMMIT=<review-commit>` and `PROJECT_SLUG=shahadattest-mcp-doctor`
- **Version binding:** `/health` returns `{"status":"ok","commit":"<review-commit>"}` and `/.well-known/xagent-verification.json` returns `{"schemaVersion":1,"slug":"shahadattest-mcp-doctor","commit":"<review-commit>"}`

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `{"status":"ok","service":"mcp-doctor","version":"0.1.0","commit":"3ce175fb14a0e176a9b29a2c213d78d4fab91bad"}`
- **Capability call:** `POST /api/projects` with `{"name":"Demo Weather API","openapi_json":{...}}` → project created, 4 endpoints discovered, readiness 62/100, repair rules generated, proxy normalizes `{"tmp":"31 C","desc":"sun"}` → `{"temperature_celsius":31,"condition":"sunny"}`
- **Expected error behavior:** invalid spec → 400; unsafe method auto-test → `skipped`; unreachable upstream → `UPSTREAM_TIMEOUT` with `retryable:true`; bad proxy args → `INVALID_ARGUMENT`

## Security and data handling

- **Data collected:** Project specs and test metadata the reviewer submits; no end-user data.
- **Purpose and retention:** Review/demo only, stored in local SQLite file.
- **Third parties / outbound network calls:** Only the upstream API under test (reviewer-supplied URL), via httpx with SSRF guard.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** Set `ALLOW_PRIVATE_NETWORK=true` only for local demo against localhost; keep `false` in production.

## Support

- **Team / builder:** shahadattest (solo)
- **Contact:** via GitHub `shahadattest`
- **License / rights:** MIT (see `source/LICENSE`); submitter authorizes review and archival per RIGHTS.md.
