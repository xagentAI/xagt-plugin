# PM Event Analyst · Dual-Surface Contract v0.1

日期：2026-07-12  
状态：**active_contract**  
产品名：**PM Event Analyst**  
关联：T0521（agent 渠道）· T0530（人面 Copilot）· `2026-07-09-pm-event-analyst-framework.md` · `copilot.read-model.v0.1`

## 一句话

**同一个事件分析内核**：人面读 Research Unit，agent 面调结构化 readout；OKX / MCP / 其他店只是 agent 面 adapter。不是两套产品。

## Surfaces

| Surface | 消费者 | 契约 / path | 计费 |
|---------|--------|-------------|------|
| **Human** | Prediction Copilot（T0530） | `copilot.read-model.v0.1` Research Unit | 产品内（现有 Copilot 路径） |
| **Agent** | 外部 agent / Leo 自用 Codex | `POST /pm-event-readout`（schema `0.2`，`service_id=pm_event_readout`） | x402 @ `api.leolabs.me` |
| **Channel** | OKX.AI ASP #3977 等 | 挂同一 agent endpoint | 平台发现 + x402 |

人面 **不是** Weather Market Lab（T0531）或内容站（T0532）。共享数据组件 ≠ 合并产品。

## Origin

```
skill / rules (pm-event-readout + category plugins)
        │
        ▼
api.leolabs.me  /pm-event-readout     ← agent origin (live)
        │
        ├── OKX.AI listing adapter (under review freeze)
        ├── future MCP / ChatGPT Apps adapters
        └── toCopilotResearchUnit()  ← human-facing projection (this contract)
                │
                ▼
        Copilot UI / bot cards (T0530)
```

当前实现真相：agent 核在 `src/pm-event-readout.mjs`；人面投影在 `src/pm-event-to-copilot-research-unit.mjs`。  
Copilot 现网仍走 `/api/v2/analyze` → SimpleAnalysis → read-model adapter；**本契约定义目标合流形状**，不授权本批改 Copilot runtime wiring。

## 字段映射（Agent → Human）

| Agent (`pm_event_readout` 0.2) | Human (`copilot.read-model.v0.1`) | 规则 |
|--------------------------------|-----------------------------------|------|
| `event_slug` / `market` / Gamma ids | `market.platform=polymarket`, `marketId`, `slug`, `eventId`, `title` | platform 固定 polymarket until multi-venue |
| `generated_at` | `freshness.asOf` | ISO 原样 |
| `matrix_status` | `freshness.status` | `complete`→complete；`incomplete`→partial；缺矩阵/价→missing |
| `tradability_reasons` | `freshness.partialReasons` | 仅当 status=partial |
| `sources_read` 长度 / 矩阵有价 | `evidence.*` | hasPrices / hasLiquidity 从 matrix 行推导 |
| `hard_gate` | `compliance.analysisAllowed` | `no_orders_no_account_mutation` → allowed=true；其它硬拒 → false |
| `tradability` | `decision.eligibility` | **从不**映射为 `BET`（L0 分离事件可读性与下单） |
| `tradability` high/medium | `eligibility=OBSERVE` | confidence 粗映射：high=0.7 / medium=0.5 |
| `tradability` weak/low/其它 | `eligibility=AVOID` | confidence=0.3；`low` 与 `weak` 同级 |
| `base_case` + `market_implied_view` | `summary.en`（+ optional `summary.zh` if present） | 拼接，不发明新句 |
| 全量 agent JSON | `extensions["pm-event-readout.v0.2"]` | 完整保留；UI 可忽略 |

### Decision 硬规则（双面共用）

1. L0 Event Analyst **不输出 buy/sell/size**；`eligibility=BET` 只允许来自未来的 Preflight / Decision Card 下游，不来自本投影。  
2. `freshness.status=missing` → `decision` 必须 `null`。  
3. `compliance.analysisAllowed=false` → `decision` 必须 `null`。  
4. 禁止根级天气 / 内容站 / 下单字段（与 Copilot v0.1 forbidden keys 对齐）。

## Agent → Human 验收

- 纯函数：`toCopilotResearchUnit(agentPayload, { unitId })`  
- 单测：`test/pm-event-dual-surface-test.mjs`  
- `validate`-style：投影结果必须带 `schemaId=copilot.read-model.v0.1`，且无 forbidden keys。

## Human → Agent（目标方向，本批不接线）

Copilot 选中市场后，应用同一 `slug|condition_id|market_url` 调 `/pm-event-readout`（或内部同函数），再投影回 Research Unit——消灭「UI 一套、OKX 一套」漂移。接线排在 T0530 Chrome E2E 恢复之后。

## 非目标（本批）

- 不改 OKX listing / activate（审核冻结）  
- 不 deploy Cloudflare Worker  
- 不改 Copilot 生产 bundle / `/api/v2/analyze`  
- 不把聪明钱 / Regime / Upset 升为主产品叙事  

## Next gates

1. Leo 或 Codex 接受本契约为 PM 线双面 SSOT。  
2. Mac trust/Chrome 恢复 → T0530 authenticated E2E。  
3. E2E 后：Copilot 读路径改调同一 origin（或共享 `assessPmEventReadoutLive`）。  
4. OKX listed 后：渠道仍挂 `/pm-event-readout`；对外品牌名统一 **PM Event Analyst**。
