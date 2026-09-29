# v2.2 Quote + Hackathon 参赛帖草稿（Audit + Football · 2026-07-10）

状态：**local draft · 未发布/未提交表单 · publish gate 未跑**。仅在 listing 终态确认通过、截图与 v2.2 视频复核后使用。

战略对齐：视频尖刀是 **Agent Delivery Audit Gate + Football Event Analyst**；Tennis 与 research gates 只作组合提示，不在 48 秒里展开。

## Video structure QA（对应已渲染 v2.2）

- **Hook（0–6s）**：`I'm one person. This is Leo Labs — my agent company on OKX.AI.` 先交代人物、产品与平台。
- **Retain（6–34s）**：先问“工人真的交证据了吗”，再展示 Football 同场 8 linked events covering 350 markets，形成第二个信息增量。
- **Reward（34–48s）**：收束到 Audit + Football 尖刀与 one-person-company / OPC build-in-public 叙事。
- `external_model_review`: done · see `2026-07-10-t0521-hackathon-model-review.md` + inline model-review below.

model-review: grok+codex 2026-07-10 · first pass=revise (trade wording / listing tense / 350 markets口径) · fixes applied in v2.3 copy · verdict: ship_after_listing

---

## Demand / Asset（v4.4）

```yaml
demand_check: demand_matched
audience_demand: "Agent builders / PM traders who need gates before ship, research, or analyze an event — not another sentiment feed"
top_performer_pattern: "hackathon demo posts that lead with one concrete proof clip + one sharp product claim + #Okxai; skipped live X search this pass — pattern from prior #Okxai scan in T0521 context"
leo_artifact: "Leo Labs #3977 · api.leolabs.me · demo v2.2 Audit+Football 48.3s · 8 linked events covering 350 markets evidence in frames"
reader_takeaway: "Before accepting agent work, ask for evidence; before sizing a football view, demand the full same-event matrix — not one price"
publish_or_park: publish_candidate
text_quality_tier: main_publish
ship_gate: listing_approved_then_leo_public_publish
```

---

## Creator System 检查

- 内容承诺等级: reusable_asset
- 先试再推荐: 本地 demo v2.2 已渲染并通过音画校验；listing 通过后再公开推荐入口
- 给步骤: 看 48s demo → 打开 api.leolabs.me → 调 Audit / Football
- 给截图: listing 页截图（过审后）+ demo 帧（8 linked / 350 markets）
- 给入口: api.leolabs.me · OKX.AI Agent #3977（过审后）
- 积累回访理由: one-person-company 闸门组合可持续加品类，不靠单次喊单
- 读者入口: X 参赛帖 + demo 视频；次入口 api.leolabs.me
- 目标指标: 黑客松表单提交成功；社交热议赛道可见；不 claim 收入
- next_required_asset: listing 通过截图 + 发帖 URL 回填表单

---

## Algorithm 5 Check

- topic_pk: OKX.AI hackathon · agent gates · Audit + Football event matrix
- not_dwelled: open on “one person / burned by empty delivery” not feature laundry list
- profile_follow: builders who want proof-before-accept + PM event matrix depth
- share_trigger: quoted_line: "If the worker said done — where is the evidence?"
- author_diversity: same_topic_24h_count: 0 (no Leo #Okxai hackathon post in last 24h)
- opening_pattern: first_person_pitfall → gate thesis → 48s demo proof

### 发后24h复盘计划

- primary_metric: impressions + bookmark on hackathon post
- dm_share_proxy: replies asking endpoint / how to call
- profile_follow_signal: profile visits from #Okxai traffic
- negative_signal_watch: “is this trading advice?” / overclaim on 350 markets
- decision_rule: if bookmarks≥3 or useful reply≥2 → quote with listing screenshot; else leave as form evidence only

---

## A. v18 Quote（listing 过审 + 截图后 · `light_quote`）

```yaml
demand_check: demand_matched
audience_demand: "Agent builders / PM traders who need gates before ship, research, or analyze an event — not another sentiment feed"
leo_artifact: "Leo Labs #3977 listed on OKX.AI · api.leolabs.me · Audit + Football live"
publish_or_park: publish_candidate
text_quality_tier: light_quote
```

### recommended（英文 · 配已核验的 OKX listing 截图）

More signals won't save a bad agent.

You need a gate before you accept work.
You need the full event matrix before you analyze an event.

Leo Labs (#3977) on OKX.AI:
Audit Gate + Football Event Analyst.

api.leolabs.me

### v18 alt（中文 · 同截图）

Agent 不缺信号，缺的是闸门。

Leo Labs 已在 OKX.AI 上架（#3977）——先验收 Agent 是否真的交了证据，再把同场足球市场展开成完整矩阵，而不是复读价格。

api.leolabs.me

### Humanizer / Voice

```text
- text_quality_tier: light_quote
- final_text_taste: AI=3.0 / YOU=57.0 / scope=final_text_only (quote EN) · warning_margin
- liuren-edit-pass: pass
- voice-layer v3 audit: 6/7 clean · N/7 hits #brochure-lite (acceptable for light_quote)
```

**发前必做**：`publish-gate.py` · 附 OKX listing 页截图 · 不 claim 收入 · listing 未过审禁止发

---

## B. Hackathon 参赛帖（demo 视频 READY · listing 通过后 · `main_publish`）

表单：https://docs.google.com/forms/d/e/1FAIpQLSfIAgP_WmMGtZ5qyW_LnKZonsjyfOYwV3bduRwiuN4oBmcqjQ/viewform

| 字段 | 值 |
|------|-----|
| ASP Name | Leo Labs |
| Agent ID | 3977 |
| X Handle | @runes_leo |
| TG | runesleo |
| Participation Post | ⏳ 发帖后回填链接 |

### recommended（中文主帖 · Leo 2026-07-11 拍板：中文优先，英文没流量）

writer_model: grok-4.5 · writer_route: leo-grok · non_grok_prose: none

#### LIVE（过审后发 · 默认）

一个人做 Leo Labs。
OKX.AI Agent #3977，已上架。

被 agent 坑过太多次。
说交付了，证据没有。
说跑完了，打开一看是空的。

后来改了：不先堆信号，先装闸门。
工人说做完了——证据在哪？
过不了，就不收。

48 秒 demo 两把尖刀：
Agent Delivery Audit Gate，卡空口交付。
Football Event Analyst，同场 8 个关联事件、覆盖 350 个市场，一次摊开，不复读单个赔率。

卖闸门，卖证据。不喊单。

入口 api.leolabs.me
#Okxai

#### PRE_LISTING（审核中口径 · 一般不发）

一个人做 Leo Labs。
OKX.AI Agent #3977，提审冲上架。

被 agent 坑过太多次。
说交付了，证据没有。
说跑完了，打开一看是空的。

后来改了：不先堆信号，先装闸门。
工人说做完了——证据在哪？
过不了，就不收。

48 秒 demo 两把尖刀：
Agent Delivery Audit Gate，卡空口交付。
Football Event Analyst，同场 8 个关联事件、覆盖 350 个市场，一次摊开，不复读单个赔率。

卖闸门，卖证据。不喊单。

入口 api.leolabs.me
#Okxai

### 英文稿（降级备查 · 不主推）

I'm one person. Leo Labs is live on OKX.AI (#3977).

I got burned by agents that said "done" with no evidence.
So I built gates first — not another signal feed.

48s demo:
1/ Audit Gate — did the worker hand over proof?
2/ Football — 8 linked events covering 350 markets → one event view. Not a price reprint.

api.leolabs.me #Okxai

### Humanizer / Voice

```text
- text_quality_tier: main_publish
- language_primary: zh (Leo override 2026-07-11: EN low traffic)
- writer_model: grok-4.5
- writer_route: leo-grok
- non_grok_prose: none
- final_text_taste: pending_recheck_after_leo_taste
- liuren-edit-pass: pending_leo_review
- voice-layer v3 audit: pending_leo_review
- manual_polish_gate: pending_leo_review
- preview: /Users/zhangxu/Projects/_inventory/2026-07-10/t0521-hackathon-post-preview.html
```

---

## C. 发序（仍是 hard gate；Leo 明确批准后才执行）

1. 只读核验 listing 已通过，并截取无敏感信息的 listing 图；审核中不做零碎 update。
2. 复核 `okx-asp-demo-v2.2-football-audio-fixed.mp4` 的整片音画、时长与字幕；确认画面文案为 **8 linked events covering 350 markets**。
3. 对本文件跑 `prepublish-check.py --type video`，并人工确认证据一致。
4. **Quote** + listing 截图（public publish gate）。
5. **参赛帖** + ≤90s demo + `#Okxai`（public publish gate）。
6. 填 Google 表单并回填 Participation Post（account/form submission gate；截止 **2026-07-17 08:00 北京**）。

---

## Change log · 2026-07-10 v2.3（model-review 后）

- 统一口径：`8 linked events covering 350 markets`
- 去掉 / 弱化交易建议口吻：`trade a match` → `analyze a match`；`match thesis` → `event view`
- listing 未过审时英文主帖用 `building Leo Labs for OKX.AI`，不用 `is live on`
- 删 EN 主帖 “Tennis and research gates sit beside them”（审稿：brochure）
- 独立 review 回执：`research/2026-07-10-t0521-hackathon-model-review.md`
