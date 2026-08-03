# ADR 0001: PR-contained MCP Hackathon submission contract

- **Status:** Accepted
- **Date:** 2026-08-03
- **Owners:** X-Agent program and marketplace maintainers

## Context

The earlier hackathon flow accepted a brief project description and an external repository link. It did not provide a reliable place to review complete code, bind a deployed service to a source version, or record reproducible API verification. It also treated existing OKX-skill installation and participant registration as eligibility gates, which narrows the capability pool before X-Agent can productize it.

## Decision

Use one pull request to add `submissions/<team-or-builder>-<project-slug>/` containing a human-readable capability manifest, a machine-readable `submission.json`, complete source code, and reproducible API verification evidence. Require a deployed API, public health check, same-origin deployment proof, pinned commit, source/reproduction instructions, and security/data notes. The trusted base-branch validator verifies scope, source packaging, the public GitHub commit, and the version-bound live service without executing submission code. Do not require MCP or payment-protocol implementation at entry. Selected projects proceed to X-Agent MCP standardization and then an OKX-facing submission package.

## Alternatives considered

1. **External GitHub URL only.** Low friction, but source can disappear, change, or fail to correspond to the deployed service.
2. **MCP-only submissions.** Standardized at entry, but excludes valuable existing APIs and shifts adapter work onto participants.
3. **Store all source in a separate private system.** Better access control in some cases, but reduces transparency and creates a parallel review workflow.

## Consequences

The repository grows with submitted source and reviewers must enforce size, secret, and security hygiene. In exchange, each accepted capability has a durable, PR-auditable artifact with clear ownership and reproducibility evidence. If scale requires private review later, the manifest and verification contract remain stable while source storage may move under a documented, time-bounded program exception.

## Rollback

If PR-contained source becomes untenable, retain `SUBMISSION.md` and `verification/` in this repository and publish a versioned replacement for the `source/` storage rule. Do not revert to accepting only an unverifiable external URL.
