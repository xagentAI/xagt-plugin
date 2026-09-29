# Agent 市场生态分析：Agent 验收门禁

Created: 2026-07-02
Status: local_research_synthesis

## 核心结论

这个产品应该是 `Agent-first, human-readable`。

也就是说：

```text
Agent 调用服务；
人类看结论；
市场按有效审计结果计费；
争议时复用证据。
```

它不是普通用户每天主动打开的 App，而是 Agent 市场里的验收基础设施。

## 1. 现在市场/生态里已经有什么

### A. Agent 工具 / MCP 市场

现状：

- MCP 已成为 Agent 连接外部工具的重要标准；
- 公开 MCP 工具数量已经非常大；
- 工具发现、工具路由、工具安全正在变成独立问题。

含义：

单纯“再做一个 MCP 工具”不够。必须明确告诉 Agent：

```text
什么场景必须调用我。
```

本产品的触发词应该是：

- `before_accept_delivery`
- `before_release_payment`
- `before_submit_delivery`
- `before_dispute_vote`
- `before_public_release_or_deploy`

### B. Agent observability / evaluation

代表：

- LangSmith
- Braintrust
- HoneyHive
- Arize

它们主要卖：

- trace；
- evaluation；
- prompt / dataset / regression；
- production monitoring；
- human annotation。

缺口：

它们偏“开发者运营 Agent 系统”，不直接解决市场交易里的问题：

```text
这次 Agent 交付到底能不能收？
```

所以我们不要和它们正面竞争 observability，而是切 `acceptance gate`。

### C. Agent commerce / task marketplace

代表方向：

- OKX.AI A2MCP / A2A；
- x402 / HTTP 402 pay-per-call；
- AI hires humans / AI hires services 类 marketplace。

OKX.AI 的关键点：

- A2MCP：标准 API/MCP，按次收费，无需协商；
- A2A：Agent 协商价格、scope、delivery，资金 escrow，用户确认后释放。

这正好给本产品两个入口：

1. A2MCP：作为可调用验收 API；
2. A2A：作为交付/争议流程里的验收门禁。

## 2. 别人都在做什么

别人主要在做四层：

### 工具连接层

让 Agent 能调用 Slack、Figma、GitHub、数据库、支付、搜索、浏览器。

问题：

工具越来越多，Agent 不知道何时该调用哪个，且调用后结果难验收。

### 观测评测层

记录 Agent trace，做 eval，找失败原因。

问题：

它们通常面向开发团队，不是面向买家付款/交付验收。

### 支付协议层

用 x402 / Payment SDK / escrow 让 Agent 能按次买 API、买服务、雇人。

问题：

支付可以自动化，但“该不该付款”仍需要验收逻辑。

### 任务市场层

让 Agent 领任务、发布任务、雇人或雇其他 Agent。

问题：

市场越开放，越需要 acceptance / dispute / evidence layer。

## 3. 大众需要的东西是什么

如果说“大众”是普通个人用户，他们不需要“agent audit”。

他们需要的是：

- 别被骗；
- 少返工；
- 不要为半成品付款；
- 不要把没验证的东西上线；
- 出问题时有人能说清楚责任。

如果说“大众”是 Agent 市场里的大量 Agent / ASP / buyer agent，它们需要的是：

- 自动找工具；
- 自动验收；
- 自动补证据；
- 自动生成交付报告；
- 自动判断是否能放款；
- 自动进入争议流程。

所以产品文案必须从：

```text
Audit agent deliverables
```

改成：

```text
Can this agent delivery be accepted?
```

## 4. 有没有 Agent 可以去领任务

有这个方向。

OKX.AI 的 A2A 模式就是 Agent 与 Agent 协商任务、价格、scope、delivery，资金进 escrow，用户确认后释放。

更广义上，AI hires humans / Agent hires services 的市场也已经出现。

这说明未来市场结构可能是：

```text
User / Buyer Agent 发布任务
↓
Seller Agent / ASP 接任务
↓
Seller Agent 调用工具完成任务
↓
Acceptance Gate 审计交付
↓
Buyer Agent / Human 决定 accept / reject / dispute
↓
Payment / escrow release
```

我们的服务应该卡在：

```text
交付 -> 放款 / 接受 / 争议
```

之间。

## 产品定位建议

不要定位：

```text
Agent Deliverable Auditor
```

应该定位：

```text
Agent Acceptance Gate
Agent 验收门禁
```

## Agent 自动发现策略

需要机器可读 metadata：

- service name；
- tool name；
- call_when；
- do_not_call_for；
- input schema；
- output schema；
- billable event；
- pricing mode；
- risk boundaries；
- tags。

本地已补：

- `discovery/agent-service.json`
- `discovery/mcp-tool-manifest.json`
- `openapi.yaml`

未来如果发布到市场，应把这些 metadata 提交到：

- OKX.AI ASP listing；
- MCP registry / directory；
- GitHub README；
- leolabs product brief；
- ChatGPT / Claude app-style manifest（如果走该渠道）。

## 最小可抢先发布形态

不要直接做正式收费。

推荐先发：

```text
Agent Acceptance Gate
Local demo + API draft + public-safe writeup
```

发布目标不是赚钱，而是抢占概念：

```text
Agent marketplace 缺的不是更多 Agent，而是交付验收层。
```

## 下一步

1. 用 10 个真实 worker writeback 跑一轮。
2. 把 `call_when` 和 `machine_flags` 调到足够精准。
3. 决定公开渠道：X / leolabs / GitHub / OKX.AI。
4. 真正上 OKX.AI 前，必须补 endpoint deploy、payment middleware、receiving wallet、privacy/terms/rate limit。
