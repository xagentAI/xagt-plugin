# Verification evidence

## Prerequisites

- Review commit: b460b88ce800839e69839a5d31aac949dfe2543c
- API base URL: https://safegate-xagent-commerce-outcome.vercel.app/v1
- Authentication: none for the public API, health, and deployment-proof endpoints.
- The successful real-commerce review attestation is intentionally not committed because it contains production commerce identifiers. It can be supplied through an approved private review channel if required.

## 1. Health check

```bash
curl --fail --silent --show-error https://safegate-xagent-commerce-outcome.vercel.app/health
```

Expected response:

```json
{"status":"ok","commit":"b460b88ce800839e69839a5d31aac949dfe2543c"}
```

Verified against production: PASS.

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://safegate-xagent-commerce-outcome.vercel.app/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"nurexen-safegate-commerce-outcome","commit":"b460b88ce800839e69839a5d31aac949dfe2543c"}
```

Verified against production: PASS.

## 3. Real capability call

With the SafeGate-signed review attestation stored locally as review-attestation.json:

```bash
curl --fail --silent --show-error --request POST https://safegate-xagent-commerce-outcome.vercel.app/v1/commerce-outcome --header "content-type: application/json" --data-binary @review-attestation.json
```

The production verification call has been executed successfully against a completed Base Mainnet USDC commerce event.

Expected redacted success fields:

```text
ok=true
outcome=COMMERCE_VERIFIED
payment_status=PAYMENT_VERIFIED
attestation_status=VALID
fulfillment_status=FULFILLMENT_COMPLETED
evidence_status=EVIDENCE_CREATED
side_effects=none
```

Verified against production: PASS.

The real production attestation fixture and its commerce identifiers are intentionally excluded from the public submission package.

## 4. Safe failure behavior

```bash
curl --silent --show-error --request POST https://safegate-xagent-commerce-outcome.vercel.app/v1/commerce-outcome --header "content-type: application/json" --data '{"foo":"bar"}'
```

Expected behavior:

- HTTP 400.
- ok=false with a deterministic verification error.
- No payment, wallet, fulfillment, evidence, or other state-changing side effect.

## 5. Offline verification

```bash
cd source
npm run check
npm test
```

Validated tests:

- COMMERCE_OUTCOME_CONTRACT_TEST=PASS
- BASE_USDC_RECEIPT_TEST=PASS
- ATTESTATION_VERIFIER_TEST=PASS
- TAMPER_DETECTION_TEST=PASS

The public synthetic signed fixture used by offline verification is included at source/verification/sample-synthetic-attestation.json.
