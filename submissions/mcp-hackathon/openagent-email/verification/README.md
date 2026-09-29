# Verification evidence

## Prerequisites

- Review commit: `5f432e4bd4019bda1f04ae5d6863975cff7721eb`
- API base URL: `https://demo.openagent.email/v1`
- Authentication: bearer token. A short-lived reviewer token is provided through the program's private review channel on request (contact kk@xagt.ai / Telegram @Kongk0u to reach us at support@openagent.email). Steps 1 and 2 need no token; step 3 does.

## 1. Health check

```bash
curl --fail --silent --show-error https://demo.openagent.email/healthz
```

Expected response:

```json
{"ok":true,"status":"ok","commit":"5f432e4bd4019bda1f04ae5d6863975cff7721eb","version":"<api version>"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://demo.openagent.email/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"openagent-email","commit":"5f432e4bd4019bda1f04ae5d6863975cff7721eb"}
```

## 3. Capability call

Create a real, working mailbox for an agent (requires the reviewer token):

```bash
curl --fail --silent --show-error \
  --request POST https://demo.openagent.email/v1/identities \
  --header "authorization: Bearer <reviewer-token>" \
  --header "content-type: application/json" \
  --data '{"name":"reviewer-bot"}'
```

Expected success (HTTP 201, token redacted here):

```json
{"id":"<identity-id>","address":"reviewer-bot@demo.openagent.email","token":"<redacted>"}
```

Follow-up: `GET /v1/messages?address=reviewer-bot@demo.openagent.email` with the same bearer lists received mail, including parsed OTP codes and confirmation links when present.

Safe failure behavior: the same call without the `authorization` header returns HTTP 401 with a JSON error body (for example `{"error":"unauthorized"}`); malformed JSON returns a 400-class JSON error. No credentials, stack traces, or other identities' data are exposed in error responses.

MCP path (optional): the same capability is available to MCP clients through the `@openagentemail/mcp` npm package (20 tools) against this origin, with OAuth discovery at `/.well-known/oauth-protected-resource`.
