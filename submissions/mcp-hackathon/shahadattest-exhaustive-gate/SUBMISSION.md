# ExhaustiveGate

## Capability

- **One-line description:** Verify an AI agent actually covered the required result set before it claims all, none, exactly N, cheapest, highest, or lowest — returns PROVEN / UNPROVEN / CONDITIONAL with blocking reasons and next actions.
- **Who it helps:** AI agents and developers that paginate third-party APIs and must avoid false exhaustive claims.
- **Capability boundary:** Sessions, scope hashing, pagination-chain validation, failure/snapshot tracking, proof obligations, verdicts, SHA-256 proof certificates. Does NOT modify upstream APIs, does NOT do security auditing, penetration testing, or risk scoring.

## Live API

- **API base URL:** `https://mean-capital-republican-understood.trycloudflare.com/v1` (local verified: `http://localhost:8100/v1`)
- **Health-check URL:** `https://mean-capital-republican-understood.trycloudflare.com/health`
- **Authentication:** none
- **Rate limits / known limits:** No auth limits; JSON body cap ~512KB. Core makes no upstream calls (evidence is posted by the agent).
- **API contract:** `source/docs/api.md`; interactive docs at `/docs`.

## Source and reproducibility

- **Source repository:** `https://github.com/ShahadatTest/exhaustive-gate`
- **Review commit:** `79a2a1c5f8a746584996b88c11aee746e079d48f`
- **Source submitted in this PR:** `source/`
- **Run tests:** `cd source/backend && pip install -r requirements.txt && python -m pytest tests/ -q` (15 passed)
- **Run locally:** `cd source && docker-compose up --build` (dashboard :8102, gate :8100, demo CRM :8101)
- **Deploy:** build `source/backend/Dockerfile`, set `GIT_COMMIT=<review-commit>` and `XAGENT_SLUG=shahadattest-exhaustive-gate`
- **Version binding:** `/health` returns `{"status":"ok","commit":"<review-commit>"}` and `/.well-known/xagent-verification.json` returns `{"schemaVersion":1,"slug":"shahadattest-exhaustive-gate","commit":"<review-commit>"}`

## Verification

Reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `{"status":"ok","service":"exhaustive-gate","version":"0.1.0","commit":"79a2a1c5f8a746584996b88c11aee746e079d48f"}`
- **Capability call:** `POST /v1/sessions` → observe 4 invoice pages → `POST /v1/sessions/{id}/verify` with `{"claim":{"type":"EXACT_COUNT","value":347}}` → `PROVEN` + proof certificate
- **Expected error behavior:** unknown session → 404; invalid pagination_type → 400; certificate before PROVEN → 404; incomplete evidence → `UNPROVEN` with `blocking_reasons` + `required_next_actions`

## Security and data handling

- **Data collected:** Retrieval-evidence metadata the reviewer posts (page/cursor/counts); no end-user data.
- **Purpose and retention:** Review/demo only, local SQLite file.
- **Third parties / outbound network calls:** none in core.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** none; verdicts are deterministic functions of posted evidence.

## Support

- **Team / builder:** shahadattest (solo)
- **Contact:** via GitHub `shahadattest`
- **License / rights:** MIT (see `source/LICENSE`); submitter authorizes review and archival per RIGHTS.md.
