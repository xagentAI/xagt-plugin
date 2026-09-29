# Settle

> Payment truth for autonomous agents.

Settle is an API-first, read-only payment reconciliation service. A caller
declares an expected USDC payment on Base, the payment happens independently,
and Settle later checks the chain and returns a deterministic payment status
plus transaction evidence.

- Product scope: [`SETTLE_PRODUCT_BRIEF.md`](./SETTLE_PRODUCT_BRIEF.md)
- Technical source of truth: [`ARCHITECTURE.md`](./ARCHITECTURE.md)

## Status

Milestone 4 — the complete v1 reconciliation state model plus the demo
inspector UI. Intents with or without a declared `payer` reconcile against
canonical native Base USDC `Transfer` logs into `pending`, `detected`,
`partial`, `paid`, `overpaid`, `expired` or `ambiguous`, with expiry-block
resolution, canonical (reorg-aware) evidence and paginated evidence. Still to
come (see `ARCHITECTURE.md` §17): abuse/failure hardening (Milestone 5) and
submission hardening (Milestone 6).

## Demo console

The interface is a demo console; the API is the product. Two pages, both
driven entirely by the public REST API below (no privileged path):

- `/` — create an expected payment (network and asset are fixed to Base /
  native USDC) with a live curl preview of the exact request.
- `/inspect/<id>` — the inspector: payment status with a one-line meaning,
  expected / received / remaining, obligation metadata, the onchain evidence
  ledger (`matched`, `candidate`, `orphaned` rows with Basescan links), a
  “Reconcile now” action, copyable curl calls, and automatic reconciliation
  every 7 seconds while the page is open (it stops on `paid`, `overpaid`,
  `expired`, `ambiguous`, while the tab is hidden, and after three consecutive
  failures until you reconcile manually). Amounts shown are the API's values;
  nothing monetary is computed in the browser.

## Stack

Node.js 24 · TypeScript 6 (strict) · Next.js 16 App Router (Node runtime, never
Edge) · React 19 · Tailwind CSS 4 · Zod 4 · Drizzle ORM 0.44 + `pg` · viem 2 ·
Neon PostgreSQL · Alchemy Base RPC · Vitest 4 · pnpm 10 · Vercel.

## Local setup

```sh
# Node 24 (see .node-version) and pnpm 10 (pinned in package.json "packageManager";
# any recent pnpm switches to the pinned version automatically).
pnpm install
cp .env.example .env.local   # fill in DATABASE_URL, DATABASE_URL_UNPOOLED, ALCHEMY_BASE_RPC_URL
pnpm db:migrate              # applies drizzle/*.sql through DATABASE_URL_UNPOOLED
pnpm dev                     # http://localhost:3000
```

Migrations are applied only by `pnpm db:migrate` (locally or from CI) — never
by `next build`, application startup, or a request handler.

## Scripts

| Script           | What it does                                   |
| ---------------- | ---------------------------------------------- |
| `pnpm dev`       | Next.js dev server                             |
| `pnpm build`     | Production build                               |
| `pnpm start`     | Serve the production build                     |
| `pnpm lint`      | ESLint (`eslint-config-next` + TypeScript)     |
| `pnpm typecheck` | Generate Next route types, then `tsc --noEmit` |
| `pnpm test`      | Vitest, single run                             |
| `pnpm test:watch`| Vitest in watch mode                           |
| `pnpm db:generate` | Generate a SQL migration from `src/db/schema.ts` into `drizzle/` |
| `pnpm db:migrate`  | Apply committed migrations using `DATABASE_URL_UNPOOLED` |

| `pnpm test:e2e`  | Playwright browser smoke suite (builds and serves the app itself; needs `pnpm exec playwright install chromium` once) |

Required CI checks: `pnpm lint && pnpm typecheck && pnpm test && pnpm build`.
The browser suite (`pnpm test:e2e`) intercepts every API call with fixtures,
so it needs no database or RPC credential; it runs at 1440×900 and 390×844.

Database integration tests (`tests/integration`) are skipped unless
`TEST_DATABASE_URL` points at a dedicated test database:

```sh
TEST_DATABASE_URL=postgres://... pnpm test tests/integration
```

## Public endpoints

### `POST /v1/payment-intents`

Declares an expected native-USDC payment on Base. The intent's matching window
starts at the Base block after the latest block observed at creation.

```sh
curl -i https://<deployment>/v1/payment-intents \
  -H 'Content-Type: application/json' \
  -d '{
    "externalReference": "INV-204",
    "chain": "base",
    "asset": "USDC",
    "amount": "850.00",
    "recipient": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "payer": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "expiresAt": "2026-09-18T18:00:00Z",
    "requiredConfirmations": 3
  }'
```

`201 Created`:

```json
{
  "id": "pi_9VF1Q6h9F0c3bqzXlmqz0xQQ0ivN3G9r1O5T7Y8b",
  "status": "pending",
  "externalReference": "INV-204",
  "chain": "base",
  "asset": "USDC",
  "expectedAmount": "850.00",
  "receivedAmount": "0.00",
  "remainingAmount": "850.00",
  "recipient": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
  "payer": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
  "requiredConfirmations": 3,
  "matchConfidence": "none",
  "paidAt": null,
  "createdAt": "2026-09-17T14:31:02.000Z",
  "expiresAt": "2026-09-18T18:00:00.000Z"
}
```

Rules: `chain` must be `"base"` (`UNSUPPORTED_CHAIN`), `asset` must be
`"USDC"` (`UNSUPPORTED_ASSET`), addresses must be valid EVM addresses
(`INVALID_ADDRESS`), `amount` is a positive decimal string with at most six
decimals, `expiresAt` is a UTC timestamp ending in `Z` between now and seven
days out, `requiredConfirmations` is `1..64` (default `3`), `externalReference`
is at most 128 characters, unknown fields are rejected, and the JSON body is
limited to 16 KiB (`VALIDATION_ERROR`). If the chain provider cannot supply the
latest block the response is `503 UPSTREAM_UNAVAILABLE` (retryable) and no
intent is created.

### `GET /v1/payment-intents/:id`

Returns the persisted state in the same shape (`200`), `404 INTENT_NOT_FOUND`
for an unknown ID, or `400 VALIDATION_ERROR` for a malformed one. No chain
access happens on read; reconciliation is a separate, caller-triggered step
(later milestone).

### `POST /v1/payment-intents/:id/reconcile`

Caller-triggered reconciliation. Settle reads the latest Base block, discovers
native USDC transfers to `recipient` (from `payer` when declared) in
`[startBlock, latestBlock]` through the Alchemy Transfers API, verifies each
one from its canonical transaction receipt (decoded `Transfer` logs — never
the API's summary values), computes confirmation depth (`latest − block + 1`),
persists the evidence idempotently and returns the updated intent:

```sh
curl -i -X POST https://<deployment>/v1/payment-intents/pi_.../reconcile
```

```json
{
  "id": "pi_...",
  "status": "paid",
  "externalReference": "INV-204",
  "chain": "base",
  "asset": "USDC",
  "expectedAmount": "25.00",
  "receivedAmount": "25.00",
  "remainingAmount": "0.00",
  "recipient": "0x...",
  "payer": "0x...",
  "requiredConfirmations": 3,
  "matchConfidence": "exact_payer",
  "paidAt": "2026-09-17T22:43:17.000Z",
  "createdAt": "...",
  "expiresAt": "..."
}
```

Statuses, in precedence order (`ARCHITECTURE.md` §7.4):

| Status | Condition |
| --- | --- |
| `ambiguous` | no declared payer and transfers from two or more senders; nothing is counted |
| `overpaid` | confirmed total > expected |
| `paid` | confirmed total = expected |
| `partial` | 0 < confirmed total < expected, and not conclusively expired |
| `detected` | evidence exists but none is confirmed yet, and not conclusively expired |
| `expired` | expiry boundary passed, confirmed total short, and even the not-yet-confirmed in-window evidence could not satisfy it |
| `pending` | nothing observed |

Confirmed means `latestBlock − blockNumber + 1 ≥ requiredConfirmations`.
`receivedAmount` sums confirmed matched transfers; `detectedAmount` sums all
matched transfers. `paidAt` is the block timestamp of the transfer that first
brought the confirmed total to the expected amount (also for `overpaid`).

Window: `[startBlock, latestBlock]` until `expiresAt`; afterwards the greatest
Base block with `timestamp ≤ expiresAt` is found by binary search, persisted
once, and becomes the end of the window. A transfer mined before expiry may
still confirm after it. `matchConfidence` is `exact_payer` for a declared
payer, `single_sender` when every in-window transfer comes from one sender,
`ambiguous` for several senders, `none` without evidence.

Each reconcile is a complete canonical scan of the window: evidence is keyed by
`(intent, txHash, logIndex)`, amounts are recomputed (never incremented),
previously stored evidence inside the window that is no longer observed is
marked `orphaned` and stops counting, and a stored transfer re-observed in a
different block takes the newest block details. A failed provider call returns
`503 UPSTREAM_UNAVAILABLE` and changes nothing — it never orphans evidence.

### `GET /v1/payment-intents/:id/evidence`

Persisted evidence in canonical order `(blockNumber, logIndex, txHash)`,
keyset-paginated (`limit` 1–100, default 50; opaque `cursor`):

```sh
curl "https://<deployment>/v1/payment-intents/pi_.../evidence?limit=50"
```

```json
{
  "evidence": [
    {
      "transactionHash": "0x7db45d69dbb848f50002285f04946b2004388f6823d6ecd3387276141561b0f5",
      "logIndex": 4,
      "blockNumber": "51447828",
      "from": "0x498581fF718922c3f8e6A244956aF099B2652b2b",
      "to": "0x03468a6A40940E4C54d8b9D8433F7aBf0481A2Bc",
      "amount": "20710.876899",
      "confirmations": 25,
      "blockTimestamp": "2026-09-17T22:43:23.000Z",
      "association": "matched"
    }
  ],
  "nextCursor": null
}
```

`blockNumber` is a decimal string; `confirmations` are as observed at the last
accepted reconciliation. `association` is `matched` (counts toward totals),
`candidate` (seen for an `ambiguous` payer-less intent; never counted) or
`orphaned` (no longer canonical; never counted).

### `GET /health`

```sh
curl -i https://<deployment>/health
```

```json
{
  "status": "ok",
  "service": "settle",
  "environment": "production",
  "commit": "<exact 40-character git commit SHA>",
  "timestamp": "2026-09-17T14:31:02.000Z"
}
```

`commit` is the deployed `VERCEL_GIT_COMMIT_SHA`; it is `null` when running
outside a Vercel deployment. `environment` is `production`, `preview`,
`development`, or `test`.

### `GET /.well-known/xagent-verification.json`

The X-Agent MCP Hackathon deployment proof:

```sh
curl -i https://<deployment>/.well-known/xagent-verification.json
```

```json
{
  "schemaVersion": 1,
  "slug": "modolu-settle",
  "commit": "<exact 40-character git commit SHA>"
}
```

Exactly these three fields. `slug` is Settle's registered hackathon slug; the
deployment variable `XAGENT_SLUG` must be set to `modolu-settle` and any other
value is a configuration error. `commit` is the same validated
`VERCEL_GIT_COMMIT_SHA` (40 lowercase hex characters) that `/health` reports —
one source for both routes, no fallback. If the slug or commit is missing or
malformed the route returns `500` with the error envelope below rather than
fabricated evidence. The shape lives only in `src/lib/xagent-verification.ts`.

### Response conventions

- Every response carries an `X-Request-Id` header. A client may supply its own
  (8–64 characters of `[A-Za-z0-9_-]`); otherwise one is generated.
- Errors use one stable envelope:

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "Server configuration is invalid",
    "retryable": false
  }
}
```

Stable codes and HTTP statuses are listed in `ARCHITECTURE.md` §9 and
implemented in `src/lib/errors.ts`.

## Configuration

All environment variables are validated once in `src/lib/config.ts`; see
[`.env.example`](./.env.example) for the full list. Chain ID (8453), the native
USDC contract (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`), decimals (6),
confirmation defaults/bounds (3, `1..64`), the 7-day expiry limit and the 16 KiB
body limit are code constants in `src/domain/payment-intent.ts`.

Money is exact everywhere: API decimal strings ⇄ `bigint` token units in the
domain ⇄ `numeric(78,0)` in PostgreSQL. JavaScript `number` is never used for
amounts.

## Production security

Settle is a public, read-only API. The controls below are code constants or
platform configuration — none of them is tunable through request input or an
environment variable.

- **Capability IDs.** Every intent ID is `pi_` + 192 bits of cryptographic
  randomness. Possession of the ID is the only access control in v1; there is
  no endpoint that lists intents (`GET /v1/payment-intents` is 405), malformed
  IDs are rejected before any database access, and logs carry only an ID prefix.
- **Bounded input.** JSON bodies are limited to 16 KiB, enforced while the body
  streams (a missing or false `Content-Length` cannot bypass it); reconcile
  takes no body at all. Amount ≤ 30 integer digits and 6 decimals, expiry ≤ 7
  days, `requiredConfirmations` 1–64, `externalReference` ≤ 128 characters,
  unknown fields rejected, chain/asset fixed to Base / native USDC.
- **Failure safety.** A provider timeout, HTTP/JSON-RPC failure, malformed
  response, block-lookup failure or database error never changes payment
  state or evidence: provider calls happen before the database transaction,
  the transaction is all-or-nothing under a row lock, and a failed scan is
  never read as canonical absence. Upstream failures return
  `UPSTREAM_UNAVAILABLE` / `UPSTREAM_INVALID_RESPONSE`, never "no payment".
- **Secrets.** `DATABASE_URL`, `DATABASE_URL_UNPOOLED` and
  `ALCHEMY_BASE_RPC_URL` are server-only (no `NEXT_PUBLIC_*`), the provider
  adapter never re-throws raw viem errors, and the logger redacts URL
  credentials, provider key paths, `*_URL=`-style assignments and database
  query parameters from every line. Settle holds no private keys and never
  signs or sends a transaction.
- **Headers.** Every response carries `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and a restrictive
  `Permissions-Policy`; `X-Powered-By` is removed. HTML pages get a
  per-request nonce Content Security Policy (`src/proxy.ts`):
  `default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic';
  style-src 'self' 'nonce-…'; img-src 'self' data:; font-src 'self';
  connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self';
  frame-ancestors 'none'` (development adds `'unsafe-eval'` only).
- **CORS.** None. The demo UI is same-origin and agents call the API
  server-to-server, which needs no CORS. No `Access-Control-Allow-Origin`
  header is ever sent.
- **Caching.** All API, health and verification responses are
  `Cache-Control: no-store`; pages are rendered per request.
- **Runtime.** Node.js 24 (`engines.node`), Next.js Node runtime only.

### Vercel Firewall rate limits (required before production submission)

Rate limiting is applied by the Vercel Firewall, not by application code, and
it cannot be expressed in `vercel.json` (which only supports `deny` and
`challenge` mitigations). Create these three **Custom Rules** in the project
dashboard (Firewall → Configure → New Rule), in this order, each keyed by
**IP address** over a **60-second** window with the follow-up action
**Deny (429)**:

| Rule | Condition | Limit |
| --- | --- | --- |
| Create intents | Request path starts with `/v1/payment-intents` **and** method is `POST` **and** path does not contain `/reconcile` | 10 requests / minute / IP |
| Reconcile | Request path matches `/v1/payment-intents/*/reconcile` **and** method is `POST` | 30 requests / minute / IP |
| All API traffic | Request path starts with `/v1/` | 60 requests / minute / IP |

Stage each rule with the *Log* action first, then switch to *Deny*. The
application still enforces its semantic bounds (body size, expiry,
confirmations) even if the firewall is misconfigured.

## Deployment (Vercel)

One Vercel project, framework preset Next.js, Node.js 24 (selected from
`package.json` `engines.node`). Set `DATABASE_URL`, `DATABASE_URL_UNPOOLED`,
`ALCHEMY_BASE_RPC_URL` and `XAGENT_SLUG` per environment (previews must never
point at the production database); `VERCEL_ENV` and `VERCEL_GIT_COMMIT_SHA`
are provided by the platform. For schema-changing commits run `pnpm db:migrate`
against the target database before promoting the deployment. After each deploy verify `/health` reports the reviewed commit and
`/.well-known/xagent-verification.json` returns `200` with the same commit.
