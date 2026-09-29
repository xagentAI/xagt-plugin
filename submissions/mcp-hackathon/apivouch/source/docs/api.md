# API contract

All responses are JSON unless otherwise noted. Interactive documentation is served at `/docs`.

## Verified outcomes

### `POST /api/outcomes/execute`

Calls two to five credential-free public `GET` providers concurrently. Each provider declares a URL, optional dotted `result_path`, optional JSON Schema, and quoted `price_usd`. Constraints set maximum selected-provider price, maximum latency, minimum agreeing providers, and numeric tolerance.

Configured providers must have unique network origins. Redirects are resolved through the bounded fetcher and duplicate final origins are rejected as well. URL query values are used for the request but redacted from the receipt.

The response is an unsigned `apivouch-outcome-receipt-v1`, or an Ed25519-signed `apivouch-outcome-receipt-v2` when signing is configured. `VERIFIED` includes a selected result and provider. `UNVERIFIED` always has a null result/provider and zero selected price. Both verdicts are signed when enabled. Invalid signing configuration or a missing required key blocks issuance before provider calls. REST (including demos) and legacy MCP return safe HTTP 503; modern MCP returns HTTP 200 with `isError: true`. Runtime signing failures occur after provider evaluation and use the same transport-specific errors, without returning or storing a receipt or falling back to unsigned issuance. See [signed receipts](signed-receipts.md).

### `POST /api/outcomes/demo`

Runs the explicitly self-contained four-fixture demonstration. Its receipt sets `provider_independence.required` to `false`; this bypass is not available in caller-supplied REST or MCP requests.

### `POST /api/outcomes/live-demo`

Calls Frankfurter, Floatrates, and ExchangeRate-API at distinct public origins to resolve a USD→EUR reference rate. It uses the same origin, schema, latency, agreement, selection, storage, and integrity path as caller-supplied requests; no demo bypass is active.

### `GET /api/outcomes/receipts/{receipt_id}`

Returns the unchanged stored receipt, `integrity_valid` recomputed from canonical JSON, and a separate `authenticity` object with `state` (`unsigned`, `signed`, `invalid`, or `unavailable`) and boolean `valid`. Production evidence is read first and takes precedence; Chaos Lab fixture receipts are retrievable through the same endpoint without ever sharing production storage. Unsigned receipts have `valid: false` without being integrity failures. MCP returns the same envelope; invalid/unavailable signed authenticity sets its `isError` flag.

### `GET /receipts/{receipt_id}` (public Receipt Explorer page)

Human-readable proof page for a 24-character lowercase-hex receipt ID. Only fullmatch `[0-9a-f]{24}` is served; anything else returns a safe 404. The page serves the existing frontend shell with the same no-cache policy plus `X-Robots-Tag: noindex, nofollow`, then fetches the authoritative `GET /api/outcomes/receipts/{id}` API. Untrusted receipt content is never embedded into server HTML; all receipt-controlled strings are escaped in the client. The explorer shows VERIFIED/UNVERIFIED, receipt ID, timestamp, goal, selection (or explicit no-result), agreement achieved vs required, quoted price labelled not charged / no settlement, deployment commit, format, fingerprint and algorithm, separate integrity and authenticity states, signing key ID when present, every provider attempt, and a same-origin discovery limitation notice. Controls are Verify again, Copy public link, Copy receipt JSON, Download receipt JSON, and Back to APIVouch. Missing receipts show Receipt not found; integrity failures are prominent red states distinct from authenticity states. No payment is executed.

### `GET /api/outcomes/lab`

Read-only catalog of exactly the six server-owned deterministic scenarios: `consensus-success` (expected VERIFIED), `provider-disagreement`, `schema-invalid`, `upstream-failure`, `over-budget`, and `origin-convergence` (each expected UNVERIFIED). No caller input is accepted.

### `POST /api/outcomes/lab/{scenario_id}`

Runs one allowlisted scenario through the real `execute_verified_outcome` path with a deterministic in-process request function. Contract A: the endpoint accepts an exact zero-byte body. Conflicting `Content-Length`/`Transfer-Encoding` framing is rejected with HTTP 400 before the stream is touched, even when the declared length is zero; only an exact single `chunked` coding may use streamed zero-body validation, and every other or ambiguous framing combination fails closed. A declared `Content-Length` greater than zero is rejected immediately with HTTP 400 before the body stream is touched; duplicate, comma-joined, empty, signed, negative, or malformed lengths fail closed; chunked or length-less bodies are rejected on the first non-empty stream chunk without buffering, parsing, or echoing caller bytes (even whitespace is a body). Caller bodies can never influence URLs, responses, schemas, expected verdicts, timing, or evidence. Only the six catalog IDs are accepted; unknown IDs return a safe 404. Each scenario uses a fixed, documented fixture timestamp (`2026-01-01T00:00:00Z`) and fixed provider latency (5 ms) through a private server-owned timing context; production execution always uses the real UTC clock and measured latency instead. The HTTP caller can never control these values. For the same scenario ID, deployment commit, and signing configuration, repeated runs produce identical canonical receipt JSON, receipt ID, fingerprint, and Ed25519 signature. The fixed timestamp is deterministic fixture evidence, never live freshness. Every receipt follows normal signing rules and is stored in the isolated `outcome_lab_receipts` table, which holds one deterministic row per scenario for a fixed deployment commit and signing configuration, is bounded independently by `MAX_LAB_RECEIPTS` (default 60, validated positive at startup), and can never count against, retain, or evict production `outcome_receipts` rows; its insert/count/evict decision is database-serialized so concurrent distinct writes cannot exceed that bound, concurrent identical runs resolve atomically on the primary key and are idempotent, conflicting same-ID evidence fails closed, and the stored receipt is proven canonical JSON round-trip exactly equal on immediate retrieval. No real external network requests occur and no sleeps simulate latency. The envelope is `{schema_version, scenario{id,title,description,expected_verdict}, evidence: "deterministic-fixture", passed, observed_verdict, checks[{id,passed,summary}], receipt, integrity_valid_after_storage}`. Scenario PASS means the receipt behaved as expected; receipt VERIFIED/UNVERIFIED is the outcome verdict, so a correct UNVERIFIED refusal is a green PASS. Deterministic fixtures are not live-provider evidence.

### Product MCP tools at `POST /mcp`

- `apivouch_resolve_verified_outcome` runs the normal independent-provider
  verification path and returns the receipt as structured content.
- `apivouch_verify_receipt` retrieves a stored receipt by its 24-character ID
  and recomputes its SHA-256 integrity fingerprint.

## Project lifecycle

### `POST /api/projects`

Import a public URL or inline object.

```json
{
  "name": "Weather API",
  "openapi_url": "https://api.example.com/openapi.json"
}
```

Use `openapi_json` instead of `openapi_url` for an inline contract. Limits: 200 operations and a 512 KiB import body by default.

### `POST /api/projects/upload`

Multipart fields: `name` and `file`. JSON and YAML are accepted.

### `GET /api/projects/{id}`

Returns source endpoints, current source score, findings, live comparison, and contract state.

### `POST /api/projects/{id}/test`

```json
{
  "samples_per_endpoint": 3,
  "arguments": {
    "getWeather": {"city": "Dhaka", "units": "metric"}
  }
}
```

Only `GET`, `HEAD`, and `OPTIONS` are automatically called. Required arguments that are not supplied produce a structured `skipped` result.

### `POST /api/projects/{id}/contract`

Generates an evidence-bound agent contract. The deprecated `/repair` alias is kept for compatibility; neither route mutates the upstream service. The comparison is produced by re-running the same deterministic evaluator against the source and generated contracts.

### `POST /api/projects/{id}/prove`

```json
{
  "operation_id": "listItems",
  "claim_type": "EXACT_COUNT",
  "expected_count": 7,
  "arguments": {"limit": 3}
}
```

Supported claims are `ALL`, `NONE`, `EXACT_COUNT`, `MIN`, and `MAX`. For min/max, add `field`, optional `candidate_id`, and optional `id_field`. Common cursor, page, and offset APIs are auto-detected; a `pagination` object can set dotted response paths and bounded limits.

The input deliberately has no evidence fields. APIVouch begins at the first page and records response digests, hashed cursor progress, record/page counts, snapshot consistency, and authoritative-total consistency. Results use `PROVEN`, `CONDITIONAL`, or `UNPROVEN`. Only the first two can include a content-addressed certificate.

### `GET /api/projects/{id}/contract`

Returns the generated OpenAPI/Swagger agent contract. Returns HTTP 409 until generation is complete.

### `GET /api/projects/{id}/comparison`

Returns the stored source-versus-generated-contract comparison.

### `POST /api/projects/{id}/proxy/{operation_id}`

Request:

```json
{"arguments":{"city":"Dhaka"}}
```

Read-only operations return a stable `{success,data,error,meta}` envelope. State-changing operations return `CONFIRMATION_REQUIRED`.

### `GET /api/projects/{id}/export`

Returns the complete `apivouch-agent-pack-v1`: score, observations, findings, changes, generated contract, MCP tools, comparison, latest exhaustiveness proof, and MCP endpoint.

### `DELETE /api/projects/{id}`

Deletes exactly one stored project.

## MCP transport

`POST /mcp` is the product-level MCP server. It exposes `apivouch_resolve_verified_outcome` with the same validation, selection, receipt, and refusal semantics as the REST endpoint.

Both endpoints support stateless modern `2026-07-28` `server/discover`,
`tools/list`, and `tools/call`. Each request requires namespaced version and
capabilities in `params._meta`, matching `MCP-Protocol-Version` and `Mcp-Method`
headers, and `Mcp-Name` for calls. See [modern MCP](mcp-modern.md) for separate
calls, exact errors, legacy separation, and tested limitations. This is not an
official conformance claim.

The preserved legacy interface accepts JSON-RPC 2.0 methods:

- `initialize`
- `notifications/initialized`
- `ping`
- `tools/list`
- `tools/call`

Supported legacy initialization versions: `2024-11-05`, `2025-03-26`, and `2025-06-18`.

`tools/list` includes `apivouch_prove_exhaustive_claim` whenever the project has a GET operation. It uses the same proof collector as the REST route.

## Deployment evidence

- `GET /health` returns `status`, service version, and the exact deployed commit.
- `GET /ready` checks bounded DB connectivity, deployment configuration, and signing; 200 means ready, 503 means not ready. It does not prove schema completeness.
- `GET /.well-known/xagent-verification.json` returns schema version, submission slug, and the same commit.
- `GET /.well-known/apivouch-signing-key.json` returns only the public Ed25519 key document, or 404 when signing is unconfigured, or safe 503 for invalid signing configuration.

Proof URLs use validated `PUBLIC_BASE_URL`, not Host/forwarded headers. Production
templates require signing and an exact SHA. Integrity is separate from issuer
authenticity; same-origin discovery does not externally pin identity. Fixtures
disable provider independence explicitly; mocked tests are not live evidence.
No endpoint settles payment. There is no authentication/tenant isolation. VPS
adds a 1 MB proxy body cap and timeouts; see [operations](deployment.md).
