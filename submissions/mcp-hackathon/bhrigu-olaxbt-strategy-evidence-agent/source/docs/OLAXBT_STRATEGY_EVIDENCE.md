# OlaXBT Strategy Evidence — primary trading-track capability

## Authority split

- **OLAXBT:** strategy + signal authority.
- **BHRIGU:** evidence interpretation layer.
- **Job:** Can an agent trust the evidence context behind this OlaXBT strategy signal right now?

BHRIGU does not generate a second signal. It preserves the observed OlaXBT direction and surrounds it with historical strategy evidence, recent behavior, equity context, contradictions, limitations, and source status.

## Observed upstream normalization

The live OlaXBT Nexus shapes observed for the bound strategy are normalized only from explicit source fields:

- `get_strategy_signal.content.trade_intent` → `signal.direction` (`BUY`, `SELL`, or `HOLD` when supplied).
- `get_strategy_signal.content.confidence` → `signal.confidence`.
- `get_strategy_signal.content.reasoning_log` → `signal.reasoning_log`.
- `get_strategy_metrics.content.win_rate_pct` → `strategy_evidence.win_rate`.

Reasoning text is never parsed to infer direction. Recent-trade positive share is never substituted for OlaXBT source win rate.

## REST

```http
POST /v1/strategy-evidence
content-type: application/json

{"symbol":"BTC/USDT"}
```

## MCP

Tool: `bhrigu_get_olaxbt_strategy_evidence`

Input schema: exactly `symbol = BTC/USDT`. Output is the same bounded Strategy Evidence object returned by REST.

## Four upstream sources

1. `get_strategy_signal`
2. `get_strategy_metrics`
3. `get_strategy_trades`
4. `get_strategy_equity`

A source failure is reported under `source_status` and in `limitations`; evidence is never fabricated.

## Assessment enum

`SUPPORTED | MIXED | WEAK | INSUFFICIENT`

This evaluates evidence quality around the observed OlaXBT signal. It is not a new BUY/SELL/HOLD output and not a price forecast.

## Secret boundary

The authorized Nexus credential exists only as the server environment variable `OLAXBT_NEXUS_API_KEY`. The repository contains no real credential value.

## Forbidden

No trading execution, wallet access, exchange credentials, payment, portfolio management, autonomous order loop, signal fabrication, or reasoning-text direction inference.
