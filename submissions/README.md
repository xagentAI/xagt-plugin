# Submission contract

This directory contains both the preserved May 2026 hackathon archive and the official code-submission location for the current X-Agent MCP Hackathon.

- Historical entries remain at `submissions/<participant-id>-<project>/` and are indexed in [`INDEX.md`](./INDEX.md).
- New MCP Hackathon entries go only under `submissions/mcp-hackathon/<team>-<project>/`.

Do not modify a historical project to enter the current program.

## Create one project directory

```text
submissions/mcp-hackathon/<team-or-builder>-<project-slug>/
├── SUBMISSION.md
├── submission.json
├── RIGHTS.md
├── source/
└── verification/
```

Use lowercase letters, numbers, and hyphens for `<team-or-builder>-<project-slug>`. Do not edit another team's directory. A later material change belongs in a new pull request against the same directory.

Copy [`TEMPLATE.md`](./TEMPLATE.md) to `SUBMISSION.md`, [`submission.example.json`](./submission.example.json) to `submission.json`, [`RIGHTS_TEMPLATE.md`](./RIGHTS_TEMPLATE.md) to `RIGHTS.md`, and [`VERIFICATION_TEMPLATE.md`](./VERIFICATION_TEMPLATE.md) to `verification/README.md`, then replace every placeholder. `source/` must contain the complete code reviewers need; `verification/` contains repeatable API evidence, such as a redacted `curl` command and response fixture.

## Required files

| Path | Required content |
| --- | --- |
| `SUBMISSION.md` | Capability description, API and health-check URLs, source repository, exact review commit, build/deploy instructions, data/security notes, and support contact. |
| `submission.json` | Machine-readable slug, source repository, review commit, API URL, health-check URL, and standard deployment-proof URL. Start with `submission.example.json` or generate it with the repository version of `xagt-plugin submit`. |
| `RIGHTS.md` | Submitter identity, ownership declaration, third-party licenses, and authorization for review and post-award retention under the official program terms. |
| `source/` | Complete source code for the reviewed version, including dependency lock files and configuration examples. Exclude generated dependency folders, build output, secrets, and private data. |
| `verification/README.md` | A reviewer can follow these steps to call the health check and one real capability endpoint. Include expected success and safe error behavior. |

## Validation before opening a PR

Run the project from a clean checkout, verify the deployed endpoints, and check that the commit in `SUBMISSION.md` is the version behind the running API. The PR should contain no tokens, private keys, production credentials, personal data, or intentionally harmful code.

## Review behavior

Reviewers may use the public API, source, dependency metadata, and the stated verification steps. If access is protected, send time-limited review access using the program's private channel; never place it in the pull request. A missing API, incomplete source, unverifiable commit, or security concern blocks acceptance until resolved.

Submitted source is treated as an untrusted review artifact. The marketplace package's CI does not install, build, or execute it; project-specific validation happens only in an isolated review environment with the submitter's documented steps.

## Automated online gate

The health check must be public and return `status: ok|healthy` plus the exact `reviewCommit` as `commit`, `version`, or the `x-source-commit` response header. The API origin must also expose `/.well-known/xagent-verification.json` with `schemaVersion: 1`, the directory slug, and the same commit.

For an offline preflight:

```bash
npm run validate:submission -- --dir submissions/mcp-hackathon/<team>-<project>
```

The GitHub pull request workflow adds online checks for the public source commit and deployed service. Passing automation proves that the artifact is reachable and version-bound; it does not prove product quality. Quality is evaluated separately with [`docs/review-scorecard.md`](../docs/review-scorecard.md).

Validated PR commits are copied to unique branches in the official repository. Rewards are issued only after merge and an immutable acceptance release; see [`docs/submission-retention-and-reward.md`](../docs/submission-retention-and-reward.md).
