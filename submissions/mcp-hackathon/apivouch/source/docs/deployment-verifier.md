# Independent Deployment Verifier

Run `python scripts/verify_deployment.py --base-url https://DEPLOYMENT --expected-commit FULL_40_CHARACTER_SHA --mode deterministic` (or `--mode live`). Requires `httpx`; v2 verification additionally requires `cryptography`. No backend modules or receipt helpers are imported.

Production runs must add `--require-signed`; the scheduled/manual workflow enables it for both modes. This rejects a fully downgraded unsigned proof with `proof.signed_required`. Even without the flag, advertising v2/signing requires every checked receipt (fixture, refusal, live, and stored) to be signed v2; an unsigned receipt fails `receipt.signed_required`. V1-only development deployments remain supported without the flag. Missing or invalid v2 signatures fail `receipt.signature`.

Exit 0 means all requested checks passed; exit 1 means an invariant or transport failed; exit 2 means the live endpoint returned an otherwise valid, stored UNVERIFIED receipt. HTTP outages, malformed evidence, and integrity failures are not downgraded to live unavailability. Output is one JSON object containing fixed invariant names, not server bodies, URLs, exception text, or secrets. Deterministic success is never labelled live verification.

HTTPS is mandatory except explicitly supplied localhost or literal loopback HTTP. Redirects and environment proxies are disabled. Responses are limited to 1 MiB, connect timeout 5 seconds, read timeout 15 seconds, and streaming deadline 45 seconds (checked after each bounded read). Compressed responses are rejected. Duplicate JSON keys and nonfinite constants are rejected.

## Deployment Contracts

- `/health`: status `ok`, service `apivouch`, exact expected commit.
- `/.well-known/xagent-verification.json`: integer schemaVersion 1, slug `apivouch`, exact expected commit. Required `apiBaseUrl`, `healthCheckUrl`, `readinessUrl`, and `mcpEndpoint` must match the supplied origin and exact endpoint paths. `signingKeyUrl` is required when v2 is advertised, absent otherwise. `productTools`, `mcpProtocolVersions`, and `receiptFormats` must match the supported contract. No advertised URL is followed.
- `/ready`: HTTP 200, status `ready`, exact expected commit. Configuration, signing, and a bounded DB `SELECT 1` must all pass; failure returns HTTP 503 with boolean checks only. `/health` remains cheap liveness, independent of these checks.
- `/mcp`: legacy initialize negotiation, initialized notification, exactly the resolve and verify tools, JSON-RPC errors for unknown method/tool and invalid arguments, matching text/structured tool content.
- Advertised modern MCP is exercised independently over HTTP according to [the modern contract and official sources](mcp-modern.md): separate `server/discover` and `tools/list` requests before legacy initialization, with per-request namespaced metadata and mirrored headers, then a modern receipt `tools/call` with `Mcp-Name`. Discovery versions/capabilities, complete result type, server identity, cache fields, exact tools, and retrieved receipt are checked. A deliberately mismatched `Mcp-Method` must return HTTP 400 and RPC `-32020` (`mcp.modern.header_mismatch`). Broken advertised service fails a named `mcp.modern.*` invariant rather than passing on legacy behavior alone. This is subset verification, not official conformance.
- The existing deterministic demo supplies malformed-schema and HTTP-503 rejection evidence. No additional demo-failure endpoint is required. An over-budget MCP resolve request proves UNVERIFIED/no-result behavior without external provider traffic.
- REST and MCP receipt retrieval must exactly reproduce the original receipt. The verifier independently recomputes integrity rather than trusting integrity_valid. Local receipt corruption must be rejected.
- Fixture independence is explicitly disabled. Distinct configured origins are recomputed from all attempted URLs; agreeing final origins must exist and collapse to one fixture origin. Live attempts require distinct configured origins and distinct final agreeing origins. Origin counts describe network origins, not proof of independently owned providers.
- Live premise is the existing three-origin USD/EUR demonstration. HTTP evidence is deployment-reported evidence, not independent observation of its upstream calls. Same-origin key discovery proves consistency with the deployed key, not externally pinned operator identity.

## V2 Handoff Contract

Format is `apivouch-outcome-receipt-v2`. Hashing remains identical to v1: omit the top-level `integrity` and `receipt_id` fields, serialize with sorted keys, compact separators, UTF-8, unescaped Unicode, and no NaN/Infinity; SHA-256 produces `integrity.fingerprint = "sha256:" + lowercase_hex`. `integrity.algorithm` is `SHA-256`; receipt_id is the first 24 hex characters. V1 remains explicitly unsigned, not authenticated.

The hashed payload contains exactly `authenticity: {"state":"signed","algorithm":"Ed25519","key_id":"KEY_ID"}`. The standard-base64 64-byte signature is stored as `integrity.signature`, outside the hash. Ed25519 signs UTF-8 bytes of `apivouch-outcome-receipt-v2\n` followed by the 64 lowercase fingerprint hex characters, without the `sha256:` prefix or trailing newline.

Public discovery uses fixed same-origin `GET /.well-known/apivouch-signing-key.json`, with `{"schemaVersion":1,"slug":"apivouch","algorithm":"Ed25519","keyId":"KEY_ID","publicKey":"BASE64_RAW_32_BYTES","commit":"FULL_SHA"}`. keyId must match authenticity.key_id, and commit must exactly match the verifier's expected SHA. Tests generate disposable Ed25519 keys and independently construct signed fixtures.

## Configuration And Local Verification

Set `PUBLIC_BASE_URL` to the HTTPS origin only (an optional single trailing slash is accepted). Credentials, paths, query strings, fragments, malformed hosts/ports, whitespace, and escapes are rejected. HTTP is allowed only for an explicitly configured `localhost` or literal loopback address, for development. Configured deployments require `PROJECT_SLUG=apivouch` and a lowercase 40-hex `GIT_COMMIT` (or `RENDER_GIT_COMMIT`). Invalid configuration stays live but not ready and proof discovery returns a fixed 503 error. URLs are never inferred from Host or forwarded headers in the proof. Without a public origin, local development retains `dev-local` and relative discovery URLs; the independent deployment gate requires a configured absolute origin and exact SHA.

Readiness waits at most two seconds for a single shared daemon DB probe, including pool checkout/connect/query. A stalled driver cannot create unbounded probe threads; native SQLite/PostgreSQL timeouts additionally limit DB waits. Only `SELECT 1` is executed by readiness, with no schema inspection or migration. The existing startup initialization is unchanged except that database errors no longer abort liveness; a failed initialization may require a restart after restoring the DB. Readiness proves connectivity, not schema completeness. Invalid or required-but-missing signing configuration returns not-ready without exposing key material or exception text.

`python -m pytest -q -s backend/tests/test_deployment_uvicorn.py` starts disposable real localhost Uvicorn with an in-memory SQLite DB, the repository HEAD SHA, a matching explicit public origin, and a generated environment-only signing key. It runs the independent deterministic CLI and terminates the child process. It writes no key/database files and does not assert external-provider or production deployment success.

In the Docker test stage (Git metadata deliberately excluded), this test uses
the synthetic SHA supplied by test configuration, not a deployed source claim.
Daily/manual HTTP gates and their URL/SHA repository variables are documented in
[operations](deployment.md#scheduled-verification). Deterministic is required;
optional live exit 2 remains non-success. No private key is supplied to CI.
