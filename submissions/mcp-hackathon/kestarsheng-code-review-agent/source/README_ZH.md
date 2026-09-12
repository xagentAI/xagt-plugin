# Code Review Agent


**双引擎 AI 代码质量评审服务**（Code Review as a Service）。规则引擎 + LLM 语义分析 + 交叉验证，输出带分维度评分和可直接应用修复代码的结构化报告。提供 REST API 与 MCP 工具，可被 Claude Code / Codex / Cursor 等 Agent 直接调用。

> [English](README.md) | 中文

> Submission for **X-Agent AI MCP Hackathon 2026 · Open Innovation Challenge**.
>
> 在线演示：https://code-review-agent-ashy-six.vercel.app

## 双引擎架构

```
┌─────────────────────────────────────────────────────────┐
│                    输入：代码 / Diff / 多文件            │
└───────────────┬─────────────────────────────────────────┘
                ▼
┌──────────────────────────┐   ┌─────────────────────────────┐
│  ① 规则引擎（确定性）      │   │  ② LLM 语义分析（深度）      │
│  · 26 条跨语言规则         │   │  · 显式接收规则预检结果       │
│  · Python/JS/Java/Go/Rust │───▶  · 确认/否定规则命中（去误报） │
│  · 安全/性能/AI幻觉/风格    │   │  · 发现语义级问题（逻辑/架构） │
│  · 零成本、毫秒级、离线可跑  │   │  · 生成分维度评分与 fix_code │
└───────────────┬──────────┘   └──────────────┬──────────────┘
                ▼                              ▼
┌───────────────────────────────────────────────────────────┐
│  ③ 交叉验证合并（merge_findings）                          │
│  · rule      — 仅规则引擎命中（高置信保留）                  │
│  · llm       — 仅 LLM 发现                                  │
│  · confirmed — 双引擎一致（置信度提升 +0.3，最高 1.0）       │
└───────────────────────────────┬───────────────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────┐
│  ④ 输出：五维度评分 + 可应用修复 + 引擎溯源                  │
│  · correctness/security/performance/maintainability/best_practice │
│  · score = 加权平均（security 30% · correctness 25%）        │
│  · 每个 issue 附带 fix_code（可直接复制替换）                │
└───────────────────────────────────────────────────────────┘
```

## 功能特性

- **双引擎评审** — 规则引擎先做确定性静态扫描，LLM 带规则上下文语义评审，交叉验证降低误报
- **五维度评分** — 正确性 / 安全性 / 性能 / 可维护性 / 最佳实践各一个 0–100 分，加权得综合分
- **可直接应用的修复代码** — 规则引擎为 8 类关键规则自动生成 `fix_code`，LLM 覆盖更复杂的修复
- **三种评审模式** — 单文件代码、Unified Diff（PR 变更）、多文件批量（跨文件架构问题）
- **CLI 一键评审** — `python cli.py` 直接读 git diff 评审，无需粘贴代码
- **MCP 工具集** — 7 个工具：评审 / Diff 评审 / 多文件评审 / 安全扫描 / 规则解释 / 修复生成 / 规则列表
- **交互式演示页** — 暗色模式、代码高亮、维度评分条、引擎可视化、"一键应用修复"

## CLI 一键评审（推荐）

```bash
python cli.py                    # 评审工作区未提交改动 (git diff)
python cli.py --staged           # 评审已暂存改动 (git diff --cached)
python cli.py --commit HEAD~1    # 评审最近一次提交
python cli.py src/utils.py       # 评审单个文件
python cli.py --remote           # 用远程 Vercel 部署（无需启动本地服务）
python cli.py --format json      # 输出 JSON（机器可读，用于管道/CI）
python cli.py --sarif out.sarif  # 导出 SARIF（GitHub Code Scanning 格式）
```

退出码：`0` 无严重问题 | `2` 存在 critical/major（可做 CI 门禁）| `1` 运行错误

自动读取 git diff → 调 API → 输出带严重度图标、维度评分、修复代码的结构化报告。

## CI/CD 集成

### GitHub Actions（PR 自动评审）

项目自带 `.github/workflows/code-review.yml`，PR 到 main 时自动触发：

1. 获取 PR diff → 调用 Code Review Agent API
2. 有 critical issue 时 Action 失败（阻断 merge）
3. 导出 SARIF 上传到 GitHub Code Scanning（issue 直接标注在 PR diff 行上）

### pre-commit hook

```bash
# .git/hooks/pre-commit
python cli.py --staged --remote || exit 1   # 有 critical/major 则阻止提交
```

### SARIF + GitHub Code Scanning

```bash
python cli.py --sarif results.sarif --remote
# 然后在 GitHub Action 中用 github/codeql-action/upload-sarif@v3 上传
```

## API 一览

| Method | Endpoint | 说明 |
| --- | --- | --- |
| `POST` | `/v1/review` | 评审源代码，返回结构化报告 |
| `POST` | `/v1/review_diff` | 评审 Unified Diff（PR 变更） |
| `POST` | `/v1/review_files` | 多文件批量评审（跨文件架构分析） |
| `POST` | `/v1/suggest_fix` | 为问题代码生成完整修复版本 |
| `GET` | `/v1/rules` | 列出全部规则引擎规则 |
| `GET` | `/v1/rules/{rule_id}` | 查看单条规则详情与修复指引 |
| `GET` | `/health` | 健康检查，返回部署 Commit |
| `GET` | `/.well-known/xagent-verification.json` | 部署证明（slug + commit） |
| `GET` | `/` | 在线演示页 |

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # 填入 LLM_API_KEY
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000 使用演示页，或 http://127.0.0.1:8000/docs 查看 Swagger。

### 示例：评审一段代码

```bash
curl -X POST http://127.0.0.1:8000/v1/review \
  -H "Content-Type: application/json" \
  -d '{"code": "result = eval(user_input)", "language": "python"}'
```

响应（节选）：

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
        "title": "使用 eval() 执行任意代码",
        "description": "eval() 会执行任意字符串作为代码，是严重的注入风险点。",
        "suggestion": "使用 ast.literal_eval() 或专用解析器。",
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

### 示例：评审一个 Diff

```bash
curl -X POST http://127.0.0.1:8000/v1/review_diff \
  -H "Content-Type: application/json" \
  -d '{"diff": "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,4 @@\n def f():\n-    return 1\n+    return eval(data)", "language": "python"}'
```

响应会包含 `files_changed` / `added_lines` / `removed_lines` 变更元数据与完整报告。

### 示例：多文件评审

```json
{
  "context": "用户服务模块",
  "files": [
    {"filename": "utils.py", "content": "import os\napi_key = os.environ['KEY']", "language": "python"},
    {"filename": "main.py", "content": "from utils import *\nresult = eval(req.body)", "language": "python"}
  ]
}
```

返回每个文件的 `file_reports`（规则扫描）与一个 `overall_report`（LLM 跨文件架构评审）。

## MCP usage

### 本地 stdio（Claude Code / Codex / Cursor）

```bash
python -m app.mcp_server          # stdio transport
```

注册到客户端配置：

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

### 远程 streamable HTTP（同一部署，无需本地 Python）

部署后访问 `https://<your-host>/mcp`，在 MCP 客户端中配置：

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

> 远程 MCP 端点与 REST API 共用同一个服务器，部署后 `/mcp` 提供 streamable HTTP 协议，`/v1/*` 提供 REST。

### 使用引导（给 Agent）

1. **先免费快筛**：用 `detect_security` / `list_rules` / `explain_issue`（无 LLM 调用，毫秒级返回）
2. **深度评审**：用 `review_code` / `review_diff` / `review_files`，默认 `detail="brief"`（节省上下文，仅返回标题级 issue）
3. **需要完整报告时**：`detail="full"` 返回每个 issue 的完整 description / suggestion / fix_code
4. **修复**：用 `suggest_fix` 获取可直接替换的 `fixed_code`

### MCP 工具

| 工具 | 参数 | LLM | 说明 |
| --- | --- | --- | --- |
| `review_code` | `code, language?, context?, detail?` | ✅ | 评审源代码（`detail: "brief"\|"full"`） |
| `review_diff` | `diff, language?, context?, detail?` | ✅ | 评审 Unified Diff |
| `review_files` | `files: [{filename, content, language?}], context?, detail?` | ✅ | 多文件批量评审（结构化参数，非 JSON 字符串） |
| `detect_security` | `code, language?` | ❌ | 仅规则引擎安全扫描，即时返回 |
| `explain_issue` | `rule_id` | ❌ | 解释某条规则（定义/严重级别/修复指引） |
| `suggest_fix` | `code, language?, context?` | ✅ | 返回修复后的完整代码（fixed_code + 变更说明） |
| `list_rules` | — | ❌ | 列出全部规则 |

> `review_files` 的 `files` 参数是**结构化数组**，每个元素 `{filename, content, language?}`，Agent 无需手工拼 JSON 字符串。

## 规则引擎

内置 **26 条跨语言规则**，覆盖 Python / JavaScript / Java / Go / Rust / 跨语言通用模式：

| 类别 | 示例 |
| --- | --- |
| Security | `eval`/`exec`、SQL 注入、命令注入、硬编码密钥、`pickle.loads`、`innerHTML` XSS |
| Performance | 嵌套循环 O(n²)、字典遍历未用 `.items()`、预生成大列表 |
| AI Pattern | 幻觉导入框架内部模块、`forEach` 中 `await`、catch 吞异常 |
| Maintainability / Best Practice | TODO/FIXME、裸 `except`、缺类型注解 |

8 类关键规则带 **自动修复代码生成**（`eval`→`ast.literal_eval`、`innerHTML`→`textContent`、硬编码密钥→`os.environ` 等）。

## 配置（环境变量）

| Var | Default | Description |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL |
| `LLM_API_KEY` | — | API key（必填） |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_TIMEOUT_SECONDS` | `120` | LLM 请求超时 |
| `MAX_CODE_CHARS` | `60000` | 单次评审最大字符数 |
| `COMMIT` | `dev` | 部署 Commit，/health 与验证文件返回 |

## 部署

- **Vercel**（当前）：`vercel.json` 已配置 Serverless 服务；在 Vercel 项目设置环境变量后推送即可
- **Docker**: `docker build -t code-review-agent . && docker run -p 8000:8000 code-review-agent`
- **Render**: 使用 `render.yaml`，推送仓库并设置环境变量

部署后验证：

```bash
curl https://<your-host>/health
curl https://<your-host>/.well-known/xagent-verification.json
```

## 测试

```bash
python -m pytest tests/ -v
```

58 个单元测试，覆盖规则引擎、Diff 解析、五维度评分、修复代码生成、多文件评审与完整双引擎流程。

## License

UNLICENSED — submission-only use for X-Agent AI MCP Hackathon 2026.