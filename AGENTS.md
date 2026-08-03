# X-Agent repository instructions for coding agents

## Scope

These instructions apply to repository maintenance and X-Agent MCP Hackathon submissions. Do not treat ordinary maintenance work as a hackathon entry.

## Hackathon submission requests

When a user asks to prepare, validate, submit, or update an MCP Hackathon project:

1. Read `skills/xagt-submit-hackathon/SKILL.md` completely.
2. Follow `submissions/README.md` and `docs/mcp-hackathon.md` as the submission contract.
3. Put new entries only under `submissions/mcp-hackathon/<slug>/`.
4. Do not modify historical records or another participant's directory.
5. Do not fabricate deployment, Commit, test, ownership, or API evidence.
6. Never commit secrets, credentials, private data, dependency folders, or generated build output.
7. Run both offline and online submission validation before opening a PR.
8. Push and open a PR only when the user explicitly asks to submit or otherwise authorizes publishing.

If real deployment evidence is missing, explain exactly what is missing and stop before publishing.

## Repository checks

For code changes, run the applicable checks:

```bash
npm run lint
npm test
npm run build
```

For a submission, also run:

```bash
npm run validate:submission -- --dir submissions/mcp-hackathon/<slug>
npm run validate:submission -- --dir submissions/mcp-hackathon/<slug> --online
```

Keep changes focused and preserve unrelated user work.
