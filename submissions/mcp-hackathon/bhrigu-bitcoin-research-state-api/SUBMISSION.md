# BHRIGU Bitcoin Research State API

## Capability

- **One-line description:** Returns a live, read-only Bitcoin research state combining Binance market time, Bitcoin protocol time, source freshness, and a precommitted observation window.
- **Who it helps:** AI agents and researchers that need a compact Bitcoin state with explicit provenance, time coordinates, and no trading authority.
- **Capability boundary:** Observation and research only. It does not trade, place orders, access wallets, move funds, read private account data, or provide a price target.

## Live API

- **API base URL:** https://bhrigu-bitcoin-research-state-api.vercel.app/v1
- **Health-check URL:** https://bhrigu-bitcoin-research-state-api.vercel.app/health
- **Authentication:** none
- **Rate limits / known limits:** BTCUSDT only; outbound public sources have their own limits; each upstream call has an 8-second timeout; no SLA is claimed.
- **API contract:** `GET /v1/state` with optional `?symbol=BTCUSDT`. JSON response contains market, protocol_time, window, memory, authority, and limits objects.

## Source and reproducibility

- **Source repository:** https://github.com/AiBhrigu/bhrigu-bitcoin-research-state-api
- **Review commit:** `05a455ba1407f7b07de226f6c78eefda15b24880`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm test`
- **Run locally:** `npm ci && npm start`, then `curl http://localhost:3000/v1/state`
- **Deploy:** deploy the exact review commit to Vercel with Node.js 22+; no environment variables or secrets are required.
- **Version binding:** `/health` and `/.well-known/xagent-verification.json` both expose the exact deployed Git commit.
## Verification

Reproducible calls and expected results are in `verification/README.md`.

- **Health-check result:** HTTP 200 with `status: ok` and exact review commit.
- **Capability call:** `GET /v1/state?symbol=BTCUSDT`.
- **Expected error behavior:** unsupported symbols return HTTP 400; non-GET state requests return HTTP 405; unavailable Binance market evidence fails closed rather than fabricating a live market state.

## Security and data handling

- **Data collected:** none. The service is stateless and does not accept user identity, account, wallet, or credential data.
- **Purpose and retention:** no user data is stored. A frozen public research baseline is shipped in source for comparison with live public observations.
- **Third parties / outbound network calls:** Binance public market-data-only endpoint and mempool.space public Bitcoin tip-height endpoint.
- **Secrets:** none required; none committed.
- **Known risks / restrictions:** public upstream availability and rate limits can affect live output. Market-source failure is fail-closed. Protocol tip failure is explicitly marked unavailable. Research state is not a trading signal.

## MCP productization shape

A future MCP wrapper can expose one read-only tool around `GET /v1/state`, with `symbol` constrained to `BTCUSDT`, no authorization scope, no side effects, and explicit source/freshness fields. MCP implementation is intentionally not required for this reviewed API artifact.

## Support

- **Team / builder:** BHRIGU / AiBhrigu
- **Contact:** https://x.com/bhrigu_io
- **Canonical project surface:** https://www.bhrigu.io/
- **License / rights:** no general open-source license is granted. X-Agent review/archive rights are limited to the bounded submitted artifact and are declared in `RIGHTS.md`.
