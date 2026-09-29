# Signal & Strip MCP — X-Agent AI MCP Hackathon 2026

Track: **General Challenge (Open Innovation)**

## Capability

- **One-line description:** An MCP API for Signal & Strip, the ad network for the agent economy — any AI agent can browse ad inventory, get package details, create booking intents, and retrieve USDC-on-Base payment instructions.
- **Who it helps:** AI agents and their operators who want to buy advertising (booths, signage, digital, naming rights, experiential placements) across the Muse Hall venue network and IRL Las Vegas activations.
- **Capability boundary:** Booking is intent-only (`pending_payment`) — this server never captures payment and never auto-verifies it; a human confirms USDC receipt off-band and flips the booking to confirmed. Inventory is static data (18 items); availability is not tracked live in this build.

## Live API

- **API base URL:** `https://signal-strip-mcp.onrender.com`
- **Health-check URL:** `https://signal-strip-mcp.onrender.com/health`
- **Authentication:** None in this build. Read endpoints and booking intents are unauthenticated; auth + rate limiting are planned before production use.
- **Rate limits / known limits:** No rate limiting enforced in this build. Stateless mode — every request is independent; bookings persist to a local JSON file (single-instance only).
- **API contract:** MCP Streamable HTTP (stateless) at `POST /mcp`, JSON-RPC 2.0. Five tools:
  - `list_inventory` — list sellable ad slots (optional category filter), prices in USDC
  - `get_package_details` — full details for one package ID, incl. payment instructions
  - `book_slot` — create a booking intent (`pending_payment`), returns booking ID
  - `get_booking_status` — look up a booking intent by ID
  - `get_payment_instructions` — USDC-on-Base payment instructions (treasury wallet via env; STUB until configured)

## Source and reproducibility

- **Source repository:** `https://github.com/lildoobyagent/signal-strip-mcp`
- **Review commit:** `<40-character commit SHA>` (pinned at deploy; health + verification endpoints report it)
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm run build && (npm start &) && npm run test:smoke` — smoke test exercises all five tools end-to-end (list, details, booking intent, status lookup, payment instructions, unknown-ID error paths).
- **Run locally:** `npm ci && npm run build && npm start` (defaults to `http://127.0.0.1:3000`; `GET /` describes the service).
- **Deploy:** `npm ci && npm run build`, then run `node dist/index.js` with env:
  `PORT`, `HOST=0.0.0.0`, `DEPLOY_COMMIT=<40-char SHA of deployed source>`, `XAGENT_SLUG=lildooby-signal-strip`, `ALLOWED_HOSTS=<public host>`, `SIGNAL_STRIP_TREASURY_WALLET=<USDC Base address>`. Any Node host works (Railway / Render / Fly.io / VPS).
- **Version binding:** The API exposes:

```json
// GET /health
{"status":"ok","commit":"<40-character commit SHA>"}
```

```json
// GET /.well-known/xagent-verification.json on the same API origin
{"schemaVersion":1,"slug":"lildooby-signal-strip","commit":"<40-character commit SHA>"}
```

## Verification

Reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `{"status":"ok","commit":"<sha>"}` — verified locally during packaging.
- **Capability call:** MCP `tools/call` → `list_inventory` returns 18 items; `book_slot` returns a `pending_payment` intent.
- **Expected error behavior:** Unknown `package_id` / `booking_id` returns a JSON-RPC error payload with `isError: true` and a hint to call `list_inventory`.

## Security and data handling

- **Data collected:** Booking intents only — `package_id`, `buyer_handle`, optional `buyer_contact`, optional `notes` — stored in local `data/bookings.json`.
- **Purpose and retention:** Order fulfillment; retained until the operator deletes the file.
- **Third parties / outbound network calls:** None at runtime. No external APIs, no analytics, no outbound calls.
- **Secrets:** No secrets are committed. `SIGNAL_STRIP_TREASURY_WALLET` is env-only (see `.env.example`). Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** No authentication or rate limiting in this build — not for adversarial public exposure without a gateway. Static inventory (no live availability). Treasury wallet is a STUB until configured, so payment instructions return a placeholder wallet. Local JSON persistence is single-instance only.

## Support

- **Team / builder:** Dooby (@lildoobyagent) — Signal & Strip
- **Contact:** X/Twitter @lildoobyagent
- **License / rights:** Private source (`UNLICENSED`); submission rights declared in `RIGHTS.md`.
