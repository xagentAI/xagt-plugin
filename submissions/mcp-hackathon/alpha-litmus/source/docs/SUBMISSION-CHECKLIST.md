# AlphaLitmus Submission Checklist

Status: submission preparation. Real Nexus Studio backtests and one authorized read-only AlphaLitmus-to-Nexus MCP reconciliation are documented in [Nexus live evidence](NEXUS-LIVE-EVIDENCE.md). A public source repository and commit-bound safe-mode HTTPS deployment are documented, but no registration proof, official validation, submission PR, acceptance or award is established by this workspace.

## Reviewed Official Requirements

Reviewed read-only on **2026-09-19**:

- https://github.com/xagentAI/xagt-plugin
- https://github.com/xagentAI/xagt-plugin/blob/main/submissions/README.md
- https://github.com/xagentAI/xagt-plugin/blob/main/docs/review-scorecard.md

These are mutable `main` URLs, not pinned rule snapshots. Recheck them and the linked event rules before submission. The reviewed README describes the build period as September 2-19, technical review September 20-October 1, and announcements October 2-4, 2026; do not infer an extension or eligibility from this document.

## Required Evidence

- [ ] Confirm registration, submitter identity and chosen track with the official process.
- [x] Complete a real Nexus Studio backtest for the intended named strategy and retain its exact strategy/run identifiers and negative result without claiming an edge.
- [x] Use OlaXBT Nexus MCP from the callable AlphaLitmus application and retain the resulting strategy evidence and contradiction. The live read-only result is `INCONSISTENT`, not a validation or profitability claim; the separate reference EMA does not validate the Nexus-bound strategy.
- [x] Deploy an HTTPS API reachable during review and capture synthetic demo capability calls plus safe error behavior; Nexus and remote compute remain disabled in the public deployment.
- [x] Publish complete source and pin the exact public GitHub 40-character reviewed commit.
- [x] Set `ALPHALITMUS_COMMIT` to the actual commit and `ALPHALITMUS_ENV=production`; verify startup rejects invalid production provenance before deployment.
- [x] Keep `/health` public with `status: ok|healthy` and the final review commit. Serve `/.well-known/xagent-verification.json` on the API origin with `schemaVersion: 1`, slug `alpha-litmus`, and the same commit.
- [x] Use submission directory `alpha-litmus`, matching the deployed proof slug exactly.
- [ ] Protect capability routes behind an authenticated reverse proxy with TLS, request limits and time-limited review access. Share credentials only through the approved private channel.
- [ ] Enable external Nexus reads only with `ALPHALITMUS_ENABLE_NEXUS=true`, an externally injected strategy-bound `NEXUS_API_KEY`, and confirmed access controls. Never place secrets in source, screenshots, command transcripts or certificates.
- [ ] Record real strategy fees, slippage, run binding, data provenance and evaluation split, or explicitly retain the gaps. Do not convert missing fields into passes.
- [x] Reproduce tests, Ruff, strict mypy, secret scan, browser behavior and hardened Linux container behavior; exact results are recorded in the verification and deployment documents.
- [ ] Resolve dependency licensing, data-use authorization, branding and source ownership with the actual rights holder. This project supplies no invented license or rights declaration.

## Official Package

The official contract requires one directory under `submissions/mcp-hackathon/<team-or-builder>-<project-slug>/` containing `SUBMISSION.md`, `submission.json`, `RIGHTS.md`, complete `source/`, and `verification/README.md`. Include manifests, applicable lockfiles, secret-free configuration examples, all required first-party implementation, setup/build/run instructions and disclosures of external services. An external repository link, submodule, symlink or Git LFS pointer is not a source substitute.

In a separately authorized official-repository checkout, the published validator commands are:

```text
npm run validate:submission -- --dir submissions/mcp-hackathon/<team>-<project>
npm run validate:submission -- --dir submissions/mcp-hackathon/<team>-<project> --online
```

Run both commands against the final package. The public source commit and matching production deployment now exist; do not create a PR or claim validator success until the package itself passes both commands.

## Interpretation

The official hard gates cover callable service, complete reproducible source, public commit binding and safe review. Quality weights are user/agent value 30, capability quality 25, engineering 20, MCP readiness 15, adoption/operation 10. These are organizer criteria, not a self-awarded score.

The official exclusions include on-chain security/auditing and related security-analysis projects. AlphaLitmus is positioned as strategy methodology and conditional financial evidence reconciliation, not a smart-contract/security audit; eligibility remains an organizer decision. A receipt, passing automated check, archive or preservation merge is not acceptance or an award. Endpoint commit strings do not independently prove the deployed binary matches source.
