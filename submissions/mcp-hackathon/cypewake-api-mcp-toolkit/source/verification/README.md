# Verification evidence

Commands below run against the live deployment and need no credentials.

## Prerequisites

- Review commit: `3db59e3afed8e1de2929197dc107b328701d7a22`
- API base URL: `https://mcpforge-cypewake.app.workbuddy.host`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://mcpforge-cypewake.app.workbuddy.host/api/health
```

Expected response:

```json
{"status":"ok","commit":"3db59e3afed8e1de2929197dc107b328701d7a22"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://mcpforge-cypewake.app.workbuddy.host/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"cypewake-api-mcp-toolkit","commit":"3db59e3afed8e1de2929197dc107b328701d7a22"}
```

## 3. Capability call

Run the service locally with `uvicorn demo_app:app --port 8000`, then reproduce the real capability calls with any MCP client or with `source/docs/judge_check.py`:

- `call_rest_api` with `base_url=https://api.github.com`, `path=/zen` → HTTP 200
- `register(github_live)` followed by `call_registered_api(getZen)` → HTTP 200

The full reproducible script is `source/docs/judge_check.py`, which reports **11/11 PASS** locally.

Expected success: HTTP 200 with the GitHub zen text or repository metadata in the body.

Expected safe failures: an unregistered API name returns an explicit error; a private-network URL is rejected by `assert_public_url` (SSRF guard).

## 4. Real task call

```bash
curl --fail --silent --show-error -X POST \
  https://mcpforge-cypewake.app.workbuddy.host/api/real-task \
  -H 'Content-Type: application/json' -d '{"topic":"model-context-protocol"}'
```

Returns the three-step chain: search candidates, verify each at the source, aggregate the brief — with the status code of every real call. When the host blocks outbound access to `api.github.com`, the response falls back to the recorded evidence snapshot and labels the data source rather than returning an empty result.
