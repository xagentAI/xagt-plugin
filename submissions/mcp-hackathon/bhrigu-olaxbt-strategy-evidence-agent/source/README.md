# BHRIGU OlaXBT Strategy Evidence Agent

**OLAXBT = strategy + signal authority.**
**BHRIGU = evidence interpretation layer.**

**Job:** Can an agent trust the evidence context behind this OlaXBT strategy signal right now?

The primary trading-track capability is a bounded, read-only evidence object around the current OlaXBT `BTC/USDT` strategy signal. It consumes the live signal, strategy metrics, recent trades, and equity context from OlaXBT Nexus MCP and surfaces support, contradictions, limitations, and evidence quality without creating a second trading signal.

## Primary interfaces

- `POST /v1/strategy-evidence` — REST Strategy Evidence object
- MCP tool `bhrigu_get_olaxbt_strategy_evidence` — the same bounded object for agents
- `GET /health` — exact deployed commit
- `GET /.well-known/xagent-verification.json` — trading-track submission slug + exact commit

Input is exactly `{"symbol":"BTC/USDT"}`. OlaXBT signal direction is preserved from the observed upstream `trade_intent` field; BHRIGU never infers BUY/SELL/HOLD from reasoning text. OlaXBT backtest win rate is preserved from the observed upstream `win_rate_pct` field.

## Safety boundary

Read-only. No order placement, exchange execution, wallet authority, payment authority, withdrawal, transfer, or second signal. Historical performance is evidence context, not a forecast. The OlaXBT Nexus credential is server-side only.

## Evidence sources

The Strategy Evidence object consumes exactly four OlaXBT Nexus tools:

- `get_strategy_signal`
- `get_strategy_metrics`
- `get_strategy_trades`
- `get_strategy_equity`

Each source is reported independently under `source_status`; missing or contradictory evidence is surfaced rather than replaced.

## Run and test

Requires Node.js 22+.

```bash
npm ci
npm test
npm start
```

The live Strategy Evidence call requires `OLAXBT_NEXUS_API_KEY` only in the server environment. Do not put it in Git, client code, fixtures, logs, or responses.

## Inherited capability

This repository also preserves the earlier BHRIGU Bitcoin Temporal Evidence capability and its read-only MCP tools. That inherited Open-Innovation capability remains available, but it is not the primary object of the OlaXBT trading-track submission.

## IP boundary

Only the bounded public adapter is present. ORION core, private prompts, planners, evaluators, private corpora, unpublished methods, credentials, wallet/payment code, and trading execution are excluded.
