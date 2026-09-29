# OKX.AI 首发 Listing 包 — World Cup Smart Money Radar

- 日期：2026-07-04
- Task：T0521
- Repo：agent-acceptance-gate
- 状态：local launch pack only；未部署、未接钱包、未接支付、未提交 listing

## 选择

首发服务：`World Cup Smart Money Radar`

批量候选：

1. `World Cup Smart Money Radar` → `/world-cup-smart-money-radar`
2. `Polymarket Smart Money Radar` → `/polymarket-smart-money-radar`
3. `Event Probability Crypto Divergence` → `/event-probability-crypto-divergence`
4. `Crypto Market Pulse Report` → `/crypto-market-pulse-report`

原因：

- OKX.AI 当前相对有销量的是 World Cup / smart-money / 数据类服务。
- `World Cup Alpha` 同类服务已卖出 52 单，说明平台上至少有少量买方理解这个需求。
- 这个服务可以复用 Leo 的 Polymarket 数据资产，且合规定位是 data and analytics，不托管资金、不执行交易。

## OKX.AI 首发 Listing 文案草案

Service name:

```text
World Cup Smart Money Radar
```

Line 1:

```text
Tracks profitable World Cup prediction-market wallets and highlights position changes, sides, and confidence.
```

Line 2:

```text
Provide a market name or use all markets; returns compact data-only signals for agent research workflows.
```

Fee:

```text
1
```

Category:

```text
World Cup
```

Endpoint:

```text
POST https://<stable-domain>/world-cup-smart-money-radar
```

## API shape

Request:

```json
{
  "market": "winner",
  "limit": 5
}
```

Response fields:

- `summary`
- `signals[].market_id`
- `signals[].address_label`
- `signals[].side`
- `signals[].action`
- `signals[].notional_usdt`
- `signals[].seven_day_pnl_usdt`
- `signals[].confidence`
- `signals[].rationale`
- `caveats`

## Hard gates before real submission

- Leo confirms Agentic Wallet email.
- Leo confirms receiving wallet/payment setup.
- Leo confirms OKX/payment SDK/API key path.
- Leo confirms stable production endpoint domain.
- Leo confirms OKX.AI ASP listing submission.
- Production endpoint must use fresh data, not demo data.

## Today’s fastest path after Leo confirms gates

1. Create Agentic Wallet / ASP identity.
2. Deploy the current HTTP server behind a stable HTTPS endpoint.
3. Replace demo smart-money rows with the fastest available fresh Polymarket-derived snapshot.
4. Add OKX payment middleware or OKX-required charging wrapper.
5. Submit this one listing.
6. After acceptance, clone the same host shape for F1/F2/F3.

## Batch listing drafts

### Polymarket Smart Money Radar

Line 1:

```text
Tracks profitable Polymarket wallets across markets and highlights position changes, sides, and confidence.
```

Line 2:

```text
Provide a market, topic, or all; returns compact data-only smart-money signals for research agents.
```

Fee: `1`

### Event Probability Crypto Divergence

Line 1:

```text
Compares prediction-market event probability changes with crypto spot and funding moves.
```

Line 2:

```text
Provide an event or asset; returns divergence signals for agent research workflows.
```

Fee: `1`

### Crypto Market Pulse Report

Line 1:

```text
Summarizes crypto market flows, anomalies, leverage conditions, and watch items for agents.
```

Line 2:

```text
Provide an asset or use all markets; returns a compact data-only market pulse report.
```

Fee: `1`
