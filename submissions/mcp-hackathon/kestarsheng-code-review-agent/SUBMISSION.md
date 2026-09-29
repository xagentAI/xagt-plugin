# Code Review Agent

## Capability

- **One-line description:** Triple-engine code review: rule-based static analysis + AST structural analysis + LLM semantic review with cross-validation, returning a structured quality report so AI-generated code can be checked before merge.
- **Who it helps:** Developers using AI coding tools (Claude Code, Codex, Cursor) and any AI Agent that needs a code-quality gate.
- **Capability boundary:** Accepts a single code snippet (up to 60 000 chars), a unified diff, multiple files (structured list), or a GitHub PR/commit URL, plus optional language and context. Returns a JSON report with score (0-100), grade (A-D), five-dimension scores (correctness, security, performance, maintainability, best_practice), issues (with source attribution: rule/ast/llm/confirmed, fix_code), strengths and improvements. The rule engine covers 40 built-in rules across 9 languages (Python, JavaScript, TypeScript, Java, Go, Rust, C/C++, Shell, PHP). AST analyzer catches structural issues (undefined vars, unused imports, duplicate defs). Also provides 10 MCP tools, 12 REST endpoints, SARIF 2.1.0 export, code quality metrics, and a CLI for git-diff review. Does not execute, compile, or persist submitted code.

## Live API

- **API base URL:** https://code-review-agent-ashy-six.vercel.app/v1
- **Health-check URL:** https://code-review-agent-ashy-six.vercel.app/health
- **Authentication:** none
- **Rate limits / known limits:** Single request limited by LLM provider timeout (120 s). Max code size 60 000 chars. Free-tier hosting may cold-start.
- **API contract:** OpenAPI at `/docs`; request `POST /v1/review` body `{"code": string, "language"?: string, "context"?: string}`, response `{"ok": true, "language": string, "model": string, "report": ReviewReport}`. Also supports `POST /v1/review_diff` (unified diff), `POST /v1/review_files` (multi-file batch), `POST /v1/review_pr` (GitHub PR URL), `POST /v1/suggest_fix` (auto-fix), `POST /v1/metrics` (code quality metrics), `POST /v1/sarif` (SARIF 2.1.0 export). MCP endpoint at `/mcp` with 10 tools.

## Source and reproducibility

- **Source repository:** https://github.com/kestarsheng/code-review-agent
- **Review commit:** `69c3d26`
- **Source submitted in this PR:** `source/`
- **Run tests:** `pip install -r requirements.txt && pytest tests/ -v`
- **Run locally:** `pip install -r requirements.txt && uvicorn app.main:app --reload`
- **Deploy:** `docker build -t code-review-agent . && docker run -p 8000:8000 code-review-agent`, Render Blueprint from `render.yaml`, or Vercel (current production deployment).
- **Version binding:** `GET /health` returns `{"status":"ok","commit":"<commit>"}`; `GET /.well-known/xagent-verification.json` returns `{"schemaVersion":1,"slug":"kestarsheng-code-review-agent","commit":"<commit>"}`. The commit is injected via the `COMMIT` environment variable at deploy time.

The API must expose:

```json
// GET /health
{"status":"ok","commit":"69c3d26"}
```

```json
// GET /.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"kestarsheng-code-review-agent","commit":"69c3d26"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `{"status":"ok","commit":"69c3d26..."}`
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