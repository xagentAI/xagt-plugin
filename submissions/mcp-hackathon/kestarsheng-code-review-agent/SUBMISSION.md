# Code Review Agent

## Capability

- **One-line description:** Dual-engine code review: rule-based static analysis + LLM semantic review with cross-validation, returning a structured quality report so AI-generated code can be checked before merge.
- **Who it helps:** Developers using AI coding tools (Claude Code, Codex, Cursor) and any AI Agent that needs a code-quality gate.
- **Capability boundary:** Accepts a single code snippet (up to 60 000 chars), a unified diff, or multiple files (structured list), plus optional language and context. Returns a JSON report with score (0-100), grade (A-D), five-dimension scores (correctness, security, performance, maintainability, best_practice), issues (with source attribution: rule/llm/confirmed, fix_code), strengths and improvements. The rule engine covers 26 built-in rules across Python, JavaScript, Java, Go, and Rust. Also provides MCP tools (7 total) and a CLI for git-diff review. Does not execute, compile, or persist submitted code.

## Live API

- **API base URL:** https://code-review-agent-ashy-six.vercel.app/v1
- **Health-check URL:** https://code-review-agent-ashy-six.vercel.app/health
- **Authentication:** none
- **Rate limits / known limits:** Single request limited by LLM provider timeout (120 s). Max code size 60 000 chars. Free-tier hosting may cold-start.
- **API contract:** OpenAPI at `/docs`; request `POST /v1/review` body `{"code": string, "language"?: string, "context"?: string}`, response `{"ok": true, "language": string, "model": string, "report": ReviewReport}`. Also supports `POST /v1/review_diff` (unified diff input) and `POST /v1/review_files` (multi-file batch review). MCP endpoint at `/mcp` with 7 tools.

## Source and reproducibility

- **Source repository:** https://github.com/kestarsheng/code-review-agent
- **Review commit:** `a4b5d3d`
- **Source submitted in this PR:** `source/`
- **Run tests:** `pip install -r requirements.txt && pytest tests/ -v`
- **Run locally:** `pip install -r requirements.txt && uvicorn app.main:app --reload`
- **Deploy:** `docker build -t code-review-agent . && docker run -p 8000:8000 code-review-agent`, Render Blueprint from `render.yaml`, or Vercel (current production deployment).
- **Version binding:** `GET /health` returns `{"status":"ok","commit":"<commit>"}`; `GET /.well-known/xagent-verification.json` returns `{"schemaVersion":1,"slug":"kestarsheng-code-review-agent","commit":"<commit>"}`. The commit is injected via the `COMMIT` environment variable at deploy time.

The API must expose:

```json
// GET /health
{"status":"ok","commit":"a4b5d3d"}
```

```json
// GET /.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"kestarsheng-code-review-agent","commit":"a4b5d3d"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `{"status":"ok","commit":"a4b5d3d..."}`
- **Capability call:** `POST /v1/review` with `{"code":"def f(x): return x/0","language":"python"}`
- **Expected error behavior:** Empty body → 422; oversized code → 413; LLM failure → 502 `{"ok":false,"error":"..."}`.

## Security and data handling

- **Data collected:** Submitted code snippet, language hint, optional context. No authentication, no user identifiers.
- **Purpose and retention:** Code is sent to the configured LLM provider (DeepSeek) for review only. The service does not persist submitted code to any database or log.
- **Third parties / outbound network calls:** DeepSeek API (OpenAI-compatible protocol) for LLM inference.
- **Secrets:** No secrets are committed. `LLM_API_KEY` is set as a deployment environment variable and never appears in source.
- **Known risks / restrictions:** Vercel serverless functions have a 10 s default timeout; long code reviews may approach this limit. The LLM may occasionally produce imperfect JSON; the parser tolerates fenced/embedded JSON.

## Support

- **Team / builder:** kestarsheng (刘宇珂)
- **Contact:** 2410251355@henu.edu.cn
- **License / rights:** UNLICENSED — submission-only use for X-Agent AI MCP Hackathon 2026. Submitter owns all source and authorizes review and post-award retention.