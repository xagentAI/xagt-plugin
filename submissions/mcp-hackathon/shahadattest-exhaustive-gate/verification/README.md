# Verification evidence

## Prerequisites

- Review commit: `79a2a1c5f8a746584996b88c11aee746e079d48f`
- API base URL: `https://mean-capital-republican-understood.trycloudflare.com/v1` (local: `http://localhost:8100/v1`)
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://mean-capital-republican-understood.trycloudflare.com/health
```

Expected response:

```json
{"status":"ok","service":"exhaustive-gate","version":"0.1.0","commit":"79a2a1c5f8a746584996b88c11aee746e079d48f"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://mean-capital-republican-understood.trycloudflare.com/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"shahadattest-exhaustive-gate","commit":"79a2a1c5f8a746584996b88c11aee746e079d48f"}
```

## 3. Capability call

Create a session, observe the 4 demo pages, then verify (local evidence: page 1
`UNPROVEN/PAGINATION_NOT_EXHAUSTED`; full set `PROVEN`, certified 347):

```bash
SID=$(curl --fail --silent --show-error --request POST https://mean-capital-republican-understood.trycloudflare.com/v1/sessions \
  --header "content-type: application/json" \
  --data '{"resource_type":"invoice","source":"demo-crm","scope":{"status":"unpaid"}}' | python -c "import json,sys; print(json.load(sys.stdin)['session_id'])")
curl --fail --silent --show-error --request POST https://mean-capital-republican-understood.trycloudflare.com/v1/sessions/$SID/observe \
  --header "content-type: application/json" \
  --data '{"page_number":1,"cursor_out":"pg_100","has_more":true,"records_seen":100,"scope":{"status":"unpaid"},"snapshot_id":"snapshot_A"}'
curl --fail --silent --show-error --request POST https://mean-capital-republican-understood.trycloudflare.com/v1/sessions/$SID/verify \
  --header "content-type: application/json" \
  --data '{"claim":{"type":"EXACT_COUNT","value":100}}'
```

Expected: `{"verdict":"UNPROVEN","blocking_reasons":[{"code":"PAGINATION_NOT_EXHAUSTED",...}],"required_next_actions":["FETCH_NEXT_PAGE"],...}`.
After observing all pages, verifying `{"type":"EXACT_COUNT","value":347}` returns
`PROVEN` with a `certificate` object; `GET /v1/sessions/$SID/certificate`
returns the SHA-256 proof certificate. Redacted: no tokens or user data involved.
