# Arcway — Build Plan (scaffold → real product)

This is the working spec for taking Arcway from hackathon scaffold to a real,
deployed, multi-tenant product. Work through it in phase order. Each phase has
a **Done when** gate — don't start the next phase until the current one passes.

---

## Context you need before writing code

**What Arcway is:** a B2B cross-border payout tool. A company adds payees by
email; each payee is automatically provisioned a Privy embedded wallet; the
company sends them USDC via Circle. Payees claim their wallet by logging in
with the same email, then hold, transfer, or off-ramp the funds.

**One hackathon submission ships from this codebase:**

| | Event | Deadline | What it needs from the code |
|---|---|---|---|
| 1 | X-Agent AI MCP Hackathon | **Sept 19** | The agent-callable capability `POST /api/capability/pay-by-email`, plus two verification endpoints. Reviewed Sept 20–Oct 1. |

The human-facing product (company dashboard + payee claim flow) ships from the
same codebase, so target feature-complete by ~Sept 14.

### Non-negotiables — do not break these

These are already submitted or committed to. Changing their shape breaks a
hackathon submission:

1. `GET /api/health` → `{"status":"ok","commit":"<40-char sha>"}`
2. `GET /.well-known/xagent-verification.json` → `{"schemaVersion":1,"slug":"agada-arcway-pay","commit":"<40-char sha>"}`
3. `POST /api/capability/pay-by-email` — request `{payeeName, payeeEmail, amountUsdc}`,
   response `{status, payeeId, walletAddress, transferId, errorMessage?}`.
   You may **add** optional fields; do not rename or remove existing ones.
4. `GET /api/capability/pay-by-email` must keep returning the capability's JSON schema.

### Keep mock mode as a fallback — but remove the demo bypass

Mock mode (in `lib/privy.ts` and `lib/circle.ts`) exists so X-Agent reviewers can
call the endpoint during their review window without depending on a funded Circle
sandbox treasury. **Keep it**, keep it clearly labeled in responses, and make live
mode take precedence whenever credentials are present.

What to *remove* is the demo theater: the public "View demo dashboard" link that
bypasses login, and unauthenticated access to `/dashboard`.

### Working rules

- This is **Next.js 16** — App Router, and it differs from older Next.js you may
  have patterns for. Read `node_modules/next/dist/docs/` before assuming an API.
- **Do not guess at Privy or Circle SDK surfaces.** Both evolve. Read the actual
  installed type definitions in `node_modules/@privy-io/*/` and the Circle SDK
  package before calling a method. The existing code has comments where the shape
  was uncertain — verify those rather than propagating them.
- Never commit secrets. Everything sensitive goes in `.env.local` (gitignored) and
  is documented in `.env.example`.
- `npm run build` and `npm run lint` must both pass before any phase is "done."
- Small commits, one concern each.

---

## Phase 0 — Postgres (blocking; do this first)

**Why first:** `lib/store.ts` writes to a JSON file. Vercel's filesystem is
read-only apart from `/tmp`, which isn't shared across invocations or persisted.
**The app as it stands cannot work deployed.** Everything else depends on fixing this.

- Add Prisma + Postgres (Neon, Supabase, or Vercel Postgres — free tiers all fine).
- Model the schema from Phase 1 below in one go, so you migrate once rather than twice.
- Reimplement `lib/store.ts`'s exported functions against Prisma, keeping the same
  function signatures so callers don't change. `lib/types.ts` was written to map
  1:1 to Prisma models — use it.
- Delete `data/payees.json` and its handling.

**Done when:** the app runs locally against a real Postgres database, `npm run build`
passes, and adding a payee through the dashboard persists across a server restart.

---

## Phase 1 — Auth and multi-tenancy (security foundation)

Right now **no API route verifies anything**. Anyone who knows the URL can add
payees and trigger payouts. In mock mode that's harmless; the moment real Circle
credentials are wired, `/api/payouts` becomes an unauthenticated endpoint that
drains a treasury. This phase closes that.

### Schema

```
Company   id, name, createdAt
User      id, privyUserId (unique), email (unique), companyId?, role, createdAt
          role: EMPLOYER | PAYEE
Payee     id, companyId (FK, required), name, email, amountUsdc, walletAddress,
          privyUserId?, status, transferId?, failureReason?, createdAt, updatedAt
          unique on (companyId, email)
```

### Work

- `lib/auth.ts`: verify the Privy access token server-side with
  `@privy-io/server-auth`'s `verifyAuthToken`. Export a helper that takes a
  `Request` and returns `{ user, company }` or throws a 401.
- Guard **every** `/api/*` route with it (except `/api/health` and the
  `.well-known` file, which are intentionally public — and the capability
  endpoint, which gets its own scheme in Phase 4).
- Scope every payee query by `companyId`. Company A must never see Company B's data.
- On an employer's first login, create their `Company` + `User` records.
- Protect the `/dashboard` route itself — redirect unauthenticated visitors to `/`.
- Remove the "View demo dashboard" bypass link from the landing page.

**Done when:** logging in as two different companies shows two isolated payee lists,
and every API route returns 401 without a valid token. Prove it with `curl`.

---

## Phase 2 — Payee claim experience

This is the half of the product that doesn't exist yet, and the thing that makes
the pitch honest: right now money is sent to an address and the story stops.

- **Login routing:** one login button, two destinations. On successful auth, look
  up the email — if it matches a `Payee` row, send them to `/claim`; otherwise
  treat them as an employer and send them to `/dashboard`.
- **`/claim` page:** payee sees who paid them, how much, the payout status, their
  wallet address, and their **live on-chain USDC balance** (read it from chain,
  don't trust the local DB).
- **Withdraw — send to an external address:** let the payee transfer their USDC to
  any address they choose, signing with their Privy embedded wallet. This is the
  minimum viable "it's really their money" proof, and it's fully buildable.
- **Withdraw — fiat off-ramp:** do **not** build this. Integrating a provider
  (Eversend, Yellow Card, Grey) requires a commercial agreement and recipient KYC.
  Instead put a clearly-labeled "Cash out to bank (coming soon)" state in the UI
  and document the intended integration in the README, naming the provider and the
  real constraint (KYC is required by AML law, not a product choice).

**Done when:** you can add a payee as Company A, pay them, log out, log back in as
that payee's email, see the balance, and move it to another address.

---

## Phase 3 — Real Circle integration

Replace the hand-rolled `fetch` calls in `lib/circle.ts` with Circle's official
SDK, `@circle-fin/developer-controlled-wallets` — it handles entity-secret
encryption and request signing, which you do not want to implement by hand.

- Create a developer-controlled treasury wallet; fund it from Circle's sandbox faucet.
- Set the correct USDC `tokenId` for your target chain (Arc testnet if available in
  your console; otherwise a supported EVM testnet — document which one you used).
- Use idempotency keys on every transfer so retries are safe.
- Replace the in-request status polling in `/api/payouts` with Circle **webhooks**
  where practical; if you keep polling, move it out of the request path.
- Keep the mock fallback intact and clearly labeled when credentials are absent.

**Done when:** a real sandbox USDC transfer lands in a payee's Privy wallet and the
balance shown on `/claim` reflects it.

---

## Phase 4 — Agent authentication (for the X-Agent submission)

The capability endpoint can't use Privy sessions — an agent can't complete an
interactive email login. It needs a service credential.

- Add an `ApiKey` model: `id, companyId, hashedKey, label, lastUsedAt, createdAt`.
  Store a hash, never the raw key. Show the raw key exactly once at creation.
- Accept `Authorization: Bearer ark_...` on `POST /api/capability/pay-by-email`,
  resolve it to a company, and scope the payout to that company.
- Add basic rate limiting.
- Add key management to the dashboard: create, label, revoke.
- **Reviewer access:** X-Agent reviewers must be able to call the endpoint. Either
  ship a documented review key in `verification/README.md` that only works in mock
  mode, or allow unauthenticated calls when Circle credentials are absent (mock
  mode) and require a key when live. Whichever you choose, state it explicitly in
  `SUBMISSION.md` — an endpoint reviewers can't call fails a hard gate.

**Done when:** an authenticated `curl` with a Bearer key executes a payout scoped
to the right company, and an unauthenticated live-mode call is rejected.

---

## Phase 5 — Ship

- Deploy to Vercel with the Postgres connection string and all Privy/Circle env vars set.
- Confirm `/api/health` and `/.well-known/xagent-verification.json` return the **real**
  deployed commit SHA (Vercel injects `VERCEL_GIT_COMMIT_SHA` automatically — see `lib/commit.ts`).
- Fill in `deployedUrl` and `commit` in the X-Agent `submission.json`, and the
  `<DEPLOYED_URL>` placeholders in `verification/README.md`.
- Record a 2–3 minute demo video: add a payee → pay them → log in as the payee →
  see the balance → withdraw. That full loop is the story; don't just show the dashboard.
- Update `README.md` to match what was actually built (it currently describes the scaffold).
- Open the X-Agent PR (Sept 19).

---

## Suggested schedule

| Days | Work |
|---|---|
| Sept 6–7 | Phase 0 (Postgres) |
| Sept 8–9 | Phase 1 (auth + multi-tenancy) |
| Sept 10–11 | Phase 2 (claim page + withdraw) |
| Sept 12–13 | Phase 3 (real Circle) |
| Sept 14 | Phase 4 (agent API keys) |
| Sept 15 | Phase 5 — deploy, demo video, README |
| Sept 16–18 | Buffer / polish |
| Sept 19 | **Open X-Agent PR** |

Buffer days are load-bearing — something in Phase 3 will take longer than planned,
because integrations always do. If you're behind, cut Phase 4's dashboard key
management UI (seed keys directly in the database instead) before cutting anything
in Phases 1–3.
