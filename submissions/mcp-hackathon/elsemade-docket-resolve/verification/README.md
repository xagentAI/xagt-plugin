# Docket Resolve verification

## Deployment binding

- Review commit: `a05274938888c1ead7627900dc3ea45db23123b2`
- API base URL: https://docket-resolve.vercel.app/v1
- Health URL: https://docket-resolve.vercel.app/health
- Deployment proof URL: https://docket-resolve.vercel.app/.well-known/xagent-verification.json

Expected health response:

```json
{"status":"ok","commit":"a05274938888c1ead7627900dc3ea45db23123b2"}
```

Expected deployment proof:

```json
{"schemaVersion":1,"slug":"elsemade-docket-resolve","commit":"a05274938888c1ead7627900dc3ea45db23123b2"}
```

## 1. Deterministic settlement-kernel check

The complete example is at `source/examples/agreement.json`. Submit it to the recommendation endpoint:

```bash
curl --fail --silent --show-error \
  --request POST https://docket-resolve.vercel.app/v1/evaluations \
  --header "content-type: application/json" \
  --data-binary @source/examples/agreement.json
```

Stable assertions from the response:

```json
{
  "evaluationId": "eval_d23e340d4a16fda24342df9d48e9d207",
  "agreementId": "agent-build-2026-019",
  "decision": "release_partial",
  "amountAtomic": 250000000,
  "recommendedReleaseAtomic": 230000000,
  "recommendedHoldAtomic": 20000000,
  "settlementRatioBps": 9200
}
```

## 2. Reachable evidence fixture

The example evidence references are served by the same deployed origin and are retrieved through the normal bounded HTTPS fetcher:

```bash
curl --fail --silent --show-error https://docket-resolve.vercel.app/fixtures/evidence/ev-smoke.txt
curl --fail --silent --show-error https://docket-resolve.vercel.app/fixtures/evidence/ev-docs.txt
curl --fail --silent --show-error https://docket-resolve.vercel.app/fixtures/evidence/ev-errors.txt
```

The agreement declares SHA-256 digests for these artifacts. A persisted case can be created through `POST /v1/cases`, then retrieved through `POST /v1/cases/{caseId}/retrieve`. The response reports verified evidence and explicit retrieval failures separately.

## 3. AI review and proportional resolution

The public reviewer workspace at `https://docket-resolve.vercel.app/` opens the sample agreement, retrieves the three evidence URLs, runs the Gemini-backed review, and displays cited findings before enabling resolution.

The expected live review behavior is:

- API criterion: high-confidence satisfied finding;
- docs criterion: satisfied or mostly satisfied finding;
- edge-case criterion: partial finding;
- every accepted finding cites its criterion evidence;
- the settlement recommendation remains recommendation-only and calculates the weighted release/hold split locally.

Model wording and confidence may vary. The local test suite validates the provider schema, citation boundary, insufficient-evidence behavior, and settlement output independently of model phrasing.

## 4. MCP flow

The persisted MCP workflow uses the following tools in order:

```text
docket_create_case
docket_retrieve_evidence
docket_review_persisted_case
docket_resolve_case
docket_get_case
```

The same workflow is exercised by `source/scripts/production-mcp-workflow.js` in production-like authenticated mode. Required-auth tests verify that bearer tokens map to tenants and that a case cannot be read or changed through another tenant.

## 5. Safe failure checks

Malformed JSON returns HTTP 400, oversized bodies return 413, a non-JSON content type returns 415, and invalid agreements return structured HTTP 422 errors. The all-failed retrieval test expects zero verified items, three explicit failures, and no invented review finding. Conflicting evaluator findings route to `manual_review` and suppress financial recommendation fields.

## Notes

The public demo uses server-side Gemini configuration and no browser-held provider credential. Docket does not move funds. The deployment is an anonymous hackathon sandbox: do not submit private evidence. Its file-backed store and per-process rate limit are reference controls, not shared serverless persistence or distributed production quotas. A multi-instance production deployment should use authenticated tenants, a shared transactional database, and a shared rate limiter.
