# GasPulse

Ethereum address gas-consumption trend and activity-score API, built for AI trading agents
that need a fast, deterministic read on how active an address currently is.

## Capability boundary

- **Does**: given an Ethereum mainnet address, returns recent gas-usage trend and a 0–100
  activity/liveliness score derived from public on-chain transaction history (via Etherscan).
- **Does not**: perform fraud, risk, compliance, or security analysis of any kind. `activityScore`
  reflects only the recency, frequency, and consistency of transactions — never trustworthiness,
  danger, or a security signal. If you need risk/compliance screening, this is not that tool.

## API

### `GET /health`

```json
{"status":"ok","commit":"<40-char-sha>"}
```

### `GET /.well-known/xagent-verification.json`

```json
{"schemaVersion":1,"slug":"visioneer-gaspulse","commit":"<40-char-sha>"}
```

### `GET /v1/address/{address}/activity?windowDays=30`

- `address` (path, required) — a `0x`-prefixed 40-hex-character Ethereum address.
- `windowDays` (query, optional) — integer, `1`–`180`, default `30`.

Success (`200`) — an address with no activity still returns `200` with zeroed fields, never
`404`, so agents get a deterministic shape either way:

```json
{
  "address": "0x0000000000000000000000000000000000dead",
  "network": "ethereum-mainnet",
  "windowDays": 30,
  "asOf": "2026-09-02T00:00:00.000Z",
  "txCount": 12,
  "firstSeen": "2024-01-05T10:20:00.000Z",
  "lastSeen": "2026-09-01T08:00:00.000Z",
  "gasTrend": {
    "totalGasUsed": "252000",
    "avgGasPriceGwei": 14.2,
    "direction": "increasing",
    "buckets": [
      { "periodStart": "...", "periodEnd": "...", "txCount": 3, "gasUsed": "63000", "avgGasPriceGwei": 11.1 }
    ]
  },
  "activityScore": { "value": 78, "recency": 90, "frequency": 70, "consistency": 65 },
  "dataSource": "etherscan"
}
```

**Errors** — stable `{"error":{"code":..., "message":...}}` shape:

| HTTP | code | meaning |
| --- | --- | --- |
| 400 | `invalid_address` | address is not a well-formed `0x` + 40 hex chars string |
| 400 | `invalid_window` | `windowDays` is missing bounds or not an integer 1–180 |
| 429 | `upstream_rate_limited` | Etherscan rate limit hit — retry after a short delay |
| 502 | `upstream_unavailable` | Etherscan request failed or timed out |

**Rate limits / caching**: bounded by the Etherscan free tier (~5 req/s). GasPulse caches the
raw transaction list per address for 60 seconds in memory to absorb repeated agent calls.

**Known limitations**: gas trend and `firstSeen`/`lastSeen` are computed from the most recent
1,000 transactions Etherscan returns for the address; extremely long-lived, high-volume
addresses may have earlier history that isn't reflected. Ethereum mainnet only.

## Setup

Requirements: Node.js `>=18.17`, a free Etherscan API key (https://etherscan.io/apis).

```bash
npm ci
cp .env.example .env   # fill in ETHERSCAN_API_KEY
npm run dev
```

## Test

```bash
npm test
```

## Build and run

```bash
npm run build
npm start
```

## Docker

The deployed commit is baked into the image at build time (never read from a mutable file or
hardcoded) via `--build-arg GIT_COMMIT`:

```bash
docker build --build-arg GIT_COMMIT=$(git rev-parse HEAD) -t gaspulse .
docker run --rm -p 8080:8080 --env-file .env gaspulse
```

## Deploy

Any always-on container host works (the image is stock Node 20 + Fastify, no host-specific
code): build the image above, push it to the host's registry, deploy with `PORT=8080` exposed
and `/health` as the health-check path, and point DNS/TLS termination at port 443. Avoid
free tiers that sleep on idle — the hard uptime requirement rules those out.

## Activity score methodology

`activityScore.value` is `0.4 * recency + 0.4 * frequency + 0.2 * consistency`, each on a 0–100
scale, computed only from transactions inside `windowDays`:

- **recency** — decays linearly from 100 (last transaction was just now) to 0 (last transaction
  was `windowDays` ago or there was none).
- **frequency** — `100 * txCount / (windowDays / 3)`, clamped to 100. One transaction every 3
  days earns full credit.
- **consistency** — `100 * (1 - min(1, coefficient of variation of the gaps between consecutive
  transactions))`; requires at least 3 in-window transactions, otherwise `0`.

See `src/lib/activityScore.ts` and `src/lib/gasTrend.ts` for the exact implementation.
