# BHRIGU Bitcoin Temporal Evidence

A bounded, read-only Bitcoin research capability for AI agents.

It turns public Bitcoin evidence into a repeatable temporal record:

`FIELD → WINDOW → REALITY → MEMORY → NEXT WINDOW`

## Why this is different

A live-price endpoint tells an agent what is true now. BHRIGU also preserves what was fixed **before a declared future boundary**, then lets the agent compare that immutable precommit with later reality.

The first real experiment, `SEP_10_2026`, crossed its boundary without rewriting the baseline. A durable post-boundary observation is included. `SEP_17_2026` is the second genuine future precommit.

## Public interfaces

- `GET /v1/state` — live BTCUSDT + protocol-time state and temporal summary
- `GET /v1/windows` — list precommitted windows
- `GET /v1/windows/{id}` — one frozen window and durable evidence
- `POST /mcp` — stateless Streamable HTTP MCP JSON-RPC
- `GET /openapi.json` — HTTP contract
- `GET /health` — exact deployed commit
- `GET /.well-known/xagent-verification.json` — slug + exact deployed commit

## MCP tools

- `bhrigu_get_bitcoin_research_state`
- `bhrigu_list_temporal_windows`
- `bhrigu_get_temporal_window`
- `bhrigu_compare_window_to_reality`

The MCP endpoint serves both lifecycle eras on the same URL:

- modern `2026-07-28`: handshake-free `server/discover`, per-request protocol/capability envelope, `Mcp-Method`/`Mcp-Name` header validation, complete-result discrimination, and explicit cache hints;
- legacy `2025-11-25` / `2025-03-26`: `initialize` compatibility for existing clients.

See `docs/MCP_PROTOCOL.md` for the exact transport contract. All tools are read-only. There is no trading, wallet, payment, transfer, withdrawal, credential, or private-account authority.

## Verification

```bash
npm ci
npm run check
npm start
```

For review, follow `docs/AGENT_WORKFLOW.md` for the exact three-step agent path and `docs/OPERATING_PROOF.md` for commit binding, failure behavior, and the reviewer challenge. See `docs/TEMPORAL_EVIDENCE.md` for the immutable-window contract and `docs/SCORECARD.md` for scorecard evidence.

## Public data dependencies

- Binance public Spot BTCUSDT 24h ticker
- mempool.space public Bitcoin tip height

Market-source failure is fail-closed. Protocol-height failure is exposed as unavailable rather than silently substituted.

## IP boundary

This repository contains only the bounded public adapter and public evidence records. It does not contain ORION, private prompts, planners, evaluators, private corpora, unpublished research methods, credentials, account state, wallet code, payment code, or trading execution.

See `IP_BOUNDARY.md`.

## License / rights

No general open-source license is granted by this repository. X-Agent review/archive rights apply only to the bounded submitted artifact when explicitly declared.
