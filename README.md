# X-Agent AI MCP Hackathon 2026 & Agent Plugin

English | [简体中文](./README.zh-CN.md) | [日本語](./README.ja.md)

[![X-Agent AI MCP Hackathon 2026 — September 2 to October 4; 1,000 USDT and 100,000 X-Points](https://xagt.ai/hackathon/og-cover.jpg)](https://xagt.ai/hackathon?lang=en)

> **Build live, verifiable Agent and MCP applications with real-world utility. Two tracks, 1,000 USDT + 100,000 X-Points in total rewards. September 2–October 4, 2026.**

This repository is the official code-submission hub for the X-Agent AI MCP Hackathon 2026. It also contains the `@xagt/agent-plugin` installer.

[Event page and rules](https://xagt.ai/hackathon?lang=en) · [Register on Luma](https://luma.com/h0qt02e4) · [Telegram community](https://t.me/XAgent_official)

Previous program: [X-Agent × OKX Agentic Wallet Hackathon · May 2026](./docs/archive/2026-xagent-okx-agentic-wallet-hackathon.md) · [code and submission archive](./submissions/INDEX.md)

## Current program: X-Agent AI MCP Hackathon 2026

Developers and teams worldwide are invited to build useful applications across AI, crypto, data, automation, and agent infrastructure. Choose **one of two tracks**; both submit through this repository and are judged separately. The [event page](https://xagt.ai/hackathon?lang=en) is the reference for the current schedule, rewards, and track rules.

### Choose your track

| Track | What to build | Track prize pool |
| --- | --- | --- |
| **General Challenge (Open Innovation)** | An original, useful API-backed Agent or MCP capability. Deploy it and demonstrate a real, verifiable call. | 500 USDT + 50,000 X-Points |
| **OlaXBT × X-Agent Trading Challenge** | Use OlaXBT Nexus MCP for strategy development, backtesting, performance analysis, and market data. Validate a trading strategy, then build your own Agent or MCP application around it. | 500 USDT + 50,000 X-Points |

OlaXBT sponsors the trading track. A strategy, backtest report, or simple API wrapper alone is **not a complete trading entry**. Start with the [Nexus MCP documentation](https://nexus.olaxbt.xyz/api/mcp/docs) and the [trading challenge rules and developer guide](https://xagt.ai/hackathon/olaxbt-guide?lang=en).

**Excluded from both tracks:** on-chain security and auditing projects, including smart-contract audits, vulnerability or exploit detection, wallet or transaction risk scoring, phishing/scam/Rug Pull detection, security monitoring, and compliance or security analysis.

You do **not** need to build your own MCP server before submitting. You must provide a working capability, a deployed API, and complete source code. This does not waive the trading track's requirement to use OlaXBT Nexus MCP.

### Event timeline

**September 2–October 4, 2026**

| Stage | Dates (2026) | What happens |
| --- | --- | --- |
| Registration & Build | September 2–19 (18 days) | Register, form a team, attend technical onboarding and community Q&A, and develop, deploy, test, and submit your project. Registration and building open together. |
| Technical Review & Judging | September 20–October 1 (12 days) | Eligibility checks, API verification, source-code review, and project scoring. |
| Winner Announcement | October 2–4 (3 days) | Final results are announced through X-Agent's official channels and community. |

### Rewards and project support

The combined prize pool is **1,000 USDT + 100,000 X-Points**. Each track awards:

| Place in each track | USDT | X-Points |
| --- | --- | --- |
| 1st | 500 | 15,000 |
| 2nd | — | 12,000 |
| 3rd | — | 10,000 |
| 4th | — | 8,000 |
| 5th | — | 5,000 |

Rewards are per team, not per member. Selected projects may also receive support for MCP standardization, marketplace integration, ecosystem exposure, and paid-call monetization. Support does not guarantee marketplace acceptance, revenue, or endorsement from OKX or OKX.AI.

### The program in one flow

```text
Register, choose a track, and build a callable capability
        ↓
Deployed API + complete source submitted by PR
        ↓
API, commit, source, and safety verification + judging
        ↓
Selected projects: X-Agent MCP standardization support
        ↓
Marketplace and ecosystem submission support
```

An entry is evaluated as a working capability, not as an idea deck. X-Agent support does not guarantee acceptance, listing, traffic, revenue, or endorsement from OKX.

### Minimum submission requirements

Every entry must include:

1. **A deployed API** that reviewers can call during the review window.
2. **A public health endpoint** that reports the exact reviewed Git commit.
3. **Complete source code** submitted in this repository through a pull request.
4. **A pinned public GitHub commit** corresponding to the deployed service.
5. **Reproducible instructions** for setup, testing, deployment, and one real API call.
6. **A deployment proof endpoint** binding the public service to the project slug and commit.
7. **Security, data, dependency, and rights declarations** sufficient for safe review and long-term archival.

Your own MCP server, Streamable HTTP, x402, EIP-3009, A2MCP, and payment SDK implementations are not required at submission time. Trading entries must still use OlaXBT Nexus MCP as described above.

### Where to submit code

Open one pull request that adds exactly one project directory:

```text
submissions/mcp-hackathon/<team-or-builder>-<project-slug>/
├── SUBMISSION.md          # capability, API, commit, and operating instructions
├── submission.json        # machine-readable source and deployment binding
├── RIGHTS.md              # ownership and archive authorization
├── source/                # complete source used for review
└── verification/
    └── README.md          # repeatable API evidence and expected results
```

An external repository link alone is not enough. Include the actual implementation under `source/`, dependency manifests and applicable lockfiles, configuration examples without secrets, and setup/build/run instructions. Disclose any external APIs or private-service dependencies. A README, submodule, symbolic link, or Git LFS pointer is not a substitute for the source files. Once the official archive is confirmed, deleting the original repository does not delete that archived copy.

Start with:

- [`Full submission contract`](./submissions/README.md)
- [`submissions/TEMPLATE.md`](./submissions/TEMPLATE.md)
- [`submissions/submission.example.json`](./submissions/submission.example.json)
- [`submissions/RIGHTS_TEMPLATE.md`](./submissions/RIGHTS_TEMPLATE.md)
- [`submissions/VERIFICATION_TEMPLATE.md`](./submissions/VERIFICATION_TEMPLATE.md)

### Submit with Codex, Claude Code, or another coding agent

Vibe-coded projects are welcome. A coding agent can package the source, verify the deployed version, run the official checks, and open the PR. The evidence requirements do not change.

Copy this prompt into Codex, Claude Code, Cursor, OpenCode, or another coding agent:

```text
Submit the project in the current directory to the X-Agent MCP Hackathon.
Follow https://github.com/xagentAI/xagt-plugin/blob/main/docs/agent-submission-guide.md
and the official submission skill linked there.

You are authorized to fork xagentAI/xagt-plugin, create a branch, push the
validated package, and open a pull request. Never expose secrets or fabricate
API, deployment, Commit, test, or ownership evidence. Stop if evidence is missing.
```

The repository includes [`AGENTS.md`](./AGENTS.md) for Codex, [`CLAUDE.md`](./CLAUDE.md) for Claude Code, and the reusable [`xagt-submit-hackathon` skill](./skills/xagt-submit-hackathon/SKILL.md). Add the project name, public repository, exact deployed Commit, API URL, and health URL to the prompt. See the [`coding-agent submission guide`](./docs/agent-submission-guide.md) for the complete version.

### Submit in four steps

First, [register on Luma](https://luma.com/h0qt02e4) and choose your track. Complete the following during the September 2–19 build period:

1. Build and deploy the API. Verify its health endpoint and one real capability call.
2. Fork this repository and create a submission branch.
3. Add the five required artifacts under `submissions/mcp-hackathon/<team>-<project>/`.
4. Open a pull request against `xagentAI/xagt-plugin:main` using the MCP Hackathon PR template.

```bash
git clone https://github.com/<your-github-name>/xagt-plugin.git
cd xagt-plugin
git checkout -b submit-team-project

PROJECT_DIR="submissions/mcp-hackathon/team-project"
mkdir -p "$PROJECT_DIR/source" "$PROJECT_DIR/verification"
cp submissions/TEMPLATE.md "$PROJECT_DIR/SUBMISSION.md"
cp submissions/submission.example.json "$PROJECT_DIR/submission.json"
cp submissions/RIGHTS_TEMPLATE.md "$PROJECT_DIR/RIGHTS.md"
cp submissions/VERIFICATION_TEMPLATE.md "$PROJECT_DIR/verification/README.md"

# Edit every placeholder, then copy the complete reviewed source into source/.
git add "$PROJECT_DIR"
git commit -m "submit: team-project"
git push -u origin submit-team-project
```

The repository version of the CLI also generates the three core metadata files after it is built:

```bash
npm ci
npm run build
node dist/cli.js submit \
  --name "Project name" \
  --slug "team-project" \
  --intro "The real task this capability completes" \
  --repo "https://github.com/you/project" \
  --api "https://api.example.com/v1" \
  --health "https://api.example.com/health" \
  --commit "<40-character-git-commit>"
```

The manual path above is the canonical submission path. The generator does not upload source or open the PR for you.

### What happens after you submit

The submission workflows cover the current event under `submissions/mcp-hackathon/`, not historical activity.

| Status | What to expect |
| --- | --- |
| Receipt | One English acknowledgment confirms that the PR was received. An existing official receipt is reused rather than repeated after every push. |
| Automated checks | Open the PR's **Checks** tab and the workflow summary for results. Missing or inconsistent materials need a correction in the same PR; repository permission, checkout, or runner failures need maintainer attention. |
| Source preservation | A separate task rechecks the current version and confirms its official archive. A successful check alone does not establish that archiving finished. |
| Human review | Reviewers assess eligibility, source completeness, reproducibility, rights, and quality. The event team records review decisions and announces final results separately. |

**A receipt, successful check, source archive, or merge for preservation does not mean the entry passed review or won an award. A workflow failure is not a judging decision.** The automation does not approve or merge PRs.

If a receipt is missing or a repository-side error blocks the checks, share the public PR link in the [Telegram community](https://t.me/XAgent_official). Keep the existing PR; do not open a duplicate or post credentials.

### Prove that the deployment is real

The public health endpoint must return the exact reviewed commit:

```json
{"status":"ok","commit":"<40-character-review-commit>"}
```

The same API origin must expose `/.well-known/xagent-verification.json`:

```json
{"schemaVersion":1,"slug":"team-project","commit":"<40-character-review-commit>"}
```

The automated gate verifies the submission scope, required source package, obvious secret patterns, public GitHub commit, health endpoint, and deployment proof. It uses a trusted validator from the base branch and never installs, imports, builds, or executes participant source inside the repository workflow.

Passing automated checks records reachable endpoints and responses that report the declared commit. It does not independently prove that the deployed service was built from the submitted source, that the source is complete, or that the code is secure. Reproducibility, ownership, quality, and eligibility still require human review.

### Rules that protect both builders and the program

- Submit only code, services, dependencies, data, and branding that you have the right to submit and authorize for review.
- Do not commit credentials, private customer data, malware, backdoors, credential theft, hidden data exfiltration, abusive automation, or undisclosed third-party calls.
- Plagiarism, fake deployment evidence, false ownership, purchased engagement, identity manipulation, or coordinated scoring abuse results in rejection.
- Keep the API reachable during the announced review window. Share any short-lived review credential only through the approved private channel, never through Git.
- A missing API, incomplete source, unverifiable commit, non-reproducible deployment, or serious safety concern blocks acceptance.
- Closing an unmerged PR withdraws the entry. A merged and rewarded entry remains in the official archive under the submitted rights declaration.

### Updates, archival, and reward release

While submissions remain open, builders may push updates to the same PR:

1. New versions trigger fresh checks. The preservation task independently rechecks the current version before creating its official archive; superseded or closed PR versions are skipped. A failed archive task remains incomplete.
2. An earlier check result does not apply to changed code. Reviewers evaluate the exact current version and record which commit they reviewed.
3. Maintainers decide whether to merge the complete source. A merge for preservation does not replace a review decision or establish an award.
4. After a recorded final review decision, maintainers separately verify the archived and merged source, recheck the live evidence, and publish an immutable acceptance release containing the source and integrity receipt.
5. Reward approval happens only after the accepted artifact is sealed and independently backed up.
6. Later improvements use a new PR and release. They never overwrite the rewarded snapshot.

Once preservation is confirmed, deleting a fork or external repository does not remove the official archived copy. Independent backup is a separate operational step, not something a green check or an archive in the same GitHub repository guarantees. Full operating rules are in [`Submission retention and reward`](./docs/submission-retention-and-reward.md).

### How entries are reviewed

| Hard gate | What reviewers verify |
| --- | --- |
| Callable | The API and health endpoint respond, and the documented task can be exercised. |
| Real and maintainable | Source, pinned commit, dependencies, and instructions correspond to the deployed service. |
| Reproducible | A reviewer can understand, test, and redeploy the capability from the submitted materials. |
| Safe to evaluate | No secret exposure, malicious behavior, serious unauthorized access, or hidden data flow. |
| Useful for agents | Inputs, outputs, errors, limits, and capability boundaries are clear enough for MCP standardization. |

Outcomes are **pass**, **conditional pass**, or **not accepted**. Scoring begins only after every hard gate passes. Reviewers then use the evidence-based [`review scorecard`](./docs/review-scorecard.md).

Selected teams proceed to MCP productization. X-Agent works with them on tool boundaries, schemas, authorization, errors, limits, observability, and an OKX-facing submission package.

## Agent plugin setup

Plugin installation is optional for the current MCP Hackathon submission. It remains available for Cursor, Claude Code, Codex, OpenCode, and AgentSkills-compatible runtimes.

```bash
npx @xagt/agent-plugin@latest setup --target all
xagt-plugin doctor
```

Node `>= 18.17` is required.

## Repository development

```bash
npm ci
npm run lint
npm test
npm run build
npm run validate:submission -- --dir submissions/mcp-hackathon/<team>-<project>
npm run validate:submission -- --dir submissions/mcp-hackathon/<team>-<project> --online
```

License: UNLICENSED — program use only unless a separate written license applies.
