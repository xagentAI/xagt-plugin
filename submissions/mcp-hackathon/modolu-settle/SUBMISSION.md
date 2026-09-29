# Settle

> Payment truth for autonomous agents.

## Capability

- **One-line description:** An agent declares an expected native-USDC payment on Base, the payment happens independently, and Settle later reads the chain and returns a deterministic payment status (`pending`, `detected`, `partial`, `paid`, `overpaid`, `expired`, `ambiguous`) with transaction evidence the agent can act on.
- **Who it helps:** Agents and automated workflows that must gate an action (deliver a report, grant access, start a job, mark an invoice paid) on whether a specific USDC payment actually settled — without building block-log parsing, decimal handling, confirmation tracking and duplicate detection themselves.
- **Capability boundary:** Read-only reconciliation of native Circle USDC (`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) on Base mainnet (chain id 8453), triggered by the caller. Settle never holds private keys, never signs or sends a transaction, never custodies funds, and does not perform fraud detection, wallet-risk scoring, compliance analysis or security scanning. It only answers whether observed onchain evidence satisfies a declared obligation. Matching is conservative: with a declared payer, matching is exact; without one, a single unambiguous sender is required and multiple plausible senders yield `ambiguous` rather than a guess.

## Live API

- **API base URL:** https://settle-beige-seven.vercel.app/v1
- **Health-check URL:** https://settle-beige-seven.vercel.app/health
- **Authentication:** none for hackathon v1. Possession of the opaque payment-intent ID (`pi_` + 192 bits of cryptographic randomness) is the capability to read or reconcile that intent; there is no endpoint that lists intents.
- **Rate limits / known limits:** Vercel Firewall: 60 requests / minute / IP on `/v1/*` (HTTP 429 above that). Request bodies ≤ 16 KiB; intent lifetime ≤ 7 days; `requiredConfirmations` 1–64 (default 3); `externalReference` ≤ 128 characters; evidence pages ≤ 100 rows (cursor pagination). Reconciliation is caller-triggered and typically completes in 1–5 s (one block-number read, one paginated Alchemy Transfers API discovery over the intent's window, one transaction-receipt read per discovered transaction, one block-header read per distinct block; after expiry, a binary search of block headers resolves the expiry boundary once). Blockchain-provider failures return `503 UPSTREAM_UNAVAILABLE` (retryable) and never change payment state.
- **API contract:** Documented in `source/README.md` ("Public endpoints") with request/response examples; the stable error envelope is `{"error":{"code","message","retryable"}}` with codes `VALIDATION_ERROR`, `INVALID_ADDRESS`, `UNSUPPORTED_CHAIN`, `UNSUPPORTED_ASSET`, `INTENT_NOT_FOUND`, `RATE_LIMITED`, `UPSTREAM_UNAVAILABLE`, `UPSTREAM_INVALID_RESPONSE`, `INTERNAL_ERROR`.

Endpoints:

```text
POST /v1/payment-intents                  declare an expected payment → 201 intent resource
GET  /v1/payment-intents/:id              current persisted state
POST /v1/payment-intents/:id/reconcile    read Base, apply canonical evidence, return updated state
GET  /v1/payment-intents/:id/evidence     matched / candidate / orphaned transfers, cursor-paginated
GET  /health                              status + deployed commit
GET  /.well-known/xagent-verification.json
```

## Source and reproducibility

- **Source repository:** https://github.com/modolu/settle
- **Review commit:** `25e958fcecaeb4ad20760c5a94c93a4670fd2b77`
- **Source submitted in this PR:** `source/`
- **Run tests:** `pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build` (unit, service and jsdom UI tests; no credentials needed). Database integration tests: `TEST_DATABASE_URL=<postgres url> pnpm test tests/integration`. Browser smoke: `pnpm exec playwright install chromium && pnpm test:e2e` (intercepts the API with fixtures; no credentials needed).
- **Run locally:** `cp .env.example .env.local` (set `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `ALCHEMY_BASE_RPC_URL`, `XAGENT_SLUG=modolu-settle`), `pnpm db:migrate`, `pnpm dev` → http://localhost:3000. Node.js 24.x, pnpm 10 (pinned via `packageManager`).
- **Deploy:** One Vercel project (framework Next.js, Node.js 24.x selected from `package.json` `engines`), one Neon PostgreSQL database, one Alchemy Base mainnet RPC app. Set the four environment variables above in the Vercel Production environment, apply migrations once with `pnpm db:migrate` using `DATABASE_URL_UNPOOLED`, then deploy the reviewed commit (`vercel deploy --prod` or a push to `main`). Migrations never run at build time, at startup or in request handlers. Full steps: `source/README.md` ("Deployment (Vercel)" and "Production security").
- **Version binding:** Both `/health` and `/.well-known/xagent-verification.json` read the platform-provided `VERCEL_GIT_COMMIT_SHA` of the running deployment through one validated configuration value (40 lowercase hex characters); if it is missing or malformed the routes return `500` instead of a fabricated commit. No commit is hard-coded.

The API must expose:

```json
// GET https://settle-beige-seven.vercel.app/health
{"status":"ok","service":"settle","environment":"production","commit":"25e958fcecaeb4ad20760c5a94c93a4670fd2b77","timestamp":"<UTC ISO-8601>"}
```

```json
// GET /.well-known/xagent-verification.json on the same API origin
{"schemaVersion":1,"slug":"modolu-settle","commit":"25e958fcecaeb4ad20760c5a94c93a4670fd2b77"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `200` with `status: "ok"` and `commit` equal to the review commit above.
- **Capability call:** `POST /v1/payment-intents` with `{"chain":"base","asset":"USDC","amount":"25.00","recipient":"0x…","payer":"0x…","expiresAt":"<UTC ISO-8601 within 7 days>","requiredConfirmations":3}` → `201` intent resource with `status: "pending"`; then `POST /v1/payment-intents/:id/reconcile` returns the current deterministic status and `GET …/evidence` the supporting transfers. A real Base USDC payment reconciled through this deployment (intent `pi_T21YOW3UagzGPvC0_2CMttKpZyMU0Qv-`, transaction `0xe65d8e633386483953b904920075fe6133d8cee425f6c924826494086e84cd30`, `pending` → `paid`) is recorded with its responses in `verification/README.md` §4.
- **Expected error behavior:** invalid or unknown fields → `400 VALIDATION_ERROR`; bad address → `400 INVALID_ADDRESS`; other chain/asset → `400 UNSUPPORTED_CHAIN` / `UNSUPPORTED_ASSET`; unknown or malformed intent ID → `404 INTENT_NOT_FOUND` / `400 VALIDATION_ERROR`; provider outage or timeout → `503 UPSTREAM_UNAVAILABLE` with `retryable: true` and unchanged payment state; over the rate limit → `429`. Errors are always the JSON envelope, never HTML or raw provider/database errors.

## Security and data handling

- **Data collected:** Per intent: expected amount, recipient address, optional payer address, optional caller-supplied `externalReference` (≤ 128 characters, stored and rendered as plain text), expiry, required confirmations, and the public onchain transfer evidence observed for it (transaction hash, log index, block, sender, recipient, amount, block timestamp). Operational request IDs and reconciliation attempt metadata. No accounts, no personal data fields, no wallet secrets.
- **Purpose and retention:** Solely to reconcile the declared obligation and return evidence. Data is retained in the Neon database for the life of the hackathon deployment; there is no automatic deletion in v1 (documented limitation).
- **Third parties / outbound network calls:** Alchemy (Base mainnet JSON-RPC: `eth_blockNumber`, `alchemy_getAssetTransfers`, `eth_getTransactionReceipt`, `eth_getBlockByNumber`), Neon (PostgreSQL), Vercel (hosting, Firewall). The demo UI links to Basescan for transaction/address lookups; no other outbound calls.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required. The RPC URL and database URLs are server-only environment variables; provider errors are redacted before logging; no `NEXT_PUBLIC_*` secrets exist.
- **Known risks / restrictions:** Base block-depth confirmations only (no L1 finality model). Reorg handling marks evidence absent from a later complete scan as `orphaned` and recomputes state; a `paid` status can therefore regress if the chain does. Rate limiting is a single 60/min/IP firewall rule on the current Vercel plan. The Vercel-generated production hostname may be replaced by a custom domain later; the version-binding endpoints are relative to whichever origin serves the API.

## Support

- **Team / builder:** modolu
- **Contact:** GitHub https://github.com/modolu (issues on https://github.com/modolu/settle) · heritage143@gmail.com
- **License / rights:** Source is submitted under the terms in `RIGHTS.md`; the submitter authorizes review and archival as described there. Third-party dependencies are MIT/Apache-2.0 (listed in `RIGHTS.md`).
