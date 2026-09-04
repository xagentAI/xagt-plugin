# GasPulse

> Replace every angle-bracket placeholder before opening the pull request.

## Capability

- **One-line description:** Given an Ethereum mainnet address, returns a recent gas-consumption
  trend and a deterministic 0–100 activity/liveliness score, so a trading agent can quickly gauge
  how active an address currently is.
- **Who it helps:** AI trading agents (and their operators) that need a fast, structured signal
  on address activity before acting — e.g. deciding whether a counterparty or watched address is
  currently live.
- **Capability boundary:** Read-only Ethereum mainnet data sourced from Etherscan. Computes gas
  trend and an activity score from an address's most recent transactions (bounded — see Known
  risks below). It does **not** perform fraud, risk, compliance, or security analysis of any
  kind: `activityScore` reflects only the recency, frequency, and consistency of transactions,
  never trustworthiness or danger.

## Live API

- **API base URL:** https://api.gaspulse.win/v1
- **Health-check URL:** https://api.gaspulse.win/health
- **Authentication:** none
- **Rate limits / known limits:** bounded by the Etherscan free tier (~5 req/s upstream);
  GasPulse caches the raw per-address transaction list for 60 seconds in memory to absorb
  repeated agent calls. Upstream requests time out after 8s server-side, surfaced to the caller
  as `429`/`502` (see error taxonomy below and in `source/README.md`).
- **API contract:** `GET /v1/address/{address}/activity?windowDays=30` — full request/response
  shapes, field meanings, and the activity-score methodology are documented in
  `source/README.md` (reproduced with a live example in `verification/README.md`). A second,
  free endpoint, `GET /v1/gas/current`, returns the current network-wide gas price (no address,
  no parameters) — also documented in `source/README.md`.

## Source and reproducibility

- **Source repository:** https://github.com/muhammad-wei/gaspulse
- **Review commit:** `f1edc68641d5bee0f6c8a72f11abc75bfa837c75`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm test`
- **Run locally:** `npm ci && cp .env.example .env` (fill in `ETHERSCAN_API_KEY`) `&& npm run dev`
- **Deploy:** `npm run build && node dist/server.js` with `GIT_COMMIT` and `ETHERSCAN_API_KEY` set
  in the environment; a Docker alternative (`docker build --build-arg GIT_COMMIT=$(git rev-parse HEAD) ...`)
  is documented in `source/README.md`.
- **Version binding:** `GIT_COMMIT` is injected into the process environment at deploy time
  (Docker: `--build-arg GIT_COMMIT` baked to `ENV`; this live deployment: a systemd service
  `Environment=` line set to the exact commit above) and read by `/health` and
  `/.well-known/xagent-verification.json` at request time — never read from `.git` or hardcoded.

The API must expose:

```json
// GET https://api.gaspulse.win/health
{"status":"ok","commit":"f1edc68641d5bee0f6c8a72f11abc75bfa837c75"}
```

```json
// GET /.well-known/xagent-verification.json on the same API origin
{"schemaVersion":1,"slug":"visioneer-gaspulse","commit":"f1edc68641d5bee0f6c8a72f11abc75bfa837c75"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `GET https://api.gaspulse.win/health` →
  `{"status":"ok","commit":"f1edc68641d5bee0f6c8a72f11abc75bfa837c75"}`
- **Capability call:** `GET https://api.gaspulse.win/v1/address/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045/activity?windowDays=30`
  → `200` with gas trend and activity score for that address.
- **Expected error behavior:** malformed address → `400 invalid_address`; out-of-range
  `windowDays` → `400 invalid_window`; Etherscan rate-limited → `429 upstream_rate_limited`;
  Etherscan unreachable/erroring → `502 upstream_unavailable`. An address with no transactions
  returns `200` with every field zeroed, never `404` — deterministic either way.

## Security and data handling

- **Data collected:** none stored persistently. The Ethereum address in the request path is
  forwarded to Etherscan's public API to look up that address's public on-chain transaction
  history; results are cached in-process for 60 seconds, then discarded.
- **Purpose and retention:** the fetched transaction data is used only to compute the response
  for that single request; nothing is logged or persisted beyond the 60-second in-memory cache.
- **Third parties / outbound network calls:** Etherscan API (`api.etherscan.io`) — the only
  outbound call GasPulse makes.
- **Secrets:** No secrets are committed. `ETHERSCAN_API_KEY` is supplied via environment variable
  only (`.env.example` ships an empty placeholder). This API requires no auth, so no review
  credential needs to be shared.
- **Known risks / restrictions:** Ethereum mainnet only. Gas trend and `firstSeen`/`lastSeen` are
  computed from the most recent 1,000 transactions Etherscan returns for the address —
  extremely long-lived, high-volume addresses may have earlier history not reflected.
  `activityScore` is deliberately not a risk/fraud/security signal (see Capability boundary).

## Support

- **Team / builder:** Visioneer
- **Contact:** https://github.com/muhammad-wei
- **License / rights:** MIT (`source/LICENSE`). Submitter confirms ownership/authorization to
  submit and license this code for review and deployment — see `RIGHTS.md`.
