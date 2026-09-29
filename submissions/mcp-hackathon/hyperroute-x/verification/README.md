# Verification evidence

## Prerequisites

- Review commit: `e8be87499fdf6f977051fa3b2d1fb0d916322e8d`
- API base URL: `https://alexbrian3-hyperroute-x.onrender.com/api/v1`
- Authentication: `None required (open public endpoints for hackathon review)`

## 1. Health check

```bash
curl --fail --silent --show-error https://alexbrian3-hyperroute-x.onrender.com/health
```

Expected response:

```json
{
  "status": "ok",
  "commit": "e8be87499fdf6f977051fa3b2d1fb0d916322e8d",
  "version": "e8be87499fdf6f977051fa3b2d1fb0d916322e8d",
  "slug": "hyperroute-x",
  "network": "xlayer-mainnet"
}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://alexbrian3-hyperroute-x.onrender.com/.well-known/xagent-verification.json
```

Expected response:

```json
{
  "schemaVersion": 1,
  "slug": "hyperroute-x",
  "commit": "e8be87499fdf6f977051fa3b2d1fb0d916322e8d"
}
```

## 3. Capability call: Quote calculation

```bash
curl --fail --silent --show-error \
  --request POST https://alexbrian3-hyperroute-x.onrender.com/api/v1/quote \
  --header "content-type: application/json" \
  --data '{"token_in":"OKB","token_out":"USDT","amount_in":"1.0","max_slippage_bps":50}'
```

Expected success response:

```json
{
  "token_in": {
    "address": "0xdf54b6c6195ea4d948d03bfd818d365cf175cfc2",
    "symbol": "OKB",
    "decimals": 18,
    "name": "OKB Token"
  },
  "token_out": {
    "address": "0x1e4a5963abfd975d8c9021ce480b42188849d41d",
    "symbol": "USDT",
    "decimals": 6,
    "name": "Tether USD"
  },
  "amount_in_base_units": "1000000000000000000",
  "amount_in_formatted": "1.0",
  "estimated_amount_out_base_units": "48475750",
  "estimated_amount_out_formatted": "48.475750",
  "guaranteed_min_amount_out_base_units": "48233371",
  "guaranteed_min_amount_out_formatted": "48.233371",
  "effective_price": 48.47575,
  "price_impact_pct": 0.05,
  "gas_estimate": 125000,
  "route": [
    {
      "pool_address": "0x4a1804Bf75B70aA770519a86bF32014b294e7724",
      "protocol": "UniswapV3_XLayer",
      "fee_tier_bps": 500,
      "split_percentage": 100.0,
      "expected_amount_out": "48475750"
    }
  ],
  "router_address": "0x098d6B00041B1F3415c48b2E15a6b0c2A8F70570"
}
```

Safe error behavior:
```bash
curl --silent --show-error \
  --request POST https://alexbrian3-hyperroute-x.onrender.com/api/v1/quote \
  --header "content-type: application/json" \
  --data '{"token_in":"OKB","token_out":"OKB","amount_in":"1.0"}'
```
Expected HTTP 400 response:
```json
{
  "detail": "token_in and token_out must be different assets"
}
```
