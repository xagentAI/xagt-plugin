# BountyProof verification evidence

## Prerequisites

- Review commit: `019f0167980d93dcae730dcf2c4467314412edf2`
- API base URL: `https://bountyproof.89-58-17-36.sslip.io/v1`
- Authentication: None
- Tools: `curl`; optionally `jq`

All examples use public data. No token, cookie, wallet, or private repository is needed.

## 1. Health check

```bash
curl --fail --silent --show-error --dump-header - \
  https://bountyproof.89-58-17-36.sslip.io/health
```

Expected: HTTP 200, `x-source-commit` equal to the review commit, and a response shaped as:

```json
{
  "status": "ok",
  "service": "bountyproof",
  "version": "0.1.0",
  "commit": "019f0167980d93dcae730dcf2c4467314412edf2",
  "checkedAt": "<current ISO timestamp>"
}
```

The response captured on 2026-09-08 is in `health-response.json`.

## 2. Deployment proof

```bash
curl --fail --silent --show-error \
  https://bountyproof.89-58-17-36.sslip.io/.well-known/xagent-verification.json
```

Expected exact stable fields:

```json
{
  "schemaVersion": 1,
  "slug": "morax-bountyproof",
  "commit": "019f0167980d93dcae730dcf2c4467314412edf2"
}
```

The captured response is in `deployment-proof-response.json`.

## 3. Capability call

```bash
curl --fail --silent --show-error \
  --request POST https://bountyproof.89-58-17-36.sslip.io/v1/check \
  --header 'content-type: application/json' \
  --data '{
    "issueUrl":"https://github.com/Dasharo/dasharo-issues/issues/1153"
  }'
```

At capture time, the important evidence was:

- `verdict` was `HOLD`, not a payout or completion claim;
- `competition.openCrossReferencedPullRequests` contained
  `https://github.com/Dasharo/open-source-firmware-validation/pull/1276`;
- `payout.status` was `NO_MONETARY_SIGNAL` because current GitHub metadata did not name
  an amount/platform even though the repository uses an external bounty program;
- `promptSafety.issueContentTreatedAsUntrusted` was `true` and no suspicious pattern was
  detected in that issue.

The complete bounded response is in `capability-response.json`. Current GitHub state may
legitimately change the result while the response schema and evidence behavior remain the
same.

## 4. Safe failure

```bash
curl --silent --show-error \
  --request POST https://bountyproof.89-58-17-36.sslip.io/v1/check \
  --header 'content-type: application/json' \
  --data '{"issueUrl":"https://evil.example/not-github"}'
```

Expected HTTP 400 and error code `INVALID_ISSUE_URL`. The captured response is in
`invalid-input-response.json`; its request ID is diagnostic only and may differ.

## 5. Rebuild and test the retained source

From `source/` in an isolated environment with Node.js 24.18+ and Docker:

```bash
npm ci --ignore-scripts
npm run check
npm audit --audit-level=low
docker build \
  --build-arg VCS_REF=019f0167980d93dcae730dcf2c4467314412edf2 \
  --tag bountyproof:review .
docker run --detach --rm --name bountyproof-review \
  --publish 127.0.0.1:18787:8787 \
  --env REVIEW_COMMIT=019f0167980d93dcae730dcf2c4467314412edf2 \
  bountyproof:review
curl --fail --silent http://127.0.0.1:18787/health
docker stop bountyproof-review
```

Expected local checks for the review commit: 21 tests pass, TypeScript compiles, npm audit
reports zero vulnerabilities, the container health check becomes healthy, and both
version endpoints return the exact review commit.
