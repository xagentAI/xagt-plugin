# MCPForge — API to MCP Factory (Open Innovation)

Turn any OpenAPI-described REST API into MCP tools an agent can call, verify, and pay for, running the full **Build → Verify → MCPize → Monetize** chain.

## Live

- API base: https://mcpforge-cypewake.app.workbuddy.host
- Health: https://mcpforge-cypewake.app.workbuddy.host/api/health
- Deployment proof: https://mcpforge-cypewake.app.workbuddy.host/.well-known/xagent-verification.json
- Review commit: `3db59e3afed8e1de2929197dc107b328701d7a22`

Both proof endpoints return the pinned commit, and the deployed code matches that commit in the public fork.

## What it does

| Stage | Implementation |
|---|---|
| Build | Resolves `$ref`, merges path-level with operation-level parameters, detects auth schemes and pagination, supports OpenAPI 2.0 and 3.x |
| Verify | Concurrent real calls; **only HTTP 2xx counts as passed**; 401/403/404/429/5xx classified separately |
| MCPize | Generates runnable bundles — URL from a template with `str.replace`, escaped docstrings, retries, pinned version line |
| Monetize | Meters every call to disk (atomic write), reports usage, bills by tier, projects the observed daily rate to 30 days |

14 MCP tools, including all 7 named in the delivery spec.

## Why it is more than a converter

`examples/real_agent_task.py` finishes a job a prompt cannot: search GitHub for MCP-related projects, verify each candidate at the source, and rank by live stars, forks, issues, and last push. Recorded result: `modelcontextprotocol/servers` at 90,384 stars. Those numbers change daily, so a model answering from memory returns wrong values.

The same run meters real calls and projects **7,600 USD/month at 1,000,000 calls** (pro tier: 50,000 included, $8.00 per additional 1,000).

## Reproduce

```bash
pip install -r requirements.txt
python docs/judge_check.py --url http://127.0.0.1:8000   # 11/11, exit 0
pytest                                                    # 53 offline tests
pytest -m live -v                                         # 6 live tests
python examples/real_agent_task.py                        # the real task
```

## Submitter confirmation

- [x] I own or have sufficient rights to submit this work.
- [x] The submission sits in a single directory: `submissions/mcp-hackathon/cypewake-api-mcp-toolkit/`.
- [x] `SUBMISSION.md`, `submission.json`, `RIGHTS.md`, `verification/README.md`, and `source/` are present.
- [x] A deployed API is reachable and returns the pinned review commit.
- [x] The pinned commit is publicly visible in the source repository.
- [x] No secrets are included.
- [x] No security, audit, or on-chain risk surface; no token speculation. Currency defaults to USD.
- [x] The deployment will stay reachable through the review window (Sept 20 – Oct 1).
- [x] Identity: Luma registration **wake** = GitHub **cypewake**, same participant.

## Compliance

Generic API and MCP engineering. The SSRF guard protects the tool as an HTTP client and produces no security assessment, score, or alert. Invoices default to USD (`MCPFORGE_CURRENCY` overrides). No position in any token.
