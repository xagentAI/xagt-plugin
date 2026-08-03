# X-Agent MCP Hackathon & Agent Plugin

English | [简体中文](./README.zh-CN.md) | [日本語](./README.ja.md)

> **Current program: submit a real, callable capability. X-Agent verifies the API and source, standardizes selected projects as MCP tools, and supports their submission to the OKX Agent ecosystem.**

This repository is the official code-submission hub for the current X-Agent MCP Hackathon. It also contains the `@xagt/agent-plugin` installer.

## Current program: X-Agent MCP Hackathon

The MCP Hackathon is not limited to predefined tracks, languages, frameworks, or project types. Builders may submit any useful capability that an AI agent can call to complete a real task.

You do **not** need to implement MCP before applying. You provide a working capability, a live API, and the complete source. X-Agent handles MCP standardization with selected teams after verification.

### The program in one flow

```text
Callable capability
        ↓
Deployed API + complete source submitted by PR
        ↓
API, commit, source, and safety verification
        ↓
X-Agent MCP standardization
        ↓
OKX Agent ecosystem submission support
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

MCP, Streamable HTTP, x402, EIP-3009, A2MCP, and payment SDKs are not required at submission time.

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

An external repository link alone is not enough. The complete reviewed source must be present under `source/` so the official record remains available if a fork or external repository is later deleted.

Start with:

- [`Full submission contract`](./submissions/README.md)
- [`submissions/TEMPLATE.md`](./submissions/TEMPLATE.md)
- [`submissions/submission.example.json`](./submissions/submission.example.json)
- [`submissions/RIGHTS_TEMPLATE.md`](./submissions/RIGHTS_TEMPLATE.md)
- [`submissions/VERIFICATION_TEMPLATE.md`](./submissions/VERIFICATION_TEMPLATE.md)

### Submit in four steps

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

Passing automation proves reachability and version binding. It does not prove quality, ownership, security, or eligibility; those require manual review.

### Rules that protect both builders and the program

- Submit only code, services, dependencies, data, and branding that you have the right to submit and authorize for review.
- Do not commit credentials, private customer data, malware, backdoors, credential theft, hidden data exfiltration, abusive automation, or undisclosed third-party calls.
- Plagiarism, fake deployment evidence, false ownership, purchased engagement, identity manipulation, or coordinated scoring abuse results in rejection.
- Keep the API reachable during the announced review window. Share any short-lived review credential only through the approved private channel, never through Git.
- A missing API, incomplete source, unverifiable commit, non-reproducible deployment, or serious safety concern blocks acceptance.
- Closing an unmerged PR withdraws the entry. A merged and rewarded entry remains in the official archive under the submitted rights declaration.

### Updates, archival, and reward release

Builders may keep pushing fixes to an open PR. There is no need to rush a merge:

1. Every new PR head reruns verification; every successfully validated head receives its own official archive reference.
2. A new push invalidates earlier verification and review context; X-Agent evaluates only the exact latest version.
3. The final accepted version is merged with its complete source.
4. X-Agent reruns online verification, creates an integrity receipt and source archive, and publishes an immutable acceptance release.
5. Reward approval happens only after the accepted artifact is sealed and independently backed up.
6. Later improvements use a new PR and release. They never overwrite the rewarded snapshot.

The submitter can delete their fork or external repository without deleting the official copy. Full operating rules are in [`Submission retention and reward`](./docs/submission-retention-and-reward.md).

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

Historical records: [May 2026 program archive](./docs/archive/2026-xagent-okx-agentic-wallet-hackathon.md) · [submission index](./submissions/INDEX.md)
