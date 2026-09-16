# ADR 0001: PR-contained MCP Hackathon submission contract

- **Status:** Accepted
- **Date:** 2026-08-03
- **Owners:** X-Agent program and marketplace maintainers

## Context

The earlier hackathon flow accepted a brief project description and an external repository link. It did not provide a reliable place to review complete code, bind a deployed service to a source version, or record reproducible API verification. It also treated existing OKX-skill installation and participant registration as eligibility gates, which narrows the capability pool before X-Agent can productize it.

## Decision

Use one pull request to add `submissions/mcp-hackathon/<team-or-builder>-<project-slug>/` containing a human-readable capability manifest, a machine-readable `submission.json`, complete source code, and reproducible API verification evidence. Require a deployed API, public health check, same-origin deployment proof, pinned commit, source/reproduction instructions, and security/data notes. The trusted base-branch validator verifies scope, source packaging, the public GitHub commit, and the version-bound live service without executing submission code. Do not require MCP or payment-protocol implementation at entry. Selected projects proceed to X-Agent MCP standardization and then an OKX-facing submission package.

## Alternatives considered

1. **External GitHub URL only.** Low friction, but source can disappear, change, or fail to correspond to the deployed service.
2. **MCP-only submissions.** Standardized at entry, but excludes valuable existing APIs and shifts adapter work onto participants.
3. **Store all source in a separate private system.** Better access control in some cases, but reduces transparency and creates a parallel review workflow.

## Consequences

The repository grows with submitted source and reviewers must enforce size, secret, and security hygiene. In exchange, each accepted capability has a durable, PR-auditable artifact with clear ownership and reproducibility evidence. If scale requires private review later, the manifest and verification contract remain stable while source storage may move under a documented, time-bounded program exception.

## Rollback

If PR-contained source becomes untenable, retain `SUBMISSION.md` and `verification/` in this repository and publish a versioned replacement for the `source/` storage rule. Do not revert to accepting only an unverifiable external URL.

## 2026-09-03 update: receipts and safe repository automation

### Problem observed

Recent current-event submissions reached a repository-side checkout refusal before source validation ran. The old `pull_request_target` workflow attempted to check out fork code in a write-capable repository context. Enabling unsafe fork checkout would remove the protection without addressing the risk. Receipt, validation, preservation, and human-review meanings also need to remain distinct.

This update changes repository infrastructure only. It does not revise participant code, change eligibility or scoring criteria, reopen historical activity, or issue decisions on the example PRs.

### Decision

- Use a metadata-only `pull_request_target` task to post one English receipt for a current-event PR. It checks out official code only, has no contents-write permission, and reuses an existing maintainer/bot receipt. It does not approve, merge, or score entries.
- Run submission checks on `pull_request` with read-only permissions. Check out only the trusted base commit. Read submitted files as data through GitHub's API; never install dependencies, execute submitted code, or check out a fork in a privileged task.
- Put archival writes in a separate `workflow_run` task running official default-branch code. Treat the upstream success flag, contributor-modified workflow, PR text, and uploaded artifacts as untrusted. Independently verify the PR association, exact current head, changed paths, submitted package, and live evidence before creating an archive ref.
- Read a bounded project subtree through the official repository API, validate regular Git file modes and paths, verify each blob's Git object hash, and materialize it in a unique temporary directory. Reject symlinks, submodules, truncated responses, excessive files, oversized content, and path escapes. Remove the temporary directory after success or failure.
- Count deletions and both sides of renames in the project-scope check. Scan the full submitted package, including manifests and verification documents, rather than skipping large source files or scanning only `source/`. Reject documentation-only source packages and Git LFS pointers. These checks still do not certify complete or safe source.
- Recheck the PR head and base before writes. Archive names include the full head SHA. Never force-update or overwrite a ref; repeated runs confirm the existing exact ref. Resolve a lost POST response by reading the expected ref, not by guessing or rewriting it. Receipt retries relist comments first.
- For manual acceptance sealing, verify that the PR was merged for the requested project and that its official archive, actual merge, and selected release commit contain identical project trees. Preserve external-source independence after archival. Record the actual merge commit and selected release commit separately. Require an accountable reviewer and review-record URL. The workflow neither judges the decision nor sends payment.
- Pin checkout and Node setup actions by full SHA, use Node 24, disable dependency caches, and avoid installing packages in these workflows. Keep local tests under the root test configuration so participant tests are never discovered automatically.

### Threat model and remaining limits

A contributor controls PR files, filenames, prior history, descriptions, fork workflows, source URLs, and responses from their deployed API. Repository write tokens and accepted-source records must not become available to participant code. API downloads are confined to the official GitHub repository, bounded, hash-checked, and treated as data. Public service checks send no GitHub token, disallow redirects, and use a validated public IP with TLS verification. No artifact or participant-supplied URL is used as executable code.

A successful `pull_request` run is not proof that the official check ran unchanged. The separate archival task therefore repeats the trusted checks. Its credential has contents-write permission for preserving the source ref; the script exposes no operation to approve or merge the PR. Workflow permissions alone cannot restrict contents-write to one ref prefix, so the fixed code paths and repository rulesets must be reviewed before rollout.

Automatic inspection does not prove reproducibility, detect every secret (including historical commits), authenticate a self-reported build version, assess private dependencies, or grant the right to republish third-party code. Those remain human review responsibilities. A source archive is not a review pass, a ranking, or an award. Archive branch protection and independent backup are operational prerequisites, not properties guaranteed by these files. The implementation does not create an independent backup.

### Verification and rollout

Regression tests cover scope escapes, deletion/rename handling, fake receipts, retries, pagination limits, symlinks, submodules, bounded blobs, stale PR versions, forged green runs, exact archive references, and the merged/archive/release relationship. Tests use mock GitHub APIs and inert source fixtures; they do not mutate real participant PRs or execute their code. Run the root lint, tests, and build before proposing publication.

The permission boundary requires an independent maintainer review before rollout. Local tests do not establish GitHub fork-event behavior, archive-ref creation permissions, ruleset enforcement, or release publication. Verify those separately with an authorized test submission after the code reaches the default branch. Do not rerun or modify existing participant PRs as an implicit test. See [retention and rollout instructions](../submission-retention-and-reward.md).

### Safe rollback

If the new automation fails, pause the receipt/archive workflows and retain all existing official archives and releases. Correct and retest official code before re-enabling it. Never restore privileged fork checkout, enable `allow-unsafe-pr-checkout`, force-rewrite preservation refs, or describe an incomplete archive as successful. Historical activity and participant source remain untouched.
