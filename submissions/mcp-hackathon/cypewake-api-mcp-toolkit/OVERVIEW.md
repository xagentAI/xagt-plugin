# MCPForge v2 — delivery overview

## 1. Market fit

| Pain | MCPForge capability | Typical competitor gap |
|---|---|---|
| Tool explosion: three servers (GitHub + Slack + Sentry) eat 72% of a 200k token budget; MCP-Atlas attributes 36% of agent failures to calling no tool | Curation: 19 raw endpoints down to 5 intent-driven tools | Most converters export everything |
| No verifiability: converters inherit spec quality, garbage in garbage out | Verify counts only real 2xx as passed, separating 401/404/429/5xx | Verification stage usually absent |
| Agents cannot pay for what they call | Metering, tiered invoices, and a listing payload | Monetize is usually a price table |

## 2. Why v1 had to be rebuilt

| # | Problem | Consequence |
|---|---|---|
| 1 | `reachable = True  # any HTTP response counts` | The headline feature cancelled itself: 404/401/500 all green |
| 2 | `_looks_like_path` treated any string containing `/` as a file path | The advertised "pasted text" source always raised `FileNotFoundError` |
| 3 | Code generation spliced raw paths into f-strings | `{account-id}` produced `NameError` |
| 4 | `build_manifest` was essentially printing a dict | Monetize became a slogan with no metering and no invoice |
| 5 | Synchronous httpx inside `async def` | `verify_api` could block up to 300 seconds |
| 6 | No boundaries on local reads, disk writes, or outbound requests | Arbitrary file read, path traversal write, SSRF including cloud metadata |
| 7 | Tool named `ingest_spec`, not the spec's `parse_openapi_spec` | Risked failing the eligibility check |
| 8 | No deployment, no live endpoint | Failed the deployed-and-reachable gate |
| 9 | No tests, no CI, acceptance depended on live internet | Evidence decayed and green lights hid defects |

## 3. Adversarial review

v2 came out of two independent passes run with a clean context and a falsification goal — 24 findings on the technical contract, 12 on competitive viability. Findings are data, not verdicts: three were dismissed as contract misreadings caused by incomplete excerpts handed to the reviewer, and the code was not changed for those.

## 4. What v2 implements

**Fixes:** real status-code truth table for verify; source detection that tries the real thing before guessing the shape; template-plus-`str.replace` URL construction; real metering and invoicing; async HTTP throughout; read, write, and outbound boundaries; contract-aligned tool names.

**New capability:** scope-based tool curation across verify, bundle generation, and manifest; `preview_scope` to see compression before generating; a curation panel on the walkthrough page.

**Engineering:** 53 offline tests plus 6 live tests, offline fixtures so acceptance never depends on the internet, `verify.py` two-layer acceptance, and a `judge_check.py` one-command reviewer script.

**Second review:** found and fixed the SSRF redirect bypass, then locked it with four regression cases.

## 5. Verified results

| Endpoint | Result |
|---|---|
| `GET /api/health` | 200, `{"status":"ok","version":"2.1.0"}` |
| `GET /` | 200, walkthrough page with the curation panel |
| `POST /api/full-pipeline` | 200, full chain including a real call to the GitHub public REST API |
| `/mcp/` over an MCP client | 14 tools, all 7 contract-named tools present, `call_rest_api` reaches `api.github.com/zen` with 200 |
| `/api/real-task` | Three-step chain finishing a real selection brief |

Deployed at https://mcpforge-cypewake.app.workbuddy.host with the pinned review commit `3db59e3afed8e1de2929197dc107b328701d7a22`.

## 6. Known limitations

- The hosted demo is a single process with no authentication, intended to stay reachable for the review window only.
- Metering persists to a local `usage.json`; it is not a durable billing store.
- Live calls depend on outbound access to `api.github.com`. Where the host blocks it, the real-task endpoint falls back to a recorded evidence snapshot and labels the source.
- Curation intent matching is lexical, not embedding-based.

## 7. Submission status

| Item | Status |
|---|---|
| Fork, directory rename, and PR | Done — PR #61 against `xagentAI/xagt-plugin:main` |
| Required artifacts | `SUBMISSION.md`, `submission.json`, `RIGHTS.md`, `verification/README.md`, `source/` |
| Deployed API with proof endpoints | Done, both return the pinned commit |
| Keep reachable Sept 20 – Oct 1 | Owner action: leave the deployment running |
