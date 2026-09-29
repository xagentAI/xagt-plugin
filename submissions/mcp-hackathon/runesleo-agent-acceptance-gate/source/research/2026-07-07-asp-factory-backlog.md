# Leo Labs ASP 工厂 Backlog（2026-07-07）

状态：**active** · 主 SSOT：本文件 · 关联：`2026-07-07-okx-wave1-roadmap.md` · Hackathon 截止 **2026-07-17 08:00 北京时间**

## 原则

1. **两步走**：Phase 1 把现成能力商品化 → Phase 2 从素材库挖新需求。
2. **自用 + 外用**：Codex/Hermes 与外部 agent 同调 `api.leolabs.me`。
3. **卖 gate，不卖 voice**：内容线卖 verify / slop-check / readiness，不整包卖 `leo-style` / 账号发布。
4. **工厂流水线**：`skill/repo 逻辑 → api.leolabs.me endpoint → onchainos listing → GitHub README`（目标 **1–3 天/SKU**）。
5. **ASP 不调 relay**：四订阅 lane（Claude/Codex/Cursor/Grok）仅 Leo 自用；外人 x402 服务 = 规则 + 公开 API，**零 LLM 边际成本**。

---

## 一个 ASP，四条产品线

```
Leo Labs (#3977) @ api.leolabs.me
├── Agent Trust      → Delivery Audit Gate（护城河）
├── PM Intelligence  → **PM Event Analyst（通用核）** + Preflight + 品类插件/可选 SKU
│                      框架 SSOT: research/2026-07-09-pm-event-analyst-framework.md
│                      双面契约: research/2026-07-12-pm-event-analyst-dual-surface-contract.md
│                      （人面=T0530 Copilot Research Unit · agent 面=/pm-event-readout · OKX=渠道）
│                      （聪明钱/Regime 等非主线，不优先扩）
├── Research         → Token DD → 对齐 Codex asset-dd skill（另对照；非薄 verdict 门面）
└── Creator Ops      → Content Verify / Slop Check / Publish Gate / Visual Spec
```

**对外叙事（2026-07-09 修正）**：尖刀 = skill 级厚度（事件分析 / 投研），不是薄接口货架占位。  
**PM 线挂法**：一个 Agent 能力 + 一个主服务；品类先 plugin，§准入过关再拆 SKU。

---

## Phase 1 — 上架队列

### Wave A — 零开发（本周 · 等 OKX 审核）

| # | SKU | 状态 | 动作 | 门禁 |
|---|-----|------|------|------|
| A1 | World Cup Smart Money Radar | listing 审核中 | 过审即可 | OKX listed |
| A2 | Polymarket Smart Money Radar | listing 审核中 | 过审即可 | OKX listed |
| A3 | Agent Delivery Audit Gate | listing 审核中 | 过审即可 | OKX listed |
| A4 | Event Price Divergence Radar | listing 审核中 | 过审即可 | OKX listed |
| A5 | Crypto Market Regime Radar | `live_unlisted` | `onchainos create` + activate | listed 后 |
| A6 | World Cup Upset Alert | `live_unlisted` | `onchainos create` + activate | listed 后 |
| A7 | v18 Quote 推 + listing 截图 | 草稿见 `2026-07-07-v18-quote-and-hackathon-post-draft.md` | 审核通过后发 | publish gate |
| A8 | Hackathon 参赛帖 + ≤90s demo | 脚本待 v2 | #Okxai + 填表 | listed 后 |

**Wave A 完成后 SKU 数**：6 listed（+2 自 A5/A6）。

---

### Wave B — 轻包装（各 1–3 天 · 审核期可并行写代码）

| # | 新 SKU | 复用来源 | 路径 | 定价建议 | 赛道 |
|---|--------|----------|------|----------|------|
| B1 | **Token DD Verdict** | `asset-dd` Quick + `auditor.mjs` | `POST /token-dd-verdict` | 0.05 | Finance + Utility | ✅ code `live_unlisted` |
| B2 | **PM Trade Preflight** | `pm-decision-card` 规则层 | `POST /pm-trade-preflight` | 0.1 | Finance + Best Product | ✅ code `live_unlisted` |
| B3 | **PM Event Readout** | `pm-event-readout` skill | `POST /pm-event-readout` | 0.1 | Finance | ✅ code `live_unlisted` deployed |
| B4 | **Content Verify API** | `content-verify` + 规则层 | `POST /content-verify-claims` | 0.1 | Software Utility | ✅ code `live_unlisted` |
| B5 | **Content Slop Check** | `publish-gate` / `stop-slop` 规则层 | `POST /content-slop-check` | 0.05 | Software Utility · **未实现** |

**Wave B 优先级**：B1 → B2 → B4 → B3 → B5（黑客松 demo 主角：B2 + A3 + B1）。**B5 排 Wave C 后**，不挡 7/17。

**B5 不做**：GLM/relay 改写、`skill-api` Hono 迁移、调用方代烧 Leo 订阅额度。

---

### Wave C — 数据线扩展（各 2–5 天 · Wave B 后）

| # | 新 SKU | 复用来源 | 路径 | 定价建议 |
|---|--------|----------|------|----------|
| C1 | **PM Profile API** | `polymarket-toolkit` CLI | `POST /pm-profile` 等 | 0.05 |
| C2 | **Elite Pool Lookup** | `polymarket-data` T014 | `POST /pm-elite-pool-lookup` | 0.1 |
| C3 | **Publish Readiness Gate** | `publish-gate.py` | `POST /publish-readiness` | 0.1 |
| C4 | **Visual Spec API** | `leo-visual-router` + `content/brand/card-layouts` | `POST /visual-spec` | 0.05 |

---

### 不做 ASP（自用 / 合规 / 敏感）

| 资产 | 原因 |
|------|------|
| `leo-style` / `tg-publish` / `xhs-publish` / `distribute` | 账号、人格、部署 hard gate |
| `prediction-trader` / `pm-manual-trading-lab` playbook | 执行、下单、内部 SSOT |
| `strategy-report` | VPS 实盘隐私 |
| `tg-reader-mcp` / `wechat-reader` | Session / 环境绑定 |
| 6551 转售类 MCP | 第三方 API 依赖 |

---

## Phase 2 — 需求挖矿（素材库）

| 层 | 路径 | 用法 |
|----|------|------|
| 社群痛点 | `leo-vault/domains/内容创作/社群需求池.md` | ≥3 次标 🔥 → 评估 SKU |
| 外部信号 | `leo-vault/domains/内容创作/外部信号池.md` | 周捞 3 条 triage |
| OKX 需求研究 | `research/2026-07-06-demand-side-and-playbooks.md` | 定价/打法参照 |
| 日更过堂 | `~/.claude/cache/today-todos-{DATE}.json` → `morning_intake_queue` | 当天路由 |
| 路由协议 | `Documents/Codex/EXTERNAL_SIGNAL_TO_OWNED_ASSET_ROUTING_20260630.md` | drop → watch → queue → worker |

### 已采集 · 待消化（首批）

| # | 需求信号 | 可能 SKU / 资产 |
|---|----------|-----------------|
| 1 | PM 跟单工具 + 幽灵订单 | Toolkit API / PMQuant 模块 |
| 2 | TG/吃单延迟 250ms | 研究 brief，非立即 API |
| 3 | Oracle / 结算源脆弱性 | `/blog` 或 Risk Case |
| 4 | Dry Run vs Live 幻觉 | 策略内容 + Preflight 叙事 |
| 5 | PMQuant Risk Case Library | 课程后补 |
| 6 | OKX 任务端全市场聪明钱 | 已有 PM radar，观察转化 |
| 7 | 背离信号 | 已 live（A4） |
| 8 | Token DD BUY-WATCH-SKIP | **B1** |

**节奏**：每周从素材池捞 **1 条** → `demand_check` → 能 1–3 天包的进 Wave B/C。

---

## Hackathon 多池映射（2026-07-17 截止）

| 赛道 | 拿什么打 | 优先级 |
|------|----------|--------|
| Software Utility | A3 Audit + B4 Verify + B1 Verdict | A |
| Finance Copilot | A4 Divergence + A5 Regime + B2 Preflight | A |
| Social Buzz | 参赛帖 + build 线程 + #Okxai | A |
| Best Product / Business Potential | 多 SKU 互调 + OPC 故事 | B |
| Revenue Rocket | 免费试用 + 自调用 tx | C（彩票） |
| Lifestyle / Art | — | 不打 |

**Demo v2 主线（90s）**：Audit → Verdict → Preflight 三连调 + 402 settle。

---

## Wave B 规格摘要

### B1 — Token DD Verdict

- **输入**：`asset`（ticker / contract / URL）、`tier`（`quick` | `standard` 仅 quick 首版）
- **输出**：`verdict_bucket`（`avoid` | `watch_only` | `research_position` | `tiny_speculative` | `conviction`）、`score_0_100`、`pillars[]`（五支柱 ✅/⚠️/➖）、`hard_stops[]`
- **实现**：`auditor.mjs` 模式 + 公开安全 API（honeypot 等）；**非 LLM 终审**
- **GET sample**：固定合约样例
- **文案**：rule-based research gate，not investment advice

### B2 — PM Trade Preflight

- **输入**：`market_url` 或 `condition_id`、`side`（`yes` | `no`）、`size_usd`（可选）
- **输出**：`action`（`trade` | `watch` | `skip`）、`confidence`、`reasons[]`、`risk_flags[]`
- **实现**：Gamma 市场元数据 + 流动性/价差规则 + `pm-decision-card` 阈值；**read-only，无下单**
- **差异化**：交易前闸门，非聪明钱榜单

### B3 — PM Event Readout

- **输入**：`market_url` 或 `condition_id`
- **输出**：`event_summary`、`priced_in[]`、`uncertainty[]`、`tradability`（`high` | `medium` | `low`）
- **形态**：首版 API；复杂案可转 escrow task

### B4 — Content Verify API

- **输入**：`claims[]` + `sources[]`（URL 或摘录）
- **输出**：`consensus`、`conflicts[]`、`unsupported[]`、`verdict`（`pass` | `needs_review` | `fail`）

### B5 — Content Slop Check（规则版 · 替代 Humanize）

- **输入**：`text`（必填）、`locale`（`zh` | `en`，默认 `en`）
- **输出**：
  - `verdict`：`pass` | `needs_edit` | `fail`
  - `slop_score_0_100`（越高越像 AI 模板腔）
  - `slop_flags[]`：`{ id, severity, excerpt, hint }`
  - `readability`：`{ avg_sentence_len, listicle_density, hedge_word_count }`
  - `suggested_actions[]`（只给编辑方向，**不改写正文**）
- **规则层（首版，无 LLM）**：
  - 套话/空洞词表（中英）：`delve` / `landscape` / `值得注意的是` / `综上所述` 等
  - 结构腔：三连列表密度、破折号滥用、全大写标题段
  - 模糊断言：无数字的「显著」「大量」「革命性」
  - 重复 n-gram（同段 3+ 次）
- **与 B4 分工**：B4 = 断言 vs 来源；B5 = 文本腔调 vs 发布可读性
- **定价**：0.05 USDT；可与 B4 组合叙事「Creator Ops 双闸门」
- **远期 LLM（单独 gate）**：仅当单价 ≥ 成本×3 且 Leo 开 paid API gate；或 BYOK；**永不接 relay**

---

## 审核通过后 Runbook（Leo 一声「listing」）

**前置**：Agent #3977 四服务审核通过；Leo 明确授权 `onchainos create`。

```bash
cd ~/Projects/agent-acceptance-gate
bash scripts/okx-batch-listing-draft.sh   # 打印 6 条 validate/create 草稿
# 逐条 review → onchainos agent validate-listing → create → activate
bash scripts/okx-asp-self-call.sh       # 自调用留 tx 证据
```

| 序 | SKU | endpoint |
|----|-----|----------|
| 1 | Crypto Market Regime Radar | `/crypto-market-regime-radar` |
| 2 | World Cup Upset Alert | `/world-cup-upset-alert` |
| 3 | Token DD Verdict | `/token-dd-verdict` |
| 4 | PM Trade Preflight | `/pm-trade-preflight` |
| 5 | PM Event Readout | `/pm-event-readout` |
| 6 | Content Verify Claims | `/content-verify-claims` |

**+48h**：录 demo v2 → v18 推（publish gate）→ #Okxai 参赛帖 → 填表（截止 7/17 08:00 北京）。

文案 SSOT：`research/2026-07-07-okx-listing-copy-bilingual.md` · 代码：`worker/service-catalog.mjs` → `PENDING_OKX_LISTING_COPY`。

---

## 执行日历（默认）

| 窗口 | 动作 |
|------|------|
| 现在 → 审核过 | 并行写 B1/B2 Worker route + 测试；不动新 listing activate |
| 审核 +48h | A5/A6 listing；参赛帖 + demo v2；自调用 10 次留 tx |
| 审核 +1 周 | B1–B4 各上线 1 个；刷新 marketplace 扫描 |
| 持续 | Phase 2 每周 1 条需求 → SKU 或内容/课程队列 |

---

## 验证清单（每个新 SKU）

- [ ] `npm test` + `worker:check`
- [ ] GET public sample
- [ ] POST free_trial + x402 付费路径
- [ ] `onchainos validate-listing` + `create`/`update`
- [ ] README 示例请求/响应
- [ ] 参赛 demo 可录屏

---

## 变更日志

| 日期 | 变更 |
|------|------|
| 2026-07-07 | 初版：Phase 1 Wave A/B/C + Phase 2 素材库 + Hackathon 映射 + B1–B5 规格摘要 |
| 2026-07-07 | **B1/B2 已实现**（Worker `live_unlisted`）：`/token-dd-verdict` · `/pm-trade-preflight`；**deployed** api.leolabs.me `23d6ea4c` |
| 2026-07-07 | **B5 改规格**：Humanize+GLM → **Content Slop Check** 规则版；ASP 不调 relay；加审核通过后 batch listing runbook |
| 2026-07-07 | **审核等待 checkpoint**：watcher `new=0`；8/8 GET sample 200；demo 三主角 GET 高亮 OK；`npm test` 全绿；v18+参赛帖草稿落盘 |
| 2026-07-09 | **头像再拒**（圆角/白底）+ `[U1] beta`；策略改为再拒时 **Big Pack**。Leo 定稿头像=`content/brand/leo-labs-avatar-1024.jpg`。runbook+print脚本+Batch2 brief 就绪；**审核中不上链**。预检：禁词0 + 10×402 |
