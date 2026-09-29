# Third-party public data

## Binance Spot public market data

Endpoint class: public market data, security type `NONE`.

Used for BTCUSDT 24-hour ticker fields only. No Binance account authentication, API key, trading endpoint, wallet endpoint, transfer endpoint, or private account endpoint is used.

## mempool.space public Bitcoin tip height

Used only to retrieve the current public Bitcoin block height and derive position within the current halving epoch.

If this source is unavailable, the API exposes the source as unavailable and does not substitute hidden data.

## Runtime dependencies

The project has no npm runtime dependencies. It uses only Node.js built-ins and the platform-provided `fetch` implementation.
