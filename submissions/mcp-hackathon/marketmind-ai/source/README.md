# MarketMind AI

Agent-callable crypto market intelligence API.

## Features

- Public crypto market candle data
- EMA 20, 50, 200
- RSI 14
- MACD
- Market assessment score
- Simple JSON API for AI agents
- X-Agent verification endpoints

## API

GET `/v1/market-intelligence/{symbol}`

Examples:

`/v1/market-intelligence/BTCUSDT`

`/v1/market-intelligence/ETHUSDT`

`/v1/market-intelligence/SOLUSDT`

## Health

GET `/health`

## X-Agent Verification

GET `/.well-known/xagent-verification.json`

## Tech Stack

- Python
- FastAPI
- Pandas
- Requests
- Kraken public market data