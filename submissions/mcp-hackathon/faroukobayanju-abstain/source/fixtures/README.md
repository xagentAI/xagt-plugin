# Cassette provenance

`NEXUS_MODE=replay` serves these instead of the network, so a reviewer with no
`nxk_` API key reproduces every receipt. Provenance is stated per file because
mixing recorded and synthesized data without saying so would make every claim
in this submission unverifiable.

## RECORDED — verbatim from the live gateway, 2026-09-17

`get_strategy_equity.json` contains the complete 91-point equity series and
`get_strategy_trades.json` contains all 19 trades returned for backtest run
`bt-7a0daf243c06`. They are not terminal excerpts. This matters because replay,
drawdown, loss-streak, and threshold-frontier claims operate on the complete
record rather than only the strategy's worst interval.

Strategy `str_515920d047ca`, backtest run `bt-7a0daf243c06`.

| File | Source call |
| --- | --- |
| `get_strategy_metrics.json` | sharpe 0.2989, `NOT_QUALIFIED`, max_drawdown "7.62%", 19 trades |
| `get_strategy_trades.json` | the bar-50 ETH/BTC/SOL cluster, all `stop_loss` at -25.38% |
| `get_strategy_equity.json` | peak 101,538.70 → trough 93,799.53 = -7.62% |
| `get_strategy_signal.BTC-USDT.json` | `trade_intent: HOLD`, confidence 0.0508 |
| `get_historical_coverage.json` | snapshot date range |

## SYNTHETIC — clearly labelled, and why

The live strategy currently emits `HOLD`, which correctly yields `NO_TRADE`.
Demonstrating the `EXECUTE` and `ABSTAIN` paths on demand needs a `BUY`, so the
`ETH/USDT` cassettes copy the recorded response shape verbatim and change only
the fields named below. Each file carries a `_provenance` string.

| File | What was changed |
| --- | --- |
| `get_strategy_signal.ETH-USDT.json` | `trade_intent` HOLD → BUY |
| `get_historical_funding.ETH-USDT.2026-09-17.json` | hostile funding rate, so `FUNDING_REGIME` has a demonstrable FAIL |
| `get_open_interest.ETH-USDT.2026-09-17.json` | calm OI, so the refusal is unambiguously attributable |

**No recorded value was altered.** Every number quoted in `SUBMISSION.md` as
evidence — sharpe 0.2989, max drawdown 7.62%, the bar-50 cluster — comes from
the RECORDED set above and can be re-fetched from Nexus with a key bound to
strategy `str_515920d047ca`.
