# X-Agent scorecard evidence

## Real agent/user value

BHRIGU gives agents a compact answer to a problem ordinary live-price tools cannot solve: **what was known before a declared future boundary, what is true now, and what changed without rewriting the past?** The loop is reusable across multiple windows.

## Demonstrated capability quality

- live Binance BTCUSDT market evidence;
- Bitcoin protocol-time coordinates;
- source freshness;
- frozen precommit baselines;
- durable post-boundary evidence;
- explicit evidence limitations;
- fail-closed market-source behavior;
- no prediction or trading claim.

## Engineering and maintainability

- zero npm runtime dependencies;
- exact deployment commit binding;
- CI on push and pull request;
- acceptance, temporal, MCP, and immutable-baseline tests;
- pinned SHA-256 for the original SEP_10 source file and committed evidence artifacts;
- public OpenAPI contract;
- typed JSON-RPC errors and bounded tool schemas;
- header/body mismatch checks for modern MCP traffic.

## MCP productization

The same stateless `/mcp` endpoint serves both MCP lifecycle eras. Modern `2026-07-28` requests use handshake-free `server/discover`, per-request protocol/capability metadata, header-based routing validation, `resultType: complete`, and explicit cache hints. Existing `2025-11-25` / `2025-03-26` clients retain `initialize` compatibility.

Four tools expose live state, window discovery, durable evidence retrieval, and live comparison. Every tool is read-only and explicitly non-destructive. See `docs/MCP_PROTOCOL.md` for the exact contract.

## Operational and adoption potential

The capability requires no user credential, wallet, API key, or account state. Agents can integrate it as a public evidence service. A second precommit (`SEP_17_2026`) proves the method is repeatable rather than a one-off demonstration.

## Boundary

The public artifact exposes only the bounded evidence adapter. ORION, private prompts, planners, evaluators, private corpora, unpublished research methods, credentials, wallets, payments, transfers, withdrawals, and trading execution remain excluded.
