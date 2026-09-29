# 预备包：hackathon 表单预填 + S1/F2 listing 草稿（T0521）

- 日期：2026-07-05 · 全部为"过审即用"的预备材料

## A. Hackathon 表单预填（W1 过审后 5 分钟内可提交）

| 字段 | 值 |
|---|---|
| ASP Name | `Leo Labs` |
| Agent ID | `3977` |
| ASP Description | Core capability: provides prediction-market smart money tracking and crypto market data signals for agent research workflows. Each service accepts simple JSON inputs such as a market keyword and a result limit, and returns compact data-only signals. |
| X Account Handle | `@runes_leo` |
| X Participation Post (Link) | ⏳ 发帖后填（帖含 ≤90s demo 视频 + #Okxai） |
| Telegram Handle | `runesleo` |

表单：https://docs.google.com/forms/d/e/1FAIpQLSfIAgP_WmMGtZ5qyW_LnKZonsjyfOYwV3bduRwiuN4oBmcqjQ/viewform

## B. F1 listing 草稿（W1 过审后 48h 内提交，两行结构已按踩坑手册）

- serviceName: `Polymarket Smart Money Radar`（27 字符 ✓ 与 agent 名不同 ✓）
- serviceDescription（两行 \n 分隔）:
  - L1: `Tracks profitable Polymarket wallets across all markets and reports position changes, sides, notional size, and a confidence score for each signal.`
  - L2: `Provide market or topic as a keyword such as bitcoin or a market name, or all, plus limit from 1 to 10; returns compact data-only smart money signals.`
- serviceType: `A2MCP` · fee: `1` · endpoint: `https://api.leolabs.me/polymarket-smart-money-radar`（✅ 已部署 live）

## C. S1 listing 草稿（Agent Delivery Acceptance Audit，软件实用工具赛道占位）

- 前置：worker 需加 POST /agent-delivery-acceptance-audit 路由（复用 src 现有 audit 逻辑，x402 agent 完工后加，≤半天）
- serviceName: `Agent Delivery Acceptance Audit`（31 字符 ⚠️ 超 30，用 `Agent Delivery Audit Gate`（25）✓）
- serviceDescription:
  - L1: `Audits an agent task delivery against its task goal, artifacts, and validation evidence, and returns pass, needs review, or fail with missing items.`
  - L2: `Provide task, delivery summary, artifacts, and validation as JSON text fields; returns a compact audit verdict with risks and buyer summary.`
- serviceType: `A2MCP` · fee: `1` · endpoint: `/agent-delivery-acceptance-audit`（待路由上线）

## D. F2 排期（x402 完工后开建，≤1 天）

- 事件概率×币价背离：PM 隐含概率变动 vs perp funding/spot 动量（数据源：Gamma + OKX 公开行情 API），白区无竞品
- serviceName 候选: `Event Probability Divergence Radar`（34 超）→ `Event Price Divergence Radar`（28 ✓）

## E. 参赛帖（发布时走 leo-style skill 出稿，要点先钉住）

- 主角 W1 + 工厂故事线；英文；#Okxai；≤90s demo 视频
- 钩子方向：`I'm one person. My agent company just opened on OKX.AI.`（对齐 Star Xu OPC 叙事 + 蓝海参赛帖）
- 红线：无真实收入前不 claim 收入；不暗示 OKX 官方背书
