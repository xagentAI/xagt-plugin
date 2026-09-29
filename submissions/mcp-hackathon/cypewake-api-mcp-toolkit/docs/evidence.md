# MCPForge — verification evidence

> For reviewers: links, commands, and recorded outputs that back every claim in this submission.

## 1. Live deployment

```bash
curl --fail --silent --show-error https://mcpforge-cypewake.app.workbuddy.host/api/health
curl --fail --silent --show-error https://mcpforge-cypewake.app.workbuddy.host/.well-known/xagent-verification.json
```

Both return commit `3db59e3afed8e1de2929197dc107b328701d7a22`, which matches `reviewCommit` in `submission.json`.

## 2. Reproduce locally, no deployment needed

```bash
cd submissions/mcp-hackathon/cypewake-api-mcp-toolkit
pip install "fastmcp>=4.0,<5.0"
uvicorn demo_app:app --port 8000     # one process: walkthrough page, health, MCP endpoint
```

- `GET /api/health` → `{"status":"ok","version":"2.1.0"}` (HTTP 200)
- `GET /` → four-stage walkthrough page, including the tool curation panel (HTTP 200)
- `GET /api/config` → pricing tiers and configuration (HTTP 200)
- `POST /api/preview-scope` → preview curation results (HTTP 200)
- `POST /api/full-pipeline` → end-to-end chain (see `docs/full_pipeline_result.json`)
- `POST /api/real-task` → the three-step real task described below

## 3. The real task (GitHub public API, not a toy spec)

To show the tools are genuinely useful and online-callable, the showcase wraps the **GitHub public REST API** (`api.github.com`, keyless, a realistic agent target). `examples/run_real_showcase.py` runs Build → Verify → MCPize → Monetize against the real internet; raw output is `examples/real_showcase_result.json`.

| Metric | Result |
|---|---|
| Verify, real 2xx | **3/3 passed** (HTTP 200 on `/zen`, `/rate_limit`, `/events`) |
| Metered calls | 6 real 2xx calls, 100% success, per-operation latency |
| Billing | pro tier, $8.00 per 1k calls, billed from real usage (pay-per-call) |
| Listing | 3 callable tools, pay-per-call model, USD |
| Compliance flags | `contains_security_audit_capability: false`, `crypto_token_speculation: false` |

`examples/real_agent_task.py` goes further and finishes a multi-step job: search → verify each candidate at the source → aggregate a selection brief. See the README for the recorded results.

## 4. One-command review script

```bash
python docs/judge_check.py --url http://127.0.0.1:8000
```

Expected result (exit code 0):

```
target: http://127.0.0.1:8000 (single local process: uvicorn demo_app:app)
[PASS] health check GET /api/health — HTTP 200 status=ok version=2.1.0
[PASS] four-stage walkthrough page GET / — HTTP 200, 15770 bytes
[PASS] pricing tiers readable GET /api/config — tiers=['free','basic','pro','enterprise'] currency=USD
[PASS] MCP endpoint lists tools — 14
[PASS] all 7 contract-named tools present — complete
[PASS] tool call: health_check — status=ok
[PASS] tool call: parse_openapi_spec on local Petstore-style spec — 5 operations
[PASS] tool call: list_operations — 276 chars, contains getPetById
[PASS] tool call: call_rest_api, real outbound (GitHub public REST API) — HTTP 200
[PASS] tool call: generate_mcp_tool_code — 59 lines of deployable FastMCP source
[PASS] tool call: register + call_registered_api(getZen), real outbound — HTTP 200
result: 11 passed / 0 failed
```

The full captured run is `docs/judge_check_result.txt`.

## 5. Full pipeline response

`POST /api/full-pipeline` with:

```json
{ "spec_source": "https://petstore3.swagger.io/api/v3/openapi.json", "pricing_tier": "basic" }
```

| Stage | Result |
|---|---|
| build | Parsed Petstore OpenAPI 3.0, 19 operations, base_url detected |
| verify | 10 endpoints probed, 1 passed, 9 marked reached-but-failed due to auth or status |
| mcpize | Generated 19 FastMCP tools into `/workspace/generated/petstore-mcp` |
| register | 19 operations registered under `petstore` |
| call | Real call to `loginUser` returned HTTP 200 |
| monetize | basic tier config, USD 2.00 per 1k calls |
| invoice preview | Projected from real call volume: USD 180.0 |

Full response in `docs/full_pipeline_result.json`; summary in `docs/full_pipeline_summary.md`.

## 6. Tests and acceptance

```bash
python -m pytest            # 53 offline tests, deterministic, no network
python -m pytest -m live -v # 6 live tests against public APIs
python verify.py            # two-layer acceptance, writes verification-evidence.md
python examples/build_examples.py   # regenerate the example bundles
python examples/real_agent_task.py  # run the real task end to end
```

## 7. Requirement-by-requirement status

| Requirement | Status | Evidence |
|---|---|---|
| Pull request against `xagentAI/xagt-plugin` | Done | PR #61, branch `submit-cypewake-api-mcp-toolkit` |
| Directory at `submissions/mcp-hackathon/<user>-api-mcp-toolkit/` | Done | `submissions/mcp-hackathon/cypewake-api-mcp-toolkit/` |
| All seven contract tools present | Done | `judge_check.py` check 5 |
| Deployed, reachable API | Done | health and deployment-proof endpoints above |
| No security/audit/on-chain surface | Done | source contains only generic API→MCP conversion |
| README, requirements, pyproject | Done | repository root |
| Verification evidence | Done | this file, `verification/README.md`, screenshots, `judge_check_result.txt` |
