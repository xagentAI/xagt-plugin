# Contract Guard

**面向 AI Agent 的确定性 API 破坏性变更检测器。**

[English](README.md) | 中文

Contract Guard 赋予任何 AI Agent 判断 API 变更是否安全的能力——无需猜测。它对比两个版本的 OpenAPI、GraphQL 或 JSON Schema 契约，在毫秒级返回结构化、可复现的检测结果。核心 diff 引擎 100% 确定性，可离线运行；可选的 LLM 咨询层在配置密钥后追加消费者影响评估。

> **为什么不直接问 LLM？** LLM 会幻觉 schema diff、漏掉嵌套约束收紧、无法保证两次回答一致。Contract Guard 的规则引擎专为这项工作而生：相同的输入永远产生相同的检测结果。

---

## 快速开始

**在线演示：** <https://contract-guard-eta.vercel.app>

**REST API：**

```bash
curl -X POST https://contract-guard-eta.vercel.app/v1/diff \
  -H "Content-Type: application/json" \
  -d '{
    "format": "openapi",
    "old_spec": "{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\"}}}}}}",
    "new_spec": "{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\"},\"404\":{\"description\":\"not found\"}}}}}}"
  }'
```

**MCP 端点：** `https://contract-guard-eta.vercel.app/mcp`

添加到任何 MCP 兼容的 Agent（Claude、Cursor 等），Agent 即获得六个工具：`check_breaking_changes`、`list_supported_formats`、`explain_change_type`、`suggest_version_bump`、`generate_changelog`、`suggest_migration`。

---

## 检测能力

### OpenAPI 3.x

| 变更类型 | 严重度 | 破坏性 |
|---|---|---|
| 端点 / 方法移除 | critical | 是 |
| 新增必填参数 | critical | 是 |
| 参数移除 | major | 是 |
| 可选 → 必填参数 | major | 是 |
| 响应状态码移除 | critical | 是 |
| Schema / 字段移除 | critical | 是 |
| 字段类型变更 | critical | 是 |
| 枚举值移除 | critical | 是 |
| 约束收紧（min/max/pattern） | major | 是 |
| 新增必填字段 | critical | 是 |
| Content-Type 移除/变更 | critical | 是 |
| 字段/端点标记废弃 | info | 否 |
| 新增端点 / 字段 | info | 否 |

### GraphQL SDL

| 变更类型 | 严重度 | 破坏性 |
|---|---|---|
| 类型移除 / kind 变更 | critical | 是 |
| 字段移除 / 类型变更 | critical | 是 |
| nullable → non-null | critical | 是 |
| 参数移除 / 新增必填参数 | critical | 是 |
| Input 字段移除 / 新增必填 Input 字段 | critical | 是 |
| Union 成员移除 | critical | 是 |
| Directive 移除 | major | 是 |
| 新增 `@deprecated` | info | 否 |

### JSON Schema

| 变更类型 | 严重度 | 破坏性 |
|---|---|---|
| 属性移除 / 类型变更 | critical | 是 |
| `const` 值变更 | critical | 是 |
| 新增必填属性 | critical | 是 |
| 枚举值移除 | critical | 是 |
| 约束收紧 | major | 是 |
| `additionalProperties` 收紧 | major | 是 |
| `prefixItems`（元组）变更 | critical | 是 |
| 新增 `dependentRequired` | major | 是 |
| `unevaluatedProperties` 收紧 | major | 是 |

---

## API 参考

### `POST /v1/diff`

对比两个契约，返回结构化破坏性变更报告。

```json
{
  "format": "openapi",
  "old_spec": "<旧契约文本>",
  "new_spec": "<新契约文本>",
  "use_llm": false
}
```

响应：

```json
{
  "schema_version": 1,
  "format": "openapi",
  "breaking": false,
  "total_changes": 1,
  "breaking_count": 0,
  "counts": { "critical": 0, "major": 0, "minor": 0, "info": 1 },
  "summary": "Detected 1 change(s); 0 breaking (1 info).",
  "llm_enabled": false,
  "findings": [
    {
      "change_type": "field_added",
      "breaking": false,
      "severity": "info",
      "location": "GET /users -> response 200.email",
      "summary": "Added field email",
      "source": "confirmed",
      "id": "openapi:field_added:GET /users -> response 200.email"
    }
  ]
}
```

每条 finding 的 `source` 为 `"confirmed"`（确定性引擎）或 `"advisory"`（可选 LLM 层）。

### `GET /health`

```json
{ "status": "ok", "commit": "92814ad…", "service": "contract-guard", "version": "1.0.0" }
```

### `GET /.well-known/xagent-verification.json`

```json
{ "schemaVersion": 1, "slug": "contract-guard", "commit": "92814ad…" }
```

### `GET /v1/formats`

列出支持的契约格式。

### MCP 工具

| 工具 | 说明 |
|---|---|
| `check_breaking_changes(old_spec, new_spec, format, use_llm)` | 核心 diff — 返回完整检测报告 JSON |
| `list_supported_formats()` | 即时、免费 — 列出支持的格式 |
| `explain_change_type(change_type)` | 即时、免费 — 解释 change_type 的含义 |
| `suggest_version_bump(old_spec, new_spec, format, current_version)` | 推导 SemVer 版本 bump（major/minor/patch） |
| `generate_changelog(old_spec, new_spec, format, old_version, new_version)` | 生成 markdown changelog |
| `suggest_migration(old_spec, new_spec, format)` | 为破坏性变更生成兼容性迁移建议 |

### 额外端点

| 端点 | 说明 |
|---|---|
| `POST /v1/chain-diff` | 多版本链式分析（v1→v2→...→vN） |
| `POST /v1/semver` | 推导 SemVer 版本 bump |
| `POST /v1/migration` | 生成迁移建议 |
| `POST /v1/sarif` | 导出 SARIF 2.1.0 格式（GitHub Code Scanning） |
| `POST /v1/changelog` | 生成 markdown changelog |

---

## 架构

```
old_spec + new_spec
        │
        ▼
  normalize_format()        ← 接受别名: swagger, oas, gql, jsonschema, json
        │
        ▼
  ┌─────────────────────────────────┐
  │  确定性 diff 引擎               │
  │  (零 LLM, 完全可复现)           │
  │                                 │
  │  OpenAPI  │ GraphQL │ JSON Schema│
  └─────────────────────────────────┘
        │
        ▼
  Finding[]  (source: "confirmed")
        │
        ▼  (可选, 配置 LLM key 时)
  LLM 咨询影响评估
        │
        ▼
  Finding[]  (source: "advisory")
        │
        ▼
  DiffReport → JSON
```

确定性引擎解析两个契约，遍历 schema 树，输出带精确位置（`GET /users -> response 200.email`）的 finding。`$ref` 引用会被解析。约束收紧（min/max/pattern/enum）通过对比新旧范围检测。

---

## 本地运行

```bash
git clone https://github.com/kestarsheng/contract-guard.git
cd contract-guard
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开 <http://localhost:8000> 查看演示页，<http://localhost:8000/docs> 查看 Swagger。

### 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `COMMIT` | `dev` | Git commit hash（部署时设置） |
| `LLM_API_KEY` | (空) | 可选 — 启用 LLM 咨询层 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容端点 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `MAX_SPEC_CHARS` | `200000` | 单个 spec 最大输入大小 |

---

## 测试

```bash
pytest -v
```

46 个测试，覆盖三个引擎、新增模块（semver/migration/sarif）和编排层。

---

## 技术栈

- **FastAPI** — REST API + Swagger 文档
- **FastMCP 4.0.3** — MCP 服务端（streamable HTTP，挂载于 `/mcp`）
- **graphql-core 3.2** — GraphQL SDL 解析
- **PyYAML** — YAML OpenAPI 支持
- **Vercel** — Serverless 部署（Python 3.12）

---

## 许可证

MIT