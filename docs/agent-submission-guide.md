# Submit with Codex, Claude Code, or another coding agent

Vibe-coded projects are welcome. A coding agent can prepare the source package, verify the deployment, run the official checks, and open the pull request. The evidence requirements are the same for human-written and agent-written projects.

## Before asking an agent to submit

Have these facts ready:

- the project source directory;
- the public GitHub repository and exact deployed Commit;
- the deployed HTTPS API and health endpoint;
- one real capability request and expected response;
- the project owner, licenses, data use, external services, and support contact;
- a GitHub account authorized to fork and push.

The agent must not guess missing evidence. Deploying a service or creating paid infrastructure is separate from preparing a submission and may require additional authorization.

## Copy this prompt

```text
Submit the project in the current directory to the X-Agent MCP Hackathon.

Follow the official workflow at:
https://github.com/xagentAI/xagt-plugin/blob/main/skills/xagt-submit-hackathon/SKILL.md

Project details:
- Project name: <name>
- Submission slug: <team-project>
- Public source repository: <https://github.com/owner/repo>
- Exact deployed Commit: <40-character Commit>
- API base URL: <https://api.example.com/v1>
- Health endpoint: <https://api.example.com/health>

You are authorized to fork xagentAI/xagt-plugin, create a submission branch,
push the validated package, and open a pull request.

Do not expose secrets or private data. Do not fabricate API responses,
deployment state, ownership, tests, or Commit evidence. If the live API cannot
prove the exact Commit, stop and tell me what is missing instead of submitting.
```

This prompt works with Codex, Claude Code, Cursor, OpenCode, and other coding agents that can read repositories and use Git/GitHub. If you only want a preview, replace the authorization paragraph with: `Prepare and validate the package, but do not push or open a pull request.`

## Repository-native instructions

- Codex reads the root [`AGENTS.md`](../AGENTS.md).
- Claude Code reads the root [`CLAUDE.md`](../CLAUDE.md), which imports the shared instructions.
- AgentSkills-compatible runtimes can use [`xagt-submit-hackathon`](../skills/xagt-submit-hackathon/SKILL.md).

The plugin installer copies both the X-Agent setup skill and the hackathon submission skill into supported runtimes.

## What the agent must deliver

The agent should return:

- the pull request URL, or a clear statement that publishing was not authorized;
- the submission slug and exact source Commit;
- the live API and version-proof result;
- offline and online validation results;
- any missing evidence, failed check, or unresolved risk.

Opening a pull request does not mean the project has passed review or been accepted by X-Agent or OKX.
