# Three-step agent workflow

BHRIGU is useful when an agent needs to distinguish **what was fixed before a future boundary** from **what is true now** without letting later reality rewrite the earlier record.

The canonical workflow is:

`DISCOVER → READ_LOCKED_PAST → COMPARE_LIVE_REALITY`

All calls below are read-only. They do not create observations, trade, sign, pay, transfer, withdraw, or access private account data.

## 1. DISCOVER

Call `server/discover` on `POST /mcp` using protocol revision `2026-07-28`, the matching `MCP-Protocol-Version` and `Mcp-Method` headers, and the required per-request `_meta` envelope.

Expected proof:

- `resultType = complete`
- `supportedVersions` contains `2026-07-28`
- server identity is present in `_meta.io.modelcontextprotocol/serverInfo`

Then call `tools/list`. The server exposes exactly four read-only tools.

## 2. READ_LOCKED_PAST

Call `bhrigu_get_temporal_window` with:

```json
{"window_id":"SEP_10_2026"}
```

Expected proof:

- baseline BTCUSDT = `78474`
- boundary = `2026-09-10T00:00:00Z`
- durable post-boundary evidence count = `1`
- precommit SHA-256 = `fd92dc8a578a2f5f393b87d3f0e65bdf2f8b9ff828ddccf21eabce66d6d39998`
- retroactive rewrite = `forbidden`

This answers: **what did the system actually know before the boundary?**

## 3. COMPARE_LIVE_REALITY

Call `bhrigu_compare_window_to_reality` with the same `window_id`.

The response reads fresh public Bitcoin evidence and returns the current BTCUSDT value and current-vs-baseline delta while preserving the locked baseline. The call does not append or mutate evidence.

For a second temporal cycle, repeat the same workflow with `SEP_17_2026`. Until its boundary, it remains a genuine future precommit with zero post-boundary evidence.

## Failure behavior

Malformed modern metadata fails with JSON-RPC `-32602`; header/body mismatches fail with `-32020`; unsupported protocol revisions fail with `-32022`; unknown windows return a structured `WINDOW_NOT_FOUND` tool error; live market-source failure fails closed rather than fabricating a comparison.
