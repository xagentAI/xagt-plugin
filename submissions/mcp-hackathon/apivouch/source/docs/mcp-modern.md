# Modern MCP HTTP subset

Both `POST /mcp` (product tools) and `POST /mcp/{project_id}` (generated
operation/proof tools) accept stateless `2026-07-28` requests. Discovery is
optional: list or call directly, without initialization, cookies, or session IDs.
Each message is a separate POST, not a JSON-RPC batch. Receipts and projects
remain application-level persisted data, not protocol sessions.

## Sources and requirements

Retrieved from the official specification on 2026-09-19:

- [Specification](https://modelcontextprotocol.io/specification/2026-07-28).
- [Lifecycle/versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/lifecycle): no modern handshake; every request declares its version and capabilities; discovery is mandatory for servers but optional for clients. Unsupported versions return `-32022` with `data.requested` and `data.supported`.
- [Transport overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) and [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http): separate POSTs, body metadata is authoritative, missing/malformed/mismatched mirrored headers return HTTP 400 / `-32020`; unsupported versions return HTTP 400 / `-32022`; unknown methods return HTTP 404 / `-32601`. Header names are case-insensitive, values case-sensitive. Encoded `Mcp-Name` must be decoded before comparison.
- [Discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover): `supportedVersions`, `capabilities`, server identity in result `_meta`, and cache fields.
- [Authoritative schema.ts](https://github.com/modelcontextprotocol/specification/blob/main/schema/2026-07-28/schema.ts): `RequestParams._meta` requires `io.modelcontextprotocol/protocolVersion` (string) and `io.modelcontextprotocol/clientCapabilities` (object). `clientInfo` is SHOULD, not MUST; when present its `name` and `version` are strings. Modern results require `resultType`; discovery and lists require `ttlMs` and `cacheScope`.
- [Official schema.json](https://github.com/modelcontextprotocol/specification/blob/main/schema/2026-07-28/schema.json): `$defs.RequestId` has type `["string", "integer"]`. Both endpoints accept exact string or integer IDs without coercion, including empty strings, zero, and negative integers. Booleans, floats (including `1.0`), explicit null, arrays, and objects return HTTP 400 / `-32600`. Absent IDs retain the legacy notification behavior below; modern HTTP requests require an ID.
- [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools): unknown tools and malformed call envelopes are RPC errors; actionable validation, API, and business-logic failures use tool results with `isError: true`.

## Separate calls

These shell examples target the product endpoint. Substitute `/mcp/PROJECT_ID`
and a listed generated tool name/arguments for a project adapter.

Optional discovery:

```bash
curl https://YOUR_DEPLOYMENT/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{},"io.modelcontextprotocol/clientInfo":{"name":"reviewer","version":"1"}}}}'
```

List, independently of discovery:

```bash
curl https://YOUR_DEPLOYMENT/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/list' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Direct call (replace the receipt ID with a stored receipt ID for success;
this all-zero ID demonstrates the missing-receipt tool error):

```bash
curl https://YOUR_DEPLOYMENT/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' \
  -H 'Mcp-Name: apivouch_verify_receipt' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"apivouch_verify_receipt","arguments":{"receipt_id":"000000000000000000000000"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

For an outcome call, use `apivouch_resolve_verified_outcome` in both `params.name`
and `Mcp-Name`, and the [outcome request](../README.md#verified-outcome-request)
as `params.arguments`. `UNVERIFIED` is a complete tool result with `isError: true`,
not a protocol error. Both text JSON and structured receipt content are returned.
Signing unavailability returns HTTP 200 with `isError: true` in modern MCP;
legacy MCP and REST return safe HTTP 503. Configuration failures block provider
calls; runtime signing failures may occur after those calls. Neither failure
returns or stores a receipt or falls back to unsigned issuance.

Every modern success includes `resultType: "complete"` and server identity in
`_meta["io.modelcontextprotocol/serverInfo"]`. Discovery/list results use
`ttlMs: 0`, `cacheScope: "private"`. Lists are complete; supplied cursors are
rejected with `-32602`. Unknown tools use `-32602`. Malformed JSON uses `-32700`,
invalid envelopes `-32600`, invalid metadata/params `-32602`, and unexpected
execution faults a sanitized `-32603`. No session ID is minted or echoed.

Both modern and legacy requests require UTF-8 JSON. Invalid UTF-8, malformed
JSON, `NaN`, `Infinity`, `-Infinity`, float overflow (such as `1e999` or `-1e999`),
unpaired surrogate escapes in string keys or values (including IDs), and duplicate
object keys at any nesting level return HTTP 400 with the sanitized JSON-RPC
`-32700` / `Parse error` response, without an ID or parser diagnostics. Parser or
string-validation recursion overflow returns the same bounded error. Valid
surrogate pairs decode to Unicode and are accepted. Escaped-equivalent keys are
duplicates too; keys in separate objects are independent.

MCP POST bodies are streamed into a bounded buffer and rejected with sanitized
HTTP 413 / JSON-RPC `-32600` once `MAX_MCP_REQUEST_BYTES` is exceeded (1 MiB by
default). This application limit applies even when a reverse-proxy cap is absent.

`Mcp-Name` supports `=?base64?BASE64_OF_UTF8?=` including non-ASCII names,
whitespace/control-containing values, and literal sentinel-pattern names. The
encoding is required for values unsafe as plain headers. Duplicate required
headers are rejected. Origin-bearing POSTs must match `PUBLIC_BASE_URL` or an
explicit entry in `CORS_ORIGINS`; otherwise HTTP 403 is returned. An untrusted
Host header does not authorize an Origin. Browser CORS preflights for origins in
`CORS_ORIGINS` allow `Content-Type`, `MCP-Protocol-Version`, `Mcp-Method`, and
`Mcp-Name` on POSTs.

## Legacy boundary

The shipped initialization interface remains supported for `2024-11-05`,
`2025-03-26`, and `2025-06-18`, including `notifications/initialized`, `ping`,
headerless list/call, and existing result/error shapes. This is preservation of
the existing JSON POST interface, not a claim to implement historical SSE
transports. Legacy `_meta` such as `progressToken` or application metadata does
not select modern validation. Keys in the `io.modelcontextprotocol/` namespace
or modern header signals select modern validation, even when malformed;
they cannot accidentally execute an old handshake. Bare `initialize` requesting
`2026-07-28` is rejected rather than silently negotiating a legacy revision.

## Tested scope and limits

`backend/tests/test_mcp_modern.py` exercises both endpoints: direct list,
discovery, required metadata and identity shape, missing/mismatched/duplicate
headers, unsupported versions, unknown methods/tools, Base64 names, malformed
JSON/envelopes/arguments, legacy versions and initialization notification,
per-request validation, cursor rejection, legacy metadata, CORS preflights, and Origin rejection. Product tests
exercise mocked-provider success, real over-budget refusal without network,
receipt persistence/reverification, signing-unavailable refusal and sanitized
internal errors. Dynamic tests execute a mocked GET and real state-changing
operation/input refusals through generated tools. Existing tests cover legacy
receipt, signing and project flows.

This is a focused, locally tested JSON-response subset, **not official MCP
conformance or certification**. No official conformance runner was executed.
No SSE, subscriptions, MRTR, extensions, custom `Mcp-Param-*` mirroring,
authorization negotiation, or full optional metadata schema validation is claimed.
Clients should send the required Accept types; this subset always returns JSON
and does not enforce Accept negotiation. These tests do not establish live
provider availability or production deployment correctness.
