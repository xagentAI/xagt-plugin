# X-Agent MCP Hackathon

> **Submit a real, callable capability. X-Agent verifies it, standardizes it as MCP, and supports its submission to the OKX Agent ecosystem.**

![X-Agent Hackathon](docs/images/hackathon-banner.png)

This repository is the official contribution hub for the X-Agent MCP Hackathon. It is for builders with a useful AI capability, API, agent, data service, or application — not only for people who already know MCP.

We do not prescribe tracks or example categories. If your project solves a real problem and an agent can call it, it can be submitted.

## The program in one flow

```text
Your callable capability
        ↓
Deployed API + complete source submitted by PR
        ↓
X-Agent verification
        ↓
X-Agent MCP standardization
        ↓
OKX Agent ecosystem submission support
```

An entry is evaluated as a working capability, not as an idea deck. X-Agent assists with MCP productization after verification; it does not promise acceptance, listing, traffic, or revenue from OKX.

## What to submit

Every entry must include all of the following:

1. A live API that reviewers can call during the review window, including a public health-check endpoint.
2. Complete, reviewable source code in this repository through a pull request.
3. A pinned commit that identifies the version connected to the deployed API.
4. Reproducible setup, test, and deployment instructions.
5. API contract, example request/response, authentication notes, and known limits.
6. A machine-readable deployment proof that binds the public service to the submitted project slug and commit.
7. Security and data-handling notes. Do not submit secrets, malicious code, undisclosed external behavior, or unauthorized data collection.

MCP, Streamable HTTP, x402, EIP-3009, A2MCP, and payment SDKs are **not required** at submission time. X-Agent handles the MCP standardization work with selected teams.

## Where code is submitted

Open a pull request that adds one directory under [`submissions/`](./submissions/):

```text
submissions/<team-or-builder>-<project-slug>/
├── SUBMISSION.md          # capability, live API, commit, and review details
├── submission.json        # machine-readable source and deployment binding
├── RIGHTS.md              # ownership and continuing archive authorization
├── source/                # complete source code used for review
└── verification/          # reproducible API call evidence and notes
```

Start from [`submissions/TEMPLATE.md`](./submissions/TEMPLATE.md). The complete source must be present under `source/`; an external GitHub URL alone is not sufficient for verification. Keep source history, generated secrets, large build artifacts, and private customer data out of the PR.

## Submit in four steps

1. Build and deploy a real API. Confirm its health check and an example capability call work.
2. Fork this repository and create a branch.
3. Generate a starter manifest, then copy the template and your complete source into `submissions/<team-or-builder>-<project-slug>/`.
4. Open one pull request against `main`. The PR is the official submission and review record.

```bash
npx @xagt/agent-plugin@latest submit \
  --name "Project name" \
  --slug "team-name-project-name" \
  --intro "One sentence describing the real task this capability completes" \
  --repo "https://github.com/you/project" \
  --api "https://api.example.com/v1" \
  --health "https://api.example.com/health" \
  --commit "<40-character-git-commit>"
```

The command writes a ready-to-copy `SUBMISSION.md` and `submission.json`. It does not upload code or replace the required PR review.

For the exact fields, sample evidence, review outcomes, and rules, read [`submissions/README.md`](./submissions/README.md) and [`docs/mcp-hackathon.md`](./docs/mcp-hackathon.md).

## Activity rules

- Submit only work you have the right to submit, deploy, and authorize for review.
- Keep the API reachable for the stated review window; disclose access credentials through the private review channel when needed, never in Git.
- Make source, dependencies, configuration, build, test, and deployment steps sufficient for a reviewer to reproduce the service.
- Bind the running service to a specific commit and report material changes after submission in the same PR.
- Do not include malware, backdoors, credential theft, hidden data exfiltration, abusive automation, or undisclosed third-party calls.
- Plagiarism, fake deployment evidence, false ownership claims, purchased engagement, identity manipulation, or coordinated scoring abuse results in rejection.
- Closing an unmerged PR withdraws the entry. Rewards are released only after complete source is merged into the official repository, copied to an official archive ref, and sealed in an immutable acceptance release.
- X-Agent may request fixes, reject an unsafe or unverifiable entry, or re-review a materially changed project. The program review is not legal, regulatory, security, or OKX approval.

## Online proof of deployment

The public health check must return the exact reviewed commit:

```json
{"status":"ok","commit":"<40-character-review-commit>"}
```

The same API origin must expose `/.well-known/xagent-verification.json`:

```json
{"schemaVersion":1,"slug":"team-name-project-name","commit":"<40-character-review-commit>"}
```

The pull request workflow checks the submission scope, required source package, obvious secret patterns, public GitHub commit, health check, and deployment proof. It uses a trusted validator from the base branch and never installs, builds, imports, or executes submitted source code.

After these checks pass, the exact PR commit is copied into a unique official `submission-archive/` ref. The participant can then delete their fork without deleting X-Agent's archived copy. Full retention and pre-payment rules are in [`docs/submission-retention-and-reward.md`](./docs/submission-retention-and-reward.md).

Participants may update an open PR, but each new head is archived separately, reruns verification, and invalidates stale approval. X-Agent rewards one exact merged commit and immutable release; later improvements require another PR and never replace the rewarded snapshot.

## How X-Agent reviews entries

| Gate | What we check |
| --- | --- |
| Callable | The API and health check respond; the documented task can be exercised. |
| Real and maintainable | The complete source, pinned commit, dependency lock, and instructions correspond to the deployed service. |
| Safe to evaluate | No secrets, malicious behavior, serious unauthorized access, or undisclosed data flows. |
| Useful for agents | The capability boundary, inputs, outputs, errors, and constraints are clear enough to turn into an Agent tool. |

Outcomes are **pass**, **conditional pass** (fixes required), or **not accepted**. Scoring starts only after the hard gates pass. Reviewers then use the evidence-based [`review scorecard`](./docs/review-scorecard.md). A passing project proceeds to MCP productization; X-Agent may then prepare an OKX-facing submission package with the team.

## Plugin setup (optional)

The CLI can install X-Agent and OKX skills into common agent runtimes. This is optional for submitting a capability.

```bash
npx @xagt/agent-plugin@latest install --target all
xagt-plugin doctor
```

Supported targets: Cursor, Claude Code, Codex, OpenCode, and AgentSkills-compatible runtimes. Node `>= 18.17` is required.

## Repository development

```bash
npm ci
npm run lint
npm test
npm run build
npm run validate:submission -- --dir submissions/<team>-<project>
npm run validate:submission -- --dir submissions/<team>-<project> --online
```

The offline command checks the package, source limits, verification evidence, and baseline secret patterns. The online command additionally verifies the public GitHub commit and the two live deployment endpoints.

License: UNLICENSED — program use only unless a separate written license applies.
