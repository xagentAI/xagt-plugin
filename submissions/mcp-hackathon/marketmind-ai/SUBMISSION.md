# MarketMind AI

## Capability

- One-line description: Agent-callable crypto market intelligence API that returns market indicators and a structured market assessment for supported trading pairs.
- Who it helps: AI agents, developers, and users who need structured crypto market research data through a simple HTTP API.
- Capability boundary: Market research and analysis only. It does not execute trades, place orders, manage wallets, or provide security/audit services.

## Live API

- API base URL: https://marketmind-ai-js97.onrender.com
- Health-check URL: https://marketmind-ai-js97.onrender.com/health
- Authentication: none
- Rate limits / known limits: Public Render free service may spin down after inactivity. Market data availability depends on the public Kraken API and supported trading pairs.
- API contract: GET /v1/market-intelligence/{symbol}

Example:
GET /v1/market-intelligence/BTCUSDT

## Source and reproducibility

- Source repository: https://github.com/gurusankar55/MarketMind-AI
- Review commit: `2578c4097be83add08543464b05c628b07425b79`
- Source submitted in this PR: `source/`
- Run tests: `python -c "from candles import get_candles; print(get_candles('BTCUSDT').tail())"`
- Run locally: `cd app && uvicorn main:app --reload`
- Deploy: Render Web Service using `pip install -r requirements.txt` and `cd app && uvicorn main:app --host 0.0.0.0 --port $PORT`
- Version binding:

GET /health

{"status":"ok","commit":"2578c4097be83add08543464b05c628b07425b79"}

GET /.well-known/xagent-verification.json

{"schemaVersion":1,"slug":"marketmind-ai","commit":"2578c4097be83add08543464b05c628b07425b79"}

## Verification

The reproducible call instructions and example responses are in `verification/README.md`.

- Health-check result: HTTP 200 with status `ok` and the exact deployed review commit.
- Capability call: GET /v1/market-intelligence/BTCUSDT returns current market price, EMA20, EMA50, EMA200, RSI14, MACD, MACD signal, and a market assessment score/regime.
- Expected error behavior: Unsupported or invalid symbols may return an HTTP error. The API does not require authentication.

## Security and data handling

- Data collected: Public cryptocurrency market candle data.
- Purpose and retention: Data is used only to calculate market indicators and assessment for the API response. No user account data is stored.
- Third parties / outbound network calls: Public Kraken market-data API.
- Secrets: No secrets are committed. No authentication credentials are required.
- Known risks / restrictions: Market data can change rapidly and should be treated as informational market intelligence, not guaranteed financial advice or trade execution.

## Support

- Team / builder: gurusankar55
- Contact: GitHub repository issues
- License / rights: Project source is submitted by the builder for hackathon review and archival.
