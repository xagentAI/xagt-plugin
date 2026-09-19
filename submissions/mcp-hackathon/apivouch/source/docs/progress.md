# Release status

## Completed for 1.2

- Proof-of-outcome routing across two to five provider candidates
- Parallel bounded calls with distinct-origin enforcement before and after redirects
- Price, latency, JSON path, JSON Schema, and agreement gates
- Numeric-tolerance consensus and deterministic provider ranking
- Honest `VERIFIED` / `UNVERIFIED` refusal semantics
- Commit-bound, content-addressed outcome receipts with storage-time integrity verification
- Product-level MCP server with `apivouch_resolve_verified_outcome`
- One-click four-provider judge demo with schema and availability failures

- Deterministic OpenAPI 3.x / Swagger 2.0 import and local-reference resolution
- Six-dimension readiness analysis with structured findings
- Bounded repeat live probes with required-argument handling
- JSON, content-type, status, and response-schema validation
- Successful-response shape-drift detection
- Evidence-labelled agent contract generation
- Real source-versus-contract re-analysis; all simulated score logic removed
- JSON Schema tool generation with MCP safety annotations
- Stateless JSON-RPC MCP `initialize`, `tools/list`, and `tools/call`
- One runtime for REST and MCP invocation with stable errors
- Redirect-aware SSRF controls and body/timeout/retry limits
- Self-contained live demo and responsive reviewer workbench
- Single-image Docker deployment and Render blueprint
- Unit plus REST/MCP integration tests
- Server-owned Exhaustiveness Gate for `ALL`, `NONE`, `EXACT_COUNT`, `MIN`, and `MAX`
- Cursor, page, and offset traversal with page/record caps
- Snapshot, total, repeated-page, repeated-cursor, and partial-start checks
- Content-addressed proof certificates through both REST and MCP

## Account-level release steps

VPS Caddy/app/PostgreSQL configuration, scheduled/manual independent verification,
safe secret scanning, and operator backup/restore/rollback documentation are
implemented. These files are not deployment evidence. Signed v2 receipts,
readiness and modern MCP have local tests; modern MCP is not officially certified.
Public URL and final reviewed release SHA remain pending. No payment is moved.

- Deploy the final public commit.
- Confirm `/health` and `/.well-known/xagent-verification.json` report that exact 40-character commit.
- Create the X-Agent Open Innovation submission package and PR with the final source, URL, commit, and verification transcript.
- Keep the public service reachable throughout review.
