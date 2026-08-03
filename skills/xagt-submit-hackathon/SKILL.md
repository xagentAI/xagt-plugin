---
name: xagt-submit-hackathon
description: Prepare, verify, and submit a project to the X-Agent MCP Hackathon through a GitHub pull request. Use when a builder asks Codex, Claude Code, Cursor, OpenCode, or another coding agent to package source, prove a deployed API, generate submission metadata, validate the entry, or open/update the official submission PR.
---

# Submit to the X-Agent MCP Hackathon

Turn the user's current project into a verifiable submission under `submissions/mcp-hackathon/<slug>/` in `xagentAI/xagt-plugin`.

## Determine the requested boundary

- If the user asks to **prepare** a submission, create and validate the package but stop before pushing or opening a PR.
- If the user asks to **submit**, **open a PR**, or otherwise explicitly authorizes publishing, create the branch, push it, and open the PR after validation.
- Treat deployment, account creation, paid services, wallet actions, and secret sharing as separate actions. Do not infer authorization for them from a request to prepare a PR.

## Require real evidence

Collect or verify all of the following before publishing:

- project name and lowercase hyphenated slug;
- public source repository URL and exact 40-character review Commit;
- deployed public HTTPS API, health endpoint, and same-origin deployment-proof endpoint;
- complete review source, including dependency locks and configuration examples;
- exact setup, test, local-run, deployment, and capability-call instructions;
- data handling, outbound services, known limits, licenses, ownership, and support contact.

Never invent a URL, response, Commit, test result, ownership claim, or deployment state. If the API is not deployed or cannot prove the exact Commit, report the missing evidence and stop before opening the PR.

## Verify the running service

Require the health endpoint to return `status: ok|healthy` and the exact review Commit as `commit` or `version`, or in the `x-source-commit` header.

Require this same-origin endpoint:

```text
/.well-known/xagent-verification.json
```

It must return:

```json
{"schemaVersion":1,"slug":"team-project","commit":"<40-character-review-commit>"}
```

Do not weaken these checks to make an entry pass.

## Prepare the official package

1. Fork or clone `https://github.com/xagentAI/xagt-plugin` separately from the participant project.
2. Create a branch named `submit-<slug>`.
3. Create exactly one directory:

```text
submissions/mcp-hackathon/<slug>/
├── SUBMISSION.md
├── submission.json
├── RIGHTS.md
├── source/
└── verification/README.md
```

4. Start from the templates under `submissions/` or use the repository-built CLI:

```bash
node dist/cli.js submit \
  --name "Project name" \
  --slug "team-project" \
  --intro "The real task this capability completes" \
  --repo "https://github.com/owner/project" \
  --api "https://api.example.com/v1" \
  --health "https://api.example.com/health" \
  --commit "<40-character-git-commit>"
```

5. Copy the complete review source into `source/`. Exclude `.git`, dependency directories, build output, caches, secrets, private data, and unrelated files.
6. Complete every placeholder in the metadata, rights declaration, and verification instructions.

## Protect the user and the repository

- Change only one project directory under `submissions/mcp-hackathon/`.
- Never modify historical submissions or another participant's project.
- Never commit `.env` files, credentials, private keys, access tokens, personal data, or production customer data.
- Never place review credentials in Git. Tell the user to provide short-lived access through the approved private review channel.
- Do not install, import, build, or execute participant source inside the official repository's privileged workflow.
- Reject symlinks, generated dependency folders, files larger than 5 MiB, packages larger than 20 MiB, or more than 2,000 submitted files.
- Do not claim that X-Agent verification guarantees OKX acceptance, listing, traffic, revenue, legality, or security.

## Validate before publishing

From a clean official-repository checkout, run:

```bash
npm ci
npm run validate:submission -- --dir submissions/mcp-hackathon/<slug>
npm run validate:submission -- --dir submissions/mcp-hackathon/<slug> --online
```

Review the final diff and confirm it changes only the intended submission directory. Record the exact validation output. If an applicable check fails, fix the cause or stop; never hide or bypass the failure.

## Open and report the pull request

When publishing is authorized:

1. Commit the exact validated package.
2. Push the submission branch to the user's fork.
3. Open a PR against `xagentAI/xagt-plugin:main` with the hackathon template.
4. Return the PR URL, submission slug, source Commit, deployed API, checks performed, and any unresolved limitation.

The PR is a submission record, not an acceptance decision. New pushes require fresh validation, and rewards bind only to the exact merged and sealed version.
