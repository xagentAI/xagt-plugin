# MarketMind AI Verification

## Live service

Base URL:

https://marketmind-ai-js97.onrender.com

## 1. Health check

Repeatable request:

curl -i https://marketmind-ai-js97.onrender.com/health

Expected response:

{
  "status": "ok",
  "commit": "2578c4097be83add08543464b05c628b07425b79"
}

## 2. Deployment verification

Repeatable request:

curl -i https://marketmind-ai-js97.onrender.com/.well-known/xagent-verification.json

Expected response:

{
  "schemaVersion": 1,
  "slug": "marketmind-ai",
  "commit": "2578c4097be83add08543464b05c628b07425b79"
}

## 3. Capability call

Repeatable request:

curl -i https://marketmind-ai-js97.onrender.com/v1/market-intelligence/BTCUSDT

Expected result:

HTTP 200 JSON containing:

- symbol
- price
- EMA20
- EMA50
- EMA200
- RSI14
- MACD
- MACD signal
- market assessment score and regime

The returned market data is live public market data and may change between requests.

## 4. Error behavior

Unsupported or invalid symbols may return an HTTP error.

The API does not require authentication.

## 5. Reproducibility

Source repository:

https://github.com/gurusankar55/MarketMind-AI

Review commit:

2578c4097be83add08543464b05c628b07425b79

Local run:

cd app
uvicorn main:app --reload

The service uses the public Kraken market-data API for candle data.
