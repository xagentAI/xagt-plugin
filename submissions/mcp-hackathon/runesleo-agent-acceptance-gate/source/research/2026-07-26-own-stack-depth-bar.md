# 对标标准 · 用 Leo 自有能力当深度条 · 2026-07-26

**纠偏**：ASP 质量条不是「货架上别人卖什么」，而是 **你本地仓库 / 开源 / Codex skill 已经做到的深度**。  
做不到对标，就别用薄包装冒充同名能力。

## 1. 挂法（不变）

```text
本地仓 / skill（能力内核）
    ↓ 只抽：只读 · 无钥 · 无下单 · 无 Leo 私账
api.leolabs.me（履约）
    ↓ x402
OKX #3977（店面）
```

一个店，多服务；**内核来自多仓，不每个仓另开 Agent。**

## 2. 对标矩阵（摘要）

| 你已有的深度 | 来源 | ASP 现状 | 差距 |
|---|---|---|---|
| Decision Card v1.6 全字段 | `~/.codex/skills/pm-decision-card` | `/pm-decision-card` 阈值闸 | **薄很多** |
| Football/Tennis 全场矩阵+fixture | pm-manual-trading-lab + skills | category plugin | **薄** |
| Weather ladder/CDF/station | weather-market-lab + pm-weather-ladder | weather readout | **薄** |
| Fee-inclusive PnL audit | polymarket-toolkit pnl skill | 仅 profile/brier | **缺** |
| Smart-money 钱包画像记忆 | prediction-copilot | 近期大额扫描 | **薄** |
| Growth daily universe/CLV | growth-engine | 无 | **缺** |
| Profile / Brier / budget / slop | toolkit / arc / talk | 已有 endpoint | **基本对齐** |

## 3. 优先搬什么（对标自己，不是对标 CoinAnk）

| 序 | 端口 | 从哪搬 | 边缘可行性 |
|---:|---|---|---|
| 1 | Decision Card 公共子集（mode/threshold/alternative/missing_evidence） | pm-decision-card skill | 高 · 调用方可选带 exposure |
| 2 | `/pm-pnl-audit` | toolkit fee-inclusive pnl | 高-中 · 分页+诚实 incomplete |
| 3 | Football/Tennis 矩阵完备性+fixture 硬闸 | local skills + event_market_matrix_monitor | 高 |
| 4 | Weather ladder/station | weather-market-lab | 中高 |
| 5 | Smart-money wallet quality | prediction-copilot profiler | 中 · 需持久化以后再做 |
| 6 | Daily universe gate | growth-engine | 中 · Cron 后置 |

## 4. 纪律

- **名字对齐能力**：叫 Decision Card / Match Card / Weather Card，就必须逼近对应 skill 的验收条，否则改名或标注 `lite`。  
- **不搬**：Leo 私有 bankroll SSOT、自动下单、需登录 cookie 的链路。  
- **可搬**：确定性规则、公开 API、调用方自带 exposure/fixture 证据。

## 5. 本轮开工

先搬 **Decision Card 公共子集** + 启动 **PnL audit**；其余按序。

## 6. Shipped this round · 2026-07-26

- `/pm-decision-card` schema bumped to `0.3` and now exposes the buyer-safe public subset from Leo's local Decision Card bar: `opportunity_state`, `decision_mode`, price/fair/max-entry fields, `price_status`, fee-buffer edge when caller supplies `fair_prob`, public threshold metadata, expression alternative comparison, `missing_evidence`, `consistency_check`, and explicit `no_orders` hard gate.
- The endpoint uses existing public preflight + event-readout/category plugin output only. Optional caller inputs now include `existing_exposure_usd`, `decision_mode`, and `fair_prob`; Leo private bankroll SSOT, orders, signing, custody, and private fills remain excluded.
- Added `/pm-pnl-audit` quick mode: resolves address/username, compares LB all-time profit vs positions `cashPnl`, returns activity first-page hints, divergence verdict (`aligned | lb_optimistic | replay_higher | unknown`), action (`trust_for_copy | verify_manually | distrust_claims`), and A-tier audit value loop. Full cashflow replay is intentionally stubbed until the polymarket-pnl pagination/cashflow engine is ported or separately authorized.
- Worker/catalog wired at fee `0.1`; no onchain OKX create/listing performed in this round.
- Validation/deploy: `node --test test/wave-b-services-test.mjs` passed; deployed Worker version `23a27c5a-0d4d-4939-8ddd-4c134e97736a`.
