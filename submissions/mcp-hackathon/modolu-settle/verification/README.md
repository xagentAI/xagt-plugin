# Verification evidence

## Prerequisites

- Review commit: `25e958fcecaeb4ad20760c5a94c93a4670fd2b77`
- API base URL: `https://settle-beige-seven.vercel.app/v1`
- Authentication: none. Every call below works anonymously; the only capability is the opaque `pi_…` intent ID returned by the create call, so keep it out of public logs if the intent is real.

All responses carry `X-Request-Id`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. Rate limit: 60 requests / minute / IP on `/v1/*` (HTTP 429 above that).

## 1. Health check

```bash
curl --fail --silent --show-error https://settle-beige-seven.vercel.app/health
```

Expected response (`timestamp` varies):

```json
{"status":"ok","service":"settle","environment":"production","commit":"25e958fcecaeb4ad20760c5a94c93a4670fd2b77","timestamp":"2026-09-18T12:00:00.000Z"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://settle-beige-seven.vercel.app/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"modolu-settle","commit":"25e958fcecaeb4ad20760c5a94c93a4670fd2b77"}
```

The `commit` values in steps 1 and 2 are the same platform-provided value; if either is unavailable the route answers `500 {"error":{"code":"INTERNAL_ERROR",…}}` rather than a fabricated commit.

## 3. Capability call

### 3a. Declare an expected payment

Use any Base addresses; the example below uses the native USDC contract as a stand-in recipient and a well-known public address as the payer. `expiresAt` must be a UTC timestamp between now and seven days out.

```bash
curl --fail --silent --show-error \
  --request POST https://settle-beige-seven.vercel.app/v1/payment-intents \
  --header "content-type: application/json" \
  --data '{
    "externalReference": "REVIEW-001",
    "chain": "base",
    "asset": "USDC",
    "amount": "25.00",
    "recipient": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "payer": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "expiresAt": "2026-09-25T00:00:00Z",
    "requiredConfirmations": 3
  }'
```

Expected success response (`201 Created`; `id`, `createdAt` vary):

```json
{"id":"pi_<32 url-safe characters>","status":"pending","externalReference":"REVIEW-001","chain":"base","asset":"USDC","expectedAmount":"25.00","receivedAmount":"0.00","remainingAmount":"25.00","recipient":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913","payer":"0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045","requiredConfirmations":3,"matchConfidence":"none","paidAt":null,"createdAt":"2026-09-18T12:00:00.000Z","expiresAt":"2026-09-25T00:00:00.000Z"}
```

The intent's matching window starts at the Base block after the latest block read at creation, so no earlier transfer can satisfy it.

### 3b. Read the persisted state

```bash
curl --fail --silent --show-error https://settle-beige-seven.vercel.app/v1/payment-intents/<id>
```

Returns the same resource shape with `200`.

### 3c. Reconcile against Base

```bash
curl --fail --silent --show-error --request POST \
  https://settle-beige-seven.vercel.app/v1/payment-intents/<id>/reconcile
```

Settle reads the latest Base block, discovers native-USDC transfers to the recipient (from the payer) inside the window through the Alchemy Transfers API, verifies each from its canonical transaction receipt (decoded `Transfer` logs), computes confirmation depth (`latest − block + 1`), applies the evidence atomically and returns the updated resource. With no payment sent, the response is the intent with `"status":"pending"`; after a matching transfer it becomes `detected` (under the confirmation threshold), then `paid` (or `partial` / `overpaid`), with `receivedAmount`, `remainingAmount`, `matchConfidence` and `paidAt` filled from onchain evidence. Repeated calls are idempotent: evidence is keyed by `(transaction hash, log index)` and totals are recomputed, never incremented.

### 3d. Evidence

```bash
curl --fail --silent --show-error \
  "https://settle-beige-seven.vercel.app/v1/payment-intents/<id>/evidence?limit=50"
```

Expected response before any payment:

```json
{"evidence":[],"nextCursor":null}
```

After a matching transfer, each row looks like:

```json
{"transactionHash":"0x<64 hex>","logIndex":4,"blockNumber":"51447828","from":"0x…","to":"0x…","amount":"25.00","confirmations":25,"blockTimestamp":"2026-09-17T22:43:23.000Z","association":"matched"}
```

`association` is `matched` (counts toward the obligation), `candidate` (seen for an ambiguous payer-less intent; never counted) or `orphaned` (no longer canonical; never counted).

### Safe error behavior

```bash
# unknown field → 400 VALIDATION_ERROR
curl --silent --request POST https://settle-beige-seven.vercel.app/v1/payment-intents \
  --header "content-type: application/json" \
  --data '{"chain":"base","asset":"USDC","amount":"1","recipient":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913","expiresAt":"2026-09-25T00:00:00Z","tokenAddress":"0x00"}'
# {"error":{"code":"VALIDATION_ERROR","message":"unknown field(s): tokenAddress","retryable":false}}

# other rail → 400 UNSUPPORTED_CHAIN
# bad address → 400 INVALID_ADDRESS
# unknown intent → 404 INTENT_NOT_FOUND
curl --silent https://settle-beige-seven.vercel.app/v1/payment-intents/pi_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
# {"error":{"code":"INTENT_NOT_FOUND","message":"Payment intent not found","retryable":false}}

# body over 16 KiB, wrong content type, or a body on /reconcile → 400 VALIDATION_ERROR
# blockchain provider unavailable → 503 {"error":{"code":"UPSTREAM_UNAVAILABLE","message":"Blockchain provider is temporarily unavailable","retryable":true}}
#   (payment state and evidence are left unchanged; retry later)
# more than 60 requests/minute from one IP on /v1/* → 429
```

## 4. Real payment evidence

A real native Base USDC payment was reconciled through this exact deployment (review commit `25e958fcecaeb4ad20760c5a94c93a4670fd2b77`, origin `https://settle-beige-seven.vercel.app`) on 2026-09-18. The payment was sent by the submitter from their own wallet, outside Settle; Settle never signs or sends transactions. Wallet addresses and the transaction hash below are public blockchain data.

- Intent ID: `pi_T21YOW3UagzGPvC0_2CMttKpZyMU0Qv-`
- External reference: `XAGENT-REAL-PROOF-20260918`
- Transaction: `0xe65d8e633386483953b904920075fe6133d8cee425f6c924826494086e84cd30` — https://basescan.org/tx/0xe65d8e633386483953b904920075fe6133d8cee425f6c924826494086e84cd30

### 4a. Intent creation (before the payment)

```bash
curl --fail --silent --show-error \
  --request POST https://settle-beige-seven.vercel.app/v1/payment-intents \
  --header "content-type: application/json" \
  --data '{"externalReference":"XAGENT-REAL-PROOF-20260918","chain":"base","asset":"USDC","amount":"0.10","recipient":"0x4d9247a33D713e05860E0f098bc2e45b2329e652","payer":"0x389b48BE5385B4d4F1c14FbacE6947695Bcfdf57","expiresAt":"2026-09-18T16:30:40Z","requiredConfirmations":3}'
```

Response `201 Created` (`X-Request-Id: req_taMh6cdi5xFQ9v2ITTUH3A`):

```json
{"id":"pi_T21YOW3UagzGPvC0_2CMttKpZyMU0Qv-","status":"pending","externalReference":"XAGENT-REAL-PROOF-20260918","chain":"base","asset":"USDC","expectedAmount":"0.10","receivedAmount":"0.00","remainingAmount":"0.10","recipient":"0x4d9247a33D713e05860E0f098bc2e45b2329e652","payer":"0x389b48BE5385B4d4F1c14FbacE6947695Bcfdf57","requiredConfirmations":3,"matchConfidence":"none","paidAt":null,"createdAt":"2026-09-18T14:30:43.132Z","expiresAt":"2026-09-18T16:30:40.000Z"}
```

### 4b. The payment

After the intent existed, the payer wallet sent exactly 0.10 native Circle USDC (contract `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) on Base mainnet to the recipient. It was mined in block `51476801` at `2026-09-18T14:49:09Z`.

### 4c. Reconciliation

```bash
curl --fail --silent --show-error --request POST \
  https://settle-beige-seven.vercel.app/v1/payment-intents/pi_T21YOW3UagzGPvC0_2CMttKpZyMU0Qv-/reconcile
```

The first reconciliation ran at `2026-09-18T14:52:17Z` (`X-Request-Id: req_ZzdHt5XA03OrhWThvNsZ2Q`). By then the transfer already had far more than the 3 required confirmations, so no intermediate `detected` state was observed; the response was directly `200`:

```json
{"id":"pi_T21YOW3UagzGPvC0_2CMttKpZyMU0Qv-","status":"paid","externalReference":"XAGENT-REAL-PROOF-20260918","chain":"base","asset":"USDC","expectedAmount":"0.10","receivedAmount":"0.10","remainingAmount":"0.00","recipient":"0x4d9247a33D713e05860E0f098bc2e45b2329e652","payer":"0x389b48BE5385B4d4F1c14FbacE6947695Bcfdf57","requiredConfirmations":3,"matchConfidence":"exact_payer","paidAt":"2026-09-18T14:49:09.000Z","createdAt":"2026-09-18T14:30:43.132Z","expiresAt":"2026-09-18T16:30:40.000Z"}
```

`paidAt` is the block timestamp of the transfer that satisfied the obligation, not the reconciliation time. A second `POST …/reconcile` returned the identical state with one evidence row (idempotent).

### 4d. Persisted state and evidence

```bash
curl --fail --silent --show-error https://settle-beige-seven.vercel.app/v1/payment-intents/pi_T21YOW3UagzGPvC0_2CMttKpZyMU0Qv-
curl --fail --silent --show-error https://settle-beige-seven.vercel.app/v1/payment-intents/pi_T21YOW3UagzGPvC0_2CMttKpZyMU0Qv-/evidence
```

`GET …/evidence` (`X-Request-Id: req_ldfi93wgEKRuIwenELfVIg`), `200`:

```json
{"evidence":[{"transactionHash":"0xe65d8e633386483953b904920075fe6133d8cee425f6c924826494086e84cd30","logIndex":125,"blockNumber":"51476801","from":"0x389b48BE5385B4d4F1c14FbacE6947695Bcfdf57","to":"0x4d9247a33D713e05860E0f098bc2e45b2329e652","amount":"0.10","confirmations":96,"blockTimestamp":"2026-09-18T14:49:09.000Z","association":"matched"}],"nextCursor":null}
```

`confirmations` is the depth observed at that reconciliation (`latest − 51476801 + 1`); a later reconcile reports a larger value. These endpoints remain publicly readable for this intent.

### 4e. Independent verification

Checked against Base mainnet through a public RPC that is not Settle's provider, and on BaseScan:

- network: Base mainnet (chain id 8453); transaction status: `success`
- block `51476801`, hash `0xeebfddf04a7bdbfbcdeda2c3a1561b840305124d1f42724de1c38e944bc7dac8`, timestamp `2026-09-18T14:49:09Z`
- exactly one `Transfer` log from contract `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (native Circle USDC), log index `125`, from `0x389b48BE5385B4d4F1c14FbacE6947695Bcfdf57` to `0x4d9247a33D713e05860E0f098bc2e45b2329e652`, value `100000` base units = `0.10` USDC

Every field of Settle's evidence row (hash, log index, block, sender, recipient, amount, block timestamp) matches the chain.
