# docs/ — review material

## One command to check the submission

`python docs/judge_check.py --url http://127.0.0.1:8000` verifies all of the following and exits non-zero on any failure:

| # | Check | Requirement it covers |
|---|---|---|
| 1 | `GET /api/health` returns `status=ok` | Live evidence |
| 2 | `GET /` returns the full four-stage walkthrough page | Visual demo |
| 3 | `GET /api/config` exposes pricing tiers | Monetize has a real pricing basis |
| 4 | The MCP endpoint lists tools | It is a real MCP service, not an HTTP shell |
| 5 | All 7 contract-named tool names present | Eligibility check |
| 6 | `health_check` is callable | Live evidence |
| 7 | `parse_openapi_spec` parses a local Petstore-style spec | Build |
| 8 | `list_operations` returns a readable inventory | Build |
| 9 | `call_rest_api` reaches the internet (GitHub public REST API `/zen`) | Online-callable capability |
| 10 | `generate_mcp_tool_code` emits deployable source | MCPize |
| 11 | `register` + `call_registered_api(getZen)` completes a real call | End-to-end |

## Two things worth a closer look

1. **Verify counts only HTTP 2xx as passed.** Many implementations treat any response as success, which makes the metric permanently true and worthless. See `classify_response` in `core.py`.
2. **Redirects are re-validated hop by hop.** `follow_redirects=True` validates only the initial URL, so a public URL that 302s to `127.0.0.1` or the cloud metadata endpoint walks straight past the guard. `request_with_validated_redirects` closes that, and four regression cases keep it closed.

## Reproduce everything locally

```bash
pip install -r requirements.txt
python demo_app.py          # or: uvicorn demo_app:app --port 8000
python docs/judge_check.py  # 11/11, exit 0
pytest                      # 53 offline tests
pytest -m live -v           # 6 live tests
```

## Contents

| File | What it holds |
|---|---|
| `evidence.md` | Verification evidence: endpoints, real-task results, pipeline response |
| `MARKET_AND_POSITIONING.md` | Market signals, audience, competitive landscape, differentiation, roadmap |
| `judge_check.py` | One-command reviewer script |
| `judge_check_result.txt` | Captured 11/11 run |
| `full_pipeline_result.json`, `full_pipeline_summary.md` | Full pipeline response and summary |
| `screenshots/` | Chrome headless captures of the walkthrough page and endpoints |
