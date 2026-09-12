# Agent workflow — OlaXBT Strategy Evidence

## Primary question

Can an agent trust the evidence context behind this OlaXBT strategy signal right now?

## Workflow

```text
ASK BTC/USDT EVIDENCE CONTEXT
→ READ OLAXBT SIGNAL
→ READ OLAXBT METRICS
→ READ OLAXBT TRADES
→ READ OLAXBT EQUITY
→ NORMALIZE OBSERVED FIELDS
→ SURFACE SUPPORT + CONTRADICTIONS + LIMITATIONS
→ RETURN BOUNDED EVIDENCE ASSESSMENT
```

OLAXBT remains strategy + signal authority. BHRIGU is the interpretation layer and never emits a replacement trading signal.

## Agent entry points

REST: `POST /v1/strategy-evidence` with `{"symbol":"BTC/USDT"}`.

MCP: call `bhrigu_get_olaxbt_strategy_evidence` with `{"symbol":"BTC/USDT"}`.

Both return the same Strategy Evidence object and the same authority flags.

## Decision discipline

An agent may use the returned object to understand evidence quality and uncertainty. It must not treat `assessment` as an order instruction. `SUPPORTED` means the historical evidence dimensions are comparatively supportive; it does not mean BUY or SELL.

## Failure discipline

- Missing upstream source → explicit `source_status.*.ok=false`.
- Missing direction → no direction is invented.
- Missing source win rate → recent trade statistics are not substituted.
- Upstream authentication failure → explicit failure.
- No trade, wallet, transfer, withdrawal, or payment side effect exists.

## Inherited temporal evidence

The repository still exposes its prior Bitcoin Temporal Evidence tools for Open-Innovation continuity. They are secondary in the trading-track judging path and do not change the Strategy Evidence authority boundary.
