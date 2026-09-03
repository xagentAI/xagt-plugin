# Verification evidence

## Prerequisites

- Review commit: `0b5562319a3e1e96adeef5e1231bd4cbd2dd3030`
- API base URL: `https://api.gaspulse.win/v1`
- Authentication: none required — all endpoints are public.

## 1. Health check

```bash
curl --fail --silent --show-error https://api.gaspulse.win/health
```

Expected response:

```json
{"status":"ok","commit":"0b5562319a3e1e96adeef5e1231bd4cbd2dd3030"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://api.gaspulse.win/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"visioneer-gaspulse","commit":"0b5562319a3e1e96adeef5e1231bd4cbd2dd3030"}
```

## 3. Capability call

```bash
curl --fail --silent --show-error \
  "https://api.gaspulse.win/v1/address/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045/activity?windowDays=30"
```

Expected success response shape (HTTP 200) — this reflects live on-chain data at call time, so
the exact numbers (`txCount`, `gasTrend`, `activityScore`) will differ on reproduction; the shape
and field semantics are what to verify, e.g.:

```json
{
  "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
  "network": "ethereum-mainnet",
  "windowDays": 30,
  "asOf": "2026-09-03T05:34:13.053Z",
  "txCount": 23,
  "firstSeen": "2026-05-01T04:32:35.000Z",
  "lastSeen": "2026-09-01T11:12:59.000Z",
  "gasTrend": {
    "totalGasUsed": "554287",
    "avgGasPriceGwei": 3.79,
    "direction": "increasing",
    "buckets": [
      { "periodStart": "...", "periodEnd": "...", "txCount": 0, "gasUsed": "0", "avgGasPriceGwei": 0 },
      { "periodStart": "...", "periodEnd": "...", "txCount": 2, "gasUsed": "42124", "avgGasPriceGwei": 0.11 },
      { "periodStart": "...", "periodEnd": "...", "txCount": 6, "gasUsed": "126372", "avgGasPriceGwei": 0.28 },
      { "periodStart": "...", "periodEnd": "...", "txCount": 12, "gasUsed": "330931", "avgGasPriceGwei": 6.78 },
      { "periodStart": "...", "periodEnd": "...", "txCount": 2, "gasUsed": "54860", "avgGasPriceGwei": 0.14 }
    ]
  },
  "activityScore": { "value": 78, "recency": 94, "frequency": 100, "consistency": 0 },
  "dataSource": "etherscan"
}
```

Safe failure response — a malformed address (HTTP 400):

```bash
curl --silent "https://api.gaspulse.win/v1/address/not-an-address/activity"
```

```json
{"error":{"code":"invalid_address","message":"address must be a 0x-prefixed 40-hex-character Ethereum address"}}
```

An address with no transactions in the window returns `HTTP 200` with every numeric field
zeroed and `gasTrend.direction: "insufficient_data"` — never a `404` — so callers get a
deterministic response shape regardless of activity level.
