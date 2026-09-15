# MCP protocol contract

BHRIGU serves the same four read-only tools across the modern and legacy MCP lifecycle eras.

## Modern era — 2026-07-28

The modern path is stateless and handshake-free. `server/discover` is available for up-front discovery, but tools can be called directly when the client already knows the contract.

Every modern non-notification HTTP request carries:

- `MCP-Protocol-Version: 2026-07-28`
- `Mcp-Method` matching the JSON-RPC method
- `Mcp-Name` where the method mirrors a `params.name` value, including `tools/call`
- `_meta.io.modelcontextprotocol/protocolVersion = 2026-07-28`
- `_meta.io.modelcontextprotocol/clientCapabilities`

`_meta.io.modelcontextprotocol/clientInfo` is recommended but optional; if present it must be well formed. Notification POSTs are exempt from the standard-header presence check.

`server/discover` advertises every protocol revision this endpoint supports so a client can negotiate the modern era or deliberately fall back to a legacy initialize-capable revision. Modern complete results carry `resultType: "complete"`; server identity is stamped in `_meta.io.modelcontextprotocol/serverInfo`, and cacheable discovery/list results carry explicit `ttlMs` and `cacheScope` hints.

The server fails closed on malformed or missing required `_meta` fields (`-32602`), header/body mismatches (`-32020`), and unsupported protocol versions (`-32022`). `-32022` errors return both the requested revision and the supported-version set. The current BHRIGU tools require no optional client capability beyond the mandatory per-request `clientCapabilities` envelope, so they do not emit `-32021` in ordinary use. Modern `initialize` and `ping` are not served because they belong to the handshake-era lifecycle.

## Legacy era — 2025-11-25 / 2025-03-26

Legacy clients can still use `initialize` and the same read-only tools. BHRIGU uses the stateless legacy HTTP form: it does not create a protocol session because these tools never require server-to-client requests or hidden transport state.

## Safety boundary

MCP calls never create observations, rewrite precommits, trade, sign, pay, transfer, withdraw, read credentials, or access private account data. Temporal evidence is committed separately and exposed read-only.
