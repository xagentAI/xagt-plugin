# YAI Agent Core 架构设计

## 1. 设计原则

1. **Library-first（进程内库）**：`pip install` 后运行在宿主进程内，不独立起服务、不要求云端。
2. **Host-declares-capability**：宿主只声明能力（普通函数/OpenAPI/MCP），Core 负责一切 Agent 逻辑。
3. **内核最小**：判断标准——"是不是任何宿主都需要？"否则进 batteries/ 或 adapter。
4. **零硬依赖**：内核只用标准库；openai / fastapi 为可选依赖、懒加载。
5. **自适应必须可解释**：每个决策产出 Observer 事件，禁止黑盒。
6. **模型/通道/存储无关**：通过 SPI 契约解耦，Core 给零配置默认实现。

## 2. 分层

```
宿主应用（AMBRACE / host_a / host_b）      只声明能力，零 Agent 代码
        │ 内省 / 注册
能力自发现 Auto-Discovery（函数 / OpenAPI[v0.3] / MCP Client[v0.2 已落地]）
        ▼
YAI Kernel
  ├─ Adaptive Router   任务分类 → direct/react/plan/clarify + 模型 tier
  ├─ Agent Loop        按策略执行（工具循环、计划拆解、澄清重入）
  ├─ Context           消息组装与 token 预算
  └─ Tool Bus          权限 → 执行（sync/async）→ 结构化结果
        ▲
SPI 契约环（可替换 + 默认实现）
  ModelProvider(OpenAI 兼容) / Channel(CLI·FastAPI·Flutter)
  MemoryStore(内存→SQLite→向量) / PermissionPolicy(auto/ask/deny)
        ▲
Integrations（可选，懒加载）：MCP Client（integrations/mcp/，[mcp] extra）
Batteries（可选）：FastAPI Server、SQLite Memory
```

### 2.1 MCP Client 集成（v0.2 已落地）

```
MCP Server（HTTP / stdio 子进程 / 内存实例）
   │  list_tools / call_tool（MCP Python SDK v2，可选依赖、懒加载）
   ▼
McpToolBridge（integrations/mcp/client.py）
   ├─ sanitize_schema      清洗 SDK 生成 schema 里的私有键
   ├─ _to_spec             每个远端工具 → ToolSpec(source="mcp")，handler 为异步闭包
   └─ _flatten_call_result content 文本 / structured_content / is_error → 返回值或异常
   ▼
ToolRegistry（与 Native 工具同构，Router/Loop/Executor 零感知）
```
- 内核本体不 import mcp（AST 测试守红线）；`uv sync --extra mcp` 才启用。
- 连接三态：`McpServerConfig.url`（Streamable HTTP）/ `command+args`（stdio 子进程）/
  `server`（内存实例，离线测试用）；`prefix` 解决多 Server 工具重名。
- 生命周期：`async with McpToolBridge(...)` 或 `connect()/aclose()` 手动管理；
  stdio 形态必须 aclose，否则子进程成为孤儿。

### 2.2 持久化记忆（SQLite，v0.2 已落地）

`memory/sqlite_store.py` 提供 `SqliteStore`：MemoryStore 契约的 SQLite 实现（标准库、
零新依赖）。history/kv 两张表，`scope` 列做会话隔离，`PRAGMA user_version` 做迁移钩子，
WAL + 单锁覆盖单进程并发；`history()` 保持契约的同步签名。装配走 `YAI_DB_PATH`
（`SqliteStore.from_env()`），未设置时回退 InMemoryStore，线上默认不开启（免费 PaaS 临时盘）。
Loop/Core/宿主示例零改动。边界（历史裁剪、多进程写、临时盘持久性）见 walkthrough 第 11 章 H 节。
历史保留策略（v0.3，opt-in）：`memory/retention.py` 提供纯函数 count_cut/ttl_cut，
两种 Store 以构造参数 max_messages / ttl_seconds / clock 对等支持；裁剪边界按"轮"
对齐（一条 user 到下一条 user 之前为一轮），保证 assistant(tool_calls)/tool 配对
不被拆散；SQLite 构造时自动 prune 一次覆盖重启场景。MemoryStore 契约与 schema
版本（仍为 v1）不变；KV 的 TTL 需 schema v2 迁移，留待 v0.4。`Context._compact`
同步改为轮边界丢弃（kernel 内同源私有实现）。

### 2.3 OpenAPI 发现（v0.2 已落地）

`integrations/openapi/` 把任意 OpenAPI 3 描述自动翻译成 ToolSpec(source="openapi")（alias 仅用于日志与 notes）：
spec.py 负责载入/版本闸/内部 $ref 内联（循环与外部引用保留并记 notes），discovery.py
纯函数地把 operations 规划成工具（operationId/合成命名、path/query/body 入参合并、
include/exclude、read_only 只留 GET/HEAD、max_operations=40 截断），client.py 用懒加载的
httpx 执行（bearer/apiKey 鉴权令牌走环境变量、调用期校验、204/非2xx/JSON/文本截断归一）。
httpx/pyyaml 在 [openapi] extra，内核本体零硬依赖；测试全部走 httpx.MockTransport 离线。
与 MCP 桥同构，在 serve_example 的 app_lifespan 中顺序挂载、共用关闭列表。

## 3. SPI 契约

| 契约 | 方法 | 默认实现 | 宿主何时替换 |
|---|---|---|---|
| ModelProvider | `achat(messages, tools, tier)` | OpenAICompatProvider（DeepSeek 等） | 接私有模型/本地模型 |
| Channel | `emit / ask / confirm` | CollectChannel、CliChannel | Web SSE、Flutter UI |
| MemoryStore | `history / put / get / clear` | InMemoryStore | SQLite、向量记忆 |
| PermissionPolicy | `check(tool, args) → allow/deny/ask` | AllowlistPolicy | 高危工具人工确认 |

## 4. Adaptive Router 状态机

```
任务文本 + 可用工具集
   ├─ 无工具                → direct（模型直接答）
   ├─ 模糊短句              → clarify（Channel.ask 后重入）
   ├─ 含行动词 + 多步骤信号 → plan（先拆解，再 react）
   └─ 含行动词              → react（工具循环）
```

v0.2（已落地）：LLM 一次性分类输出 `{strategy, reason, tier}`，异常/超时/非法输出回退规则路由；
两条路径统一返回 RouteDecision，`strategy_selected` 事件带 `source=llm|rules` 可审计。

## 5. 启动在线 API（batteries）

```python
import os, uvicorn
from yai_core import AgentCore, OpenAICompatProvider
from yai_core.batteries.fastapi_server import create_app
import my_app_capabilities as cap

core = AgentCore.auto(cap, OpenAICompatProvider())
app = create_app(core)
# 环境变量：YAI_GIT_COMMIT=<40位 commit>、YAI_PROJECT_SLUG=<slug>
# 容器内监听 8000；宿主机端口由部署侧映射（本项目约定 8001:8000）
# uvicorn module:app --host 0.0.0.0 --port 8000
```

v0.3 评审期限流（默认开启）：`rate_limit.py` 提供每 IP 滑动窗口（`enabled=True`、
`per_minute=30`、`window_seconds=60`，可用 `YAI_RATE_LIMIT_*` 调整或关闭）。中间件只拦
`POST /v1/agent/run`，超限返回 429 + `Retry-After`（与响应体同源），被限请求不触达
模型；三个 GET 验证端点永不限流（评审硬门槛）。客户端身份取 XFF 最左非空、回退对端
地址；状态只在内存，重启清零；全局限流兜底不做（单实例）。

## 6. 与生态的差异化（诚实对比，用于比赛材料）

- Claude/OpenAI Agents SDK、LangGraph：developer-builds-agent，工具/编排需显式定义，且绑定自家生态；
- agentic-kernel（TS）：嵌入式运行时理念相近，但仅 TypeScript 且无能力自发现/策略自适应；
- MCP：工具互操作**协议**，不是运行时；YAI 是 MCP 的消费者（v0.2 Client）而非竞争者；
- YAI：host-declares-capability、Python 进程内、模型/通道/存储全无关、自适应过程可观测。

## 7. 明确不做（v0.1 红线）

MCP Server、Multi-Agent 编排、自进化写工具、向量长期记忆、内置 UI、coding agent 场景、队列/中间件、K8s。
