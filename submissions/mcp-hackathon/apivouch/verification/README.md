# APIVouch verification evidence

## Prerequisites

- Review commit: `cead54a30bb3b7cc1e4b4e198d9da88cdc184ff9`
- API base URL: `https://apivouch.sklab.cc`
- Authentication: None for the public review deployment.
- Tools: `curl`; Python 3 is optional for inspecting the dynamic response.

The calls below contain no credential or personal data. Exchange-rate values and the selected provider can change, so verify the stated invariants rather than a hard-coded rate.

## 1. Health check

```bash
curl --fail --silent --show-error https://apivouch.sklab.cc/health
```

Expected response:

```json
{"status":"ok","service":"apivouch","version":"1.2.0","commit":"cead54a30bb3b7cc1e4b4e198d9da88cdc184ff9"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://apivouch.sklab.cc/.well-known/xagent-verification.json
```

The response must include these exact fields:

```json
{"schemaVersion":1,"slug":"apivouch","commit":"cead54a30bb3b7cc1e4b4e198d9da88cdc184ff9","apiBaseUrl":"https://apivouch.sklab.cc","healthCheckUrl":"https://apivouch.sklab.cc/health","mcpEndpoint":"https://apivouch.sklab.cc/mcp"}
```

## 3. Real capability call through MCP

This calls two independently operated public origins and asks APIVouch to return a result only when both USD-to-EUR values satisfy their schemas and agree within 2%.

```bash
curl --fail --silent --show-error \
  --request POST https://apivouch.sklab.cc/mcp \
  --header 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":"review-live-1","method":"tools/call","params":{"name":"apivouch_resolve_verified_outcome","arguments":{"goal":"Resolve the latest public USD to EUR reference rate","providers":[{"name":"Frankfurter","url":"https://api.frankfurter.app/latest?from=USD&to=EUR","result_path":"rates.EUR","expected_schema":{"type":"number","exclusiveMinimum":0},"price_usd":0},{"name":"ExchangeRate-API","url":"https://open.er-api.com/v6/latest/USD","result_path":"rates.EUR","expected_schema":{"type":"number","exclusiveMinimum":0},"price_usd":0}],"constraints":{"max_price_usd":0,"max_latency_ms":8000,"minimum_agreement":2,"numeric_tolerance_percent":2}}}}'
```

For a successful live run, HTTP status is 200 and the JSON-RPC result has:

- `id` equal to `review-live-1`;
- `result.isError` equal to `false`;
- `result.structuredContent.verdict` equal to `VERIFIED`;
- exactly two provider attempts with different resolved origins;
- `result.structuredContent.authenticity.state` equal to `signed`;
- `result.structuredContent.deployment_commit` equal to the review commit.

The selected provider and numeric result are live data and are intentionally not fixed. If the public providers are unavailable or disagree, APIVouch must return an evidence-bearing `UNVERIFIED` refusal rather than a fabricated value.

## 4. Safe invalid-input behavior

```bash
curl --fail --silent --show-error \
  --request POST https://apivouch.sklab.cc/mcp \
  --header 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":"review-invalid-1","method":"tools/call","params":{"name":"apivouch_resolve_verified_outcome","arguments":{}}}'
```

Expected behavior is HTTP 200 with a JSON-RPC result whose `isError` is `true`. The structured error is bounded and no provider call is attempted. Malformed JSON instead returns sanitized HTTP 400 / JSON-RPC parse error; an MCP body over 1 MiB returns sanitized HTTP 413.

## 5. Independent deployment gate

From the submitted source directory:

```bash
python -m pip install -r backend/requirements-dev.txt
python scripts/verify_deployment.py \
  --base-url https://apivouch.sklab.cc \
  --expected-commit cead54a30bb3b7cc1e4b4e198d9da88cdc184ff9 \
  --mode deterministic \
  --require-signed
```

Expected final report fields are `"status":"passed"`, `"mode":"deterministic-fixture"`, and `"invariant":null`. Use `--mode live` for the separate public-provider gate; on 2026-09-19 it returned `"status":"passed"` and `"live_verified":true`.
