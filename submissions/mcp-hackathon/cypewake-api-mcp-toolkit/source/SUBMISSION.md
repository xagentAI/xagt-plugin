# MCPForge — API-to-MCP Factory

> Filled from the official `submissions/TEMPLATE.md`. Deployment URL and review commit are the live values verified in `verification/README.md`.

## Capability

- **One line:** turns an existing REST API into MCP tools an AI agent can call, covering the four official stages — **Build → Verify → MCPize → Monetize**.
- **Who it serves:** developers and teams connecting internal or third-party REST APIs to agents.
- **Scope:** takes an OpenAPI/Swagger description or a live API and produces deployable MCP tools, real verified calls, and per-call billing. No security, audit, or on-chain risk surface — the track's disqualifying categories do not apply.

## Live API

- **API base URL:** `https://mcpforge-cypewake.app.workbuddy.host`
- **Health-check URL:** `https://mcpforge-cypewake.app.workbuddy.host/api/health`
- **Auth:** none. Public and keyless for the review window.
- **Rate limits / known limits:** single-process demo; live calls depend on `api.github.com` reachability from the host.
- **API contract:** `source/examples/github-openapi.json` and generated code under `source/examples/*/server.py`.

## Source and reproducibility

- **Source repository:** https://github.com/cypewake/xagt-plugin
- **Review commit:** `3db59e3afed8e1de2929197dc107b328701d7a22`
- **Source submitted in this PR:** `source/`
- **Run tests:** `pip install -r source/requirements.txt && pytest source/tests` (53 offline + 6 live-marked, all green)
- **Run locally:** `pip install "fastmcp>=4.0,<5.0"` then `uvicorn demo_app:app --host 0.0.0.0 --port 8000`
- **Deploy:** `uvicorn demo_app:app --host 0.0.0.0 --port $PORT` with `REVIEW_COMMIT=3db59e3afed8e1de2929197dc107b328701d7a22`
- **Version binding:** the deployment exposes the review commit through `REVIEW_COMMIT`; `/api/health` and `/.well-known/xagent-verification.json` both return it.

The deployment returns exactly:

```json
// GET https://mcpforge-cypewake.app.workbuddy.host/api/health
{"status":"ok","commit":"3db59e3afed8e1de2929197dc107b328701d7a22"}
```

```json
// GET https://mcpforge-cypewake.app.workbuddy.host/.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"cypewake-api-mcp-toolkit","commit":"3db59e3afed8e1de2929197dc107b328701d7a22"}
```

## Verification

Reproducible call instructions and redacted sample responses live in `verification/README.md`.

- **Health-check result:** `status=ok`, `commit=3db59e3afed8e1de2929197dc107b328701d7a22`.
- **Capability call:** over the MCP endpoint, `call_rest_api` against GitHub `/zen`, or `register(github_live)` followed by `call_registered_api(getZen)`, both return HTTP 200.
- **Expected error behavior:** an unregistered API name returns an explicit error; a private-network URL is rejected by `assert_public_url` (SSRF guard).

## Real task

The heaviest scoring dimension asks whether the entry completes a meaningful real task rather than a prompt demo. This entry answers with a task that depends on live data.

**Task:** build a technology selection brief for a topic (default `model-context-protocol`).

**Why a prompt cannot do it:** the answer rests on live stars, forks, open issues, and last-push timestamps. Those change daily, so a model recalling training data returns wrong numbers. The tools have to go back to the source.

**Three-step orchestration**, every step a real HTTP call, re-runnable on the deployed page:

1. `searchRepositories` — find candidate repositories.
2. `getRepository` — verify each candidate at the source, since search summaries go stale.
3. Local aggregation — rank and emit the brief.

**Latest real result** (full evidence: `source/examples/real_agent_task_result.json`):

| # | Repository | Stars | Forks | Open issues | Language |
|---|---|---:|---:|---:|---|
| 1 | modelcontextprotocol/servers | 90,384 | 11,640 | 536 | TypeScript |
| 2 | HKUDS/nanobot | 48,216 | 8,523 | 784 | Python |
| 3 | DeusData/codebase-memory-mcp | 43,513 | 3,541 | 591 | C |

**Monetization figures:** metering recorded 24 calls for this API. At the pro tier ($8.00 per 1k calls, 50,000 included), scaling to 1,000,000 calls per month gives **7,600 USD/month** (field `invoice_scaled`). The actual invoice reads 0 USD because usage stays inside the free quota — expected behavior, not a broken meter — so the evidence ships both an actual-basis and a scaled-basis invoice.

**Reproduce live:** open the deployment → "Real task" section → run it; or `POST /api/real-task` (defaults to the live JSONPlaceholder sample) / `POST /api/real-task {"api":"github"}` to see each real call with its status code.

## Security and data handling

- **Data collected:** none persisted. Usage counters live in process memory and in the local `usage.json` store.
- **Purpose and retention:** metering exists to demonstrate per-call billing. No long-term retention.
- **Third-party / outbound:** only `api.github.com` for live verification; `assert_public_url` plus per-hop redirect validation blocks private-network pivots (SSRF).
- **Secrets:** none committed. Review access is granted only through approved channels.
- **Known risks / limits:** the demo service has no authentication and is meant to stay reachable for the review window (Sept 20 – Oct 1).

## Support

- **Author:** cypewake
- **Contact:** GitHub @cypewake
- **Rights:** the submitter owns the source and grants X-Agent the right to review and archive it.

## Identity mapping

> For reviewer reconciliation: both identifiers below are the same participant.

| Channel | Identifier |
| --- | --- |
| Luma registration (Open Innovation track) | **wake** |
| GitHub account / PR author | **cypewake** |
| Public deployment domain | mcpforge-cypewake.app.workbuddy.host |
| This PR | xagentAI/xagt-plugin#61 |

To match the registration record against this PR: `wake` (Luma) = `cypewake` (GitHub), one person.
