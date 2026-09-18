# How to test and deploy Abstain

This guide takes a candidate source revision through offline verification, Vercel configuration, deployment, and live proof.

## Prerequisites

- Node.js and npm
- Git
- A Vercel project connected to this repository
- A Nexus API key for live mode
- An Upstash Redis database connected through Vercel or configured directly
- A strong demo write key for `POST /v1/evaluate`

## Run the offline quality gates

```bash
npm ci
npm test
npm run typecheck
npm run build
bash -n scripts/verify-live.sh
git diff --check
```

Expected result:

- 168 tests pass across five files.
- TypeScript emits no errors.
- The production build completes.
- The live-verification script has valid shell syntax.
- Git reports no whitespace errors.

The suite defaults to replay mode and makes no Nexus or Redis network calls.

## Configure Vercel

Set these production environment variables:

| Variable | Required | Purpose |
| --- | ---: | --- |
| `ABSTAIN_WRITE_KEY` | Yes | Authenticates the only write endpoint. |
| `NEXUS_MODE=live` | Yes | Selects the live Nexus gateway instead of fixtures. |
| `NEXUS_API_KEY` | Yes | Server-side Nexus credential. Never expose it to clients. |
| `KV_REST_API_URL` and `KV_REST_API_TOKEN` | One complete pair | Credentials injected by the Vercel Upstash integration. |
| `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` | Alternative complete pair | Direct Upstash credentials. |
| `ACCOUNT_EQUITY` | No | Account equity used by the position-size check; defaults to `100000`. |

Do not mix one Redis URL namespace with the other namespace's token. Abstain accepts only a complete Vercel KV pair or a complete direct Upstash pair.

Vercel supplies `VERCEL_GIT_COMMIT_SHA`; the hard-gate endpoints use it as deployment identity.

## Deploy the reviewed revision

Commit and push the exact source you intend to verify. Wait for Vercel to finish deploying, then capture the source commit:

```bash
git rev-parse HEAD
```

The deployment is not proven until `/health`, the well-known verification document, and your local expected SHA all match.

## Run the live verification gate

```bash
./scripts/verify-live.sh \
  https://your-app.vercel.app \
  YOUR_DEMO_WRITE_KEY \
  "$(git rev-parse HEAD)"
```

The script checks:

1. Health and the exact deployed source commit.
2. Verification schema version and project slug.
3. Nexus, store, and durable readiness.
4. Write authentication and input validation.
5. Receipt creation and policy hashes.
6. Eight concurrent writes with unique sequence numbers.
7. Duplicate rejection when the live strategy emits a non-HOLD signal.
8. Full-chain verification and independent receipt-hash recomputation.

The script writes real receipts. Run it only against a deployment whose chain you intend to extend.

## Verify production manually

```bash
curl -s https://your-app.vercel.app/health | jq
curl -s https://your-app.vercel.app/v1/ready | jq
curl -s https://your-app.vercel.app/v1/verify | jq
```

A production deployment is ready only when `/v1/ready` returns HTTP 200 with:

```json
{
  "ready": true,
  "nexus": true,
  "store": true,
  "durable": true
}
```

## Troubleshooting

### Production `/v1/ready` reports `durable:false`

Confirm Vercel exposes either the complete `KV_REST_API_*` pair or the complete `UPSTASH_REDIS_REST_*` pair. Redeploy after changing environment variables.

### `/v1/evaluate` returns `store_not_durable`

Production intentionally refuses to create ephemeral evidence. Configure Redis and redeploy; do not bypass the check.

### Live verification reports the wrong commit

The deployment is stale relative to your checkout. Confirm `git status`, push the intended commit, and wait for the corresponding Vercel deployment before rerunning the script.

### The concurrency step says duplicate safety was skipped

The live Nexus signal was `HOLD`, so there was no non-HOLD proposal on which to exercise duplicate rejection. Sequence allocation was still tested. The offline suite covers duplicate contention deterministically.

### Nexus data fails validation

Abstain rejects malformed numeric fields, mismatched symbols or dates, nonpositive signal
timestamps, missing prior open interest, nonpositive or nonchronological equity, and invalid
trade directions. It also fails `SIGNAL_STALE` when a signal is dated in the future. Inspect
the named `NexusParseError` path for malformed payloads rather than weakening validation.

## Related

- [API and configuration reference](reference-api.md)
- [Receipt-chain explanation](explanation-receipt-chain.md)
- [Submission verification evidence](../submission/verification/README.md)
