# Verification evidence — BHRIGU OlaXBT Strategy Evidence Agent

## Prerequisites

- Review commit: `d29423daf121a4318dec063d0694b5fec8eb2ed3`
- API base URL: `https://bhrigu-bitcoin-research-state-rn4vpiwc8-aibhrigus-projects.vercel.app`
- Authentication: no reviewer credential. The OlaXBT Nexus credential remains server-side.

## 1. Health check

```bash
curl --fail --silent --show-error https://bhrigu-bitcoin-research-state-rn4vpiwc8-aibhrigus-projects.vercel.app/health
```

Expected:

```json
{"status":"ok","commit":"d29423daf121a4318dec063d0694b5fec8eb2ed3"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://bhrigu-bitcoin-research-state-rn4vpiwc8-aibhrigus-projects.vercel.app/.well-known/xagent-verification.json
```

Expected:

```json
{"schemaVersion":1,"slug":"bhrigu-olaxbt-strategy-evidence-agent","commit":"d29423daf121a4318dec063d0694b5fec8eb2ed3"}
```

## 3. Real REST strategy-evidence call

```bash
curl --fail --silent --show-error \
  --request POST https://bhrigu-bitcoin-research-state-rn4vpiwc8-aibhrigus-projects.vercel.app/v1/strategy-evidence \
  --header 'content-type: application/json' \
  --data '{"symbol":"BTC/USDT"}'
```

Real proof captured on 2026-09-12 returned HTTP 200. Review-critical fields were:

```json
{
  "signal": {"direction":"SELL","confidence":0.16865581885564507},
  "strategy_evidence": {"win_rate":52.94,"sharpe_ratio":1.7668,"profit_factor":1.6494},
  "source_status": {
    "signal": {"ok":true,"tool":"get_strategy_signal","http_status":200},
    "metrics": {"ok":true,"tool":"get_strategy_metrics","http_status":200},
    "trades": {"ok":true,"tool":"get_strategy_trades","http_status":200},
    "equity": {"ok":true,"tool":"get_strategy_equity","http_status":200}
  },
  "authority": {"new_trading_signal_created":false,"trade_execution":false,"wallet_authority":false}
}
```

The direction is normalized only from the observed OlaXBT `trade_intent` field. The source win rate is normalized only from the observed OlaXBT `win_rate_pct` field. Reasoning text is not used to infer BUY/SELL/HOLD, and recent-trade positive share is not substituted for source win rate.

## 4. Real MCP strategy-evidence call

```bash
curl --fail --silent --show-error \
  --request POST https://bhrigu-bitcoin-research-state-rn4vpiwc8-aibhrigus-projects.vercel.app/mcp \
  --header 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"bhrigu_get_olaxbt_strategy_evidence","arguments":{"symbol":"BTC/USDT"}}}'
```

Real proof captured on 2026-09-12 returned HTTP 200 with `result.isError=false`. `result.structuredContent` contained the same bounded Strategy Evidence object, including all four successful source statuses and the same false execution/second-signal/wallet authority flags.

## 5. Safe failure

Unsupported symbols are rejected explicitly and do not produce substitute evidence. Missing upstream data is surfaced under `source_status` / `limitations`; BHRIGU never fabricates direction, source win rate, or evidence.

## Review boundary

- OLAXBT = strategy + signal authority.
- BHRIGU = evidence interpretation layer.
- Read-only.
- No trading execution.
- No wallet authority.
- No second BHRIGU signal.
- No secret is returned.
