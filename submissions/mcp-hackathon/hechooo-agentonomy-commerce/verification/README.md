# Verification evidence

Use the public browser flow first. Open [https://review.agentonomy.xyz](https://review.agentonomy.xyz), click **开始演示**, and follow the supplied CSV purchase flow. No signup, review token, or organizer credential is needed. The public browser uses an isolated HttpOnly cookie session; the private `/v1/*` Bearer API remains an operator-only baseline and is not required for review.

The evidence files for this revision are `public-demo-evidence.json`,
`upgrade-evidence.json`, and `TEST_RESULTS.md`. Read those files together with
the exact commit and public health/proof responses before making a final claim
about deployment or test status.

## Prerequisites

- Review commit: `029cd0ba9aff3c25fffa33ae27f94615c1eebe2b`
- Public review URL: `https://review.agentonomy.xyz`
- No credentials are needed for the public browser flow.
- Keep any verifier state file outside the source tree. It contains the
  browser’s private HttpOnly cookie credential and must not be committed,
  uploaded, or printed.

## 1. Public health and version proof

These endpoints do not require authentication:

```bash
BASE_URL='https://review.agentonomy.xyz'
curl --fail --silent --show-error "$BASE_URL/health"
curl --fail --silent --show-error "$BASE_URL/.well-known/xagent-verification.json"
```

The responses should report `status: "ok"`, `real_funds: false` where exposed,
the slug `hechooo-agentonomy-commerce`, and commit
`029cd0ba9aff3c25fffa33ae27f94615c1eebe2b`. An exact response is deployment
evidence only when it is recorded in the current evidence artifacts.

## 2. Primary browser walkthrough

1. Open `https://review.agentonomy.xyz/` and click **开始演示**. The page
   creates or restores the current browser’s visitor session and shows a 1.00
   simulated-USDC budget. There is no registration or token field.
2. Use the prefilled synthetic CSV, click **锁定报价**, then **确认购买**.
   The merchant calculation runs over real HTTP to the loopback service; the
   settlement is simulated. The delivered result has two unique transactions,
   duplicate ID `demo-001`, and a USD net total of `27.50`.
3. Confirm the visitor budget shows 0.30 used and 0.70 remaining, with one
   settlement submission and one merchant delivery.
4. Refresh the page. The same browser cookie restores the session and the
   existing order. Replaying the same preview or reading the same order must
   return the same result without a second charge or a budget reset.
5. Use a separate browser profile to start a second session. It must receive a
   separate 1.00 budget and must not read the first profile’s order or preview.

The browser cookie is `HttpOnly`, `SameSite=Strict`, and `Secure` on HTTPS. It
is never exposed in JSON, page text, or the browser application state. Public
mutations require an `Origin` exactly equal to the configured review origin;
missing or different origins fail closed.

## 3. Credential-free public verifier

The checked helper performs the same cookie-backed public flow, including
health/proof checks, private `/v1` unauthenticated rejection, public session
bootstrap, purchase/delivery, replay, and cross-visitor isolation. It reads no
Bearer token and writes sanitized JSON to stdout. The state file is private and
must be created outside the source tree:

```bash
BASE_URL='https://review.agentonomy.xyz'
STATE_FILE="${TMPDIR:-/tmp}/agentonomy-public-demo-state.json"
test ! -e "$STATE_FILE" || {
  echo "State file exists; choose a new private path or use --resume" >&2
  exit 1
}

.venv/bin/python source/scripts/verify_public_demo.py \
  --base-url "$BASE_URL" \
  --expected-commit "029cd0ba9aff3c25fffa33ae27f94615c1eebe2b" \
  --state-file "$STATE_FILE"
```

The first run creates two isolated visitor sessions and one 0.30 simulated-USDC report; the second visitor is used only to check isolation.
The helper writes the session credential and intermediate IDs to the state file
with mode `0600`; do not display or publish that file. If the service is
restarted, reuse the same private path with `--resume`:

```bash
.venv/bin/python source/scripts/verify_public_demo.py \
  --base-url "$BASE_URL" \
  --expected-commit "029cd0ba9aff3c25fffa33ae27f94615c1eebe2b" \
  --state-file "$STATE_FILE" \
  --resume
```

`--resume` restores the existing cookie-backed session and replays the saved
purchase; it avoids creating a new session or charging an already-paid preview again. Recovery from an interrupted unpaid preview can complete that original purchase. Running
without `--resume` while the state file exists is rejected for the same reason.

## 4. Public routes and limits

The browser uses `GET`/`POST /demo/session` and these cookie-authenticated
aliases: `/demo/v1/services`, `/demo/v1/budget`, `/demo/v1/previews`,
`/demo/v1/purchases`, and `/demo/v1/purchases/{purchase_id}`. The private
operator API remains at `/v1/*` and requires its Bearer credential; that API’s
original persistent review tenant and order state are isolated from public
visitor sessions.

Each public visitor session has a persistent 1.00 simulated-USDC budget and a
0.30 charge per delivered report. Sessions last seven days, up to 128 sessions
are retained, and no more than 10 new sessions are created in a rolling minute.
Each visitor is limited to 60 requests per minute; public traffic is capped at
120 requests per minute globally. Bodies are limited to 256 KiB, CSV input to
128 KiB and 1,000 rows, and previews expire after five minutes. Delivered
results and sessions expire after seven days; expired visitor state is cleaned on subsequent session creation. Refresh, cookie restore,
and replay do not create a new grant, replenish a budget, or reset state.

## 5. Failure and boundary checks

The public path should reject missing or invalid cookies, missing or mismatched
mutation origins, malformed CSV, oversized bodies, exhausted budgets, expired
previews, rate-limit violations, and unavailable workers without retrying a
settled payment. A private `/v1/*` request without a Bearer credential remains
401 and a public cookie does not grant access to it.

Merchant transport is real HTTP to the fixed loopback listener. Settlement and
USDC accounting are simulated, `real_funds` remains false, and this package
does not claim a live blockchain transaction, formal security audit, or
production-wallet behavior.

## Source integrity

Use the outer `../source-manifest.json` and `../source-manifest.sha256` for the
review snapshot. `../source/docs/source-manifest.json` is inherited historical
Clink working-tree metadata and is not authoritative for this current source.
The outer manifest is the file set bound to the review commit.

## Evidence status

`public-demo-evidence.json` records the current public browser/helper evidence;
`upgrade-evidence.json` records restart/recovery evidence when available; and
`TEST_RESULTS.md` records the test commands and results. These artifacts are
the source of truth for final status. This README documents the reproducible
flow and does not assert a final deployment pass before those artifacts are
finalized.
