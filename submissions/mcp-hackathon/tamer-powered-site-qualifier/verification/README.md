# Verification evidence

All calls below target the public reviewed deployment. The example site is fictional and non-confidential.

## Prerequisites

- Review commit: `b2fc190fad8705c89ca2f07b0d0cb19c8c6c75ee`
- API base URL: `https://qualifier.cryptoleaks.agency/v1`
- Authentication: None for the health, proof, unpaid qualification, and unpaid paid-boundary checks. Do not send payment credentials.

## 1. Root

```bash
curl --fail --silent --show-error --include https://qualifier.cryptoleaks.agency/
```

Expected: HTTP 200 with HTML for the interactive Powered-Site Qualifier browser UI.

## 2. Health

```bash
curl --fail --silent --show-error https://qualifier.cryptoleaks.agency/health
```

Expected response:

```json
{"status":"ok","commit":"b2fc190fad8705c89ca2f07b0d0cb19c8c6c75ee"}
```

## 3. Deployment proof

```bash
curl --fail --silent --show-error https://qualifier.cryptoleaks.agency/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"tamer-powered-site-qualifier","commit":"b2fc190fad8705c89ca2f07b0d0cb19c8c6c75ee"}
```

## 4. Real capability

```bash
curl --fail --silent --show-error \
  --request POST https://qualifier.cryptoleaks.agency/v1/qualify \
  --header 'content-type: application/json' \
  --data @source/examples/site-ready.json
```

Expected: HTTP 200, Bitcoin Mining Readiness `100`, AI/Data Center Readiness `100`, classification `READY`, no missing information, and no major blockers. The response identifies the method as deterministic, says unknowns are not guessed, and says scores are not advice.

## 5. Incomplete input

```bash
curl --fail --silent --show-error \
  --request POST https://qualifier.cryptoleaks.agency/v1/qualify \
  --header 'content-type: application/json' \
  --data @source/examples/site-incomplete.json
```

Expected: HTTP 200 with low readiness scores and classification `NOT SUITABLE` for the example's intended use. `missing_information` remains populated with items such as power price, utility/interconnection evidence, permitting, fiber, and water; the service does not fill those unknowns with assumptions.

## 6. Paid boundary without payment

```bash
curl --silent --show-error --include \
  --request POST https://qualifier.cryptoleaks.agency/v1/paid/qualify \
  --header 'content-type: application/json' \
  --data @source/examples/site-ready.json
```

Expected: HTTP 402 with x402 version 2, scheme `exact`, network `hedera:testnet`, native HBAR asset `0.0.0`, amount `100000` tinybars (`0.001` HBAR), pay-to `0.0.10489770`, and fee payer `0.0.7162784`. Do not attach a payment header and do not execute a new payment.

## Existing paid evidence

The already completed real Hedera Testnet request is documented in the redacted files under `source/evidence/hedera-real/`. It records successful Blocky402 verification and settlement, final HTTP 200, classification `READY`, buyer `0.0.10488940`, seller `0.0.10489770`, fee payer `0.0.7162784`, and transaction `0.0.7162784@1789186391.831327025`. No private key, seed phrase, or signed raw payment payload is included.
