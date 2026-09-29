# Genesis Hackathon Demo 视频脚本 v2（≤90s，#Okxai）

- 日期：2026-07-07 · 替代 v1（v1 以 smart-money radar 为主，冲奖弱）
- 定位：faceless 屏录 + 动效字幕 · **英文旁白/字幕**（评委）· 中文版后出
- 叙事：**Agent 工厂三角栈** — Trust → Research → PM Preflight（不是又一个聪明钱雷达）

## 主角线（85s）

| 时码 | 画面 | 旁白/字幕 |
|------|------|-----------|
| 0–8s | okx.ai「One person, one company」→ Leo Labs #3977 卡片（过审后录真 listing） | I'm one person. This is Leo Labs — my agent company on OKX.AI. |
| 8–18s | 三个标签闪过：Audit Gate · Token DD · PM Preflight | Agents don't just need signals. They need gates before they ship, research, or trade. |
| 18–32s | 终端 ① `POST /agent-delivery-acceptance-audit` → `pass` / `needs_review` 高亮 | First: an agent hires my Audit Gate — did the worker actually deliver evidence? |
| 32–48s | 终端 ② `POST /token-dd-verdict` → `verdict_bucket` + pillars 高亮 | Second: Token DD Verdict — quick research gate, not another chatbot report. |
| 48–65s | 终端 ③ `POST /pm-trade-preflight` → `action: watch` + `risk_flags` 高亮 | Third: PM Trade Preflight — trade, watch, or skip before a prediction-market order. |
| 65–75s | 服务列表 6+ SKU 快闪 · 免费试用 → 402 流程图（**无真 tx 不 claim 收入**） | One ASP, many services. Try free, then pay per call on X Layer. |
| 75–85s | 收尾卡：Leo Labs · #3977 · #Okxai · Building the OPC playbook in public | One person, one company — agents do the work. |

## 录屏命令（生产环境）

```bash
# 1 Audit（compact input）
curl -sS -X POST https://api.leolabs.me/agent-delivery-acceptance-audit \
  -H 'content-type: application/json' \
  -d '{"task":"Ship health endpoint","delivery_summary":"Added GET /health; npm test passes.","artifacts":["worker/index.mjs"],"validation":["npm test"]}'

# 2 Token DD Verdict
curl -sS -X POST https://api.leolabs.me/token-dd-verdict \
  -H 'content-type: application/json' \
  -d '{"asset":"ETH"}'

# 3 PM Trade Preflight
curl -sS -X POST https://api.leolabs.me/pm-trade-preflight \
  -H 'content-type: application/json' \
  -d '{"slug":"will-egypt-win-the-2026-fifa-world-cup","side":"yes","size_usd":100}'

# 4 Event Readout
curl -sS -X POST https://api.leolabs.me/pm-event-readout \
  -H 'content-type: application/json' \
  -d '{"slug":"will-egypt-win-the-2026-fifa-world-cup"}'
```

自调用批跑：`bash scripts/okx-asp-self-call.sh`

## 素材清单

- [ ] okx.ai Leo Labs listing（**审核通过后**）
- [ ] 上述三条 curl 终端录屏（asciinema 或 Terminal 高亮）
- [ ] GET sample 三连（可选 B-roll）
- [ ] 402 协议流程图（无真实付费 tx 时用）
- [ ] 收尾卡

## 红线

- 不 claim 收入/销量，除非有真实链上 settle 截图
- 不暗示 OKX 官方背书
- 聪明钱 radar 仅作 SKU 列表一闪，**不作主 demo**

## 赛道对应

- Software Utility → Audit Gate
- Finance Copilot → Verdict + Preflight
- Best Product → 三服务互调 + 工厂叙事
- Social Buzz → 本帖 + #Okxai
