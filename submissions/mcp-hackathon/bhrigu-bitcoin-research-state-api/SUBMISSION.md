# BHRIGU Bitcoin Temporal Evidence

## Capability

- **One-line description:** Lets an AI agent read what Bitcoin evidence was fixed before a declared future boundary, compare it with live reality after the boundary, and inspect durable hash-bound evidence without rewriting the past.
- **Who it helps:** AI agents and researchers that need reproducible temporal evidence rather than only a live-price snapshot.
- **Capability boundary:** Read-only Bitcoin research. It does not predict price, trade, place orders, access wallets, move funds, read private account data, or accept credentials.

## Live API

- **API base URL:** https://bhrigu-bitcoin-research-state-api.vercel.app/v1
- **Health-check URL:** https://bhrigu-bitcoin-research-state-api.vercel.app/health
- **Authentication:** none
- **Rate limits / known limits:** BTCUSDT only; public upstream services impose their own limits; market calls fail closed when fresh evidence is unavailable; no SLA is claimed.
- **API contract:** `GET /v1/state`, `GET /v1/windows`, `GET /v1/windows/{id}`, `POST /mcp`, and `GET /openapi.json`. The MCP endpoint exposes four read-only tools and supports modern `2026-07-28` stateless discovery plus legacy `2025-11-25` / `2025-03-26` compatibility.

## Source and reproducibility

- **Source repository:** https://github.com/AiBhrigu/bhrigu-bitcoin-research-state-api
- **Review commit:** `905adc26632e4595d998c01da26b3ccd88bf8a6f`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm test` (106 deterministic checks: acceptance 18 + temporal 17 + MCP 56 + integrity 15)
- **Run locally:** `npm ci && npm start`, then call `http://localhost:3000/v1/state`, `/v1/windows`, or `/mcp`.
- **Deploy:** deploy the exact review commit to Vercel with Node.js 22+; no environment variables or secrets are required.
- **Version binding:** `/health` and `/.well-known/xagent-verification.json` expose the exact deployed review commit.

## Verification

Repeatable commands and expected results are in `verification/README.md`.

- **Health-check result:** HTTP 200 with `status: ok` and exact review commit.
- **Capability call:** an agent can `DISCOVER → READ_LOCKED_PAST → COMPARE_LIVE_REALITY` using the four read-only MCP tools or equivalent HTTP endpoints.
- **Expected error behavior:** unsupported symbols return HTTP 400; write methods are rejected; unsupported modern MCP versions and header/body mismatches fail closed; unavailable market evidence is not fabricated.

## Security and data handling

- **Data collected:** none from users. The service is stateless with respect to user identity and accepts no account, wallet, or credential data.
- **Purpose and retention:** frozen precommit records and committed post-boundary evidence are public research artifacts retained in source; no personal data is retained.
- **Third parties / outbound network calls:** Binance public Spot BTCUSDT market data and mempool.space public Bitcoin tip height.
- **Secrets:** none required; none committed.
- **Known risks / restrictions:** public upstream availability and rate limits affect live evidence. `SEP_10_2026` has one durable post-boundary evidence record; `SEP_17_2026` is a genuine second precommit and remains pre-boundary until its declared UTC boundary.

## Temporal-evidence proof

`SEP_10_2026` was committed before its `2026-09-10T00:00:00Z` boundary. The original baseline remains hash-pinned and unchanged, and the reviewed source contains a durable post-boundary observation. `SEP_17_2026` provides a second future window. The public registry exposes append-only intent, evidence counts, phases, and artifact hashes so reviewers can distinguish frozen past evidence from live current state.

## MCP productization

`POST /mcp` is shipped, not proposed. It provides four read-only tools for current Bitcoin state, temporal-window discovery, frozen-window retrieval, and live comparison. Modern `2026-07-28` requests are stateless and handshake-free via `server/discover`; legacy clients retain `initialize` compatibility. No MCP tool creates observations or carries trading, wallet, payment, transfer, withdrawal, credential, or private-account authority.

## Support

- **Team / builder:** BHRIGU / AiBhrigu
- **Contact:** https://x.com/bhrigu_io
- **Canonical project surface:** https://www.bhrigu.io/
- **License / rights:** no general open-source license is granted. X-Agent review/archive rights are limited to the bounded submitted artifact and are declared in `RIGHTS.md`.
