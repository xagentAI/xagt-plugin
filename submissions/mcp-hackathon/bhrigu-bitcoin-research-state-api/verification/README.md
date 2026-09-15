# Verification evidence

## Prerequisites

- Review commit: `905adc26632e4595d998c01da26b3ccd88bf8a6f`
- API origin: `https://bhrigu-bitcoin-research-state-api.vercel.app`
- Authentication: none

## 1. Exact deployment binding

```bash
curl --fail --silent --show-error https://bhrigu-bitcoin-research-state-api.vercel.app/health
curl --fail --silent --show-error https://bhrigu-bitcoin-research-state-api.vercel.app/.well-known/xagent-verification.json
```

Expected: HTTP 200; both surfaces expose commit `905adc26632e4595d998c01da26b3ccd88bf8a6f`; verification also exposes slug `bhrigu-bitcoin-research-state-api`.

## 2. Temporal registry

```bash
curl --fail --silent --show-error https://bhrigu-bitcoin-research-state-api.vercel.app/v1/windows
curl --fail --silent --show-error https://bhrigu-bitcoin-research-state-api.vercel.app/v1/windows/SEP_10_2026
```

Expected: two windows; `SEP_10_2026` is post-boundary with one durable evidence record and `retroactive_rewrite: forbidden`; `SEP_17_2026` is the next precommitted window before `2026-09-17T00:00:00Z`.

## 3. Live state

```bash
curl --fail --silent --show-error 'https://bhrigu-bitcoin-research-state-api.vercel.app/v1/state?symbol=BTCUSDT'
```

Expected properties: exact review commit; `market.symbol = BTCUSDT`; public-source freshness; Bitcoin protocol-time coordinates; temporal evidence summary; every financial/private field under `authority` is `false`.

## 4. Modern MCP discovery

```bash
curl --fail --silent --show-error -X POST \
  https://bhrigu-bitcoin-research-state-api.vercel.app/mcp \
  -H 'content-type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  --data '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Expected: HTTP 200, `resultType: complete`, supported modern version `2026-07-28`, and read-only server capabilities.

## 5. MCP locked-past read

Call `tools/call` with `Mcp-Name: bhrigu_get_temporal_window`, `window_id: SEP_10_2026`, the same protocol metadata, and matching `Mcp-Method: tools/call`. Expected: the frozen SEP10 window plus its durable post-boundary evidence, with no write side effect.

## 6. Safe failure behavior

- `GET /v1/state?symbol=ETHUSDT` → HTTP 400 `UNSUPPORTED_SYMBOL`.
- write methods on read-only HTTP surfaces → rejected.
- unsupported modern MCP protocol version → fail-closed protocol error.
- modern MCP header/body method or tool-name mismatch → fail closed.
- unavailable Binance market evidence → no fabricated live market state.

## 7. Reproducible source verification

```bash
cd source
npm ci
npm test
```

Expected deterministic suites: acceptance 18 + temporal 17 + MCP 56 + integrity 15 = 106 PASS. Integrity tests pin the original SEP10 source hash and committed evidence artifacts.
