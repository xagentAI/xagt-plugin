# Next 24h 四项核实结果 + 候选 endpoint 清单

- 日期：2026-07-03
- 数据来源：两个后台研究 agent 实测浏览 okx.ai（zh-hans）+ web 交叉核实；合规对照见 `2026-07-03-compliance-memo-a2mcp-data-service.md`

## ① Hackathon 数据冲突 — 已裁决

- **「Genesis Hackathon $100K」查无此事**：OKX.AI 上线报道（~15 篇）、官方 learn 页、web3.okx.com 均无。`million-dollar-opc-strategy-cn.md` 中该数字视为编造/混淆，基于它的策略段落作废
- 真实事件：Build X Hackathon 14,000 USDT，2026-04-15 已截止
- $100M X Layer 生态基金真实存在（2025-08 公告）但无公开自助申请入口，BD 导向
- ASP 上手路径极轻：`npx skills add okx/onchainos-skills`，Agentic Wallet 仅需邮箱（不需 OKX 交易所账号），收 USDT/USDG

## ② OKX.AI marketplace 实测吞吐（load-bearing 数字）

Task Marketplace 实时计数（2026-07-03，okx.ai/zh-hans/tasks）：
- **总成交额 $268**（上线 10 天累计）· 已发布 9,610 · 待接单 6,268 · 已完成 1,101 → 单任务均值 ~$0.24
- 结论：**供给侧堆积 + PR，真实经济吞吐接近零**。原 kill criteria（<$50/周）在平台层面已经预触发

Agent 供给侧（分类：世界杯🔥/金融/软件服务/生活/艺术创作）：
- 头部全是世界杯营销位：WorldCupCaller 已售140（0.5 USDT）、World Cup Alpha 已售51（1 USDT）
- 金融类非世界杯 ASP 全部个位数销量：CertiK 44、FundingArb 4、Stable Auto Earn 3
- 需求侧任务里有**未被满足的真实金融需求**：「Polymarket 聪明钱信号追踪」「加密市场脉动报告」「BTC/ETH/SOL 市场概况」等挂单无对应 ASP；但也有大量 X 关注互刷（0.01-0.88 USDT）灌水

**关键佐证 Leo 直觉**：平台上卖得动的（世界杯 Alpha=聪明钱跟单 51 单、赔率信号 140 单）恰恰全是「帮人赚钱」类服务——验证「金融/赚钱依据」是正确类目，只是整个市场还太小。

## ③ 候选 endpoint 清单（按观察到的需求排序）

| # | 服务 | 需求证据 | Leo 资产 | 竞争 | 定价 |
|---|---|---|---|---|---|
| 1 | **Polymarket 聪明钱追踪（全市场版）** | Task 端有同名挂单需求；World Cup Alpha（仅世界杯版）51 单 = 品类最好成绩 | profile-address 分析 + PolyData 全量数据 | World Cup Alpha 只做世界杯，无通用版 | 1-2 USDT/call |
| 2 | **事件概率 vs 币价背离信号**（PM 隐含概率 × perp funding/spot） | 白区：官方 tradekit 明说「signal generation depends on external analysis」 | prediction-trader 跨市场基建 | 无 | 1-2 USDT/call |
| 3 | 资金流/异动雷达（加密市场脉动） | Task 端「加密市场脉动报告」挂单 | trader 数据管线 | FundingArb 仅 4 单（品类未证） | 1 USDT/call |
| 4 | 组合风控 readout | 白区但零需求证据 | lb-api/PnL 工具链 | 无 | 观察 |

首发建议：#1 + #2（一个接现成需求、一个占白区），复用 acceptance-gate 的 HTTP/计费/discovery 脚手架。

## ④ 合规 & 资格（两道未清的门）

1. **大陆 ASP 资格未确认**：注册 KYC-light（邮箱即可）但查不到 okx.ai ToS 是否排除 PRC 居民；OKX 2021 已退出大陆。「没查 KYC ≠ 大陆可用」
2. **crypto 收入灰点**：ASP 收 USDT = 持续性 crypto 服务收入，见合规 memo 灰点 1，需 Leo 拍板

## 总裁决（修正后）

- 方向类目正确（金融/帮 agent 赚钱），Leo 直觉被平台销量数据佐证
- 但 **$268 平台总 GMV = 这现在不是收入 lane，是一张便宜期权 + 内容素材**
- 诚实定位：低成本 listing 实验（占位 + build in public 素材 + 学 agent commerce 一手经验），不做收入预期
- **推进前置条件**（都过才动，全是 hard gate）：① Leo 拍板 crypto 收入灰点 ② 确认大陆 ASP 资格 ③ Leo 批准 Agentic Wallet 创建
- **Park 触发器**（不满足条件就挂起，条件到了再看）：平台周 GMV 突破 $10K 或出现独立 ASP 收入实锤报道 → 重新评估
