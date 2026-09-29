# Verification evidence

## Prerequisites

- Review commit: `efe61edb90358463c45f901e42964aa90261723c`
- API base URL: https://www.multipu.fun/api
- Authentication: None required for public query endpoints.
- Run commands from `submissions/mcp-hackathon/wisdomdivine-multipu/`.

## 1. Health check

```bash
curl --fail --silent --show-error https://www.multipu.fun/api/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "multipu",
  "version": "1.0.0",
  "commit": "efe61edb90358463c45f901e42964aa90261723c",
  "environment": {
    "appPhase": "mainnet",
    "network": "mainnet-beta"
  },
  "supportedChains": [
    { "id": "solana", "name": "Solana", "gas": "SOL" },
    { "id": "bsc", "name": "BNB Smart Chain", "gas": "BNB" },
    { "id": "robinhood", "name": "Robinhood Chain", "gas": "ETH" }
  ],
  "mcp": {
    "enabled": true,
    "protocol": "2024-11-05",
    "server": "multipu-mcp"
  }
}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://www.multipu.fun/.well-known/xagent-verification.json
```

Expected response:

```json
{
  "schemaVersion": 1,
  "slug": "wisdomdivine-multipu",
  "commit": "efe61edb90358463c45f901e42964aa90261723c"
}
```

## 3. Capability call

Explore active multi-chain launches and trading pools aggregated across top launchpads:

```bash
curl --fail --silent --show-error \
  --request GET https://www.multipu.fun/api/launches/explore \
  --header "accept: application/json"
```

Expected success response:
A JSON payload containing an array of active launches across supported chains with pricing, liquidity pool address, market cap, and 24-hour volume metrics:

```json
{
  "launches": [
    {
      "id": "EDnqSPoUjcfGEXyb56Qs9VvwESNQSU9cFp4DFp1Yfspf",
      "launchpad": "meteoradbc",
      "network": "Solana",
      "pool_address": "7HtcJ9j2e1cBw1d2ZW3dqbwqtUWR8wx6UPbQqGeqaRVN",
      "volume_24h": 6874.61,
      "market_cap": 45100.48,
      "fdv": 45100.48,
      "price_usd": 0.0000451,
      "price_change_24h": 235,
      "tokens": {
        "name": "Meteora Dynamic Pool",
        "symbol": "MDP"
      }
    }
  ],
  "column_counts": {
    "final_stretch": 26,
    "migrated": 36,
    "new_pairs": 35
  },
  "stats": {
    "total_24h_volume": 170870533.4,
    "active_tokens_count": 62
  }
}
```

## 4. Safe failure response

```bash
curl --silent --show-error https://www.multipu.fun/api/launches/nonexistent
```

Expected error response:
HTTP 404 with structured JSON:

```json
{
  "error": "Not Found"
}
```
