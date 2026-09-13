# 在线验证手册（verification）

- **API 同源基址**：`https://yai-agent-core.onrender.com`
- **评审基线 commit**：以 `../submission.json` 的 `reviewCommit`（40 位 SHA）为准。
- **冷启动提示**：免费实例 15 分钟无流量会休眠，首次请求约 30–90 秒冷启动；建议先 curl 一次 health 唤醒，再做后续验证。
- 以下 curl 命令在任意装有 curl 的环境可直接复现（Windows PowerShell / macOS / Linux 均可）。

## 1. health 健康检查（硬门槛）

```bash
curl -sS https://yai-agent-core.onrender.com/health
```

期望返回（commit 必须与 reviewCommit 完全一致）：

```json
{"status": "ok", "commit": "<40位 reviewCommit>"}
```

## 2. 部署证明端点（硬门槛，与 health 同源同 commit）

```bash
curl -sS https://yai-agent-core.onrender.com/.well-known/xagent-verification.json
```

期望返回：

```json
{"schemaVersion": 1, "slug": "yai-agent-core", "commit": "<40位 reviewCommit>"}
```

## 3. 工具清单（能力自发现 + 来源标注）

```bash
curl -sS https://yai-agent-core.onrender.com/v1/tools
```

期望返回宿主演示应用自动发现的 3 个 native 工具（count_notes / list_notes / search_notes）
以及线上通过 MCP Client 挂载的 3 个 `source: "mcp"` 远程工具（ask_question /
read_wiki_contents / read_wiki_structure，来自公共免鉴权的 DeepWiki MCP Server）。

## 4. 真实 Agent 任务（POST，会真实调用 DeepSeek 模型）

> 限流说明：`POST /v1/agent/run` 每 IP 每分钟 30 次；超限返回 429 与 `Retry-After`，
> 稍后重试即可。健康与验证端点（本手册第 1–3 节）不受限。

```bash
curl -sS -X POST https://yai-agent-core.onrender.com/v1/agent/run \
  -H "Content-Type: application/json" \
  -d '{"task": "搜索笔记里关于比赛的内容并总结"}' \
  --max-time 180
```

期望返回 JSON，包含：

- `strategy`：自适应路由结果（该任务通常为 `plan` 或 `react`）；
- `events[0]`（`strategy_selected`）带 `source`（`llm` 模型分类 / `rules` 规则兜底）、
  `reason`（中文决策理由）与 `tier`（standard/strong）——决策本身可审计；
- `final_text`：模型基于真实工具结果给出的中文总结；
- `events`：完整过程事件序列（`strategy_selected` → `tool_call` → `tool_result`（ok=true）→ … → `done`），证明工具被真实调用而非提示词演示。

PowerShell 若对内联 JSON 引号处理不一致，可改用：

```powershell
$body = @{ task = "搜索笔记里关于比赛的内容并总结" } | ConvertTo-Json -Compress
curl.exe -sS -X POST https://yai-agent-core.onrender.com/v1/agent/run `
  -H "Content-Type: application/json" --data $body --max-time 180
```

## 4b. 真实外部 MCP 工具调用（MCP 产品化硬证据）

```bash
curl -sS -X POST https://yai-agent-core.onrender.com/v1/agent/run \
  -H "Content-Type: application/json" \
  -d '{"task": "用 MCP 工具问一下 GitHub 仓库 modelcontextprotocol/python-sdk：MCP 的 Client 怎么初始化？用中文给结论。"}' \
  --max-time 180
```

期望：`strategy` 为 `react`；`events` 中出现对 `ask_question`（source=mcp）的
`tool_call` / `tool_result(ok=true)`；`final_text` 是基于远程 MCP 返回内容的中文回答。
该调用链为：本服务 → DeepSeek 规划工具调用 → Streamable HTTP 调远程 MCP Server → 结果回灌 → 模型总结。

## 5. 本地/隔离环境复现

```bash
git clone https://github.com/Gi-Tuu/yai-agent-core
cd yai-agent-core
git checkout <reviewCommit>
uv sync --extra dev --extra llm --extra server --extra mcp
uv run pytest                      # 125 项离线测试全绿（截至 v0.3，以 pytest -q 实跑为准），不需要 API Key
uv run ruff check src tests examples scripts
python scripts/smoke_test.py       # 三宿主自适应冒烟（离线）
docker compose up --build          # 容器化：容器内 8000，宿主 127.0.0.1:8001
# 本地容器验证：curl http://127.0.0.1:8001/health
```

## 6. 证据留存

- 部署平台：Render 免费层 Docker Web Service（Blueprint 见 `source/render.yaml`），
  平台注入 `RENDER_GIT_COMMIT`，服务启动时按 `YAI_GIT_COMMIT → RENDER_GIT_COMMIT → git HEAD → dev`
  解析且只接受 40 位哈希，保证 health 上报的就是本次部署的真实 commit；
- CI：每次推送在 GitHub Actions（Ubuntu 3.11/3.12/3.13 + Windows 3.13）执行 ruff + pytest，状态见仓库 README 徽章与 Actions 页；
- 正式评审期如迁移常驻 VPS，仅更换部署环境，端点契约、slug、commit 校验逻辑不变，并会通过补充 PR 披露。
