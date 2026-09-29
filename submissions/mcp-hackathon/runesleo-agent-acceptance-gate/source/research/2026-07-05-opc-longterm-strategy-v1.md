# OKX.AI OPC 长期战略 v1（T0521）

- 日期：2026-07-05
- 状态：active strategy · 每两周 review 一次本文件
- 前置研究：million-dollar-opc-strategy-cn.md · 2026-07-03 四份 research · 2026-07-05 OPC 奖励调研（Explore agent）

## 一、事实基础（2026-07-05 调研确认）

1. **"OPC" 不是奖励计划，是平台叙事**：okx.ai 主标语 "The future belongs to OPC: one person, one company, $1M a year"。没有报名表、没有评选、没有奖金池。
2. **两个真实奖励锚点**：
   - Star Xu 个人承诺：第一个在 OKX.AI 做到 $1M 年收入的 OPC，捐 ≥1 BTC 庆祝（社交承诺，非合同）。
   - X Layer「OKX AI Genesis Hackathon」：$100K 总奖池，建 ASP 参赛。
3. **平台现实**：BETA 上线 10 天全平台 GMV 仅 $268；闭测标杆 ASP = CertiK（安全评估）/ CoinAnk（付费行情）/ GenLayer（争议基础设施）。金融数据类是唯一验证过卖得动的类目（World Cup Alpha 51+ 单）。
4. **收入机制**：无评奖发钱，纯交易结算（USDT/USDG，x402 pay-per-call 或 A2A escrow）。链上 reputation 逐笔累积、跨交互持久。

**推论**：冲 OPC = 把真实收入做起来 + 让 OKX 官方在讲 OPC 故事时非提到我们不可。收入和叙事双线，缺一不可。

## 二、定位

```
Leo Labs = OKX.AI 上的 prediction-market & crypto 数据信号 ASP 组合
一个钱包 · 一个 ASP 身份 · N 个数据服务 · 全部薄 wrapper 复用自有数据资产
```

差异化护城河（按可防御性排序）：
1. **PolyData 全量 Polymarket 数据资产**（竞品只有 top-50 列表，我们有持仓变动事件流）
2. **链上 reputation 先发累积**（平台早期，每一笔都在建历史）
3. **多服务组合占位**（需求撞上来时我们已经在货架上）

## 三、目标分层（诚实版）

| 层级 | 目标 | 判定 | 概率自评 |
|---|---|---|---|
| T1 存活 | 首个 listing 过审 + 首笔有机付费调用 | 上架后 2 周内 | 高 |
| T2 组合 | 4 服务上架（W1/F1/S1/F2）+ 收款闭环跑通 | 4 周内 | 高 |
| T3 早期信号 | 全组合 ≥100 有机付费调用/周 | kill line 反向 | 中 |
| T4 Hackathon | Genesis Hackathon 提交 + 分奖 | 按官方 deadline | 中 |
| T5 平台红利 | 平台周 GMV 破 $10K 且我们份额 ≥5% | 平台增长挂钩 | 低-中 |
| T6 OPC 叙事位 | OKX 官方内容引用 Leo Labs 作 OPC 案例 | 任意时点 | 低-中 |
| T7 北极星 | $1M ARR（Star Xu 的 BTC） | — | 极低，方向锚 |

**纪律**：T3 是 4 周 kill line（<100 调用/周且平台无增长 → 降维护模式）。T5-T7 不投前置成本，只在平台数据证明增长后加码。这条线的本质是**低成本期权**，不是 all-in。

## 四、五条工作流（Workstreams）

### WS1 · 产品组合（建设顺序锁定）
1. ✅ W1 World Cup Smart Money Radar — endpoint 已部署，listing 待提交
2. F1 Polymarket Smart Money Radar 全市场版（同代码二次 listing，W1 过审后 48h 内提交）
3. S1 Agent Acceptance Gate（已建成，改定价即上，零成本占位）
4. F2 事件概率×币价背离（白区无竞品）→ F3 Market Pulse
5. 观察项：Evaluator/Arbitrator 角色（质押 ≥100 OKB + 7×24 + slashable，仅当组合有收入后评估）

规则：单服务建设 ≤1 天，超了就砍范围。listing 文案严守审核规则（禁 URL/技术栈/名人名/免责声明）。

### WS2 · 收入闭环（当前最大缺口）
- 现状：endpoint 无 402 挑战 = 实际免费，listing fee "1" 只是展示价
- 路径：`@okxweb3/x402-express` 接 OKX 托管 facilitator → **需要 SA API key（hard gate 待 Leo）**
- 策略选择：首个 listing 可以先免费跑（换调用量和 reputation），但 **2 周内必须闭环收款**，否则调用量再大也是零收入
- 收款地址 = Agentic Wallet X Layer 0x1e1a…16e15（已建）

### WS3 · 数据质量（信任根基）
- P0：demo 数据 → live Polymarket 数据（2026-07-05 已派 agent 实施中）
- 上游失败降级返回 200 + degraded + caveats，绝不 5xx（付费调用失败伤链上评分）
- 中期：PolyData 派生信号预计算 → 定时推送 serving 层，endpoint 只读快照
- 数据诚实红线：拿不到的字段置 null + caveats 说明，不编造（reputation 是长期资产）

### WS4 · 叙事与分发（OPC 故事线）
- **Build in public 主线**：「一个人 + agents 在 OKX.AI 上从 $0 开始做 OPC」——这个过程本身就是 Leo 内容资产（对齐 T310 网站 + X）
- 节奏：里程碑驱动（上架/首单/首周数据/hackathon），不日更凑数
- 每篇先过 asset_decision 路由（网站资产优先，X 分发回链）
- Genesis Hackathon 提交包：用 million-dollar 文档里的 acceptance layer 叙事 + 真实调用数据
- 红线：不夸大（没收入不说收入，没官方合作不暗示）

### WS5 · 合规与风控（既定边界）
- 允许区：卖数据/分析；硬线：不归集/不托管用户资金、不代客交易
- 大陆 operator 灰点：ToS 无明确条款，风险自担推进（Leo 已决策），出现 50125/80001 region block 立即停下评估
- crypto 收入金额阈值：待定（当前量级可忽略，月入 >$500 时回来定）

## 五、节奏与 Review

| 节点 | 动作 |
|---|---|
| 每周一 | 拉调用量/GMV/平台整体数据 → 一条 build-in-public 素材判断 |
| 2026-07-11 | 首次 review（listing 审核结果 + live 数据质量） |
| 上架 +2 周 | 收款闭环必须完成，否则停新增 listing 先补 |
| 上架 +4 周 | kill line 判定（<100 调用/周 → 维护模式） |
| 每 2 周 | 本文件 review：目标层级达成情况 + 平台 GMV 趋势 |

## 六、当前 Hard Gates（待 Leo）

1. ⏳ ASP listing 提交命令（本次已被 classifier 拦，等 Leo 批准 exact command）
2. ⏳ SA API key 申请（WS2 收款闭环前置）
3. ⏳ crypto 收入金额阈值（可延后）
