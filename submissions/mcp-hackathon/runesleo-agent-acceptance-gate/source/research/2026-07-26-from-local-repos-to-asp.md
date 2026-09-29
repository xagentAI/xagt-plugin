# 从本地仓出发 · Agent 服务化清单 · 2026-07-26

Leo 纠偏：**别拍脑袋造 SKU。从「本人在用」或「开源已被 star/fork 验证」的仓出发；服务化是第二步。**

---

## 0. 原则

```
本地仓 / skill（已验证）
    → 抽出：只读 · 无钥 · 无下单 · 无 Leo 私账
    → api.leolabs.me（履约）
    → OKX #3977（插座 / 激励）
```

| 过关 | 不过关 |
|---|---|
| 开源有 star/fork，或你每天自己用 | AI 起名的「副驾驶/雷达」拼盘 |
| 有清晰买家场景（验真、矩阵、闸） | 「谁都可以用 AI 下午仿一个」 |
| 能边缘化、无会话无私钥 | 本地 session / Remotion / 跟单执行 |

---

## 1. 需求已验证的本地资产（优先看这些）

### A. 开源 · 市场已投票

| 仓 | 证据 | 是什么 | 适不适合当 ASP |
|---|---|---|---|
| **`polymarket-toolkit`** | **175★ / 24 fork**；npm MCP 有下载 | 地址画像 / Brier / **含费 PnL 回流** / MCP 只读工具 | **最适合** · 已有 profile/brier/pnl-audit，继续搬 toolkit 缺口 |
| **`x-reader`** | **954★ / 90 fork** | 多平台 URL→内容 MCP | 需求真，但 **Worker 难跑**（yt-dlp/本地）；别当 #3977 尖刀 |
| **`claude-code-workflow`** | **705★ / 86 fork** | Claude Code 工作流模板 | **不是 API 服务**；养 GitHub，不上货架 |
| **`claude-video-kit`** | **108★ / 26 fork** | brief→Remotion 视频 | 需求真，**渲染太重**；非 x402 边缘 SKU |
| **`tg-reader-mcp`** | **35★ / 5 fork** | TG 只读 MCP | 要用户 Telethon session，**共享 Worker 不适合** |

### B. 私有 · 本人在用（深度条）

| 仓 / skill | 证据 | 是什么 | 服务化要点 |
|---|---|---|---|
| **`pm-manual-trading-lab` + `~/.codex/skills/pm-*`** | 你手动盘日常 | 决策卡、同场矩阵、天气阶梯、硬闸文化 | **公共子集**上架；私账/下单永不搬 |
| **`polymarket-data`** | 长跑数据飞轮 | 精确 PnL / 钱包报告脚本 | 只抽合约/算法，不搬整库 VPS |
| **`weather-market-lab`** | 天气盘研究 | station/ladder/CDF | 不爬站；硬否决诚实 |
| **`prediction-copilot`** | 产品线/内测 | 聪明钱 + 研究 UI | 全站难；只抽 profiler 切片 |
| **`prediction-trader`** | 执行栈 | 含 overround 等纯函数 | **只抽只读工具**；不下单路径 |
| **`agent-acceptance-gate`** | 店面本身 | x402 + 27 SKU | **加深内核，别另开店** |

### C. 明确不要往 OKX 上放

`prediction-farmer`（刷量）· 交易执行仓签名路径 · Leo 私账 SSOT · `network-doctor`/`wechat-reader`（本机会话）· C 端玩具（证件照/拼豆）· 别人的爆款 prompt 仓。

---

## 2. 服务化优先级（从仓 → 插座）

### P0 · 已有仓、继续做深（别再发明名字）

| 本地来源 | 对外中文名（建议） | 现状 | 下一刀 |
|---|---|---|---|
| toolkit `polymarket-pnl` | **晒单流水验真** | `/pm-pnl-audit` 已有 | Worker 内 full 更稳；sample 期望；username 边界 |
| skill `pm-decision-card` | **下单前决策卡** | `/pm-decision-card` 偏薄 | 继续对齐 v1.6 公共字段，达不到别吹满名 |
| skill `pm-football/tennis` | **同场盘口矩阵** | match card 有硬闸 | 对齐本地矩阵验收条；名=能力 |
| toolkit profile/brier | **地址快照 / 校准分** | 已挂 | 维护即可 |

### P1 · 仓里有、货架还缺（真正「从本地搬」）

| 本地来源 | 候选服务 | 难度 | 备注 |
|---|---|---|---|
| toolkit `pm scan` | **市场扫描** | — | **已上 Worker** `/pm-market-scan`（okx_service_id 待 create） |
| toolkit / trader 只读 | **盘口健康（spread/深度/overround）** | — | **已上 Worker** `/pm-market-health`（okx_service_id 待 create） |
| toolkit profile+brier+pnl | **钱包情报一页纸** | — | **已上 Worker** `/pm-wallet-report`（okx_service_id 待 create） |
| toolkit `pm updown` | **涨跌盘读出** | — | **已上 Worker** `/pm-updown-readout`（okx_service_id 待 create） |
| toolkit | **充值钱包诊断 deposit-wallet** | 中 | **跳过本轮**：依赖非公开/充值路径与钥相关面，不合无钥只读 Worker hard gate |
| weather-market-lab | **气温阶梯读盘** 加深 | 中 | `/weather-event-readout` 已挂；继续加深但不爬站 |

**Skip note（deposit-wallet）**：本地 toolkit 的充值钱包诊断若需私钥、签名、或非公开充值 API，则不符合本仓「只读公开 API / 无钥边缘」门禁；本轮不接线，保留在本地/MCP。

### P2 · 有 star 但换通道，不硬塞 OKX

| 仓 | 怎么办 |
|---|---|
| x-reader / tg-reader | 继续 MCP/本地 Agent 分发；或以后自建站，**不抢 #3977 尖刀位** |
| claude-code-workflow / video-kit | GitHub 增长环；与付费闸无关 |

---

## 3. 「怎么 Agent 服务化」——关键但可拆步骤

对每一个候选模块，只问四句：

1. **输入是什么？**（0x / slug / query / 调用方自带证据）  
2. **输出是否结构化、可复购？**（会过期 → 才值得按次付）  
3. **能否无钥跑在 Worker？**（不能 → 换 MCP/本地，别硬上 OKX）  
4. **名字能否对齐本地验收条？**（不能 → 叫 `lite` 或别上）

模板：

```
仓内命令/脚本：pm xxx / skill Y
  → 抽纯函数 + 公开 API
  → Worker POST /snake-name
  → 中文刀具名对外
  → x402 定价
  → （可选）OKX listing
```

---

## 4. 和当前货架的关系（别再铺）

货架上 27 个里，**大量是拼盘 commodity**（副驾驶、多条聪明钱）。  
策略改为：

- **尖刀对外只讲**：从 `polymarket-toolkit` + `pm-*` skill 长出来的 2–3 个刀具名  
- **其余**：履约库存 / lite，不占 demo、不占简介脸面  
- **新 SKU**：只允许「本地仓已有实现 → 上架」，禁止反向「先想名字再写薄包装」

---

## 5. 建议的下一步（你点头再动代码）

1. **冻结**再发明 Finance Cockpit 类叙事  
2. 以 **`polymarket-toolkit` README 能力表** 为 backlog SSOT，勾「已上 Worker / 未上」  
3. P1 扫描器四件套（scan / health / wallet-report / updown）**已上 Worker**；Leo 侧：OKX create/activate + listing copy  
4. deposit-wallet **跳过**（非公开/钥相关）— 见上表  
5. 参赛物料：视频/帖只讲 toolkit+skill 长出来的刀（验真 / 矩阵 / 决策卡 + 扫描器）；`scripts/build-cn-demo-video.py` 旁白已改，**需 Leo 本机重跑出片**  
6. star 仓（x-reader 等）继续养开源，**不假装是 OKX 尖刀**

---

## 6. 一句话

**开源 star = 市场需求初筛；本人日用 skill = 深度条；Agent 服务化 = 把两者里「能无钥边缘跑」的切片挂上插座。**  
不是让 AI 再生成 27 个名字。
