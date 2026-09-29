# Verification

Live deployment: **https://arcwaypay.xyz**
Commit this submission describes: `d9f1108bf28255ce436aa74212ccae6313d71ee4`

Production runs in **live mode**. The capability endpoint requires an API key and moves real testnet USDC on Arc. Steps 1–3 need no key. The primary credential-free way to exercise the capability itself is local mock mode (step 4), which needs no key at all.

---

## 1. Health check — confirms the deployment matches this submission

```bash
curl -s https://arcwaypay.xyz/api/health
# -> {"status":"ok","commit":"d9f1108bf28255ce436aa74212ccae6313d71ee4"}
```

If `commit` differs, it is because documentation was updated after this commit. Any later commits on `main` are documentation-only; no application code changed.

## 2. X-Agent verification file

```bash
curl -s https://arcwaypay.xyz/.well-known/xagent-verification.json
# -> {"schemaVersion":1,"slug":"agada-arcway-pay","commit":"<same sha as step 1>"}
```

## 3. Capability schema (self-describing)

```bash
curl -s https://arcwaypay.xyz/api/capability/pay-by-email
```

Returns the capability's JSON input/output schema.

**Note:** this schema does not currently document the authentication requirement — see step 5. That's a gap in the schema, not in the endpoint.

## 4. Call the capability without credentials — local mock mode

Mock mode needs no Circle, Privy or Resend credentials and **no API key**. Transfers are simulated; everything else is the real code path. **Postgres is required** — it is the one external dependency.

```bash
git clone https://github.com/Tonylex18/arcway-pay.git
cd arcway-pay/source
npm install
cp .env.example .env.local
```

Add to `.env.local`:

```
DATABASE_URL="postgresql://USER:PASS@localhost:5432/arcway"
DIRECT_URL="postgresql://USER:PASS@localhost:5432/arcway"
```

No Postgres to hand:

```bash
docker run -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
```

Then:

```bash
npm run db:deploy
npm run dev
```

In mock mode the API key is ignored, so this works with no key at all:

```bash
curl -s -X POST http://localhost:3000/api/capability/pay-by-email \
  -H "Content-Type: application/json" \
  -d '{"payeeName":"Ada Lovelace","payeeEmail":"ada@example.com","amountUsdc":50}'
# -> {"status":"sent","payeeId":"…","walletAddress":"0x…","transferId":"mock_…"}
```

Roughly 15% of mock calls return HTTP 200 with `"status":"failed"` and a simulated network error. That is deliberate — it means failure handling is exercised rather than assumed. Retry with a different email.

The employer dashboard at `/dashboard` requires Privy and will report that sign-in isn't configured. The capability endpoint is the part that runs credential-free.

## 5. Call the live capability — scoped key, on request

Requires an API key. A scoped reviewer key (0.5 USDC per payout, 6 req/min, own company, revocable) is available on request through the program's private review channel — contact anthonyagada2000@gmail.com.

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

`status` is normally `"pending"`. The endpoint checks Circle once and returns; Arc settles a moment later. Pending means *submitted*, not *uncertain*.

Calling again with the same `payeeEmail` reuses that payee's existing wallet rather than provisioning a new one.

## 6. Confirm the money actually moved — on chain

Take `walletAddress` from the step 5 response:

```
https://testnet.arcscan.app/address/<walletAddress>
```

You will see an incoming USDC transfer from the treasury at `0x98c0159314014953a5b91d566daeba3fc427f8a0`, usually within a few seconds.

**Do not look up `transferId` on the explorer** — it is Circle's internal transfer identifier, not a chain hash. The address view above is the correct way to verify settlement.

The chain is the source of truth here for a reason: agent-initiated payouts are not settled by a background job. Their status in the application's own ledger — and the payee's notification email — updates only when an employer opens that run's receipt page, so until then they stay `pending` even though the USDC has landed on chain. That limitation is documented in [SUBMISSION.md](../SUBMISSION.md#known-limits).

## 7. Check the auth model holds

```bash
# No key -> 401
curl -s -X POST https://arcwaypay.xyz/api/capability/pay-by-email \
  -H "Content-Type: application/json" \
  -d '{"payeeName":"Ada","payeeEmail":"ada.demo@example.com","amountUsdc":0.25}'

# Over the cap -> 403, no payout recorded, no money moved (the key's counter and last-used time do update)
curl -s -X POST https://arcwaypay.xyz/api/capability/pay-by-email \
  -H "Authorization: Bearer <reviewer-key>" \
  -H "Content-Type: application/json" \
  -d '{"payeeName":"Ada","payeeEmail":"ada.demo@example.com","amountUsdc":5}'

# More than 6 calls in a minute -> 429 with Retry-After
```

Every 401 returns byte-identical output whether the key is absent, malformed, unknown or revoked — nothing leaks about whether a company or key exists.
