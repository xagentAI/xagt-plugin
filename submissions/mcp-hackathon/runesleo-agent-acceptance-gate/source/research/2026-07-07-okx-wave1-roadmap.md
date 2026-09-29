# Leo Labs OKX 路线图（2026-07-07）

状态：**Wave 1 审核中 · ASP 工厂 active · Hackathon 并行**  
**主 Backlog SSOT**：`research/2026-07-07-asp-factory-backlog.md`

---

## Wave 1 — 优化 → 审核 → 发推 ✅ 代码完成

| 步骤 | 动作 | 状态 |
|------|------|------|
| 1 | Worker：分服务定价 + 每 IP 每服务 1 次免费试用 + GET sample | ✅ |
| 2 | Cloudflare deploy + KV `TRIAL_KV` | ✅ 2026-07-07 |
| 3 | onchainos：4 服务改价 + listing 文案 + activate | ✅ 审核中 |
| 4 | 等 OKX 审核（头像 + 服务更新） | 待 |
| 5 | Leo 截图 listing → 发 v18 Quote 推 | 待审核通过 |

### 定价（链上 listing + x402）

| 服务 | 新价 (USDT) |
|------|-------------|
| Agent Delivery Audit Gate | 0.2 |
| Event Price Divergence Radar | 0.1 |
| World Cup Smart Money Radar | 0.1 |
| Polymarket Smart Money Radar | 0.05 |

计费：每 IP 每 path 首次 POST 免费 → 之后 x402；GET = public sample。

---

## Wave A — 零开发上架（见 backlog § Wave A）

- 过审后：**Regime Radar** + **Upset Alert** listing
- **Hackathon**：参赛帖 + demo v2 + 填表（截止 7/17 08:00 北京）

---

## Wave B — 轻包装 SKU（审核期并行开发）

优先级：**B1 Token DD Verdict** → **B2 PM Trade Preflight** → B4 → B3 → B5  
规格：`asp-factory-backlog.md` § Wave B 规格摘要

---

## Wave C — 数据线（Wave B 后）

PM Profile API · Elite Pool Lookup · Publish Readiness Gate · Visual Spec API

---

## Phase 2 — 需求挖矿

素材库与每周节奏见 `asp-factory-backlog.md` § Phase 2。

---

## 本阶段不做

- 不整包卖 leo-style / 账号发布类 skill
- Revenue Rocket 不押宝（有 tx 即可）
- 不堆第 N 个 smart-money radar SKU
