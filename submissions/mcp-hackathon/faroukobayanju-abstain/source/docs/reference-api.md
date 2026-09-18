# HTTP API and configuration reference

Abstain exposes a small JSON API. Reads are public so anyone can inspect evidence. `POST /v1/evaluate` is the only authenticated write.

Local default base URL: `http://localhost:3000`

## Authentication

Send the configured write key in this header:

```http
X-ABSTAIN-KEY: <ABSTAIN_WRITE_KEY>
```

Authentication applies only to `POST /v1/evaluate`. An absent server-side key fails closed; it does not make the endpoint public.

## Endpoints

### `GET /health`

Dependency-free liveness and source identity.

Response: HTTP 200

```json
{
  "status": "ok",
  "service": "faroukobayanju-abstain",
  "commit": "<40-character lowercase SHA or unknown>",
  "commit_reviewable": true
}
```

The same commit is returned in the `x-source-commit` header. This endpoint deliberately does not contact Nexus or Redis.

### `GET /.well-known/xagent-verification.json`

Deployment proof used by the submission gate.

```json
{
  "schemaVersion": 1,
  "slug": "faroukobayanju-abstain",
  "commit": "<source SHA>",
  "commit_reviewable": true
}
```

### `GET /v1/ready`

Dependency readiness. The configured probe checks Nexus and the receipt store.

Status:

- HTTP 200 when `nexus`, `store`, and durability are all true.
- HTTP 503 when a dependency is down or storage is ephemeral.
- HTTP 200 with `ready:null` only when the application was constructed without a probe.

Local replay normally reports `nexus:true`, `store:true`, and `durable:false`.

### `GET /v1/policy?policy=<name>`

Returns the merged policy and the SHA-256 hash that identifies the applied rules.

Parameters:

| Name | Required | Values | Default |
| --- | ---: | --- | --- |
| `policy` | No | `strict`, `permissive` | `strict` |

The overlays differ only in `require_qualified`: strict uses `true`; permissive uses `false`.

### `GET /v1/receipts?from=<seq>&to=<seq>`

Returns an inclusive receipt sequence range.

Parameters:

| Name | Type | Default |
| --- | --- | --- |
| `from` | Number | `1` |
| `to` | Number | Current chain length |

Response fields: `count`, `total`, and `receipts`.

### `GET /v1/receipts/:seq`

Returns one receipt. `seq` must be a positive integer. Missing receipts return HTTP 404.

### `GET /v1/verify` and `POST /v1/verify`

Recomputes the entire receipt chain.

Valid response: HTTP 200

```json
{"ok":true,"length":2,"head":"sha256:..."}
```

Invalid response: HTTP 409, including the first affected sequence and one of these divergence kinds:

- `sequence`: a sequence number is missing, repeated, or out of order.
- `link`: `prev_hash` does not match the previous receipt.
- `content`: a stored hash does not match the canonical receipt body.

### `POST /v1/evaluate`

Fetches evidence, evaluates the gate, appends a receipt, then returns the decision. A response is never returned as successful authorization unless its receipt was committed first.

Headers:

```http
Content-Type: application/json
X-ABSTAIN-KEY: <configured key>
```

Request body:

| Field | Type | Required | Constraint |
| --- | --- | ---: | --- |
| `symbol` | String | Yes | Uppercase pair matching `^[A-Z0-9]{1,20}/[A-Z0-9]{1,20}$`. |
| `side` | String | Yes | `BUY` or `SELL`. |
| `notional` | Number | Yes | Positive and finite. |
| `policy` | String | No | `strict` or `permissive`; defaults to `strict`. |

Callers cannot supply `signalId`. Abstain derives it from the requested symbol and Nexus signal timestamp.

The request body is limited to 16,384 UTF-8 bytes. Abstain rejects both an oversized
declared `Content-Length` and an oversized body when that header is absent or inaccurate.

Response:

```json
{
  "verdict": "EXECUTE | ABSTAIN | NO_TRADE",
  "policy": "strict",
  "policy_hash": "sha256:...",
  "as_of": "YYYY-MM-DD",
  "checks": [],
  "receipt": {
    "seq": 1,
    "hash": "sha256:...",
    "prev_hash": "sha256:..."
  },
  "reason": "optional comma-separated failure ids or NO_TRADE explanation"
}
```

`NO_TRADE` contains no checks because a `HOLD` signal proposes no trade. `EXECUTE` and `ABSTAIN` contain all ten checks.

## Gate checks

| Check | Purpose |
| --- | --- |
| `SIGNAL_STALE` | Refuse signals older than the configured maximum age or dated in the future. |
| `NOT_QUALIFIED` | Enforce the Nexus listing qualification in strict policy. |
| `FUNDING_REGIME` | Refuse an adverse funding regime. |
| `OI_SHOCK` | Refuse a large open-interest move against the prior snapshot. |
| `DRAWDOWN_BUDGET` | Refuse when peak-to-trough drawdown exceeds policy. |
| `CORRELATED_CLUSTER` | Bound simultaneous same-direction exposure and per-symbol size. |
| `LOSS_STREAK` | Refuse after too many consecutive losses. |
| `DATA_GAP` | Turn unavailable required evidence into a refusal. |
| `SIZE_BOUND` | Enforce minimum and maximum proposal notional. |
| `DUPLICATE` | Prevent repeat authorization of a committed non-HOLD signal. |

## Receipt schema

| Field | Description |
| --- | --- |
| `ts` | ISO-8601 UTC decision timestamp. |
| `signal_id` | Server-derived signal identity. |
| `as_of` | Resolved market snapshot date. |
| `policy_hash` | SHA-256 identifier of the merged policy. |
| `inputs_digest` | SHA-256 digest of the Nexus payloads consulted. |
| `verdict` | `EXECUTE`, `ABSTAIN`, or `NO_TRADE`. |
| `checks` | Deterministic check results with observations, thresholds, and sources. |
| `reason` | Optional explanation or failed check identifiers. |
| `seq` | One-based chain position. |
| `prev_hash` | Previous receipt hash or the all-zero genesis hash. |
| `hash` | SHA-256 of the canonical receipt body, sequence, and previous hash. |

## Rate limits

Authenticated, valid evaluation requests are limited to:

- 20 writes per client per 60 seconds.
- 200 writes globally per 60 seconds.

Rate-limited responses use HTTP 429 and `Retry-After: 60`. Invalid request bodies are rejected before consuming the valid-write allowance.

## Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `PORT` | `3000` | Local HTTP port. |
| `ABSTAIN_WRITE_KEY` | Empty | Write credential. Empty means every evaluation is unauthorized. |
| `COMMIT_SHA` | `unknown` | Local or non-Vercel deployment identity. |
| `VERCEL_GIT_COMMIT_SHA` | Unset | Vercel deployment identity; takes precedence over `COMMIT_SHA`. |
| `NEXUS_MODE` | `replay` | Set to `live` to call Nexus over the network. |
| `NEXUS_API_KEY` | Empty | Server-side Nexus credential for live mode. |
| `NEXUS_BASE_URL` | Nexus production MCP URL | Optional gateway override. |
| `ABSTAIN_NOW` | Wall clock | Fixed millisecond timestamp for deterministic replay. |
| `ACCOUNT_EQUITY` | `100000` | Equity used by exposure checks. |
| `KV_REST_API_URL`, `KV_REST_API_TOKEN` | Unset | Vercel Upstash credential pair. |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Unset | Direct Upstash credential pair. |
| `VERCEL_ENV` | Unset | When `production`, evaluations require durable Redis storage. |

## Error responses

| Status | Error | Meaning |
| ---: | --- | --- |
| 400 | `bad_request` | Invalid JSON, request field, query parameter, or sequence. |
| 401 | `unauthorized` | Write key missing, wrong, or not configured. |
| 404 | `not_found` | Receipt or route does not exist. |
| 409 | Verification result | Receipt-chain divergence. |
| 413 | `payload_too_large` | Declared content length or actual request body exceeds 16,384 bytes. |
| 429 | `rate_limited` | Per-client or global write limit reached. |
| 503 | `store_not_durable` | Production has no durable Redis configuration. |
| 503 | `store_unavailable` | Receipt store operation failed; no receipt was written. |
| 503 | `chain_contended` | Atomic append failed after 16 attempts; no receipt was written. |

## Related

- [Getting-started tutorial](tutorial-getting-started.md)
- [Testing and deployment how-to](how-to-test-and-deploy.md)
- [Receipt-chain explanation](explanation-receipt-chain.md)
