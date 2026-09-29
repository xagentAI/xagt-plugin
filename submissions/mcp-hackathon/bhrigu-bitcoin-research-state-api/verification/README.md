# Verification evidence

## Prerequisites

- Review commit: `05a455ba1407f7b07de226f6c78eefda15b24880`
- API base URL: `https://bhrigu-bitcoin-research-state-api.vercel.app/v1`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error \
  https://bhrigu-bitcoin-research-state-api.vercel.app/health
```

Expected response:

```json
{"status":"ok","commit":"05a455ba1407f7b07de226f6c78eefda15b24880"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error \
  https://bhrigu-bitcoin-research-state-api.vercel.app/.well-known/xagent-verification.json
```
Expected response:

```json
{"schemaVersion":1,"slug":"bhrigu-bitcoin-research-state-api","commit":"05a455ba1407f7b07de226f6c78eefda15b24880"}
```

## 3. Capability call

```bash
curl --fail --silent --show-error \
  'https://bhrigu-bitcoin-research-state-api.vercel.app/v1/state?symbol=BTCUSDT'
```

Expected response properties:

- `schema = bhrigu_bitcoin_research_state_v0_1`
- `commit` equals the review commit
- `market.symbol = BTCUSDT`
- `market.security_type = NONE`
- `market.freshness = FRESH` when current public Binance evidence is available
- `protocol_time.halving_epoch = 4`
- `window.id = SEP_10_2026`
- `memory.append_only = true`
- every field under `authority` is `false`
## 4. Safe failure behavior

Unsupported symbol:

```bash
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' \
  'https://bhrigu-bitcoin-research-state-api.vercel.app/v1/state?symbol=ETHUSDT'
```

Expected: HTTP 400 with `UNSUPPORTED_SYMBOL` and `BTCUSDT` as the only supported symbol.

Non-read method:

```bash
curl --silent --show-error --request POST --write-out '\nHTTP %{http_code}\n' \
  'https://bhrigu-bitcoin-research-state-api.vercel.app/v1/state'
```

Expected: HTTP 405 with `METHOD_NOT_ALLOWED` and `GET` as the only allowed method.

If Binance public market evidence is unavailable, the state endpoint returns a fail-closed error rather than inventing a live market state. If the Bitcoin tip-height source is unavailable, protocol `source_status` is explicitly `unavailable` while the fixed epoch metadata remains visible.
