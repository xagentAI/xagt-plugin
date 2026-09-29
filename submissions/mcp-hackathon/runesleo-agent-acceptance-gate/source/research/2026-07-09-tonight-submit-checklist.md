# 今晚 Agent #3977 再提审核清单 · 2026-07-09

给 Leo 的本地 readiness 清单。默认 **不上链**；授权后按大包一次做完。

权威 runbook：`research/2026-07-09-okx-resubmit-big-pack.md`  
命令打印稿：`bash research/2026-07-09-okx-big-pack-commands.sh`（默认 print-only）

当前状态：**已提交 · Listing under review**（2026-07-09 晚大包完成；回执 `_inventory/2026-07-09-listing-bigpack/RECEIPT.md`）

---

## 已就绪

- [x] 链上实况：`approvalStatus=6`（已拒，头像）；4 服务 id **29496–29499** 仍在
- [x] 定稿头像本地文件：`~/Projects/content/brand/leo-labs-avatar-1024.jpg`（1024×1024，直角、非白底）
- [x] **无字母候选**（推荐优先试）：`~/Projects/content/brand/okx-avatar-1024-signal-only-candidate.jpg`（仅橙信号弧 + 深底，无 L）
- [x] 双语 Agent 简介 + 4 已有服务文案（catalog `OKX_LISTING_COPY` + listing md）
- [x] 6 个待 create 文案（`PENDING_OKX_LISTING_COPY`）；PM Event Readout 已升为 Football-ready（同场矩阵 / fixture / 足球/网球品类深度；不下单）
- [x] `/polymarket-smart-money-radar` catalog `mode: 'live'`（对外无 beta）
- [x] 禁词：catalog + listing md 对 beta / test / -dev = **0 hit**
- [x] `onchainos agent validate-listing`（Agent 简介 + 4 update + 6 create）→ **`pass: true`**
- [x] 大包执行顺序与 print 脚本已写好
- [x] 10 个 endpoint Worker 已部署；GET sample 可用（本机部分路径曾 403/需 UA，workers.dev `/health` OK）

### 已有 4 服务（update 用）

| id | Name | Fee | Path |
|----|------|-----|------|
| 29496 | World Cup Smart Money Radar | 0.1 | `/world-cup-smart-money-radar` |
| 29497 | Polymarket Smart Money Radar | 0.05 | `/polymarket-smart-money-radar` |
| 29498 | Agent Delivery Audit Gate | 0.2 | `/agent-delivery-acceptance-audit` |
| 29499 | Event Price Divergence Radar | 0.1 | `/event-price-divergence-radar` |

### 待 create 6 个

| Name | Fee | Path |
|------|-----|------|
| Crypto Market Regime Radar | 0.1 | `/crypto-market-regime-radar` |
| World Cup Upset Alert | 0.1 | `/world-cup-upset-alert` |
| Token DD Verdict | 0.05 | `/token-dd-verdict` |
| PM Trade Preflight | 0.1 | `/pm-trade-preflight` |
| PM Event Readout | 0.1 | `/pm-event-readout` |
| Content Verify Claims | 0.1 | `/content-verify-claims` |

### 大包执行顺序（授权后）

按 `research/2026-07-09-okx-big-pack-commands.sh` 打印稿：

1. 预检：头像文件 + 禁词扫描（catalog **+** listing md）+ 可选 10×402  
2. `onchainos agent upload` 定稿头像 → 记下 `PICTURE_URL`  
3. `service-list --agent-id 3977` 刷新 id  
4. **一次** `update`：picture + Agent 双语 + 4 服务双语（29496–29499）  
5. 逐条 `validate-listing` → `create` ×6  
6. **一次** `activate`  
7. 冻结；盯邮件 / watcher  

---

## 已执行（Leo「按你的建议来」）

- [x] 头像 B 上传（signal-only）
- [x] 一次 update：picture + 双语 Agent + 4 update + 6 create
- [x] 一次 activate → **Listing under review**（AI 质检建议通过）
- [x] 服务现为 **30207–30216**（共 10）

---

## 明确不做（今晚 / 明天再看）

- **视频推文 / 黑客松 demo 视频** → **明天**  
- 发推、内容展示、黑客松报名宣传  
- Batch 2 PM Category Analyst 上架  
- commit / push（除非 Leo 另开 gate）  

