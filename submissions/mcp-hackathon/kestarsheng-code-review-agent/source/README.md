# Code Review Agent

**A code review agent for AI-generated code.** When Claude Code / Codex / Cursor writes code, who checks it before merge? This agent does — triple-engine review (rule engine + AST structural analysis + LLM semantic review) with cross-validation, catching the patterns AI coding tools most commonly get wrong: hallucinated imports, `eval()` injections, shell=True, swallowed exceptions, and more. Returns structured reports with per-dimension scores, deterministic metrics, SARIF export, and directly applicable fix code. Provides REST API and 10 MCP tools.

> [中文](README_ZH.md) | English

> Submission for **X-Agent AI MCP Hackathon 2026 · Open Innovation Challenge**.
>
> Live demo: https://code-review-agent-ashy-six.vercel.app

## Why: AI-generated code needs a different kind of review

AI coding tools (Claude Code, Codex, Cursor, GitHub Copilot) are fast — but they repeat the same mistakes:

| AI pattern | What happens | Rule that catches it |
| --- | --- | --- |
| Hallucinated imports | `from django.core import some_nonexistent_module` — AI guesses API names | `AI-H001`–`AI-H006` |
| `eval()` / `exec()` for parsing | AI uses `eval(user_input)` instead of `ast.literal_eval()` | `PY-S001` |
| `shell=True` command execution | AI builds shell strings instead of arg lists | `PY-S003` |
| Swallowed exceptions | `except: pass` — AI adds bare catches to "be safe" | `PY-B001` |
| `forEach` + `await` | AI writes `arr.forEach(async (x) => await fetch(x))` — doesn't await | `AI-H004` |
| Hardcoded secrets | AI inlines API keys instead of using env vars | `PY-S004` / `JS-S004` |

This agent's rule engine includes **6 dedicated AI-pattern rules** (`AI-H001`–`AI-H006`) that target these hallucination patterns. The triple-engine design means: rule engine catches deterministic patterns (ms-level, free), AST analyzer catches structural errors (undefined vars, duplicate defs), and LLM confirms/denies rule hits to reduce false positives — the cross-validation that a single-engine tool can't do.

## Triple-Engine Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Input: Code / Diff / Multi-file / PR URL     │
└───────────────┬─────────────────────────────────────────┘
                ▼
┌──────────────────────────┐   ┌─────────────────────────────┐
│  ① Rule Engine (regex)    │   │  ② AST Analysis (Python)     │
│  · 40 cross-language rules │   │  · Syntax errors (exact)     │
│  · Python/JS/TS/Java/Go/  │   │  · Undefined variables       │
│    Rust/C/C++/Shell        │   │  · Unused imports            │
│  · Security/Perf/AI/style  │   │  · Duplicate definitions     │
│  · Zero-cost, ms-level     │   │  · Empty stub functions      │
└──────────┬───────────────┘   └──────────┬──────────────────┘
           ▔▔▔▔▔▔▔▔┬────────────────────▘
                     ▼
┌──────────────────────────┐
│  ③ LLM Semantic Analysis  │
│  · Receives rule + AST    │
│    pre-scan results       │
│  · Confirms/denies hits   │
│  · Semantic issues        │
│  · Scores & fix_code      │
└──────────┬───────────────┘
           ▼
┌───────────────────────────────────────────────────────────┐
│  ④ Cross-Validation Merge (merge_findings)                  │
│  · rule / ast / llm / confirmed (both agree → +0.3 conf)   │
└───────────────────────────────┬───────────────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────┐
│  ⑤ Output: 5-dimension scores + metrics + SARIF + fixes     │
│  · correctness/security/performance/maintainability/best    │
│  · quality metrics (cyclomatic complexity, function length)  │
│  · SARIF 2.1.0 export (VS Code / GitHub Code Scanning)      │
│  · each issue includes fix_code (copy-paste ready)           │
└───────────────────────────────────────────────────────────┘
```

## Features

- **Triple-engine review** — Regex rule engine (40 rules, 9 languages, 6 AI-pattern rules) + AST-level static analysis (Python syntax/undefined vars/unused imports/duplicate defs) + LLM semantic review with cross-validation
- **5-dimension scoring** — Correctness / Security / Performance / Maintainability / Best Practice, each 0–100, weighted composite score
- **Deterministic quality metrics** — Cyclomatic complexity (McCabe), function length distribution, comment ratio, long lines — zero LLM cost, instant
- **SARIF 2.1.0 export** — Standards-compliant output for VS Code (Sarif Viewer) and GitHub Code Scanning, CI-ready
- **GitHub PR/commit URL review** — Paste a PR or commit URL, auto-fetch diff and review
- **Directly applicable fix code** — Rule engine auto-generates `fix_code` for 8 key rule types, LLM covers complex scenarios
- **Four review modes** — Single file code, Unified Diff, Multi-file batch, GitHub PR URL
- **CLI one-click review** — `python cli.py` reads git diff directly, no pasting needed
- **MCP toolset** — 10 tools: review / diff review / multi-file / PR review / security scan / metrics / SARIF export / rule explanation / fix generation / rule listing
- **Interactive workbench** — Live demo with Metrics, SARIF, Rules, and PR URL tabs (free & instant, no LLM needed)

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
| `POST` | `/v1/review_pr` | Review GitHub PR/commit URL (auto-fetch diff) |
| `POST` | `/v1/suggest_fix` | Generate complete fixed version for problematic code |
| `POST` | `/v1/metrics` | Deterministic code quality metrics (no LLM) |
| `POST` | `/v1/sarif` | SARIF 2.1.0 export (VS Code / GitHub Code Scanning) |
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
| `review_pr` | `url, language?, context?, detail?` | ✅ | Review GitHub PR/commit URL (auto-fetch diff) |
| `detect_security` | `code, language?` | ❌ | Rule engine security scan only, instant response |
| `analyze_metrics` | `code, language?` | ❌ | Deterministic quality metrics (complexity, function length) |
| `explain_issue` | `rule_id` | ❌ | Explain a rule (definition/severity/fix guidance) |
| `suggest_fix` | `code, language?, context?` | ✅ | Return fixed code (fixed_code + change explanation) |
| `export_sarif` | `code, language?, uri?` | ❌ | SARIF 2.1.0 export (VS Code / GitHub Code Scanning) |
| `list_rules` | — | ❌ | List all rules |

> `review_files` `files` parameter is a **structured array**, each element `{filename, content, language?}`. Agents don't need to manually compose JSON strings.

### Real MCP tool calls (captured output)

The following are **real tool outputs** from the deployed agent — non-LLM tools called locally, LLM tools called against the live endpoint.

**Agent → `detect_security`** (instant, no LLM):

```
Agent: detect_security(code="import os\napi_key='sk-1234567890abcdef'\nresult = eval(user_input)\nos.system('rm -rf /tmp/x')\ndata = pickle.loads(raw_data)", language="python")

Tool → {"ok": true, "total_findings": 3, "findings": [
  {"rule_id": "PY-S001", "severity": "critical", "line": 3,
   "title": "使用 eval() 执行任意代码",
   "suggestion": "避免使用 eval()。如需解析表达式，使用 ast.literal_eval() 或专用解析器。",
   "confidence": 0.95},
  {"rule_id": "PY-S004", "severity": "major", "line": 2,
   "title": "硬编码密钥/密码",
   "suggestion": "使用环境变量或密钥管理服务：api_key = os.environ['API_KEY']",
   "confidence": 0.8},
  {"rule_id": "PY-S005", "severity": "major", "line": 5,
   "title": "使用 pickle 反序列化不可信数据",
   "suggestion": "使用 JSON 等安全格式序列化数据",
   "confidence": 0.9}
]}
```

**Agent → `analyze_metrics`** (instant, no LLM):

```
Agent: analyze_metrics(code="def process_data(items):\n    result = []\n    for i in range(len(items)):\n        for j in range(len(items)):\n            ...", language="python")

Tool → {"ok": true, "metrics": {
  "complexity": {"average": 4.0, "max": 4,
    "most_complex": [{"name": "process_data", "line": 1, "complexity": 4}]},
  "functions": {"count": 1, "average_length": 7.0, "max_length": 7},
  "lines": {"total": 7, "code": 7, "comment": 0, "blank": 0}
}}
```

**Agent → `list_rules`** (instant, no LLM):

```
Agent: list_rules()

Tool → {"total": 40, "rules": [
  {"id": "PY-S001", "severity": "critical", "category": "security", "title": "使用 eval() 执行任意代码"},
  {"id": "PY-S002", "severity": "critical", "category": "security", "title": "使用 exec() 执行任意代码"},
  {"id": "PY-S003", "severity": "critical", "category": "security", "title": "命令注入风险"},
  {"id": "PY-S004", "severity": "major", "category": "security", "title": "硬编码密钥/密码"},
  {"id": "PY-S005", "severity": "major", "category": "security", "title": "使用 pickle 反序列化不可信数据"},
  ... (35 more)
]}
```

**Agent → `review_pr`** (LLM, live endpoint `https://code-review-agent-ashy-six.vercel.app/v1/review_pr`):

```
Agent: review_pr(url="https://github.com/kestarsheng/code-review-agent/commit/952fa21", language="python")

Tool → {"ok": true, "files_changed": 5, "added_lines": 240, "model": "deepseek-chat",
  "report": {
    "score": 46, "grade": "D",
    "dimension_scores": {"correctness": 36, "security": 9, "performance": 85,
                         "maintainability": 88, "best_practice": 54},
    "issues": [
      {"severity": "critical", "source": "rule", "rule_id": "PY-AST-S001",
       "line": 104, "title": "Python 语法错误，代码无法解析"},
      {"severity": "critical", "source": "rule", "rule_id": "PY-S001",
       "line": 229, "title": "使用 eval() 执行任意代码",
       "fix_code": "result = ast.literal_eval(x)"},
      {"severity": "major", "source": "llm",
       "line": 78, "title": "fetch_diff 跟随重定向且未校验最终主机，存在 SSRF 风险"},
      ... (9 more)
    ],
    "engine_info": {"rule_count": 8, "llm_count": 4, "confirmed_count": 0,
                    "engines": ["rule", "ast", "llm"]}
  }
}
```

> The `review_pr` call demonstrates the full pipeline: GitHub URL → diff fetch → triple-engine review → structured report with cross-engine attribution (`source: "rule"` vs `source: "llm"`) and auto-generated `fix_code`.

## Rule Engine

Built-in **40 cross-language rules** covering Python / JavaScript / TypeScript / Java / Go / Rust / C/C++ / Shell / PHP:

| Category | Count | Examples |
| --- | --- | --- |
| Security | 15 | `eval`/`exec`, SQL injection, command injection, hardcoded secrets, `pickle.loads`, `innerHTML` XSS |
| Performance | 6 | Nested loops O(n²), dict iteration without `.items()`, pre-generating large lists |
| **AI Pattern** | **6** | **Hallucinated imports** (`AI-H001`–`AI-H003`), `forEach`+`await` (`AI-H004`), catch swallowing (`AI-H005`), nonexistent method calls (`AI-H006`) |
| Maintainability / Best Practice | 13 | TODO/FIXME, bare `except`, missing type annotations |

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

93 unit tests covering rule engine (40 rules), AST analysis, diff parsing, 5-dimension scoring, fix code generation, multi-file review, PR URL review, metrics, SARIF export, and full triple-engine flow.

## License

UNLICENSED — submission-only use for X-Agent AI MCP Hackathon 2026.