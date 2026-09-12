# Third-party services and public data

## OlaXBT Nexus MCP

Primary external service for the trading-track Strategy Evidence capability. The server calls only the bound strategy's read interfaces used here: signal, metrics, trades, and equity. The authorized Nexus credential is server-side only and is not committed or returned. OlaXBT remains strategy + signal authority.

## Binance Spot public market data

Inherited Bitcoin Temporal Evidence capability only. Public BTCUSDT market data; no Binance account credential, trading, wallet, transfer, or private-account endpoint is used.

## mempool.space public Bitcoin data

Inherited Bitcoin Temporal Evidence capability only. Used for public Bitcoin tip-height context.

## Runtime dependencies

No npm runtime dependencies. The project uses Node.js built-ins and platform-provided `fetch`. Third-party services and data remain subject to their respective terms.
