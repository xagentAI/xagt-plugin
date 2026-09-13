# YAI Agent Core · X-Agent MCP Hackathon 提交说明

- **项目名**：YAI Agent Core（yai-agent-core）
- **提交团队**：YAI（单人开发者 Gi-Tuu，https://github.com/Gi-Tuu）
- **一句话定位**：进程内嵌入式、自适应的 Agent 内核——已有软件只需声明自己的普通业务函数（或挂载 MCP Server），Core 自动发现能力、自适应选择执行策略并完成任务，**宿主不写一行 Agent Loop / Planner / 工具选择代码**。
- **在线 API**：https://yai-agent-core.onrender.com
- **源码仓库**：https://github.com/Gi-Tuu/yai-agent-core（MIT）
- **评审基线 commit**：以 `submission.json` 的 `reviewCommit`（40 位 SHA）为准，与 `/health`、`/.well-known/xagent-verification.json` 三处一致。

---

## 1. 解决什么真实问题

市面上的 Agent 形态分两类：平台型（Dify/Coze，要把东西搬进别人的云）和框架型（LangGraph/OpenAI Agents SDK，开发者仍要自己定义 Agent、工具、编排）。
大量已有软件（笔记应用、数据后台、陪伴 App）想要 Agent 能力，但不想重写、不想上云、也不想在业务代码里堆 Agent 胶水代码。

YAI Agent Core 类比"Agent 世界的 SQLite"：以库的形式运行在宿主进程内，范式是 **host-declares-capability / core-adapts**：

1. 宿主只提供普通 Python 函数（type hints + docstring），Core 内省生成工具规格；
2. 外部 MCP Server 的工具经 MCP Client 同构接入（v0.2 已落地）；
   Core 同时内置 OpenAPI 发现（可选）：任意 OpenAPI 3 REST API 提供描述即可被自动注册为工具，
   与 MCP 工具在同一 Tool Bus 上同构调度（read_only 只读模式可用于公网演示）；
3. Adaptive Router 把任务路由到 `direct / react / plan / clarify` 四种策略：
   v0.2 起先由模型做一次轻量分类（输出 `{strategy, reason, tier}` JSON），
   超时/异常/非法输出自动回退确定性规则，**两条路径都返回带来源的决策记录**；
4. Agent Loop 完成 ReAct 工具循环 / 计划拆解执行（规划轮使用路由建议的模型档位）；
5. 每一次策略选择（含 `source=llm|rules` 与理由）、工具调用、权限确认都作为事件流出，
   **过程可审计，不是黑盒**。

它不是又一个需要开发者拼装的 Agent 框架，而是可以"装进软件里"的内核；项目最终将回流嵌入开源 AI Companion 项目 AMBRACE。

## 2. 在线能力（评审可直接调用）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查，返回 `status` 与本次部署的 40 位 commit |
| `/.well-known/xagent-verification.json` | GET | 部署证明：`schemaVersion=1` + `slug` + `commit` |
| `/v1/tools` | GET | 当前宿主注册的全部工具（含 `source: native/mcp` 来源标注；线上实例同时挂载本地笔记工具与公共 DeepWiki MCP Server 的 3 个远程工具） |
| `/v1/agent/run` | POST | 入参 `{"task": "..."}`，返回策略、最终结果与**全过程事件流**；任务涉及外部仓库问答时会真实发起 MCP 工具调用 |

可复现的 curl 命令与期望输出见 `verification/README.md`。

> 免费实例 15 分钟无流量会休眠，首次请求冷启动约 30–90 秒，请耐心等待或先请求一次 `/health` 唤醒。

## 3. 工程与架构

```
src/yai_core/
├── types.py             # ToolSpec / AgentEvent / Strategy 等核心数据结构（零依赖）
├── spi/                 # Model / Channel / Memory / Policy 四个可替换契约
├── discovery/           # 宿主函数内省 → ToolSpec（能力自发现）
├── tools/               # ToolRegistry（统一花名册）+ ToolExecutor（权限→执行→事件）
├── kernel/              # AdaptiveRouter（策略路由）+ Context + AgentLoop（主循环）
├── llm/                 # OpenAI 兼容模型后端（DeepSeek 等，可选依赖、懒加载）
├── memory/ policy/ channels/   # 默认实现：内存记忆 / 白名单权限 / CLI·收集通道
├── integrations/mcp/    # MCP Client 桥接（可选 [mcp] 依赖、懒加载）
└── batteries/fastapi_server/   # 在线 API Battery（可选 [server] 依赖）
```

关键工程原则：

- **内核本体零第三方硬依赖**：`pyproject.toml` 的 `dependencies` 为空；openai / fastapi / mcp 全部是可选 extras 并在模块内懒加载，有 AST 测试防止顶层误引入。
- **工具同构**：本地函数与外部 MCP 工具在 ToolRegistry 中都是 ToolSpec，Router/Loop/Executor 对工具位置零感知。
- **错误回灌而非崩溃**：工具（含 MCP 工具）异常被捕获为失败结果回灌模型，事件流照常完整。
- **可复现**：`uv.lock` 锁定全部依赖；Dockerfile 多阶段构建、`docker compose` 一键起；Render Blueprint（`render.yaml`）即点即部署。

## 4. 测试与可观测

- 离线测试 **125 项**全部通过（截至 v0.3，以 `pytest -q` 实跑为准；不需要网络与 API Key）：用 ScriptedModel 假模型、内存态 MCP Server 假外部服务、`httpx.MockTransport` 假 REST 端点，覆盖路由、ReAct/Plan 循环、权限、MCP/OpenAPI 桥接、记忆保留策略、限流与 API 端点。
- GitHub Actions CI 矩阵：Ubuntu × Python 3.11/3.12/3.13 + Windows × 3.13。
- 每次运行返回完整事件序列（strategy_selected / plan_created / tool_call / tool_result / done…），可直接作为评审的"能力证据"。
- 长期运行的记忆治理：历史支持条数上限与 TTL（opt-in，按对话轮对齐裁剪，不拆散工具调用对），SQLite 存储在写入与启动时自动清理过期历史，裁剪规则为纯函数并有对等测试。

## 5. MCP 产品化准备（对应 15 分评分项）

- 工具边界清晰：每个工具有 name / description / JSON Schema 入参，MCP 工具 schema 经白名单清洗后与本地工具同构；
- 已实现 MCP Client（官方 Python SDK v2），支持 Streamable HTTP、stdio 子进程、内存直连三种传输；
- **线上 API 自身即 MCP 消费方**：部署期通过 `MCP_SERVER_URL` 环境变量挂载公共免鉴权 MCP Server（DeepWiki），评审可直接 POST 任务让线上服务真实调用远程 MCP 工具，挂载失败不影响本地工具与验证端点（优雅降级）；
- 错误语义明确：MCP `is_error` 统一翻译为失败结果并产生 `tool_result(ok=false)` 事件；
- 权限、副作用边界在 Tool Bus 一层统一收口；超时（规划中）同样收口于此；已实现评审期限流（每 IP 每分钟 30 次、429 + Retry-After，GET 验证端点不受限）；
- 入选后可直接配合 X-Agent 做工具边界与 I/O schema 标准化，本项目自身不绑定任何特定 MCP Server。

## 6. 安全与数据处理（评审须知）

- 线上服务不提供账号体系、不采集个人信息：仅使用演示宿主自带的 3 条虚构笔记；会话历史按部署配置可落盘（`YAI_DB_PATH`，Render 免费层为临时盘、实例重建即清空），不用于任何训练或分析用途。
- 出站请求仅发往配置的 LLM 端点（线上为 DeepSeek 官方 API）；代码内无任何遥测/统计 SDK。
- API Key 仅存在于部署平台 Secret 与本地 `.env`（gitignore），不入库、不入镜像层（`.dockerignore` 排除）。
- 评审期端点开放调用（满足"可在线调用"要求），已加按 IP 的零依赖限流（每 IP 每分钟 30 次，超限返回 429 与 Retry-After；health/verification/tools 三个验证端点不受限）；不提供登录墙。
- 依赖与授权清单见 `RIGHTS.md`。

## 7. 本地复现（隔离环境，5–10 分钟）

```bash
git clone https://github.com/Gi-Tuu/yai-agent-core && cd yai-agent-core
uv venv && uv sync --extra dev --extra llm --extra server --extra mcp
uv run pytest                     # 23 passed，离线
uv run ruff check src tests examples scripts
python scripts/smoke_test.py      # 同一内核自适应三个不同宿主（离线）
docker compose up --build         # 容器化（容器内 8000，宿主 127.0.0.1:8001）
```

接真实模型：复制 `.env.example` 为 `.env` 填入 OpenAI 兼容 Key（DeepSeek 等），运行
`python examples/host_d_mcp/run.py` 可看到本地工具与 MCP 工具在同一注册表里协同。

## 8. 已知限制（诚实声明）

- 免费层部署会休眠、冷启动约 1 分钟；正式评审期将迁移常驻 VPS（手册见仓库 `docs/competitions/deployment.md`）。
- 当前模型路由为确定性规则（LLM 路由器在 v0.2 路线上，规则兜底）；记忆为内存态（SQLite 在路线图）。
- 不做 MCP Server、Multi-Agent、向量记忆、内置 UI（明确的 v0.1 红线，避免过度设计）。
