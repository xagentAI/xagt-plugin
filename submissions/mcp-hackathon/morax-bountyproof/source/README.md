# BountyProof

BountyProof is an evidence-first GitHub bounty preflight API for humans and agents. It
checks the current issue, repository, assignment, open cross-referenced pull requests,
maintenance freshness, advertised reward signals, and suspicious instruction patterns
before anyone invests implementation time.

**Live API:** `https://bountyproof.89-58-17-36.sslip.io`

## What it decides

The API returns one deliberately conservative verdict:

- `STOP` — a hard current-state blocker such as a closed issue or archived repository.
- `HOLD` — resolve assignment, competition, authenticity, safety, staleness, or payout
  warnings before implementation.
- `PROCEED_TO_MAINTAINER_CONFIRMATION` — no visible blocker was found, but the maintainer
  must still confirm scope, acceptance, assignment, and the payout route.

It never calls an issue “guaranteed,” and every reward signal is reported as
`ADVERTISED_ONLY` unless a separate platform-specific verification exists.

## Call the capability

```bash
curl --fail --silent --show-error \
  --request POST https://bountyproof.89-58-17-36.sslip.io/v1/check \
  --header 'content-type: application/json' \
  --data '{
    "issueUrl":"https://github.com/Dasharo/dasharo-issues/issues/1153"
  }' | jq
```

The current example returns `HOLD` because it discovers an open cross-referenced pull
request and no amount/platform signal in live issue metadata. The response includes the
PR URL and explains that payout still needs separate verification.

Optional checks catch stale claims:

```json
{
  "issueUrl": "https://github.com/owner/repository/issues/123",
  "expectedRewardUsd": 100,
  "expectedPlatform": "Algora"
}
```

See the live OpenAPI document at
[`/openapi.json`](https://bountyproof.89-58-17-36.sslip.io/openapi.json).

## Agent-facing verification

```bash
curl --fail --silent --show-error https://bountyproof.89-58-17-36.sslip.io/health
curl --fail --silent --show-error \
  https://bountyproof.89-58-17-36.sslip.io/.well-known/xagent-verification.json
```

Both endpoints expose the exact deployed source commit. The well-known response uses
submission slug `morax-bountyproof` and schema version 1.

## Analysis pipeline

```text
canonical GitHub issue URL
      │ strict parsing; fixed api.github.com host
      ▼
repo + issue + timeline requests (parallel, bounded timeout)
      │
      ├─ repository authenticity / archived / disabled / push age
      ├─ issue open / locked / assignment state
      ├─ open cross-referenced pull requests
      ├─ advertised fiat, token, and platform signals
      └─ untrusted-instruction safety flags (matched text is never returned)
      ▼
STOP | HOLD | PROCEED_TO_MAINTAINER_CONFIRMATION
      │
      └─ evidence URLs, reasons, next actions, limitations, rate-limit state
```

## Local development

Requires Node.js 24.18 or newer.

```bash
npm ci --ignore-scripts
npm test
npm run build
REVIEW_COMMIT=development npm start
```

The server listens on `127.0.0.1:8787` by default. Set `HOST`, `PORT`,
`REVIEW_COMMIT`, and `SOURCE_REPOSITORY` as shown in `.env.example`.

## Verified checks

```bash
npm run check
npm audit --audit-level=low
docker build --build-arg VCS_REF="$REVIEW_COMMIT" -t bountyproof .
```

- 21 unit/service tests cover URL boundaries, money/platform parsing, prompt-injection
  flags, competition extraction, verdicts, cache expiry/eviction, version proof,
  structured errors, and request-size limits.
- The dependency audit currently reports zero vulnerabilities.
- The production image pins Node 24.18.0 Bookworm slim by digest and runs as UID 1000 on
  a read-only, capability-free container.

## Production layout

```text
Internet :443
  → OpenResty TLS + 16 KiB body cap + per-IP request limit
  → 127.0.0.1:18789
  → non-root BountyProof container :8787
  → public api.github.com metadata only
```

`compose.production.yml` binds loopback only. `deploy/bountyproof.nginx.conf` is the exact
public reverse-proxy configuration, and `deploy/certbot-renew-hook.sh` installs renewed
certificates into the mounted 1Panel/OpenResty site directory after validating syntax.

## Security, privacy, and limitations

Read [`SECURITY.md`](SECURITY.md). BountyProof does not execute or echo issue bodies,
authenticate to GitHub in the public deployment, or store caller data. GitHub state may
change immediately after a response, private/unlinked work is not visible, and a label or
dollar amount does not establish funding.

## License

[MIT](LICENSE)
