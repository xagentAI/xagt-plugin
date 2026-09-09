# VenueClock

Deterministic **market-session calendar** that AI agents can call. Given a venue and a timestamp (or a calendar date), it returns whether that market is in pre-market, regular hours, after-hours, holiday, weekend, or closed, plus the next open or close.

This is an Open Innovation entry for the [X-Agent AI MCP Hackathon 2026](https://xagt.ai/hackathon?lang=en). It is **not** a trading bot, not a risk scorer, and not an on-chain security tool.

- Live API origin: https://kele0929.github.io
- Source: https://github.com/kele0929/venueclock
- MCP tool list: https://kele0929.github.io/mcp/tools.json
- Local MCP stdio: `node src/mcp.js`

## Why this is agent-useful

Agents that schedule orders, fetch prices, or write “is the market open?” answers routinely hallucinate holidays, early closes, and DST. VenueClock answers from explicit calendars and session rules, with ISO-8601 timestamps and machine-readable phases.

Supported venues:

| id | MIC | Market | Timezone |
| --- | --- | --- | --- |
| `xnys` | XNYS | New York Stock Exchange | America/New_York |
| `xnas` | XNAS | Nasdaq Stock Market | America/New_York |
| `xlon` | XLON | London Stock Exchange | Europe/London |
| `crypto` | — | 24/7 crypto (synthetic) | UTC |

US 2026 holidays and 13:00 ET early closes follow the Nasdaq / NYSE 2026 calendars. LSE 2026 dates follow UK bank holidays. Crypto is always in `regular`.

## HTTP API

All JSON, CORS `*`, no authentication.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health.json` | `{ "status": "ok", "commit": "<sha>" }` |
| GET | `/.well-known/xagent-verification.json` | X-Agent deployment proof |
| GET | `/v1/venues.json` | Venue index |
| GET | `/v1/venues/{id}.json` | Rules, sessions, 2026 holidays |
| GET | `/v1/resolve/{id}/{YYYY-MM-DD}.json` | Full day schedule in the venue timezone |
| GET | `/v1/resolve?venue={id}&at={iso8601}` | Instant session state (Node server) |
| GET | `/mcp/tools.json` | MCP tool descriptors |

The GitHub Pages deploy is a static snapshot of the same router used by `node src/server.js`. Instant query-string resolve is available on the Node server; the public Pages origin exposes the day-schedule capability plus health/proof.

### Example

```bash
curl -sS https://kele0929.github.io/v1/resolve/xnys/2026-09-04.json
```

Friday 4 September 2026 is a normal NYSE day: pre 04:00–09:30, regular 09:30–16:00, after-hours 16:00–20:00 America/New_York (EDT).

```bash
curl -sS https://kele0929.github.io/v1/resolve/xnys/2026-09-07.json
```

Labor Day 2026: `status` is `holiday`, `sessions` is empty.

Unknown venues return HTTP 404 JSON `{ "error": "not_found", ... }`. Invalid dates return HTTP 400.

## Run locally

Requires Node.js 18.17+.

```bash
npm test
REVIEW_COMMIT=$(git rev-parse HEAD) npm start
# http://127.0.0.1:8787/health.json
# http://127.0.0.1:8787/v1/resolve?venue=xnys&at=2026-09-04T15:00:00Z
```

MCP stdio:

```bash
node src/mcp.js
```

Generate the static GitHub Pages snapshot:

```bash
REVIEW_COMMIT=$(git rev-parse HEAD) npm run generate -- --out ./site
```

## Deploy

1. Push this repository to `https://github.com/kele0929/venueclock`.
2. Record `REVIEW_COMMIT=$(git rev-parse HEAD)`.
3. Generate the site with that commit and publish the `site/` tree to `https://github.com/kele0929/kele0929.github.io` on branch `main` (GitHub Pages user site).
4. Confirm:
   - `GET https://kele0929.github.io/health.json` → `status=ok` and the same commit
   - `GET https://kele0929.github.io/.well-known/xagent-verification.json` → slug `kele0929-venueclock` and the same commit

The Pages origin is `https://kele0929.github.io`, so the well-known proof sits at the origin root as required by X-Agent.

## Boundary

VenueClock reports **session calendars**. It does not place orders, return prices, score wallets, detect exploits, or provide financial advice. Holiday tables cover **2026** (the review year). Other years use the same weekly hours and DST rules but only 2026 named holidays are encoded.

## License

MIT. Builder: kele0929.
