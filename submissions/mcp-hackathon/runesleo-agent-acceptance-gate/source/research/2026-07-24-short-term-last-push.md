# 短期最后一搏 · 物料包 · 2026-07-24

目标：把**现在还能做的**做完，让你只剩「录 / 发 / 交表」；用付费标准约束，不自证方向。

## 0. 此刻实况

| 项 | 状态 |
|---|---|
| #3977 | **Listing under review** / not listed |
| api.leolabs.me `/health` | 200 |
| decision-card / finance-cockpit / publish-readiness GET | 200 |
| 审核中 update | **不做**（纪律：不零碎搅审） |
| 新 SKU / pnl-audit 代码 | **不做** |

过审后立刻：用下方「尖刀简介」`update` + 必要时 `activate`（另候你一句「改简介/上」）。

---

## 1. 尖刀简介（过审后 update 用 · 已定稿）

**不要**再列 26 个场景名。强调可付费价值 + 非喊单。

```
Pay-per-call data gates for agents: live PM/crypto signals that go stale, pre-trade decision cards, and delivery/publish checks. JSON in, structured verdict out — not a chatbot, not trade tips.
给 Agent 的按次付费数据闸：会过期的预测市场/加密信号、下单前决策卡、交付与发布检查。JSON 进、结构化结论出；非聊天、非喊单。
```

字符短、双语、无 URL。  
落盘：`research/2026-07-24-tip-knife-agent-description.txt`

---

## 2. 录屏单页（≤90s · 默认主画面 B 偏「已有人付」逻辑）

市场已证明更有人付的是**信号**；闸门未证明。  
**默认主 demo = Finance Cockpit**（信号合成，金融副驾驶叙事仍在）；决策卡作 15s 彩蛋。  
你若更信闸门，把 A/B 对调即可。

### 时码

| 时码 | 画面 | 旁白 |
|---|---|---|
| 0–8s | okx.ai → Leo Labs #3977 | One person. Leo Labs on OKX.AI. |
| 8–18s | 标签：live signals · pay per call | Agents pay for data that goes stale — not chat. |
| 18–55s | 终端 `POST /finance-cockpit` → regime + divergence 高亮 | Finance copilot: regime score + event-price divergence in one call. |
| 55–72s | 闪一下 `pm-decision-card` 的 action / paid_checks | Optional gate: skip / watch / manual-review before an order. |
| 72–85s | 收尾 #OKXAI | Edge on demand. No always-on laptop. |

### 录屏命令

```bash
# 主 · Finance Cockpit（生产可能 402；付费或新 IP 试用）
curl -sS -X POST https://api.leolabs.me/finance-cockpit \
  -H 'content-type: application/json' \
  -d '{"focus":"bitcoin","limit":5}'

# 彩蛋 · Decision Card
curl -sS -X POST https://api.leolabs.me/pm-decision-card \
  -H 'content-type: application/json' \
  -d '{"slug":"REPLACE_LIVE_SLUG","side":"yes","size_usd":25}'

# 软件工具赛道备用（可替换彩蛋）
curl -sS -X POST https://api.leolabs.me/publish-readiness \
  -H 'content-type: application/json' \
  -d '{"title":"Leo Labs","body":"Pay-per-call agent gates on OKX.AI.","channel":"x"}'
```

高亮：`regime` / `divergence` / `action` / `paid_checks` / `value_loop.stale_at`  
红线：无有机结算截图 → 不说 GMV；不暗示官方背书。

---

## 3. #OKXAI 帖（可直接发）

I'm one person building Leo Labs on OKX.AI (#3977).

Agents pay per call for **data that goes stale**:
• Finance cockpit — regime + event/price divergence  
• Decision card — skip / watch / manual-review (not a buy tip)  
• Publish & delivery checks when agents ship  

Edge on demand. JSON in, verdict out.

#OKXAI #Okxai

（中文附句可选，见 `research/2026-07-24-okxai-social-draft.md`）

---

## 4. 你只剩这 4 步

1. [ ] 按 §2 录 ≤90s（或 asciinema + 口述）  
2. [ ] 发 X 帖（§3），带 demo  
3. [ ] 交官方表单（ASP + X 链接）；奖项勾：金融副驾驶 + 软件工具 + 社交；**营收火箭仅当有有机单证据**  
4. [ ] 过审邮件到了 → 回我「改简介」或「上」→ 我推尖刀 description + activate  

---

## 5. 我这边已做完的

- 暂时结论 + 杀线已记录  
- 尖刀简介 + 本物料包  
- endpoint 健康复查 OK  
- **未**在审核中 update（避免搅审）  
- **未**扩 SKU  

再努力一把 = **物料闭环 + 你完成录发交**；商业是否成立留给有机付费裁判。
