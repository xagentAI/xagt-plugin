# Phase H · Demo + 提交证据包 · 2026-07-24

对齐路线图：金融副驾驶主线 + 软件工具副线 + 营收/社交证据。  
**尖刀已从 Football Event Analyst 换成 PM Decision Card**（买前闸，可复购 A 档）。

## 0. 扩货架裁决（已定）

几乎见底 → **本周不扩新 SKU**。延后候选见 `research/2026-07-24-expand-shortlist-honest.md`。

## 1. 两条 ≤90s Demo（固定）

### A · 金融副驾驶（主）

旁白要点：Agent 下单前付一笔 → 拿 skip/watch/eligible + paid_checks → eligible≠买点。

```bash
# 生产（可能 402；录屏用付费或新 IP 试用）
curl -sS -X POST https://api.leolabs.me/pm-decision-card \
  -H 'content-type: application/json' \
  -d '{"slug":"REPLACE_LIVE_SLUG","side":"yes","size_usd":25}'

# 高亮字段（录屏圈出）
# action · confidence · buyer_summary_en · paid_checks · value_loop.stale_at · agent_loop
```

备选同赛道：`POST /finance-cockpit`（宏观+体制一屏）。

### B · 软件实用工具（副 · 可切）

```bash
curl -sS -X POST https://api.leolabs.me/publish-readiness \
  -H 'content-type: application/json' \
  -d '{"title":"Leo Labs on OKX.AI","body":"One person shipping paid agent gates.","channel":"x","claims":["x402 pay-per-call","edge fulfillment"]}'

# 或
curl -sS -X POST https://api.leolabs.me/agent-delivery-acceptance-audit \
  -H 'content-type: application/json' \
  -d '{"task":"Ship health endpoint","delivery_summary":"Added GET /health; tests green.","artifacts":["worker/index.mjs"],"validation":["npm test"]}'
```

### 时码稿（85s）

| 时码 | 画面 | 旁白 |
|---|---|---|
| 0–8s | okx.ai → Leo Labs #3977 | I'm one person. This is Leo Labs on OKX.AI. |
| 8–20s | 标签：Decision Card · Publish Gate | Agents need gates before they pay — and before they post. |
| 20–55s | 终端 A decision-card → action + paid_checks | Finance copilot: mechanical trade gate. Skip, watch, or manual-review only. |
| 55–72s | 终端 B publish-readiness 或 audit | Utility: publish/delivery proof before the agent ships. |
| 72–85s | 收尾 · #Okxai | Pay per call. Edge on demand. No always-on laptop. |

## 2. 营收火箭证据（有则带，无则勿吹）

- [ ] 有机 x402 成功调用截图 / 结算记录（**禁止自买**）
- [ ] 架构一句：Cloudflare Worker 边缘按需；无卖家在线、无 LLM key
- [ ] listing 可展示或审核中进度可述

## 3. 社交热议草稿（#Okxai）

见下文「社交帖」；发前确认 listing 状态与是否可放 agent 链接（遵守禁 URL 规则若在平台内）。

## 4. 提交动作清单

- [ ] Demo 片 ≤90s 或 asciinema
- [ ] #Okxai 帖
- [ ] 官方表单（若仍开放）
- [ ] 奖项勾选：金融副驾驶 + 软件实用工具 +（有证据才勾）营收火箭 + 社交热议
- [ ] 冻结新 SKU；只修 A 档 / 文案 / 过审

## 5. 本轮已做工程加深

`pm-decision-card` → schema 0.2：`paid_checks` · `buyer_summary_en` · `value_loop.stale_at`（方便 demo 圈重点）。
