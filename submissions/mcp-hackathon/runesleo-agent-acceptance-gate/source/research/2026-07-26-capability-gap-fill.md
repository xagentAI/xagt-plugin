# Capability gap fill · 2026-07-26

拒因：实际调用结果与描述不一致。Leo 要求 **补足能力**（非只改文案）。

## 已补

| 缺口 | 修复 |
|---|---|
| 场景卡 query 搜不到 → throw → fake degraded demo | 多 query/tag/品类默认盘发现；真无盘 → `capability_status=no_active_markets` |
| 世界杯盘空仍声称 WC 雷达 | WC smart-money / upset **自动扩展到 football**，带 `scope_expanded` |
| Worker 把无市场伪装成 demo 成功 | 结构化 unavailable / `upstream_degraded` 可区分 |

## 实测（本地 live，2026-07-26）

- weather / football / macro / politics / nba → `mode=live` + `expected_ok=true` + 真实 slug  
- world-cup smart-money / upset → live，buyer_summary 标明扩展到 football，有信号  
- `node --test test/wave-b-services-test.mjs` pass  

## 链上

- catalog 文案已对齐新能力（WC auto-expand；场景卡 discovery / no_active_markets）  
- 尖刀 Agent 简介待 `update` + `activate` 重提审  

## 文件

- `src/pm-scenario-skus.mjs`
- `src/worldcup-smart-money-live.mjs`
- `src/sports-upset-alert.mjs`
- `worker/index.mjs`
- `worker/service-catalog.mjs`
- `test/wave-b-services-test.mjs`

## Ship

- Worker deploy Version ID: `37055196-e714-4ad2-b19f-b055e520b1db`
- Listing: tip-knife description + 8 service copy updates pushed; `activate` → `submitApproval` **approvalStatus=2 under review** again
- Note: activate payload still echoed prior rejectReason once; `agent get` confirms **Listing under review**
