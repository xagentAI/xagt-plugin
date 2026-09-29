# Architecture

## Proof-of-outcome router

```text
Agent goal + constraints
        │
        ├─ Provider A ─┐
        ├─ Provider B ─┼─ concurrent bounded GET calls
        ├─ Provider C ─┤
        └─ Provider D ─┘
                │
                ├─ budget + latency gates
                ├─ JSON path + schema validation
                ├─ independent agreement / outlier rejection
                └─ deterministic price/latency/trust ranking
                ▼
       VERIFIED outcome | UNVERIFIED refusal
                │
                └─ commit-bound SHA-256 integrity receipt
                           │
                           └─ stored + re-verifiable through MCP
```

The router never turns disagreement into confidence. Fewer than the requested number of agreeing providers produces `UNVERIFIED` and no selected provider. Public receipts redact every query-string value and distinguish a quoted provider price from actual settlement.

## Provider qualification pipeline

```text
OpenAPI URL / JSON / YAML
        │
        ├─ bounded fetch + SSRF/redirect checks
        ▼
local-ref resolver + operation extractor
        │
        ├─ deterministic static analyzer
        ├─ safe repeated live probes
        ├─ JSON/content-type/schema validation
        └─ response-shape drift evidence
        ▼
evidence-labelled agent contract
        │
        ├─ re-analysis (real before/after score)
        ├─ JSON Schema MCP tool definitions
        ├─ stable runtime result envelope
        ├─ server-owned exhaustive pagination proof
        └─ stateless JSON-RPC MCP endpoint
```

## Trust boundaries

The imported API remains an untrusted external system. APIVouch never installs code from a contract, executes generated code, accepts embedded URL credentials, or automatically invokes state-changing methods.

The proof caller is also untrusted. It may state a claim and ordinary operation arguments, but it cannot send observed records, counts, cursors, page state, totals, or snapshots. APIVouch collects those facts directly. Any broken pagination, inconsistent total, changed snapshot, repeated page/cursor, or collection cap is a blocking obligation, so `PROVEN` cannot coexist with failed evidence.

The generated contract is a derived artifact. Every inserted field is marked with `x-apivouch-generated` where applicable, and the exported change list records its evidence basis.

## Storage

SQLAlchemy stores project JSON documents in `projects` and unchanged receipts in
`outcome_receipts`. SQLite is local default; production templates use PostgreSQL.

This keeps the review artifact reproducible. Production multi-tenant operation should use PostgreSQL, access control, quotas, project ownership, and expiry policies.

## Transport

The REST API manages projects and evidence. Each project also becomes a stateless MCP server at `/mcp/{project_id}`. REST proxy calls and MCP `tools/call` share the same runtime, validation, error envelope, and read-only boundary. REST and MCP exhaustiveness calls share the same bounded collector and verifier.

## Network controls

Every initial URL and redirect target is checked. The service blocks credentials in URLs and production access to loopback, private, link-local, metadata, multicast, reserved, or unspecified addresses. Response bytes, redirects, timeouts, retries, project count, operation count, upload size, proof pages, and proof records are bounded.

## Production Topology

Internet -> Caddy (only host ports 80/443) -> non-root app -> PostgreSQL.
Caddy/app share an outbound-capable edge network; app/DB share a separate
internal network. Named volumes retain DB and TLS state. Public provider access
does not require enabling private-network requests. Render remains supported.

SHA-256 receipts gain Ed25519 authenticity when configured (required by production
templates), using an environment-only seed. The independent verifier imports no
backend receipt helpers. Same-origin key discovery proves consistency, not pinned
operator identity or upstream truth. Fixtures/mocks are not live calls. Modern
MCP is a locally tested JSON subset, not official conformance. There is no payment
or tenant authorization layer; templates do not establish deployment success.
