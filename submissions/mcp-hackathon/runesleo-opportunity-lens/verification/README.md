# Verification evidence

## Prerequisites

- Review commit: `8a441bd39b6899ca10af1f3a36b78f9376f5c01f`
- API base URL: `https://opportunity-lens-api.leolabs.me`
- Authentication: None
- Observed from an external HTTPS client on 2026-09-17.

## 1. Health check

```bash
curl --fail --silent --show-error \
  https://opportunity-lens-api.leolabs.me/health
```

Expected response:

```json
{"commit":"8a441bd39b6899ca10af1f3a36b78f9376f5c01f","status":"ok"}
```

The reviewed response was HTTP 200 and included `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and a restrictive Content Security Policy.

## 2. Deployment proof

```bash
curl --fail --silent --show-error \
  https://opportunity-lens-api.leolabs.me/.well-known/xagent-verification.json
```

Expected response:

```json
{"commit":"8a441bd39b6899ca10af1f3a36b78f9376f5c01f","schemaVersion":1,"slug":"runesleo-opportunity-lens"}
```

## 3. API contract

```bash
curl --fail --silent --show-error \
  https://opportunity-lens-api.leolabs.me/openapi.json
```

Expected properties:

- OpenAPI version `3.1.0`.
- `POST /v1/profile` exists.
- `ProfileRequest`, nested evidence objects, and `ProfileResponse` set `additionalProperties` to `false`.
- Execution, capital, account, routing, notification, and public-publish authority fields are constants fixed to `false`.

## 4. Capability call

```bash
curl --fail --silent --show-error \
  --request POST https://opportunity-lens-api.leolabs.me/v1/profile \
  --header 'Content-Type: application/json' \
  --data '{"headline":"X-Agent MCP Hackathon for a deployed AI agent API","why_now":"The official submission deadline is near.","candidate_class":"GENERAL_OPPORTUNITY","evidence":[{"source_id":"official:event","kind":"OFFICIAL_GRANT_TERMS","first_party":true}]}'
```

Observed response:

```json
{"profile":{"capital_effect":false,"domains":["AI_AGENT_SOFTWARE","DATA_INFRA","GRANT_BOUNTY_PARTNERSHIP"],"evidence_classes":["COMMERCIAL","FIRST_PARTY"],"execution_authorized":false,"human_notification_authorized":false,"innovation_types":["TOOL","API","WORKFLOW","INCENTIVE","RELATIONSHIP_PATH"],"primary_domain":"AI_AGENT_SOFTWARE","schema":"opportunity_lens_profile.v1","signal_state":"READY_FOR_VALIDATION","unknowns":[]},"safety":{"account_effect":false,"advisory_only":true,"capital_effect":false,"execution_authorized":false,"public_publish_authorized":false},"schema":"opportunity_lens_response.v1","validation":{"action_type":"COMMERCIAL_REVIEW","actual_routing_enabled":false,"capital_effect":false,"execution_authorized":false,"human_notification_authorized":false,"mode":"ADVISORY_ONLY","next_checks":["Verify eligibility, deadline, source-code rights, reward economics, and selection terms from first-party documents.","Estimate incremental build, deployment, and maintenance effort before committing."],"reason_codes":["GRANT_BOUNTY_OR_PARTNERSHIP"],"schema":"opportunity_lens_validation.v1"}}
```

## 5. Safe failure behavior

```bash
curl --silent --show-error --include \
  --request POST https://opportunity-lens-api.leolabs.me/v1/profile \
  --header 'Content-Type: application/json' \
  --data '{"headline":"test","private_state_path":"/tmp/private"}'
```

Expected status and response:

```text
HTTP/2 400
```

```json
{"detail":"unknown fields: private_state_path","error":"INVALID_REQUEST"}
```

This verifies that unknown fields fail closed rather than being retained or processed.
