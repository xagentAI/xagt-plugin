# Agent 市场需求调研：先看生态，再选产品

Created: 2026-07-02
Status: market_research_v1

## 结论先行

`Agent Acceptance Gate` 不是当前最确定的大需求。

它是一个 **有战略价值、但依赖 Agent 市场交易量起来的基础设施切口**。

如果目标是 OKX.AI 上 $1M ARR OPC，应该先研究整个 Agent 市场的高频交易节点，而不是先押一个产品。

当前最可能赚钱的方向不是“验收工具”本身，而是：

```text
Agent commerce operations layer
```

也就是围绕 Agent 接任务、花预算、调用服务、交付、结算、争议、信誉这些动作，提供高频、可计费、可自动调用的基础服务。

## 1. Agent 市场未来会是什么样

未来 Agent 市场大概率不是一个单点工具市场，而是多层市场：

```text
User / Human
↓
Buyer Agent
↓
Task / Intent Market
↓
Seller Agent / ASP
↓
Tool / MCP / API Market
↓
Payment / Escrow / Settlement
↓
Evidence / Verification / Reputation
```

### Layer A: Intent / Task layer

用户不再逐个找服务，而是把目标交给 Agent。

需求：

- 把人类意图转成可执行任务；
- 定义预算；
- 定义验收标准；
- 选择 seller agent / ASP。

高频点：

- task clarification；
- scope decomposition；
- vendor/service matching；
- budget allocation。

### Layer B: Service / Tool layer

Agent 为完成任务调用工具：

- MCP server；
- paid API；
- data service；
- research service；
- code/build/deploy service；
- human service。

需求：

- 发现工具；
- 判断工具是否可信；
- 控制预算；
- 记录调用结果；
- 防止恶意工具 / 过度调用。

### Layer C: Transaction / Payment layer

Agent 会自己发起小额、高频交易。

需求：

- pay-per-call；
- subscription；
- escrow；
- refund；
- settlement；
- rate limit；
- payment authorization。

这层是大市场，因为所有服务都要过钱。

### Layer D: Verification / Clearing layer

交易之后要判断是否完成。

需求：

- evidence envelope；
- acceptance check；
- dispute packet；
- reputation update；
- settlement instruction。

这层不是最高频，但一旦平台有真实交易，会变成基础设施。

## 2. 当前生态具体情况

### OKX.AI

OKX.AI 文档已经定义三类角色：

- User；
- ASP；
- Evaluator。

ASP 有两种服务模式：

- A2MCP：标准 API/MCP 服务，按次收费，瞬时结算；
- A2A：Agent 间协商价格、scope、delivery，资金 escrow，用户确认后释放。

这说明 OKX.AI 想做的不只是聊天机器人，而是 Agent commerce marketplace。

证据：

- https://web3.okx.com/onchainos/dev-docs/okxai/asp
- https://web3.okx.com/onchainos/dev-docs/payments/service-seller

### MCP 工具生态

公开研究统计了 177,436 个 MCP tools。软件开发占比很高，action tools 的占比从 27% 上升到 65%。

含义：

```text
Agent 正在从“读信息”变成“改环境/执行动作”。
```

高频需求会从信息检索转向：

- action safety；
- permissions；
- tool trust；
- cost control；
- observability；
- rollback。

证据：

- https://arxiv.org/abs/2603.23802

### Agent hiring / task market

RentAHuman 这类 marketplace 已经出现，AI agent 可以通过 API/MCP 雇佣人类完成任务，并用 escrow / payment 处理交付。

研究也指出这类市场已经带来 abuse / credential fraud / impersonation / referral fraud 等问题。

含义：

```text
Agent 市场一旦有任务和钱，安全、验收、争议会很快变成平台问题。
```

证据：

- https://www.wired.com/story/ai-agent-rentahuman-bots-hire-humans
- https://arxiv.org/abs/2602.19514

### Agentic payment / commerce

x402、AP2、UCP、Visa / Mastercard agent payments 都说明一个趋势：

```text
Agent 会开始自动发起商业交易。
```

但相关论文也指出支付协议存在 replay、context binding、paid-but-denied、unpaid-service 等问题。

含义：

支付本身不是终点。Agent commerce 还需要：

- authorization；
- mandate；
- context binding；
- fraud detection；
- clearing / verification；
- dispute handling。

证据：

- https://arxiv.org/abs/2605.11781
- https://arxiv.org/abs/2604.11430
- https://arxiv.org/abs/2606.08790
- https://www.axios.com/2025/09/16/google-ai-agents-ecommerce-online-shopping

## 3. 哪些服务需求会很高、调用量很大

按调用频率排序：

### 1. Tool discovery / routing

问题：

```text
Agent 现在该调用哪个服务？
```

频率：

极高。每个任务都可能触发多次。

付费意愿：

中等。平台/开发者愿付，普通用户感知弱。

竞争：

强。MCP registry、tool router、Composio/Zapier 类都会做。

Leo 适配度：

中低。需要强平台分发和大量工具索引。

### 2. Budget / payment guard

问题：

```text
Agent 这次该不该花钱？
是否越过预算或授权边界？
```

频率：

高。每次 paid API / service call 都可触发。

付费意愿：

高。因为直接保护钱。

竞争：

正在形成。支付方、wallet、x402/AP2 middleware 都会做。

Leo 适配度：

中。可做轻量 policy / evidence / metadata filter，但钱包集成是 hard gate。

### 3. Credential / permission / action safety

问题：

```text
Agent 是否可以访问这个凭证、执行这个 action？
```

频率：

高。尤其 enterprise agent。

付费意愿：

高。

竞争：

强。安全公司、身份权限平台、cloud provider 会进入。

Leo 适配度：

中低。需要安全资质和企业 trust。

### 4. Delivery acceptance / verification

问题：

```text
Agent 做完了吗？能不能收？证据够不够？
```

频率：

中。每个任务交付触发一次或几次。

付费意愿：

中高。金额越大越强。

竞争：

中。现有 eval/observability 偏开发者，不是 marketplace acceptance。

Leo 适配度：

高。这是当前最适合切入的 wedge。

### 5. Dispute / evaluator packet

问题：

```text
买卖双方争议时，事实是什么？该怎么判？
```

频率：

低到中。取决于交易量和 dispute rate。

付费意愿：

高。因为每次争议有明确价值。

竞争：

早期。可能会被平台内建。

Leo 适配度：

中高。适合作为 acceptance 的高价扩展。

### 6. Reputation / credit scoring

问题：

```text
这个 Agent / ASP 历史上可靠吗？
```

频率：

高。每次选服务都可用。

付费意愿：

高，但更像平台资产。

竞争：

平台会强控。

Leo 适配度：

低到中。除非先积累大量验收/争议数据。

### 7. Data / research / analysis services

问题：

```text
Agent 需要外部数据和分析能力。
```

频率：

高。

付费意愿：

中高。

竞争：

极强。数据/API/研究服务非常拥挤。

Leo 适配度：

中。可以做垂直 niche，但不适合泛化。

## 4. 哪些领域市场容量最高

按潜在市场容量排序：

### Tier 1: Payment / budget / transaction infrastructure

市场容量最高。

原因：

- 所有 agent commerce 都要经过支付和授权；
- 高频；
- 和钱直接相关；
- 企业/平台愿付。

风险：

- 监管/合规/钱包/安全要求高；
- 大公司和支付网络会进入；
- 一人公司很难直接做核心 payment rail。

适合 Leo 的切口：

```text
pre-payment policy / budget guard / metadata risk check
```

不要碰 custody / signing / settlement。

### Tier 2: Security / permission / abuse prevention

市场容量很高。

原因：

- Agent 能执行 action 后，安全风险迅速上升；
- 恶意 MCP server、prompt injection、credential fraud 都是真问题。

风险：

- 需要深安全信誉；
- 销售周期偏企业。

适合 Leo 的切口：

```text
lightweight agent action risk preflight
```

### Tier 3: Tool routing / workflow orchestration

市场容量高，调用频率高。

原因：

- Agent 需要找工具、组合工具、执行工作流；
- Zapier / Composio / MCP registry 都说明这是大方向。

风险：

- 竞争最激烈；
- 平台型玩家强。

适合 Leo 的切口：

```text
不要做泛工具路由，做 trust-aware routing / risk-aware routing。
```

### Tier 4: Verification / acceptance / clearing

市场容量中高，但取决于交易量。

原因：

- 只要有交易，就需要验收和清算；
- 但早期交易量不足时需求不明显。

风险：

- 太早；
- 容易被平台内建；
- 独立工具感知弱。

适合 Leo 的切口：

```text
先作为 OKX.AI / ASP hackathon wedge，验证平台是否愿意采用。
```

### Tier 5: Domain-specific agent services

市场容量取决于领域。

高潜领域：

- coding / deployment；
- data / research；
- trading / market data；
- compliance / legal ops；
- customer support；
- commerce / shopping。

风险：

- 每个领域都需要专业深度；
- 泛化困难。

适合 Leo 的切口：

```text
用自身强项做 niche：agent workflow QA / trading research QA / website release QA。
```

## 5. 对当前 Agent Acceptance Gate 的重新判断

### 它不是最大市场

最大市场在：

- payment / budget；
- permission / safety；
- tool routing；
- workflow orchestration。

### 它是合理 wedge

原因：

- 小团队能做；
- 和 OKX.AI ASP 叙事相关；
- 可以快速 demo；
- 可拓展到 dispute / reputation；
- 不必一开始碰钱包和签名。

### 最大风险

它可能是：

```text
平台应该内建的功能，而不是第三方 ASP。
```

如果 OKX.AI 自己在 delivery / escrow / dispute flow 内建验收，独立 ASP 空间会变小。

### 是否继续

继续，但必须改目标：

```text
不要把 Agent Acceptance Gate 当终局。
把它当进入 Agent commerce ops 的 wedge。
```

## 6. 更好的机会排序

按照 `市场容量 × 高频 × Leo 可做性 × 当前时机` 排序：

### #1 Agent Spend Guard

一句话：

```text
Before an agent spends money, check policy, evidence, budget, and risk.
```

为什么好：

- 高频；
- 跟钱直接相关；
- 比 delivery acceptance 更广；
- 可从 metadata / policy 做起，不碰签名。

风险：

- 接近 payment hard gate；
- 需要和 x402 / OKX Payment SDK / Agentic Wallet 关系清楚。

### #2 Agent Acceptance Gate

一句话：

```text
Before accepting or releasing payment for an agent delivery, check evidence and gates.
```

为什么好：

- 当前已有 demo；
- 易解释；
- 可参加 hackathon；
- 可作为 spend guard 的后置场景。

风险：

- 频率不如 spend guard；
- 依赖任务市场流量。

### #3 Agent Evidence Envelope

一句话：

```text
Standard package for agent delivery evidence: artifacts, validation, logs, risk flags, next gate.
```

为什么好：

- 更底层；
- 可被 acceptance、dispute、reputation 复用；
- 不一定需要收费服务，可能成为标准。

风险：

- 标准化很难变现；
- 需要生态采纳。

### #4 Dispute Fact Packet

一句话：

```text
When buyer and seller disagree, generate a structured fact packet for evaluators.
```

为什么好：

- 高价值；
- 争议场景有强需求；
- 和 OKX Evaluator 角色贴合。

风险：

- 交易量和 dispute volume 未知；
- 低频。

### #5 Trust-aware Tool Router

一句话：

```text
Route agents to tools based not only on capability, but also cost, risk, and evidence requirements.
```

为什么好：

- 高频；
- 市场大。

风险：

- 竞争强；
- 需要大量工具索引。

## 7. 当前最应该做什么

不要继续只打磨 demo。

应该做市场验证：

### A. X / OKX community 反应测试

发一个问题，不发硬广：

```text
If AI agents can spend budget and hire services,
what should happen before they pay?

I think the missing layer is not another agent,
but a transaction gate:
scope, budget, evidence, hard gates, dispute trail.
```

看谁回应：

- OKX / X Layer；
- hackathon builders；
- MCP builders；
- x402 / payment people；
- agent security people。

### B. Hackathon discovery

看 OKX.AI hackathon 具体要求：

- 是否必须上线 ASP；
- 是否看 real usage；
- 是否有 task hall；
- 是否允许 infra/tooling；
- 是否要 Agentic Wallet。

### C. 访谈 5 类人

1. ASP builder；
2. MCP tool builder；
3. agent workflow user；
4. payment/x402 builder；
5. evaluator / dispute-minded builder。

问：

- Agent 花钱前你担心什么？
- Agent 交付后你怎么验收？
- 你愿意为哪一步付费？
- 你觉得平台会内建还是第三方服务？

### D. 用真实任务跑样例

至少 20 个：

- coding agent delivery；
- research agent delivery；
- paid API call decision；
- unsafe action decision；
- failed delivery dispute。

目标不是 accuracy，而是找高频 pattern。

## 8. 最终判断

当前需求结论：

```text
Agent Acceptance Gate 本身不是已验证刚需。
Agent transaction trust / spend guard / evidence layer 是更大方向。
```

执行建议：

```text
继续小成本推进；
不要重仓；
不要急着接钱包/支付；
先用 OKX hackathon 和 X 反应验证 demand。
```

如果市场反馈说明 builders 真正在找：

- budget guard；
- transaction policy；
- evidence envelope；
- dispute packet；

那就从 `Agent Acceptance Gate` 扩成：

```text
Agent Commerce Ops
```

如果反馈只是点赞但没人想用，就停止，不继续投入。

