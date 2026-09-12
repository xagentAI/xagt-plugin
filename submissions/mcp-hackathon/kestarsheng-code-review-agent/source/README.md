# Code Review Agent

**Dual-engine AI code quality review service** (Code Review as a Service). Rule engine + LLM semantic analysis + cross-validation, producing structured reports with per-dimension scores and directly applicable fix code. Provides REST API and MCP tools, callable by Claude Code / Codex / Cursor and other Agents.

> [中文](README_ZH.md) | English

> Submission for **X-Agent AI MCP Hackathon 2026 · Open Innovation Challenge**.
>
> Live demo: https://code-review-agent-ashy-six.vercel.app

## Dual-Engine Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Input: Code / Diff / Multi-file             │
└───────────────┬─────────────────────────────────────────┘
                ▼
┌──────────────────────────┐   ┌─────────────────────────────┐
│  ① Rule Engine (deterministic) │   │  ② LLM Semantic Analysis (deep) │
│  · 26 cross-language rules     │   │  · Receives rule pre-scan results │
│  · Python/JS/Java/Go/Rust      │───▶  · Confirms/denies rule hits (removes false positives) │
│  · Security/Perf/AI hallucination/style │   │  · Finds semantic issues (logic/architecture) │
│  · Zero-cost, ms-level, offline │   │  · Generates per-dimension scores & fix_code │
└───────────────┬──────────┘   └──────────────┬──────────────┘
                ▼                              ▼
┌───────────────────────────────────────────────────────────┐
│  ③ Cross-Validation Merge (merge_findings)                  │
│  · rule      — rule engine only (high confidence retained)  │
│  · llm       — LLM only                                     │
│  · confirmed — both engines agree (confidence +0.3, max 1.0) │
└───────────────────────────────┬───────────────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────┐
│  ④ Output: 5-dimension scores + applicable fixes + traceability │
│  · correctness/security/performance/maintainability/best_practice │
│  · score = weighted avg (security 30% · correctness 25%)    │
│  · each issue includes fix_code (copy-paste ready)          │
└───────────────────────────────────────────────────────────┘
```

## Features

- **Dual-engine review** — Rule engine performs deterministic static scan first, LLM reviews with rule context, cross-validation reduces false positives
- **5-dimension scoring** — Correctness / Security / Performance / Maintainability / Best Practice, each 0–100, weighted composite score
- **Directly applicable fix code** — Rule engine auto-generates `fix_code` for 8 key rule types, LLM covers complex scenarios
- **Three review modes** — Single file code, Unified Diff (PR changes), Multi-file batch (cross-file architecture issues)
- **CLI one-click review** — `python cli.py` reads git diff directly, no pasting needed
- **MCP toolset** — 7 tools: review / diff review / multi-file review / security scan / rule explanation / fix generation / rule listing
- **Interactive demo page** — Dark mode, syntax highlighting, dimension score bars, engine visualization, "one-click apply fix"

## CLI One-Click Review (Recommended)

```bash
python cli.py                    # Review uncommitted changes (git diff)
python cli.py --staged           # Review staged changes (git diff --cached)
python cli.py --commit HEAD~1    # Review the last commit
python cli.py src/utils.py       # Review a single file
python cli.py --remote           # Use remote Vercel deployment (no local server needed)
python cli.py --format json      # Output JSON (machine-readable, for pipes/CI)
python cli.py --sarif out.sarif  # Export SARIF (GitHub Code Scanning format)
```

Exit codes: `0` no serious issues | `2` critical/major found (CI gate) | `1` runtime error

Auto-reads git diff → calls API → outputs structured report with severity icons, dimension scores, and fix code.

## CI/CD Integration

### GitHub Actions (PR Auto-Review)

Includes `.github/workflows/code-review.yml`, auto-triggers on PR to main:

1. Gets PR diff → calls Code Review Agent API
2. Fails Action if critical issues found (blocks merge)
3. Exports SARIF and uploads to GitHub Code Scanning (issues annotated on PR diff lines)

### pre-commit hook

```bash
# .git/hooks/pre-commit
python cli.py --staged --remote || exit 1   # Blocks commit if critical/major found
```

### SARIF + GitHub Code Scanning

```bash
python cli.py --sarif results.sarif --remote
# Then upload in GitHub Action with github/codeql-action/upload-sarif@v3
```

## API Overview

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/v1/review` | Review source code, return structured report |
| `POST` | `/v1/review_diff` | Review Unified Diff (PR changes) |
| `POST` | `/v1/review_files` | Multi-file batch review (cross-file architecture analysis) |
| `POST` | `/v1/suggest_fix` | Generate complete fixed version for problematic code |
| `GET` | `/v1/rules` | List all rule engine rules |
| `GET` | `/v1/rules/{rule_id}` | View single rule details and fix guidance |
| `GET` | `/health` | Health check, returns deployment commit |
| `GET` | `/.well-known/xagent-verification.json` | Deployment proof (slug + commit) |
| `GET` | `/` | Interactive demo page |

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Fill in LLM_API_KEY
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 for the demo page, or http://127.0.0.1:8000/docs for Swagger.

### Example: Review Code

```bash
curl -X POST http://127.0.0.1:8000/v1/review \
  -H "Content-Type: application/json" \
  -d '{"code": "result = eval(user_input)", "language": "python"}'
```

Response (abridged):

```json
{
  "report": {
    "score": 68,
    "grade": "C",
    "dimension_scores": {
      "correctness": 88, "security": 35,
      "performance": 90, "maintainability": 80, "best_practice": 75
    },
    "issues": [
      {
        "severity": "critical",
        "category": "security",
        "line": 1,
        "title": "Using eval() to execute arbitrary code",
        "description": "eval() executes arbitrary strings as code, posing a severe injection risk.",
        "suggestion": "Use ast.literal_eval() or a dedicated parser.",
        "fix_code": "result = ast.literal_eval(user_input)",
        "source": "confirmed",
        "rule_id": "PY-S001",
        "confidence": 1.0
      }
    ],
    "engine_info": {
      "rule_count": 0, "llm_count": 0, "confirmed_count": 1,
      "total_rules_run": 3, "engines": ["rule", "llm"]
    }
  }
}
```

### Example: Review a Diff

```bash
curl -X POST http://127.0.0.1:8000/v1/review_diff \
  -H "Content-Type: application/json" \
  -d '{"diff": "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,4 @@\n def f():\n-    return 1\n+    return eval(data)", "language": "python"}'
```

Response includes `files_changed` / `added_lines` / `removed_lines` change metadata with the full report.

### Example: Multi-file Review

```json
{
  "context": "User service module",
  "files": [
    {"filename": "utils.py", "content": "import os\napi_key = os.environ['KEY']", "language": "python"},
    {"filename": "main.py", "content": "from utils import *\nresult = eval(req.body)", "language": "python"}
  ]
}
```

Returns per-file `file_reports` (rule scan) and one `overall_report` (LLM cross-file architecture review).

## MCP Usage

### Local stdio (Claude Code / Codex / Cursor)

```bash
python -m app.mcp_server          # stdio transport
```

Register in client config:

```json
{
  "mcpServers": {
    "code-review-agent": {
      "command": "python",
      "args": ["-m", "app.mcp_server"]
    }
  }
}
```

### Remote streamable HTTP (same deployment, no local Python needed)

After deployment, access `https://<your-host>/mcp`, configure in MCP client:

```json
{
  "mcpServers": {
    "code-review-agent": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-client", "https://<your-host>/mcp"]
    }
  }
}
```

> The remote MCP endpoint and REST API share the same server. After deployment, `/mcp` provides streamable HTTP protocol, `/v1/*` provides REST.

### Usage Guide (for Agents)

1. **Free quick scan first**: Use `detect_security` / `list_rules` / `explain_issue` (no LLM call, ms-level response)
2. **Deep review**: Use `review_code` / `review_diff` / `review_files`, default `detail="brief"` (saves context, returns title-level issues only)
3. **Full report when needed**: `detail="full"` returns complete description / suggestion / fix_code for each issue
4. **Fix**: Use `suggest_fix` to get directly replaceable `fixed_code`

### MCP Tools

| Tool | Parameters | LLM | Description |
| --- | --- | --- | --- |
| `review_code` | `code, language?, context?, detail?` | ✅ | Review source code (`detail: "brief"\|"full"`) |
| `review_diff` | `diff, language?, context?, detail?` | ✅ | Review Unified Diff |
| `review_files` | `files: [{filename, content, language?}], context?, detail?` | ✅ | Multi-file batch review (structured params, not JSON string) |
| `detect_security` | `code, language?` | ❌ | Rule engine security scan only, instant response |
| `explain_issue` | `rule_id` | ❌ | Explain a rule (definition/severity/fix guidance) |
| `suggest_fix` | `code, language?, context?` | ✅ | Return fixed code (fixed_code + change explanation) |
| `list_rules` | — | ❌ | List all rules |

> `review_files` `files` parameter is a **structured array**, each element `{filename, content, language?}`. Agents don't need to manually compose JSON strings.

## Rule Engine

Built-in **26 cross-language rules** covering Python / JavaScript / Java / Go / Rust / cross-language general patterns:

| Category | Examples |
| --- | --- |
| Security | `eval`/`exec`, SQL injection, command injection, hardcoded secrets, `pickle.loads`, `innerHTML` XSS |
| Performance | Nested loops O(n²), dict iteration without `.items()`, pre-generating large lists |
| AI Pattern | Hallucinated imports of framework internals, `forEach` with `await`, catch swallowing exceptions |
| Maintainability / Best Practice | TODO/FIXME, bare `except`, missing type annotations |

8 key rule types have **auto fix code generation** (`eval`→`ast.literal_eval`, `innerHTML`→`textContent`, hardcoded secret→`os.environ`, etc.).

## Configuration (Environment Variables)

| Var | Default | Description |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL |
| `LLM_API_KEY` | — | API key (required) |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `LLM_TIMEOUT_SECONDS` | `120` | LLM request timeout |
| `MAX_CODE_CHARS` | `60000` | Max characters per review |
| `COMMIT` | `dev` | Deployment commit, returned by /health and verification file |

## Deployment

- **Vercel** (current): `vercel.json` configured for Serverless service; push after setting env vars in Vercel project
- **Docker**: `docker build -t code-review-agent . && docker run -p 8000:8000 code-review-agent`
- **Render**: Use `render.yaml`, push repo and set env vars

Post-deploy verification:

```bash
curl https://<your-host>/health
curl https://<your-host>/.well-known/xagent-verification.json
```

## Testing

```bash
python -m pytest tests/ -v
```

58 unit tests covering rule engine, diff parsing, 5-dimension scoring, fix code generation, multi-file review, and full dual-engine flow.

## License

UNLICENSED — submission-only use for X-Agent AI MCP Hackathon 2026.