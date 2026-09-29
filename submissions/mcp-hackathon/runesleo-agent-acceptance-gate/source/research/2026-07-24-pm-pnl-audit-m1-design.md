# M1 设计稿 · `/pm-pnl-audit`（先不写代码）

- 日期：2026-07-24
- 状态：design only · **黑客松本周不实现**；过审/demo 后进入 M1
- 来源：`polymarket-toolkit`（`pm pnl-check` / fee-inclusive PnL / activity replay）
- 战略位：相对 AlphaCopy「跟聪明钱」——我们卖「**这钱包成绩单经不经得起含费审计**」

---

## 1. 为什么是 A 档

| 问题 | 谁会反复付 |
|---|---|
| 跟单 / 招聘信号源前 | Agent 要验证对方声称的 PnL |
| 研究报告引用钱包表现前 | 需要 fee/rebate/redeem 后的现金口径 |
| 自己的策略日报 | 每日/每周对账 |

`/pm-profile`、`/pm-brier` 已覆盖轻量画像与校准；**本 SKU 是重审计闸**，不要做成又一个 profile。

---

## 2. API 草图

```
POST /pm-pnl-audit
```

### Input

```json
{
  "address": "0x...",          // 或 username → 解析 proxy
  "window": "30d" | "90d" | "all",
  "mode": "quick" | "full",    // quick=LB+hints; full=activity cashflow replay（更贵）
  "include_positions": true
}
```

### Output（目标形状）

```json
{
  "schema_version": "0.1",
  "service_id": "pm_pnl_audit",
  "action": "trust_for_copy" | "verify_manually" | "distrust_claims",
  "layers": {
    "leaderboard_profit": {"value": null, "source": "lb-api", "status": "ok|degraded"},
    "positions_cash_pnl": {"value": null, "source": "data-api/positions"},
    "cashflow_replay": {"value": null, "status": "ok|pagination_incomplete|skipped_quick_mode"}
  },
  "divergence": {
    "lb_vs_replay_usd": null,
    "verdict": "aligned|lb_optimistic|replay_higher|unknown"
  },
  "paid_checks": [],
  "value_loop": {
    "why_pay_again": "Wallet keeps trading; claims and windows go stale.",
    "stale_after_minutes": 1440,
    "paid_value_tier": "A_repeat_audit_loop",
    "fulfillment": "edge_on_demand_no_llm"
  },
  "caveats": [
    "Not investment advice.",
    "Pagination incomplete ⇒ do not treat replay as ground truth."
  ],
  "buyer_summary_en": "...",
  "buyer_summary_zh": "..."
}
```

### Pricing（建议）

| mode | fee | 理由 |
|---|---:|---|
| quick | 0.05–0.1 | 对齐 profile |
| full | 0.2–0.5 | activity 翻页成本与价值 |

---

## 3. 实现约束

1. **只读**：无下单、无签名、无私有 cookie。  
2. **边缘按需**：优先 JS 移植关键层；full replay 若必须 Python，则：  
   - 方案 A：Worker 调自有轻量 replay（推荐长期）  
   - 方案 B：预计算快照（有收入后再做）  
   - **禁止**依赖 Leo 笔记本常驻进程履约  
3. 诚实降级：`pagination_incomplete` / upstream fail → 200 + degraded，不 5xx。  
4. Listing 文案禁：保证收益、跟单必赚、名人钱包。

---

## 4. 与现有 SKU 关系

```
pm-profile     → 轻画像
pm-brier       → 校准
pm-pnl-audit   → 含费现金审计（本设计）
smart-money    → 主题扫描（红海）
decision-card  → 单笔下单前闸
```

Agent 编排示例：`smart-money 候选 → pnl-audit 验证 → decision-card 下单前闸`。

---

## 5. 工作量与杀线

| 阶段 | 估计 | 完成定义 |
|---|---|---|
| M1a quick | 0.5–1 天 | LB + positions + divergence hints + listing |
| M1b full | 1–2 天 | activity replay 可分页 + incomplete 标志 |
| Kill | 上线 2 周 | 若 0 有机调用且 decision-card 也冷 → 降维护，不继续加深 full |

---

## 6. 非目标（明确不做）

- 自动跟单 / 复制交易  
- 「谁是最聪明钱包」排行榜产品化（红海）  
- 需要 LLM 写研报的包装  

---

## 7. 何时开工

**触发**：#3977 过审可公开展示 **或** Leo 明确说「做 pnl-audit」。  
**本周**：只保留本设计稿；工程时间给 demo / 过审 / 社交帖。
