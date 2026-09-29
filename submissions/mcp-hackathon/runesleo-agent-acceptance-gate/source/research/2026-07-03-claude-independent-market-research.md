# Claude 独立市场重估 — OKX.AI / Agent Commerce（Phase 1 盲评）

- 日期：2026-07-03
- 方法：deep-research workflow（102 agents / 5 搜索角度 / 20 信源 / 93 条 claim 提取 / 25 条对抗验证：22 confirmed · 3 refuted）
- 约束：**未读本 repo 任何产品代码/文档**，纯外部证据盲评（按 CLAUDE_INDEPENDENT_RESEARCH_PROMPT.md Phase 1 要求）
- Run ID：wf_08dca8da-99d（journal: ~/.claude/projects/-Users-zhangxu/323b8d08-9e03-4895-8576-6b1030109b64/subagents/workflows/wf_08dca8da-99d/journal.jsonl）

## TL;DR

OKX.AI（~2026-06-30 上线，BETA）是垂直整合平台：市场、支付、托管、验收/仲裁、核心交易工具**全是平台自营面**。市场战略上大（Bain $300-500B US / McKinsey $3-5T global by 2030）但当下极小且掺水（x402 有机量仅 ~$28-37K/天，约一半交易是刷的）。当下真实高频层是 **A2MCP pay-per-call 数据服务**。**独立验收/验证产品不是正确切入点**——验收已捆绑在平台托管流里（用户签收放款 + 3 天自动验收 + staked Evaluator 仲裁）。一人公司的可防守切入点 = 注册**自有数据 A2MCP 服务**（预测市场信号 / 跨市场数据 / okx-trade-mcp 164 工具未覆盖的交易分析），单次调用定价 $1+，副业挂 Evaluator 赚 OKB bounty。

## 1. Market structure map（confidence: high, 3-0）

- 双边市场：**Agent Marketplace**（ASP 列服务+定价）+ **Task Marketplace**（发任务、交付后付款）
- 三角色：Users / ASPs / staked Evaluators
- 叙事："one person, one company, $1M/year"（OPC）；$1M 是愿景数字不是奖金
- 服务分类：**A2MCP**（标准化 pay-per-call MCP/API：数据查询、价格 feed、工具 API；需 OKX Payment SDK，无议价）vs **A2A**（议价+托管+用户签收才放款）
- 声誉绑定 OKX Agentic Wallet 单一链上身份

## 2. High-frequency service demand map

- 天然高频层 = **A2MCP pay-per-call**（数据查询/价格 feed/工具 API）——OKX 注册文档自己点名的类型
- MCP 生态供给已成规模（官方 registry ~9.6K servers，SDK ~97M 月下载）但 **<5% 注册 server 有真实使用**，变现层缺失（MCP 协议无原生支付）
- A2A 议价层 = 高客单低频，且依赖 Task Marketplace 真实吞吐（BETA 期未知，可能只有供给侧）

## 3. Highest-revenue opportunity ranking（当下 vs 战略）

| 排名 | 机会 | 当下有需求？ | 战略有趣？ |
|---|---|---|---|
| 1 | 自有数据 A2MCP 服务（$1+/call 价值密集型） | ✅ 平台指定高频道 | ✅ |
| 2 | Evaluator staking 赚 bounty（副业） | ⚠️ 机制未验证是否已 live | ✅ |
| 3 | A2A 高客单交付服务 | ❌ 吞吐未知 | ✅ |
| 4 | 独立验收/验证产品 | ❌ 平台已捆绑 | ⚠️ |
| 5 | 支付/托管/钱包中间件 | ❌ 平台自营 | ❌ |

定价证据：x402 支付分布中 $1+ 从 49% 涨到 95% of value，10c-$1 段从 46% 塌到 4% → **sub-dollar 微支付叙事弱，按价值密集调用定价 $1+**。

## 4. Risks / platform-owned areas

**平台自营面（别建）**：Agentic Wallet（TEE/session keys/20+ chains）、Payment SDK（X Layer 零 gas）、APP 协议全生命周期（quote→negotiate→escrow→meter→settle→dispute）、内置托管合约、staked Evaluator 仲裁网络（GenLayer 提供 dispute 基础设施）、okx-trade-mcp（164 tools / 11 modules 覆盖 OKX 交易全流程）。

**验收/验证不是第三方产品面**（3-0 verified）：用户签收放款 + 3 天 auto-accept + rejection→arbitration 全在平台托管流内；Evaluator 是「可参与的角色」（stake OKB 赚 bounty）不是「可自建的产品层」。

**其他风险**：
- 平台 days-old BETA，所有能力声明是营销拷贝不是运行数据；escrow/disputes 部分 2026-04 时还标 "coming soon"
- 需求侧证据全部来自 x402/Base 代理指标，且约一半是 wash/self-dealing + PING memecoin 投机
- 多轨割裂风险：Google AP2 / Stripe Machine Payments / AWS AgentCore / x402 v2 与 OKX APP 互不兼容 → OKX 独占集成有搁浅资产风险
- Hackathon 奖池仅 14K USDT（最近一季已结束）= 营销曝光非收入；但 X Layer 有 $100M 生态基金
- 大陆合规叠加：卖预测市场衍生数据是否踩 T0520 关闭线（卖数据 ≠ 促成投注，但需 Leo 自行法律判断）

## 5. Recommended wedge（synthesis, medium confidence）

**注册自有数据 A2MCP 服务**：
- 预测市场/Polymarket 衍生信号、跨市场数据 feed、okx-trade-mcp 未覆盖的交易分析
- 理由：(a) A2MCP 是平台指定高频道 (b) 数据/价格 feed 是 OKX 文档自己举的例子 (c) Leo 的 Polymarket 数据护城河与 OKX 一方工具差异化 (d) 卖数据/分析而非促成投注，避开赌博邻近变现（仍需合规复核）
- 副收入：permissionless Evaluator staking 赚 OKB bounty（**hard gate：staking 涉及资金，需 Leo 批准**）
- **不要建**：支付轨、托管、钱包、独立验收/验证产品、与 okx-trade-mcp 重复的 OKX 交易工具

## 6. 7-day execution plan

1. D1-2：注册 ASP（**hard gate：账号/钱包，需 Leo 批准**），读 A2MCP 注册要求
2. D2-4：把 2-3 个已有 Polymarket 数据 endpoint 包成 A2MCP 服务（OKX Payment SDK 集成 = **hard gate**）
3. D4-5：定价 $1+/call，写 listing 文案
4. D5-7：埋点 call counts / revenue，观察平台 BETA 有机需求
- 全程小赌注：不做大建设，先验证平台有没有买方

## 7. Kill criteria

- 上架 3-4 周后 <100 有机付费调用/周 或 <$50/周收入 → kill
- 平台 BETA 指标显示 Task Marketplace 吞吐接近零（纯供给侧）→ kill 或 park
- 预测市场数据销售出现任何大陆合规红旗 → 立即 kill（对齐 T0520 结论）
- OKX APP 轨道被 AP2/Stripe/x402 v2 明显边缘化 → 降级为观察

## Open questions（未决）

1. OKX.AI BETA 实际吞吐（任务量/ASP 收入/A2MCP 调用量）——现在到底有没有买方？
2. Evaluator 具体经济学（最低 OKB stake、单案 bounty、slashing 实操）+ 大陆个人能否注册
3. 预测市场衍生数据变现是否清过 T0520 合规线
4. 多支付轨割裂：押注 OKX 独占是否搁浅资产风险

## Refuted claims（对抗验证杀掉的）

1. "escrow 和支付是平台自营原语、非第三方机会"的**绝对化表述**（1-2）——APP 名义上是开放标准，边界是方向性的不是绝对的
2. "APP 覆盖全周期因此 escrow/disputes 是平台自营"的推论表述（1-2）
3. "APP 已上线且跨 Solana/Ethereum 全周期可用"（0-3）——dispute 等部分未 live

## 信源质量

Primary：okx.ai 官网/tutorial、okx.com learn（OKX.AI + APP）、X Layer hackathon 页、github.com/okx/agent-trade-kit、APP whitepaper、Chainalysis x402 报告。Secondary：TheBlock、CoinDesk、SiliconAngle。注意：AP2/UCP 细节、RentAHuman 类市场、eval 公司（LangSmith/Braintrust/Arize）的 claim 未通过验证进入结论集，报告在这几个邻域偏薄。
