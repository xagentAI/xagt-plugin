# Signal & Strip MCP Server

An MCP (Model Context Protocol) server for **Signal & Strip** — the ad network
for the agent economy, selling advertising to AI agents (online + IRL Vegas
activations).

**Purpose:** let any Meta Muse user say *"connect to Signal & Strip"* and have
their Muse build a custom connector to this server over Streamable HTTP. Muse
can then browse ad inventory, explain packages, take booking intents, and hand
out USDC-on-Base payment instructions — all inside the conversation.

> **Scaffold status.** This is a working prototype, not production software.
> Every stub is marked `STUB` in code and responses. Read
> [What's stubbed vs real](#whats-stubbed-vs-real) before deploying anything.

## Quickstart

```bash
cd ~/workspace/signal-strip-mcp
npm install
npm run dev
```

The server starts on `http://127.0.0.1:3000`:

- `GET /` — server info
- `GET /health` — health check
- `POST /mcp` — the MCP endpoint (Streamable HTTP, stateless)

Other useful commands:

```bash
npm run build        # compile TypeScript to dist/
npm start            # run the compiled server
npm run test:smoke   # end-to-end MCP smoke test (requires the dev server running)
```

Copy `.env.example` to `.env` to configure:

```bash
cp .env.example .env
```

## Tools

All prices are in **USDC**.

| Tool | Input | What it does |
|---|---|---|
| `list_inventory` | `category?` (`booth` \| `signage` \| `digital` \| `naming` \| `experiential`) | Lists all 18 sellable ad slots with prices. |
| `get_package_details` | `package_id` | Full details for one package (draft specs + payment pointer). |
| `book_slot` | `package_id`, `buyer_handle`, `buyer_contact?`, `notes?` | **Creates a booking INTENT only** (`status: "pending_payment"`). No payment captured, slot not reserved in any real system. |
| `get_booking_status` | `booking_id` | Looks up a booking intent from the local store. |
| `get_payment_instructions` | `booking_id?` | USDC-on-Base payment instructions. Treasury wallet is a **placeholder** until `SIGNAL_STRIP_TREASURY_WALLET` is set. |

### Inventory snapshot

Expo booths AX1–AX6 at **$5** each, plus the sponsor ladder: food stall **$8**,
floor decal **$10**, escalator **$12**, atrium/skybridge **$15**, facade **$20**,
ribbon **$20**, billboard **$25**, keynote LED **$35**, jumbotron **$40**, stage
backdrop **$50**, facade wrap **$75**, arena naming **$150**.

## How a Muse custom connector would use it

Meta Muse supports **custom connectors**: a user tells their Muse about a
public API or hosted MCP server, and Muse builds the integration itself on its
own VM (this is documented Meta functionality — no directory listing required).

The flow for Signal & Strip:

1. **Deploy** this server to a public HTTPS endpoint (see below — required,
   because Muse runs in Meta's cloud and cannot reach `localhost`).
2. The user says: *"Connect to the Signal & Strip MCP server at
   `https://<your-domain>/mcp`"*, optionally sharing this README or the tool
   list above.
3. Muse builds an MCP client over Streamable HTTP, calls `initialize`,
   discovers the five tools, and can then:
   - answer "what ad slots do you have and what do they cost?" via
     `list_inventory`;
   - explain a package via `get_package_details`;
   - take an order via `book_slot` (intent only — Muse must tell the buyer a
     human confirms after payment);
   - hand the buyer `get_payment_instructions` with their booking ID as the
     payment memo.

No credentials are needed for the current scaffold (there is no auth yet —
see deployment notes).

## What's stubbed vs real

**Real / working:**

- MCP protocol implementation via the official `@modelcontextprotocol/sdk`
  (v1.30.0), Streamable HTTP transport, stateless mode.
- All five tools, with zod-validated inputs and proper JSON-RPC error
  responses for unknown package/booking IDs.
- Booking intents persist to `data/bookings.json` (gitignored local file).
- `npm run test:smoke` exercises the full flow: initialize → list tools →
  inventory → details → book → status lookup → payment instructions.

**Stubbed (clearly marked `STUB` in code and tool responses):**

- **Inventory is static data** (`src/inventory.ts`). Every item reports
  `status: "available"`. There is no live availability, no double-booking
  protection, no connection to any real system. Descriptions are draft copy.
- **Bookings are local JSON** (`src/bookings.ts` → `data/bookings.json`).
  A booking is an *intent* (`intent_only: true`, `status: "pending_payment"`).
  Nothing captures payment, nothing verifies payment, nothing reserves the
  slot. A human must confirm manually after receiving USDC off-band.
- **Treasury wallet is a placeholder.** `get_payment_instructions` returns
  `treasury_wallet: null` with a stub warning until the
  `SIGNAL_STRIP_TREASURY_WALLET` env var is set. **No wallet address is
  invented anywhere in this repo** — configure the real one at deploy time
  and never commit it.
- **No authentication, no rate limiting, no per-user scoping.** Anyone who can
  reach the endpoint can list inventory and create booking intents.

## Deployment notes (do NOT deploy as-is)

1. **Public HTTPS is required.** Muse runs in Meta's cloud; `localhost` is
   not reachable. Deploy behind a proper host (VPS, Fly.io, Railway, etc.)
   with TLS.
2. Set `ALLOWED_HOSTS` to your real domain(s) — the SDK enforces
   DNS-rebinding protection via exact Host-header matching (port included).
3. Set `SIGNAL_STRIP_TREASURY_WALLET` to the real Signal & Strip USDC-on-Base
   receiving address (chain ID 8453).
4. **Before taking real orders**, add at minimum: API-key or OAuth auth,
   rate limiting, a real database, live inventory/availability checks, and
   on-chain USDC payment verification (or a manual-confirmation workflow with
   a human in the loop).
5. Bind address: the scaffold listens on `127.0.0.1` for local dev. For
   deployment behind a reverse proxy keep that; for direct exposure change
   with care and add auth first.

## Project layout

```
signal-strip-mcp/
  src/
    index.ts       # Express app + Streamable HTTP transport (stateless)
    server.ts      # McpServer factory + the 5 tool definitions
    inventory.ts   # STUB: static inventory data + sponsor ladder prices
    bookings.ts    # STUB: local-JSON booking-intent store
  scripts/
    smoke.mjs      # end-to-end MCP smoke test (npm run test:smoke)
  data/
    bookings.json  # created at runtime, gitignored
  .env.example     # config template (treasury wallet placeholder)
  README.md
```
