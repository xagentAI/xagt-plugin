# PM Event Analyst · 产品架构框架（可扩展 SSOT）

日期：2026-07-09  
状态：**active_framework**  
Owner thread：product_distribution（T0521）  
实现 repo：`agent-acceptance-gate`  
本地 skill 源：`~/.codex/skills/pm-event-readout` + `pm-decision-card` + 品类 skills  

关联：

- 对照样例：`research/2026-07-09-pm-event-readout-contrast.md`
- 品类 brief（并入本框架，不再单独当总产品）：`research/2026-07-09-pm-category-analyst-batch2-brief.md`
- 工厂总表：`research/2026-07-07-asp-factory-backlog.md`
- **双面契约（人面 Copilot ↔ agent readout）**：`research/2026-07-12-pm-event-analyst-dual-surface-contract.md` · mapper `src/pm-event-to-copilot-research-unit.mjs`
- 投研线（并行、不抢）：Codex 优化 `asset-dd-and-opportunity-evaluation` → 另文 ASP 包装

---

## 1. 一句话

**一个 Agent 能力 = 通用预测市场事件分析；品类是加深插件；对外先卖一个主服务，验证后再拆品类 SKU。**

不是「只有网球/足球/天气/Musk 四种能分析」，也不是「一上来四个平行服务」。

---

## 2. 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  Agent（身份）  Leo Labs / PM Analyst                     │
│  一个 ASP 钱包身份 · N 个服务槽 · 统一信任与入口            │
└─────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐  ┌─────────────────┐  ┌──────────────────┐
│ 主服务（先做） │  │ 品类服务（后加） │  │ 配套服务         │
│ PM Event      │  │ tennis/football │  │ Preflight        │
│ Analyst       │  │ weather/musk/…  │  │ (eligible/watch/ │
│ 任意 slug     │  │ 更深 · 可更高价 │  │  skip)           │
└───────────────┘  └─────────────────┘  └──────────────────┘
        │                   │
        ▼                   ▼
┌───────────────────────────────────────┐
│ 本地 skill 源（持续优化）               │
│ pm-event-readout（通用核）             │
│ pm-decision-card（动作卡 · 默认可选）  │
│ pm-*-match / weather / musk（插件）    │
└───────────────────────────────────────┘
```

| 层 | 是什么 | 不是什么 |
|----|--------|----------|
| **Agent** | 身份 + 叙事入口 | 不是「每个品类一个 Agent」 |
| **L0 通用核** | 任意事件读出框架 | 不是体育专用 |
| **L1 品类插件** | 四种（及未来新类）加深规则 | 不是唯一能分析的范围 |
| **L2 决策卡** | buy/size/no_trade（可选下游） | 不是 v1 主卖点；不下单 |
| **配套** | Preflight 机械可交易检查 | 不是事件分析本身 |

---

## 3. L0 通用核（任意事件）

**触发**：已知 `slug` / `condition_id` / `market_url`。  
**本地权威字段**：`pm-event-readout` Required Readout。

最低对外 JSON（ASP v1 必须具备）：

| 字段组 | 要求 |
|--------|------|
| 身份与价格 | event, market, current_price, event_time, event_time_source |
| 矩阵 | `event_matrix[]`, `matrix_status`, `related_market_count`, `missing_market_groups` |
| 含义 | `market_implied_view`, `base_case`, `what_is_already_priced`, `what_may_not_be_priced` |
| 诚实边界 | `key_uncertainties`, `sources_read`, `tradability`, `fixture_status` |
| 路由 | `category`（generic 或已注册品类）, `next_decision_card_needed`, `hard_gate` |

硬规则：

1. **事件概率 ≠ 交易吸引力**（读出不输出下单指令）。  
2. 矩阵缺失或外部锚冲突时，`tradability` **不得**标 `high`。  
3. 禁止与价格矛盾的模板句（对照样例里 82% 却写「mid-range」那种）。  
4. ASP **不调** Leo 四订阅 relay；v1 = 规则 + 公开 API（Gamma 等）。  
5. Strip Leo-only：`bankroll_pct`、个人仓位、内部 gate 文案。

**对照验收盘**：Fed July hold（见 contrast 文件）——能回答矩阵、跨市锚差、hold@0.82 是否已贵。

---

## 4. L1 品类插件（可扩展注册表）

品类 = 在 L0 之上叠加的规则/数据适配器，**不是**独立产品线名称。

| category id | 本地 skill | 加深内容（摘要） | ASP SKU 策略 |
|-------------|------------|------------------|--------------|
| `generic` | `pm-event-readout` | 仅 L0 | 主服务默认 |
| `macro_fed` | （可用 L0 + Fed 锚） | FOMC 矩阵 + FedWatch 类锚 | 先做进主服务适配器，不急独立 SKU |
| `football` | `pm-football-match` | 阵容/赛程/动机/同事件矩阵 | 主服务 plugin → 验证付费后再拆 SKU |
| `tennis` | `pm-tennis-match` | fixture 核验 + 全矩阵 | 同上 |
| `weather` | `pm-weather-ladder` | 站点/METAR/ladder/split | **更像该独立 SKU**（输出形态特殊） |
| `musk` | `pm-musk-count` | 发推档 ladder | **更像该独立 SKU** |
| （未来）`election` / `crypto_event` / … | 新 skill | 按 §6 准入 | 先 plugin，后 SKU |

主服务响应里带：

```json
"category": "generic",
"category_depth": "core_only",
"plugins_available": ["football", "tennis", "weather", "musk"]
```

命中已实现插件且 `depth=category`（或买家调品类 endpoint）时：`category_depth: "enriched"`，并多返回品类块（matrix 形状、fixture 核验等）。

---

## 5. 对外服务怎么挂（Agent 一个 · 服务可增）

### 5.1 现在就规划的槽位

| 服务 | path（建议） | 何时上 | 定价带 |
|------|--------------|--------|--------|
| **PM Event Analyst**（主） | `/pm-event-analyst`（或升级现 `/pm-event-readout`） | **下一项实现** | 0.2–0.5 |
| PM Trade Preflight | `/pm-trade-preflight` | 已有；文案 `eligible` | 0.1 |
| （可选）Weather Ladder Analyst | `/pm-weather-analyst` | L0 稳 + 天气样例过关 | 0.3–0.5 |
| （可选）Musk Count Analyst | `/pm-musk-analyst` | 同上 | 0.3–0.5 |
| （可选）Football / Tennis Analyst | `/pm-football-analyst` 等 | 有付费/复购信号再拆 | 0.3–0.5 |

### 5.2 默认挂法

- **先只宣传 / 深做主服务**（通用核）。  
- 品类默认以 **plugin 字段** 活在主服务里。  
- 仅当 §6 准入通过，才 `onchainos create` 独立品类服务。

### 5.3 与旧 10 SKU 关系

| 旧 SKU | 在本框架中的位置 |
|--------|------------------|
| `/pm-event-readout` | **被主服务升级/替换**（薄复读不够收费） |
| `/pm-trade-preflight` | 配套保留 |
| 聪明钱 / Upset / Regime / Divergence | **非本框架主线**；红海或观察中，不按本架构优先优化 |
| Token DD | **投研线**（Codex skill → 另框架），不并进 PM Event Analyst |
| Delivery Audit / Content Verify | 其他产品线（Trust / Creator） |

---

## 6. 新品类 / 新服务准入（以后持续用）

新开一个 category 或独立 SKU 前，必须书面回答：

1. **需求名**：买家会搜什么？平台上是否已有销量旁证？  
2. **真实调用场景**：谁、何时、输入、输出、为什么愿付（不是「POST 回 JSON」）？  
3. **相对 L0 增量**：没有品类规则是否明显更差？增量是否值得加价？  
4. **对照样例**：同一活跃盘，L0-only vs L0+plugin，厚度差可见。  
5. **技术边界**：能否规则 + 公开 API？若需 LLM → escrow/异步/BYOK，不塞进同步薄 endpoint。  
6. **合规**：只读分析；无托管/下单/账户 mutation。  
7. **挂法**：先 plugin 还是直接独立 SKU？（默认先 plugin。）

任一题答不清 → **不开发、不 listing**。

---

## 7. 本地优化 ↔ 线上 ASP 同步节奏

```
优化本地 skill（Codex/Cursor）
    → 更新本注册表 category / 字段
    → 对照样例（同盘 L0 vs 加深）
    → 实现/升级 worker endpoint
    → npm test + 同盘回归
    → （Leo）deploy
    → （Leo）listing 文案 / create|update
    → 冻结审核期不零碎改
```

原则：

- **Skill 可以持续优化**；链上 listing 按大包/明确授权再动。  
- 宣传只讲 **已达 skill 级厚度** 的服务；薄接口不配做黑客松门面。  
- 投研（Asset DD）与本框架 **并行**：Codex 优化 skill 期间 Cursor 不抢；两边各自对照样例后再谈上架。

---

## 8. 实现顺序（当前默认）

| 步 | 内容 | 状态 |
|----|------|------|
| 0 | 架构框架本文 | **done** |
| 1 | Fed 对照样例（证明 L0 厚度） | **done**（contrast md） |
| 2 | 实现 L0：`event_matrix` + 诚实 tradability + 宏观锚适配器 | **done**（schema 0.2） |
| 3 | 路径：升级 `/pm-event-readout`（保留 path，schema 0.2） | **done** |
| 4 | Musk ladder plugin（形状样例） | **done** — **禁止当尖刀/宣传主角** |
| 5 | 独立品类 SKU | 仅付费/复购信号后 |
| 6 | **Football plugin（尖刀）** | **done**（FRA–MAR 350 markets · Worker 已上） |
| 6b | **Tennis plugin（同标准）** | **done**（2026-07-09 · Muchova–Gauff 15 markets · BO3/BO5 · domination check · 见 `pm-tennis-plugin-contrast.md`） |
| 7 | Weather plugin | 等 probation 解除 + 对照样例 |
| — | Asset DD ASP / Pro Pack | **Codex skill v2.2 stage_ready** · Cursor 已交产品站 mock（`_inventory/.../asset-dd-pro-pack-product-site/`）；独立站 deploy / checkout 仍 Leo gate |

---

## 9. 非目标（写死，防回潮）

- 不为「占位」批量 create 聪明钱类同质 SKU。  
- 不把十几个薄接口当黑客松主叙事。  
- 不把四种体育/天气/Musk schema 当成「只能分析这四类」。  
- 不在同步 x402 里假装完整 LLM Standard/Full 报告（投研线另议）。  
- 审核中不零碎 update；大包需 Leo 授权。

---

## 10. Next gate

Leo 确认本框架可作 PM 线长期 SSOT 后：

1. Cursor 实现 L0（步 2–3）。  
2. Codex 继续 Asset DD skill；稳后开投研对照样例。  
3. 品类加深按 §6 排队，不并行铺四个独立服务。

**Writeback 提案（待 Leo/Codex）**：T0521 `next_action` 改为「PM Event Analyst L0 实现 + Asset DD 等 Codex skill」；本文件路径写入 task context。
