# Deployment

Status: worker_api_live_xagent_patch_local_only

## Public surfaces currently live

- Static demo: https://agent-acceptance-gate.pages.dev/
- Cloudflare Worker API: https://api.leolabs.me
- Current production health: https://api.leolabs.me/health
- Existing paid service catalogue: https://api.leolabs.me/api/okx-ai-services

The existing Worker API is live. The X-Agent commit-bound health response,
same-origin verification document, and reviewer POST route prepared on
`codex/xagent-mcp-hackathon-prep-20260917` are **not yet deployed**.

## X-Agent deployment identity

A review deployment must set all three values. Start from
`config/xagent-review.env.example` and bind the exact public source commit:

```text
XAGENT_GIT_COMMIT=<exact 40-character public Git commit deployed>
XAGENT_PROJECT_SLUG=runesleo-agent-acceptance-gate
XAGENT_REVIEW_ENABLED=true
```

`XAGENT_GIT_COMMIT` must match the public source commit submitted for review.
With a missing or malformed commit, `/health` and the verification endpoint
fail closed with HTTP 503. When `XAGENT_REVIEW_ENABLED` is unset or false, the
reviewer POST route returns HTTP 404 and the existing x402 route remains intact.

## Local verification

```bash
npm test
npm run worker:check
npm run test:xagent
npm run test:xagent-submission
```

## Deployment command

After the source commit is public and Leo explicitly approves deployment,
inject the non-secret Worker variables explicitly through Wrangler:

```bash
npm run deploy:worker -- \
  --var XAGENT_GIT_COMMIT:<exact-40-character-public-commit> \
  --var XAGENT_PROJECT_SLUG:runesleo-agent-acceptance-gate \
  --var XAGENT_REVIEW_ENABLED:true
```

For a local Worker check, use the same `--var` arguments with `npx wrangler dev`.
Shell environment variables alone are not treated as Worker bindings.

After deployment, verify:

```bash
curl --fail --silent --show-error https://api.leolabs.me/health
curl --fail --silent --show-error https://api.leolabs.me/.well-known/xagent-verification.json
```

The two responses must expose the same exact 40-character commit as the public
review commit. A reviewer capability call is documented in the submission
verification packet.

## Rollback

Rollback means redeploying the previously verified Worker source and restoring
its prior environment configuration. Do not deploy, alter Worker variables,
push source, or open the official submission PR without explicit Leo approval.
The static Pages demo is a separate surface and is not changed by this patch.
