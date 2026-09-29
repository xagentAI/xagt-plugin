# Arcway — Submission

**Stablecoin payroll on Arc. Pay a contractor with their email address; they receive USDC in a wallet only they control.**

Live: **https://arcwaypay.xyz**
Repo: https://github.com/Tonylex18/arcway-pay
Chain: Arc testnet (chainId `5042002`) · Explorer: https://testnet.arcscan.app
Commit this submission describes: `d9f1108bf28255ce436aa74212ccae6313d71ee4`
*(Any later commits on `main` are documentation-only.)*

---

## The problem

Paying a contractor across a border means a bank intermediary, three to five days, and fees that fall hardest on the smallest payments. Paying them in crypto usually means asking a non-technical person to create a wallet, safeguard a seed phrase, and hold a second token for gas before they can touch their own money.

Arcway removes both. An employer adds someone by name and email. A wallet is provisioned for them silently. When the run is sent, USDC settles on Arc in about a second, and the recipient signs in with the same email they already use — no seed phrase, no gas token, no prior crypto knowledge.

The reason it works on Arc specifically: **USDC is the native gas token.** On a general-purpose chain a freshly-paid contractor holds money they cannot move until someone sends them ETH. On Arc, being paid is sufficient — they can sign a withdrawal the moment funds arrive, out of the same balance.

---

## Verify it

### Without credentials — local mock mode

This is the primary credential-free way to exercise the capability: no Circle, Privy or Resend keys, and **no API key**. Transfers are simulated; everything else is the real code path.

```bash
git clone https://github.com/Tonylex18/arcway-pay.git
cd arcway-pay/source
npm install
cp .env.example .env.local
```

Add a Postgres connection to `.env.local` — this is the only requirement:

```
DATABASE_URL="postgresql://USER:PASS@localhost:5432/arcway"
DIRECT_URL="postgresql://USER:PASS@localhost:5432/arcway"
```

(No Postgres handy? `docker run -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16`)

```bash
npm run db:deploy
npm run dev
```

Then, with **no API key at all** — mock mode ignores auth:

```bash
curl -s -X POST http://localhost:3000/api/capability/pay-by-email \
  -H "Content-Type: application/json" \
  -d '{"payeeName":"Ada Lovelace","payeeEmail":"ada@example.com","amountUsdc":50}'
```

You will get `{"status":"sent", …, "transferId":"mock_…"}`. Roughly 15% of mock calls return a simulated failure on purpose, so that failure handling is exercised rather than assumed. The employer dashboard requires Privy and will report that sign-in isn't configured.

### Against the live deployment — scoped key, on request

Production runs in **live mode** and moves real testnet USDC on Arc. It requires an API key: a scoped reviewer key (0.5 USDC per payout, 6 req/min, own company, revocable) is available on request through the program's private review channel — contact anthonyagada2000@gmail.com.

```bash
curl -s -X POST https://arcwaypay.xyz/api/capability/pay-by-email \
  -H "Authorization: Bearer <reviewer-key>" \
  -H "Content-Type: application/json" \
  -d '{"payeeName":"Ada Lovelace","payeeEmail":"ada.demo@example.com","amountUsdc":0.25}' \
  -w '\nHTTP %{http_code}\n'
```

Expected:

```json
{"status":"pending","payeeId":"c…","walletAddress":"0x…","transferId":"<uuid>"}
HTTP 200
```

**To confirm the money actually moved**, take `walletAddress` from the response and open:

```
https://testnet.arcscan.app/address/<walletAddress>
```

Within a few seconds you will see an incoming USDC transfer from the treasury at `0x98c0159314014953a5b91d566daeba3fc427f8a0`.

Two notes so you are not misled:

- `status` is almost always `"pending"`. The endpoint checks Circle once and returns; Arc settles a moment later. Pending here means *submitted*, not *uncertain*.
- **Do not look up `transferId` on the explorer.** It is Circle's internal transfer identifier, not a chain hash. The `walletAddress` view above is the correct way to verify.

### Error responses

| Case | Status | Body |
|---|---|---|
| No key, wrong scheme, unknown or revoked key | 401 | `{"status":"failed","errorMessage":"A valid API key is required. Send it as: Authorization: Bearer ark_…"}` |
| Rate limited | 429 + `Retry-After` | `{"status":"failed","errorMessage":"Rate limit exceeded for this key (6/min). Retry in 55s."}` |
| Over the per-payout cap | 403 | `{"status":"failed","errorMessage":"This key is limited to 0.5 USDC per payout."}` |
| Malformed JSON | 400 | `{"error":"Invalid JSON body."}` |
| Validation | 400 | `{"error":"payeeName is required."}` etc. |
| Circle refuses the transfer | 502 | `{"status":"failed","payeeId":"…","walletAddress":"0x…","errorMessage":"…"}` |

Every 401 returns byte-identical output regardless of which failure occurred, so nothing leaks about whether a company or key exists.

---

## Architecture

**Employer** signs in with email (Privy), adds payees, and reviews a run before anything moves — totals, balance-after, and a flag on anyone who hasn't yet claimed their wallet. On confirm, Circle's developer-controlled wallet API transfers USDC to each payee on Arc. The receipt shows the network fee actually paid, read from the transaction on chain rather than stored on the payout.

**Payee** receives an email from Arcway naming the employer, signs in with that address, and sees their balance read directly from the chain. Withdrawal is signed **in their browser** by their Privy embedded wallet. The server holds no signing authority over payee funds and cannot move them — which is what makes "this wallet is yours" a true statement rather than a marketing one. The server's only role is to record the transaction hash after the broadcast has already succeeded.

**Agents** call `POST /api/capability/pay-by-email` with a scoped API key. Keys are SHA-256 hashed at rest, shown once at creation, revocable, rate-limited per key, and resolve to exactly one company. Every read and write of company-owned data is scoped to the caller's company; payee and payout updates in the store key on `{id, companyId}`.

Stack: Next.js 16 · TypeScript · Postgres (Neon) · Prisma · Circle Developer-Controlled Wallets · Privy · viem · Resend · Vercel.

---

## Known limits

These are boundaries we chose knowingly, not defects we haven't found.

**One shared treasury.** Database tenancy is fully enforced — every payee, payout and run is scoped by `companyId`. Treasury *funds* are not yet partitioned: all companies draw on a single Circle wallet. Per-company wallets, provisioned at signup with their own deposit address, are the next change.

**Agent payouts don't send email on demand.** The capability endpoint never sends mail itself: a public API key that could emit mail to arbitrary addresses under the deployment's sending domain would be a spam vector.

**Agent payouts don't settle in the ledger on their own.** Agent-initiated payouts are not settled by a background job. A run's status — and the payee's notification email — updates when an employer opens that run's receipt page, which polls until the transfer settles. So a payout made through the API for an employer who never opens their dashboard stays `pending` in the ledger even though the USDC has landed on chain. Verify agent payouts on the explorer rather than in the app. The effect is that a public API key cannot emit mail to arbitrary addresses on demand, which is deliberate.

**The rate limiter is a fixed window and is not concurrency-safe.** Sequential calls are capped at 6 per minute within a window; because the window is fixed, a caller can make up to 12 in about 61 seconds across a boundary. The limiter also fails open when the database is unreachable. Simultaneous calls can exceed the cap. It's abuse-mitigation, not a hard guarantee — which is why the reviewer key is capped at 0.5 USDC per payout.

---

## What was verified, and how

Claims here were checked against the live deployment and the chain, not against the application's own reporting:

- Real USDC settlement confirmed by reading `balanceOf` on the payee's wallet and the transaction receipt status from the Arc RPC — not by trusting Circle's API response.
- Tenant isolation was proven at the store layer across 16 checks (`scripts/isolation-check.mts`). The script predates the payout-run change and no longer compiles against the current `createPayout` signature — the checks passed when written at `245547b` and the script has not been maintained since.
- Auth failure modes verified byte-identical across five distinct causes.
- The rate limiter verified by a burst designed so at least one refusal was guaranteed regardless of window timing, after an earlier timing-dependent test nearly produced a false pass in both directions.
- Withdrawal gas is estimated against the live chain for each transaction — `estimateGas` × current fee data × a 1.25 margin — rather than a fixed constant; the original constant was roughly 8× the real fee and would have made the Max button wrong. The fee recorded on the withdrawal is that padded estimate, not the amount finally paid.

---

Built by Agada Anthony Alex — [portfolio](https://portfolio-clue.vercel.app) · [GitHub](https://github.com/Tonylex18)
