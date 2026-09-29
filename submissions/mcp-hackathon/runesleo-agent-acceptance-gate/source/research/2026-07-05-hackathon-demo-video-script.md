# Genesis Hackathon Demo 视频脚本 v1（≤90s，#Okxai 参赛帖用）

- 定位：faceless 屏录+动效字幕风（对齐 Leo 视频管线），英文配音/字幕（评委国际化），中文版后出
- 叙事线：不讲"我做了个工具"，讲"one person + agents 在 OKX.AI 从 0 开始做 OPC"——把参赛帖本身变成 OPC 叙事的第一集

## 分镜（85s）

| 时码 | 画面 | 旁白/字幕 |
|---|---|---|
| 0-8s | okx.ai 首页标语 "One person, one company, $1M a year" → 切 Leo Labs ASP 卡片（#3977） | I'm one person. This is my agent company on OKX.AI — Leo Labs. |
| 8-20s | 痛点：Polymarket 页面快速滚动 + 钱包地址流 | Prediction markets leak alpha: the most profitable wallets move first. But no agent can see it — until now. |
| 20-45s | **核心 demo**：终端/agent 调用 World Cup Smart Money Radar → 402 → 支付 → 返回真实 JSON（真实钱包缩写、7d PnL、confidence 高亮） | An agent calls my radar, pays 1 USDT on X Layer, and gets live smart-money signals: who's loading up, which side, how profitable they've been. Real data, straight from Polymarket order flow. |
| 45-60s | 第二服务 F1 全市场版调用（{topic:"bitcoin"}）→ 信号返回；闪 ASP 服务列表（多服务组合） | Same engine, any market — World Cup today, Bitcoin tomorrow. One ASP, a growing factory of data services. |
| 60-75s | 链上收款记录 / Agentic Wallet 余额变化（若有真实付费调用就用真图；没有就用 testnet/结构图，**不伪造**） | Every call settles in stablecoins, on-chain, automatically. No invoices. No employees. |
| 75-85s | 收尾卡：Leo Labs · Agent #3977 · #Okxai · "Building the OPC playbook in public" | One person, one company — and the agents do the work. Find Leo Labs on OKX.AI. |

## 素材清单

- [ ] okx.ai 首页 + Leo Labs listing 页录屏（过审后录）
- [ ] 终端调用录屏：402 challenge → 支付 → live JSON（x402 接好后录，asciinema/终端录屏加高亮）
- [ ] Polymarket 页面 B-roll
- [ ] 链上 settle 记录截图（OKLink X Layer tx）
- [ ] 收尾卡设计（design-system 起手）

## 制作注意

- 长 render 走独立 runtime（Codex/Terminal），不在 CC 后台 bash 跑（feedback-video-render-runtime）
- voice_text 改动后 voice-align-captions.py 必须 --force
- 红线：60-75s 段没有真实付费记录就不 claim 收入，画面用协议流程图代替
