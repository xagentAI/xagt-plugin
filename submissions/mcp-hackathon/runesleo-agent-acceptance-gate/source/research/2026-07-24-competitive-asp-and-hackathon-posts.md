# 竞品与参赛帖整体分析 · Leo Labs #3977 · 2026-07-24

方法：
- 公开 X/GitHub 可检索的 Genesis 参赛物（样本，非全量；X 帖本身常 403）
- `onchainos agent search` 抽样刷新货架（133 个去重 ASP）
- 对照 07-06/07 目录扫描 + 今日 live

**一句话**：市场上**明显更好、且同赛道碾压你**的产品不多；真正碾压销量的是**另一类生意**（廉价数据 API / 病毒生活工具 / 品牌物料）。同赛道里你缺的不是「再多一个场景卡」，而是**过审 + 一条尖刀叙事 + 有机复购**。

---

## 1. Listing 状态（刚才查的）

| 项 | 值 |
|---|---|
| Agent | Leo Labs **#3977** |
| Approval | **Listing under review**（`approvalDisplayStatus=2`） |
| Status | **not listed**（公开展示仍受限） |
| Online | 1（endpoint 侧在线） |
| Services | **26** 条已 create |
| 历史销量信号 | agentInfo `salesCount` 曾见 **1**（极低；勿当营收火箭主证据） |

→ 黑客松硬门槛仍是：**过审上架**。产品厚度够不够评，先过这关。

截止日期口径（官网 Build X）：提交可延至 **2026-07-27 23:59 UTC**（以官方页为准）。

---

## 2. X 上别人的参赛帖在秀什么？

公开可核验的「参赛型」样本（GitHub README 自报 #OKXAI / demo）：

| 项目 | 卖点 | 形态 | 对你意味着什么 |
|---|---|---|---|
| **SentriAgent** (#5103) | “Agent 碰钱前的 trust/risk 层” | token/wallet risk MCP + x402；有 90s X demo 链接 | **叙事极干净**：一句话 + 4 tools。与 CertiK/token-DD 红海重叠；你的 `token-dd`/`audit` 同族，但他们**演示更尖** |
| **Aura Card** | 付 0.5U 生成 vibe 卡片 | 社交玩具 + 完美 x402 演示 | **社交热议向**；产品深度弱，但「付费→立刻有结果」演示极爽。评委友好，不是长期护城河 |
| **ASP LaunchPad** | 帮别人把脚本变成 ASP | meta 工具（脚手架/文案/readiness） | 软件工具赛道叙事；与你的 `publish-readiness`/`budget` 同属「Agent 基建」，但他们卖的是**上架工厂** |
| **EVIDIQ** | Agent 身份/信誉 trust score | PROCEED / DO-NOT-PROCEED | 又一个 trust gate；货架 sold 仍低（样本里 ~4） |

**观察（重要）**：

1. 多数参赛帖赢在 **一条尖刀 + 90s 付费闭环演示**，不是 26 个 SKU 目录。  
2. 很多「很好看」的应用 = **协议演示正确**（402→支付→200），不等于数据护城河。  
3. 你现在的公开描述仍偏「货架目录」（天气/政治/比赛卡…）——对发现有用，对**评委/买家第一印象偏稀释**。  
4. 尚未看到谁公开甩出「明显完整碾压 Leo 的 PM 决策闸全家桶」；更多是 **单点 tip / 聪明钱 / 安全分 / vibe**。

---

## 3. 现有 ASP 市场：谁真的在卖？

### 3.1 销量头部（今日抽样 Top）

| sold≈ | ASP | 本质 |
|---:|---|---|
| 10k+ | PixelBrief | 品牌/视觉物料（艺术） |
| 1.8k | ScoutGate | ASP 匹配/发现 meta |
| 1.6k+ | Onchain Data Explorer / CoinAnk / CoinWM | **原始/聚合数据 API**（极低价走量） |
| 900+ | Quiver / AgentFund | 期权情报 / 市场扫描 |
| 500+ | 这个能吃吗？ / Argus | 生活病毒 / 合约审计 |
| 300+ | Barker Yield | 收益雷达 |
| 179 | **AlphaCopy** | **Polymarket 聪明钱**（你的直接对标红海） |
| 149 | OnChain Arb Scout | 套利扫描 |
| 105 | CertiK | 安全 API（官方级背书） |

### 3.2 和你同族的「闸门 / 副驾驶」

| ASP | 点什么 | sold≈ | 判读 |
|---|---|---:|---|
| AlphaCopy | PM 聪明钱 | 179 | **同赛道 GMV 标杆**；你不要用 smart-money 单品硬刚 |
| Predict-Raven 等 | PM 机会推荐 | ~23 | 喊单/推荐型；合规与长期信任弱于「闸门」 |
| PA Decision Lab | 单市场深度读 | 2 | 决策层存在但未起量 |
| QTrade Guard / PreFlight / SentriAgent | 交易前检查 | 0–4 | **赛道被验证为「像样」但还没人跑出来** → 你的 decision-card 仍有窗口 |
| Keryx Finance Copilot | 名是副驾驶，顶服务却是 price feed | 37 | 名字好 ≠ 决策层；别被 branding 吓到 |
| latch402 | x402 readiness | 26 | 协议工具，非金融 alpha |

**市场结构诚实结论**：

```
卖得动的大头 = 数据水龙头 + 病毒生活/创意
金融里卖得动 = 聪明钱/套利/收益扫描（信号）
「决策闸 / preflight」= 正确方向，但全场都还没做出第二个 AlphaCopy
```

你的组合（decision-card / cockpit / budget / audit / publish）在**产品逻辑上比多数参赛玩具更像可复购 ASP**；在**市场结果上仍远落后于数据水龙头与 AlphaCopy**。

---

## 4. 有没有「明显比我更好」的？

分三层答：

### A. 整体市场（跨品类）——有，而且很多

CoinAnk、PixelBrief、「能吃吗」、官方 Onchain Data —— **销量与分发碾压**。  
这不是「你产品差」，是**品类与获客结构不同**。别用他们的 sold 数衡量金融闸门成败。

### B. 同赛道金融/PM ——部分更好（在单一维度）

| 维度 | 谁更好 | 你怎么应对 |
|---|---|---|
| 聪明钱销量/心智 | **AlphaCopy** | 不主打雷达；主打 **decision-card / cockpit / pnl-audit** |
| 安全背书 | **CertiK** / Argus | token-dd 只做轻闸，不碰审计品牌战 |
| 原始行情覆盖 | CoinAnk / Quiver | 继续「判断层」，不做第二 CoinAnk |
| 演示叙事清晰度 | SentriAgent / Aura | **砍目录感，一条尖刀 90s** |
| PM 事件矩阵深度 | 未见公开同等厚度 | 你的 event-readout/plugins 仍是差异点，但别当主标题 |

### C. 「Agent 工作流钉子」全家桶 —— 未见明显更好

把 **budget → decision-card → delivery-audit → publish-readiness** 串成 Agent 可编排回路，公开货架上仍稀缺。  
这是你该在帖子里讲的，而不是 26 个 endpoint 名。

---

## 5. 对黑客松奖项的启示

| 奖项 | 市场现实 | 你的打法 |
|---|---|---|
| 金融副驾驶 | 名字滥；真决策层未起量 | **Decision Card 一条线**讲透；cockpit 作配菜 |
| 营收火箭 | 头部是数据/病毒；你 sales≈1 | 有有机单就展示架构+收据；**别硬刚 CoinAnk 数字** |
| 软件实用工具 | ScoutGate/API2ASP/latch402 很卷 | audit + publish + budget 够用；演示「Agent 发货前闸」 |
| 社交热议 | Aura 这类玩具更易传播 | 靠 OPC 故事 + 90s 爽感，不靠 SKU 数 |

---

## 6. 战略含义（接到路线图）

1. **不要因为「别人帖子好看」就再扩 C 档 SKU。**  
2. **要输也输在：过审慢、叙事稀释、有机复购未起** —— 这些是 Phase H 该修的。  
3. **真正值得跟的竞品动作**：  
   - AlphaCopy：订阅/高频信号分发（你可用 A 档复购替代，不必抄聪明钱）  
   - Sentri/Aura：一句话 + 付费瞬间出结果  
4. **M1 差异化加深**：`pm-pnl-audit`（含费 PnL 审计）—— AlphaCopy 卖「跟谁」，你卖「这成绩单是不是真的」。

---

## 7. 置信度与缺口

- X 全量 #OKXAI 时间线未能完整抓取（平台 403）→ 参赛帖结论是**样本级**，不是普查。  
- soldCount 是平台字段，**≠ 精确 GMV**，且可能含试单/活动。  
- 07-07 全目录 358 ASP；今日是关键词抽样 133 —— 头部趋势一致即可用。

---

## 8. 给你的直接回答

> 有没有明显比我更好的应用？

- **跨市场**：有（数据 API / 病毒工具），但不在同一评价坐标系。  
- **同赛道聪明钱**：AlphaCopy 明显更会卖。  
- **同赛道「Agent 决策/交付闸」**：**没有看到明显整体更好的**；多数参赛物叙事更尖、产品更薄。  
- **你最大的相对风险**：货架看起来杂、listing 还在审、销量未起 —— 不是「技术被全面吊打」。
