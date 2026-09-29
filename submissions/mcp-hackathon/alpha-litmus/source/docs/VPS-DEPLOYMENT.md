# VPS Deployment Evidence

Recorded on **2026-09-19**. This document retains the reproducible pre-commit
deployment evidence and records the completed review-commit binding. The public
endpoints, not a copied value in this file, are authoritative for the active
commit.

## Executed deployment

- Target: the existing 12 GiB-class VPS that hosts APIVouch behind Caddy.
- Pre-commit evidence release path: `/opt/alphalitmus-release-20260919-2`, with
  `/opt/alphalitmus` pointing to that immutable release directory.
- Source archive SHA-256:
  `1bf452d7c23a5cdfe88fef9109ef37c63474e9bfcf344b4856049267ebd2d4e4`.
- Built image ID:
  `sha256:a6a94b8eaa0e3d489481d7da3502e6160a5120b6f7506c6c527a9035cc002de8`.
- The build installed the runtime lock with `pip --require-hashes` and completed
  from the checked-in Dockerfile.

The running `alpha-litmus` container was observed healthy and enforced:

- UID/GID `10001:10001` (`runner`), not root;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges:true`;
- 256 PID, 1 GiB memory and 1 CPU limits;
- 32 MiB `noexec,nosuid` tmpfs;
- bounded JSON-file logs;
- no host port binding;
- private attachment to the existing `apivouch_edge` Docker network only.

From the existing Caddy container, the private service returned HTTP-success JSON
for `/health`, `/.well-known/xagent-verification.json` and `/v1/capabilities`.
That pre-commit build reported service `alpha-litmus`, status `ok`, commit
`local-dev` and `commit_reviewable: false`. Capabilities reported five MCP tools and confirmed
both Nexus reads and remote compute were disabled. No Nexus key was copied to the
VPS. All APIVouch app, database and Caddy containers remained healthy after the
deployment.

## Public edge verification

`alphalitmus.sklab.cc` resolves publicly to the target VPS. The combined Caddy
configuration was validated before the Caddy service alone was recreated; the
APIVouch application and database were not restarted. Let's Encrypt completed
the HTTP-01 challenge and issued the certificate for the AlphaLitmus hostname.

Public checks then confirmed:

- `GET https://alphalitmus.sklab.cc/` returned HTTP/2 `200` and the judge UI;
- `/health`, `/.well-known/xagent-verification.json`, and `/v1/capabilities`
  returned HTTP/2 `200` through the public TLS edge;
- plain HTTP redirected to the corresponding HTTPS URL with `308`;
- the HTTPS responses included `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, and `X-Frame-Options: DENY`;
- AlphaLitmus, Caddy, and all APIVouch containers were healthy, and the existing
  public APIVouch health endpoint still returned `200` after the Caddy change.

Release 2 adds the judge-facing responsive result summary, fold-return bars,
cost-fragility curve and parameter-sensitivity heatmap without changing the
report contract or enabling additional capabilities. A real 390px browser pass
measured document and body scroll widths equal to the viewport, exercised the
shock-demo transition, rendered all three visualizations and observed no page
errors.

The final review release was built from `git archive` of the exact public review
commit, uses an immutable `/opt/alphalitmus-release-<short-commit>` directory,
and runs with `ALPHALITMUS_ENV=production` plus the full commit build argument.
The archive SHA-256 matched before extraction. A canary passed health through
the private Caddy network before traffic switched. The active container and
symlink were then updated, while the previous release/image were retained for
rollback. `/health` and `/.well-known/xagent-verification.json` exposed the same
40-character public commit; capabilities reported six tools with
`evaluate_strategy_release` first. Public mixed-demo and safe Nexus-disabled
release-gate calls returned verified `INSUFFICIENT_EVIDENCE`, never a fabricated
success.

The redesigned live UI also received a current Chromium pass at desktop and
390×844 mobile viewports. Mixed auto-load and shock interaction completed,
Copy/Download enabled only after a result, no document-level horizontal overflow
appeared, and no application console warning/error was observed. This is not a
formal accessibility or cross-browser certification.

This remains a public **safe-mode** deployment, not a live Nexus deployment.
`no_execution` stays true, Nexus reads and remote compute remain disabled, and no
key is present on the VPS. Enabling live Nexus later is a separate security
decision requiring TLS, authentication, explicit quotas and external secret
injection; it is not part of this deployment.
