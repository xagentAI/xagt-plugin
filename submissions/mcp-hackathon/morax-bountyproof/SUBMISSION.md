# BountyProof

## Capability

- **One-line description:** Preflight a public GitHub bounty issue against current
  repository, assignment, competition, reward-advertisement, maintenance, and
  prompt-injection evidence before an agent invests implementation time.
- **Who it helps:** Coding agents, their operators, and contributors screening noisy or
  adversarial bounty feeds.
- **Capability boundary:** BountyProof reads public GitHub metadata and returns `STOP`,
  `HOLD`, or `PROCEED_TO_MAINTAINER_CONFIRMATION` with evidence URLs. It does not clone or
  execute code, follow issue instructions, claim work, verify escrow, promise payment,
  or replace maintainer/platform confirmation.

## Live API

- **API base URL:** https://bountyproof.89-58-17-36.sslip.io/v1
- **Health-check URL:** https://bountyproof.89-58-17-36.sslip.io/health
- **Authentication:** None. The public deployment intentionally uses GitHub's
  unauthenticated public API and does not expose or store a GitHub token.
- **Rate limits / known limits:** OpenResty allows 30 requests per minute per source IP
  with a burst of 10; identical checks are cached for five minutes. The shared GitHub
  unauthenticated allowance is normally 60 requests per hour and each uncached check uses
  three requests. GitHub calls time out after eight seconds and the proxy after fifteen.
  Request bodies are capped at 16 KiB.
- **API contract:** Live OpenAPI 3.1 at
  https://bountyproof.89-58-17-36.sslip.io/openapi.json; implementation and response
  types are included in `source/src/`.

## Source and reproducibility

- **Source repository:** https://github.com/fzlzjerry/bountyproof
- **Review commit:** `019f0167980d93dcae730dcf2c4467314412edf2`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci --ignore-scripts && npm run check && npm audit --audit-level=low`
- **Run locally:** `REVIEW_COMMIT=development npm start` after `npm run build`
- **Deploy:** Set `REVIEW_COMMIT=019f0167980d93dcae730dcf2c4467314412edf2`
  in an uncommitted environment file, run
  `docker compose --env-file .env.production -f compose.production.yml up -d --build`,
  install `deploy/bountyproof.nginx.conf`, obtain the named Let's Encrypt certificate,
  validate OpenResty syntax, and reload. Exact topology and verification commands are in
  `source/README.md`.
- **Version binding:** The same review commit is a container environment value and OCI
  image revision label. Both health and same-origin well-known endpoints return it, and
  health also emits it as `x-source-commit`.

The live responses are:

```json
{"status":"ok","service":"bountyproof","version":"0.1.0","commit":"019f0167980d93dcae730dcf2c4467314412edf2","checkedAt":"<current ISO timestamp>"}
```

```json
{"schemaVersion":1,"slug":"morax-bountyproof","commit":"019f0167980d93dcae730dcf2c4467314412edf2"}
```

## Verification

The reproducible calls and captured live responses are in `verification/README.md` and
the adjacent JSON fixtures.

- **Health-check result:** HTTP 200, `status: ok`, exact 40-character review commit, and
  matching `x-source-commit` header.
- **Capability call:** `POST /v1/check` with a canonical public GitHub issue URL and
  optional expected reward/platform. The captured Dasharo #1153 check currently returns
  `HOLD`, discovers the real open OSFV #1276 pull request, and reports that no amount or
  recognized platform appears in current issue metadata.
- **Expected error behavior:** Non-canonical URLs return HTTP 400 with
  `INVALID_ISSUE_URL`; unsupported content types return 415; oversized bodies return 413;
  upstream not-found, rate-limit, and availability errors map to 404, 429, and 502.

## Security and data handling

- **Data collected:** Request `issueUrl`, optional `expectedRewardUsd` and
  `expectedPlatform`; proxy logs also contain source IP, request path, user agent, status,
  and response size. Request bodies and matched issue text are not logged or returned.
- **Purpose and retention:** Inputs are used only for the requested preflight. Identical
  result objects are cached in process memory for five minutes and disappear on restart.
  OpenResty access-log retention follows host-operator rotation and is not represented as
  a fixed application guarantee.
- **Third parties / outbound network calls:** Public `api.github.com` repository, issue,
  and timeline endpoints. Runtime has no other outbound service.
- **Secrets:** No secrets are committed. Review access is not required. A future operator
  can add a fine-grained read-only GitHub token outside Git, but the submitted deployment
  has none.
- **Known risks / restrictions:** GitHub state may change immediately; private or
  unlinked work is invisible; issue labels and money strings do not prove funding; regex
  safety flags are conservative and can have false positives/negatives. Callers must
  inspect the returned evidence and confirm scope/payout themselves.

## Support

- **Team / builder:** Yixuan Cheng (Morax)
- **Contact:** https://github.com/fzlzjerry/bountyproof/issues
- **License / rights:** MIT. The submitter owns the project-specific source and can
  authorize review, archival, publication, deployment, and the rights stated in
  `RIGHTS.md`; third-party components retain their own licenses.
