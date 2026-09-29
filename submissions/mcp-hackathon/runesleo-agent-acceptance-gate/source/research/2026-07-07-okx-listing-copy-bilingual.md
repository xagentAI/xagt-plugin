# OKX Listing 文案（双语规范 · 2026-07-07）

SSOT 代码：`worker/service-catalog.mjs` → `OKX_LISTING_COPY` + `PENDING_OKX_LISTING_COPY`

## 产品原则（Leo 2026-07-08）

- **主用户**：人 + 调用 ASP 的 AI Agent；listing 页必须 **L1 英文 + L2 中文**（同字段两行），不能只英文。
- **截图**：只用 **okx.ai 真页自截**；禁止 CLI/HTML 拼的假预览当配图。
- **定价展示**：旧截图因价高废弃；Wave 1 链上价为 0.05–0.2 USDT/次 + 每 IP 每服务 1 次免费试用。过审后重截。
- **更新时机**：**审核中不零碎 update**。默认等本轮结果；若再拒 / Leo 说「listing」→ 按 `research/2026-07-09-okx-resubmit-big-pack.md` **一次打包**（sharp 头像 + 双语 + 现有 4 服务 + 6 个 unlisted create）。若本轮直接 listed → 24h 内刷双语（若仍纯英文）+ 真页截图，新 SKU 同日一批 create。

## 规范

| 字段 | 语言 | 限制 |
|------|------|------|
| `name` | 英文 `Leo Labs` | 品牌名 |
| `description` L1 | 英文：ASP 能力总述 | 无 URL |
| `description` L2 | **中文总述** + 谁该用 | 同上 |
| `serviceName` | **英文**，≤30 字符 | 与 ASP 名 `Leo Labs` 区分 |
| `serviceDescription` L1 | 英文：干什么 + 输出什么 | 无 URL、无技术栈堆砌 |
| `serviceDescription` L2 | **中文一句** + 输入提示 | 同上 |
| API path / `service_id` / JSON | 英文 | 不改 |

## Agent #3977 简介（2026-07-24 尖刀版 · 过审后 update）

审核中不零碎 update。定稿文件：`research/2026-07-24-tip-knife-agent-description.txt`

```
L1: Pay-per-call data gates for agents: live PM/crypto signals that go stale, pre-trade decision cards, and delivery/publish checks. JSON in, structured verdict out — not a chatbot, not trade tips.
L2: 给 Agent 的按次付费数据闸：会过期的预测市场/加密信号、下单前决策卡、交付与发布检查。JSON 进、结构化结论出；非聊天、非喊单。
```

旧版（目录感，勿再作为主简介）：
```
L1: Data-only gates for agents and solo builders: prediction-market signals, delivery audits, token DD, and trade preflight. JSON in, structured verdict out — not chatbots or trade tips.
L2: 给 Agent 和独立开发者的数据闸门：预测市场信号、交付验收、代币尽调、下单前检查。JSON 进、结构化结论出；不是聊天机器人，也不是喊单。
```

链上 service id（update 用）：以 `onchainos agent service-list --agent-id 3977` 为准（2026-07-24：**30207+ / 36661+**，共 26 服务）。

---

## 已上架（approvalStatus=6 已拒 · 可再提大包时 `onchainos update`）

| ID | serviceName | 价 (USDT) | endpoint |
|----|-------------|-----------|----------|
| 29496 | World Cup Smart Money Radar | 0.1 | `/world-cup-smart-money-radar` |
| 29497 | Polymarket Smart Money Radar | 0.05 | `/polymarket-smart-money-radar` |
| 29498 | Agent Delivery Audit Gate | 0.2 | `/agent-delivery-acceptance-audit` |
| 29499 | Event Price Divergence Radar | 0.1 | `/event-price-divergence-radar` |

### 29496 World Cup Smart Money Radar

```
L1: Heuristic World Cup prediction-market wallet signals from large public trades and 7-day leaderboard stats; data only.
L2: 世界杯预测市场聪明钱雷达：大额成交与7日盈利钱包信号。输入 market 关键词（如 winner、队名或 all）+ limit 1-10。
```

### 29497 Polymarket Smart Money Radar

```
L1: Heuristic Polymarket wallet signals from recent large trades; topic search with limited coverage per call.
L2: Polymarket 全市场聪明钱雷达。输入 market/topic 关键词（如 bitcoin 或 all）+ limit 1-10；数据信号，非投资建议。
```

### 29498 Agent Delivery Audit Gate

```
L1: Rule-based audit of agent task delivery vs goals and evidence; returns pass, needs review, or fail.
L2: Agent 交付验收闸门：对照任务目标与证据，输出 pass/需复核/fail。输入 task、delivery_summary、artifacts、validation。
```

### 29499 Event Price Divergence Radar

```
L1: Flags where 24h prediction-market probability moves diverge from 24h OKX spot momentum on major crypto assets.
L2: 事件概率与币价背离雷达：PM 24h 概率变动 vs OKX 现货 24h 动量。输入 asset（bitcoin/ethereum/solana 或省略查主流）。
```

---

## 待 create（listed 后 `onchainos create`）

| service_id | serviceName | 价 | endpoint |
|------------|-------------|-----|----------|
| crypto_market_regime_radar | Crypto Market Regime Radar | 0.1 | `/crypto-market-regime-radar` |
| world_cup_upset_alert | World Cup Upset Alert | 0.1 | `/world-cup-upset-alert` |
| token_dd_verdict | Token DD Verdict | 0.05 | `/token-dd-verdict` |
| pm_trade_preflight | PM Trade Preflight | 0.1 | `/pm-trade-preflight` |
| pm_event_readout | PM Event Readout | 0.1 | `/pm-event-readout` |
| content_verify_claims | Content Verify Claims | 0.1 | `/content-verify-claims` |

### Crypto Market Regime Radar

```
L1: Blends OKX spot momentum, perp funding/premium and Polymarket drift into risk_on/off/neutral/mixed with explainable score.
L2: 加密市场状态雷达：现货动量+资金费率+PM 情绪 → risk_on/off/neutral 及 0-100 分。输入 focus/asset 关键词 + limit。
```

### World Cup Upset Alert

```
L1: Flags profitable wallets entering low-probability World Cup outcomes; potential upset positioning signals only.
L2: 世界杯冷门预警：盈利钱包涌入低概率赛果。输入 market 关键词（winner/队名/all）+ limit 1-10；数据信号，非投注建议。
```

### Token DD Verdict

```
L1: Quick rule-based token research gate; optional DEX liquidity scan for EVM contracts; returns avoid/watch/research buckets.
L2: 代币快速尽调闸门：规则引擎输出 avoid/观望/可研究等分桶；EVM 合约可查 DEX 流动性。输入 asset（ticker 或合约地址）。
```

### PM Trade Preflight

```
L1: Read-only eligible/watch/skip gate before a Polymarket order; checks liquidity, price zone, and spread. eligible ≠ buy tip.
L2: 预测市场下单前检查：eligible/观望/跳过，只读不下单。eligible 表示机械检查通过，不是买入建议。输入 market_url 或 slug + side(yes/no)，可选 size_usd。
```

### PM Event Readout

```
L1: Football-ready event evidence card: same-event market matrix, fixture-aware tradability, and football/tennis category depth when available. Not a buy tip.
L2: 预测市场事件解读卡（Football-ready）：同场矩阵、赛程/fixture 可交易性，足球/网球品类深度可选。输入 market_url 或 slug；不下单。
```

### Content Verify Claims

```
L1: Rule-based check that publish claims overlap caller-supplied source excerpts; pass, needs_review, or fail.
L2: 发布前断言核查：对照你提供的原文摘录核对数字/关键词。输入 claims[] + sources[].text；不抓网页。
```

---

## 对外中文对照（X / 参赛帖用，非 listing 字段）

| 英文 SKU | 中文人话 |
|----------|----------|
| Agent Delivery Audit Gate | Agent 交付验收闸门 |
| Event Price Divergence Radar | 事件概率×币价背离雷达 |
| PM Trade Preflight | 预测市场下单前检查 |
| PM Event Readout | 预测市场事件解读卡 |
| Content Verify Claims | 发布前断言核查 |
| Token DD Verdict | 代币快速尽调闸门 |
| Crypto Market Regime Radar | 加密市场状态雷达 |
| World Cup Smart Money Radar | 世界杯聪明钱雷达 |
| Polymarket Smart Money Radar | Polymarket 聪明钱雷达 |
| World Cup Upset Alert | 世界杯冷门预警 |

---

## 下一步

1. **今晚再提大包**（approvalStatus=6）：对 **29496–29499** 一次 update 刷双语 + 定稿头像；见 `research/2026-07-09-tonight-submit-checklist.md`
2. **同批 create 6 个 unlisted**：`validate-listing` → `create` ×6 → **一次** `activate`（命令稿：`research/2026-07-09-okx-big-pack-commands.sh`）
3. **参赛帖 / 视频**：明天黑客松视频推文；今晚不做
