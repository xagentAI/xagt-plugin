# Agent Acceptance Gate 收入路线拆分

Created: 2026-07-02
Status: execution_map

## 目标

目标不是做一个小工具，而是冲 OKX.AI 上的 OPC 级收入：

```text
$1M ARR = $83,333 MRR = $2,740/day
```

要达到这个收入，必须服务最广泛的 Agent 交易场景，而不是只服务“交付后验收”。

## 产品总定位

```text
Agent Acceptance Gate
= Agent 市场里的交易信任层
```

它回答的不只是：

```text
这个交付能不能收？
```

更广义的问题是：

```text
这个 Agent 交易动作现在能不能继续？
```

## 四条收入路线

### Route 1: Pre-hire Gate

触发点：

```text
before_hire_agent
before_accept_task
before_assign_budget
```

用户：

- Buyer Agent；
-任务发布者；
-需要找服务的 Agent。

问题：

```text
这个任务描述够不够清楚？
预算/验收标准/风险边界是否足够让 Agent 接？
```

价值：

- 减少坏任务；
- 减少 scope dispute；
- 帮 Agent 判断该不该接单。

收费：

- 低价高频；
- 可打包进 marketplace task posting flow。

### Route 2: Pre-call Gate

触发点：

```text
before_paid_tool_call
before_buy_service
before_agent_spends_budget
```

用户：

- 会调用付费 API/MCP 的 Agent；
- 管预算的 buyer agent；
- ASP workflow。

问题：

```text
这次调用是否必要？
输入是否足够？
会不会触发钱包/凭证/部署等 hard gate？
```

价值：

- 避免无效付费调用；
- 防止 agent 乱花预算；
- 保护敏感动作。

收费：

- 高量低价；
- 可作为 agent wallet / budget guard。

### Route 3: Delivery Acceptance Gate

触发点：

```text
before_submit_delivery_to_buyer
before_accept_delivery
before_release_payment
```

用户：

- Seller Agent；
- Buyer Agent；
-人类买家。

问题：

```text
这次 Agent 交付能不能被接受？
缺什么证据？
有没有 hard gate 没过？
```

价值：

- 防止为半成品付款；
- 提高 ASP 交付通过率；
- 形成标准验收包。

收费：

- 中价；
- 可按交付任务计费；
- 最适合当前 demo。

### Route 4: Dispute / Evaluator Gate

触发点：

```text
before_dispute_vote
after_buyer_rejects_delivery
after_seller_claims_completion
```

用户：

- Evaluator Agent；
- marketplace dispute system；
-买卖双方。

问题：

```text
争议里的事实是什么？
seller 是否真的交付？
buyer 拒绝是否有证据？
```

价值：

- 降低仲裁成本；
- 提高 dispute 一致性；
- 可沉淀 reputation / credit。

收费：

- 高价低频；
- 可从 dispute bounty / evaluator tooling 收费。

## 最广泛应用场景

最广泛的不是“交付验收”，而是：

```text
Agent transaction gate
```

任何 Agent 想做一个会消耗钱、释放钱、影响外部状态、产生争议的动作前，都可以调用。

这包括：

- 接任务；
- 花预算；
- 买服务；
- 交付成果；
- 放款；
- 发布；
- 仲裁；
- 记录信誉。

## 收入结构

如果只靠 Route 3，规模受 Agent 任务交付量限制。

要冲 $1M ARR，需要组合：

```text
Route 2 高频调用守门
+ Route 3 中频交付验收
+ Route 4 高价值争议包
+ ASP / marketplace subscription
```

推荐收入目标拆分：

| Revenue source | Target MRR | Role |
|---|---:|---|
| Pre-call / budget guard | $20k | 高频底盘 |
| Delivery acceptance | $30k | 核心 wedge |
| Dispute/evaluator packets | $15k | 高价值场景 |
| ASP subscription / marketplace plan | $20k | 稳定收入 |
| Total | $85k | $1M ARR pace |

## 当前产品该怎么扩

现在已有 Route 3。

下一步要扩到 Route 2：

```text
Can this agent spend budget on this paid service call?
```

原因：

- 更高频；
- 更贴近 agent wallet / payment；
- 更容易产生付费调用；
- 和 OKX.AI / x402 / A2MCP 关系更强。

但 Route 2 也更接近支付/钱包 hard gate，所以当前只能先做 metadata / schema / dry-run demo。

## 30 小时抢先路线

### 0-3 小时

- 已上线 static demo；
- 已建 repo；
- 已有 discovery / MCP manifest / OpenAPI。

下一步：

- 发一条 build-in-public X；
- 明确 category：`Agent transaction gate`。

### 3-12 小时

补：

- `assess_agent_transaction` schema；
- Route 2 sample；
- demo 文案从 delivery-only 改为 transaction gate；
- hackathon packet。

### 12-24 小时

补：

- public API endpoint；
- auth/rate limit draft；
- idempotency key；
- privacy / terms draft。

Hard gate:

- public endpoint deploy 需要 Leo 明确确认。

### 24-30 小时

准备：

- OKX.AI ASP listing packet；
- hackathon submission;
- demo video / screenshots;
- first 10 usage examples.

Hard gate:

- OKX Agentic Wallet / receiving address / payment middleware / ASP submission。

## 现在不该做什么

- 不要直接声称能冲 $1M；
- 不要声称是 OKX 官方；
- 不要接钱包/支付；
- 不要把 demo 说成生产服务；
- 不要只停留在“验收页面”。

## 当前最短发布文案

```text
Agent marketplaces do not just need more agents.
They need transaction gates.

Before an agent accepts a task, spends budget, submits delivery, releases payment, or votes on a dispute, another agent should be able to ask:

Can this transaction continue?

I built the first prototype: Agent Acceptance Gate.
```

