# Verification evidence

## Prerequisites

- Review commit: `752c513d63b141b7acbf812ac71f33d5d99a98e1`
- API base URL: https://bountylens-api.onrender.com
- Authentication: None. Do not send a GitHub token or any other credential to this API.
- Runtime note: The free Render instance can take longer on the first request after inactivity.

## 1. Health check

```bash
curl --fail --silent --show-error \
  https://bountylens-api.onrender.com/health
```

Expected HTTP 200 response:

```json
{"status":"ok","commit":"752c513d63b141b7acbf812ac71f33d5d99a98e1"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error \
  https://bountylens-api.onrender.com/.well-known/xagent-verification.json
```

Expected HTTP 200 response:

```json
{"schemaVersion":1,"slug":"bowenhb-bountylens","commit":"752c513d63b141b7acbf812ac71f33d5d99a98e1"}
```

The health response, deployment proof, `submission.json`, and public source repository must all name the same review commit. The proof slug must match the submission directory.

## 3. Real capability call

This request evaluates a public GitHub Issue using a sample developer profile:

```bash
curl --fail --silent --show-error \
  --request POST https://bountylens-api.onrender.com/v1/evaluate \
  --header "content-type: application/json" \
  --data '{
    "issue_url": "https://github.com/fastify/fastify/issues/7030",
    "developer_profile": {
      "languages": ["JavaScript", "TypeScript"],
      "hourly_rate_usd": 30,
      "max_hours": 24
    }
  }'
```

Verified on 2026-09-20 with HTTP 200. Representative response fields were:

```json
{
  "issue": {
    "url": "https://github.com/fastify/fastify/issues/7030",
    "repository": "fastify/fastify",
    "number": 7030,
    "state": "open"
  },
  "decision": "investigate",
  "score": 60,
  "confidence": 0.86,
  "estimated_effort": {
    "min_hours": 13,
    "max_hours": 26,
    "confidence": 0.95
  },
  "reward": {
    "amount": null,
    "currency": null,
    "evidence": ["No explicit USD bounty or reward amount was found."]
  }
}
```

The actual response also includes a unique `request_id`, six dimension scores, evidence, next actions, and limitations. Scores can change when the public Issue or repository changes; response shape and decision rules are defined in `source/openapi.yaml`.

## 4. Safe failure behavior

An invalid Issue URL is rejected without making an arbitrary outbound request:

```bash
curl --silent --show-error \
  --request POST https://bountylens-api.onrender.com/v1/evaluate \
  --header "content-type: application/json" \
  --data '{"issue_url":"https://example.com/not-a-github-issue"}' \
  --write-out '\nHTTP %{http_code}\n'
```

Expected HTTP 400 response, with a different generated `request_id` on each call:

```json
{
  "request_id": "req_generated-per-request",
  "error": {
    "code": "INVALID_ISSUE_URL",
    "message": "Only public https://github.com issue URLs are supported.",
    "retryable": false
  }
}
```

No token, full Issue body, comment body, developer profile, or private upstream error is returned in either success or failure responses.
