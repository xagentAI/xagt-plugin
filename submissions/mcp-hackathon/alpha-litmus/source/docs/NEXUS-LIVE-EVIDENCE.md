# Nexus Studio Live Evidence

Recorded on **2026-09-19** from the authenticated OlaXBT Nexus Studio UI. This is
operator-observed platform evidence, not a response captured by AlphaLitmus, a
digitally signed attestation, or a public unauthenticated report.

## Bound Strategy and Completed Run

| Field | Observed value |
| --- | --- |
| Strategy name | `SKLab AlphaLitmus Baseline v1` |
| Strategy ID | `str_97efcd85b9fd` |
| Symbol | `BTC/USDT` |
| Backtest run ID | `bt-cb379a212935` |
| Platform strategy-run ID | `srun_bbb0f5b39a12421c` |
| Status | `COMPLETED` |
| Evaluation window | 2026-06-20 through 2026-09-18 |
| Starting capital | $100,000 |
| Final equity | approximately $98,700 |
| Total return | -1.42% |
| Annualized return | -1.42% |
| Annualized volatility | 5.09% |
| Sharpe ratio | -0.91 |
| Sortino ratio | -0.82 |
| Calmar ratio | -0.51 |
| Omega ratio | 0.54 |
| Maximum drawdown | 2.79% |
| Win rate | 50.00% |
| Profit factor | 0.54 |
| Total trades | 4 |

The strategy was left **stopped** after the backtest. No paper or live position was
opened as part of this evidence capture, and no trading deployment is claimed.

## Correction Trail

An earlier attempt, `bt-136e2528377e`, failed because the Studio scanner had been
given `BTC` and `USDT` as separate custom tokens, producing the invalid symbol
`/USDT`. The scanner was corrected to retain only `BTC`, which Studio resolved as
`BTC/USDT`; the completed run above followed. The failed attempt did not consume
the displayed credit balance.

## Interpretation

This result is useful falsification evidence, not a profitability claim. The
negative return, negative risk-adjusted ratios, sub-one profit factor, and only
four trades do not support an edge. AlphaLitmus should therefore preserve the
failure and insufficient-sample limitations instead of tuning them away or
presenting the run as qualified.

The run proves that a named Nexus strategy can complete a real Studio backtest.
It does **not** yet prove that AlphaLitmus can retrieve and reconcile that run
through Nexus MCP. That remaining integration requires an authorized
strategy-bound API key, kept outside source and logs, followed by a captured
read-only capability call. A live window experiment is a separate compute action
and must retain all four application gates and explicit per-request confirmation.

## Separate Candidate Run

The baseline was preserved unchanged. A separately named candidate was created
with a predeclared, explainable configuration rather than editing the failed
baseline after seeing its result:

- strategy: `SKLab AlphaLitmus Candidate v1`
- strategy ID: `str_b840280ce037`
- run ID: `bt-7544746ff32d`
- platform strategy-run ID: `srun_6301f2d0bc034534`
- window: 2026-06-21 through 2026-09-19
- configuration: Swing, Standard synthesis, long and short, 15% maximum position,
  1x leverage, 6% stop and 10% target
- scanner configuration: BTC custom token plus VCP, Wyckoff, breakout and
  momentum scanners; the later live trade surface proved that the custom token
  did not make the traded universe exclusive
- risk controls: 3% daily-loss halt and 10% drawdown halt
- observed summary: +1.02% total return, 0.49 Sharpe, 3.50% maximum
  drawdown, 41.43% win rate, 1.02 profit factor and 70 trades

The candidate is also **stopped**, with no open position or trading deployment.
Its positive summary is weak evidence: Sharpe is below one and profit factor is
only marginally above one. No parameter was retuned after seeing this result.

The same detailed Studio report displayed `FINAL EQUITY $99.7K` against a
`$100.0K` start while also displaying `TOTAL RETURN +1.02%`. Those values are not
arithmetically consistent at the shown precision. This is recorded as an
unresolved cross-surface contradiction, not silently reconciled into a pass. The
Nexus MCP read is required to determine whether the cached metrics, equity curve
or UI summary is authoritative and whether their run identifiers agree.

## Final Independent Challenger

One final strategy was predeclared before execution, with no further strategy
search permitted after its result. `SKLab AlphaLitmus Trend Guard v2` used a
technical-heavy ensemble rather than tuning Candidate v1:

- strategy ID: `str_d2923a49b53c`
- run ID: `bt-c106cad79a59`
- platform strategy-run ID: `srun_11c70c47bfb946bc`
- window: 2026-06-21 through 2026-09-19
- configuration: Day Trader, Standard synthesis, long and short, 15% maximum
  position, 1x leverage, 6% stop and 10% target
- scanner configuration: BTC custom token plus VCP, breakout and momentum
  scanners; no exclusive-universe claim is made
- agent emphasis: 30% technical analysis, 25% pattern recognition, 15%
  liquidity/order flow and 10% statistical alpha
- risk controls: 3% daily-loss halt and 10% drawdown halt

Predeclared acceptance required positive return, at least 30 trades, Sharpe at
least 0.5, profit factor at least 1.10, maximum drawdown no greater than 10%, and
no displayed metric/equity contradiction. The observed run had -4.65% total
return, -3.51 Sharpe, 5.04% maximum drawdown, 20.75% win rate, 0.41 profit factor,
53 trades and approximately $94.6K final equity from $100K. It therefore failed
unambiguously despite satisfying the trade-count and drawdown limits.

Trend Guard remains **stopped**, with no open position or order. The attempt is
retained as negative evidence. No additional strategy will be generated to hide
or optimize around this failure; the complete inspected set is the baseline,
Candidate v1 and Trend Guard v2.

## Live MCP Reconciliation of Candidate v1

After explicit operator authorization, one API key was created and bound to
Candidate v1. The secret was retained only in the process session and is not
recorded here, in source, logs or command output. AlphaLitmus then called the four
documented read-only Nexus MCP surfaces. It did not call `run_backtest`, start
paper trading or place an order.

The first call exposed a production-envelope compatibility gap: Nexus returned
the tool result as a JSON object in `content`, while the client accepted only the
standard one-item MCP text-content list. `app/nexus.py` now accepts both bounded
forms before applying the same recursive validation, duplicate-key rejection,
secret check and field allowlist. A regression test pins the object envelope.

The corrected live result was:

| Field | Observed value |
| --- | --- |
| AlphaLitmus report ID | `3a54d42364feb9378174d7e75656eba80602ff13e541a567b7871d7414c8a87f` |
| Reconciliation hash | `5b59fa3e55d1417d932b201da63cd505b55e53a9662e8c0daea3e17335838e25` |
| Evidence classification | `nexus_snapshot` |
| Verdict | `INCONSISTENT` |
| Eligible | `false` |
| Reconciliation mismatches | 1 |
| Insufficient/unavailable checks | 7 |
| Signal | `HOLD` for `BTC/USDT`; fresh at capture time |
| Metrics status | `NOT_QUALIFIED` |
| Metrics | 1.0221% return, 0.4897 Sharpe, 1.0178 profit factor, 3.50% maximum drawdown, 41.43% win rate, 70 trades |
| Equity | run `bt-7544746ff32d`, 91 points |
| Recent trades | run `bt-7544746ff32d`, 50 returned rows |

Equity and recent trades identified the same run. The equity series recomputed
1.022085% return and 3.496655% maximum drawdown, agreeing arithmetically with the
cached metrics within 0.01 percentage point. That resolves the direction of the
browser UI's displayed final-equity contradiction in favor of the MCP metric and
equity series, while the UI discrepancy remains recorded as a presentation issue.

The material mismatch was instrument scope. The 50 returned trades contained 11
`AIO/USDT`, 11 `ADA/USDT`, 10 `DOT/USDT`, 8 `SOL/USDT`, 5 `ETH/USDT` and only 5
`BTC/USDT` fills. AlphaLitmus requested and the signal claimed `BTC/USDT`, so
`TRADE_SYMBOLS` correctly returned `MISMATCH`. The metrics count of 70 versus 50
recent rows, 41.43% versus recomputed 44% win rate, and 1.0178 versus recomputed
1.1514 profit factor remain `INSUFFICIENT_EVIDENCE`, not hard contradictions,
because Nexus documents the trade surface as recent fills and metrics/signal do
not carry a run identifier.

Candidate v1 is therefore not a verified profitable BTC-only strategy. The live
MCP run demonstrates AlphaLitmus's intended value: it preserved partial numeric
agreements, refused to overstate incomplete comparisons, and failed closed on a
real cross-instrument contradiction.

## Recorded Replay Versus Live Evidence (credential-free historical replay)

The live MCP reconciliation above required an authorized strategy-bound key and
is not replayable by a reviewer without that secret. The recorded replay is the
separate credential-free path for that same Candidate v1 evidence:

- Strategy: `SKLab AlphaLitmus Candidate v1`, ID `str_b840280ce037`, symbol `BTC/USDT`, run `bt-7544746ff32d`.
- Documented reconciliation hash: `5b59fa3e55d1417d932b201da63cd505b55e53a9662e8c0daea3e17335838e25`.
- Expected genuine replay: `INCONSISTENT`, `BLOCK_DEPLOYMENT`/`DO_NOT_DEPLOY`, `TRADE_SYMBOLS MISMATCH`, four surfaces, `source_report_verified:true`, `no_execution:true`, `profitability_claimed:false`.
- Capture: `python -m tools.capture_nexus_snapshot` (fixed Candidate v1 identity and repository destination, four read-only tools only, staged atomic publication, complete repository secret scan, never logs the key).
- Replay: `GET /v1/nexus/replay/candidate-v1` and MCP `replay_recorded_nexus_evidence` (`{}`), both via `app.transport.run_recorded_replay` with zero network calls and byte-identical results.
- Recorded means historical snapshot, not a live Nexus call, not independent authenticity attestation, not profit proof, not trading authorization. Signal/metrics carry no run ID; trades are recent fills. The aggregate binds the manifest metadata and file hashes for source-commit-bound consistency, but does not authenticate Nexus or independently prove the operator-asserted strategy identity.

Status in this workspace: CAPTURED AND VERIFIED. The sanitized canonical production snapshot is checked in at `evidence/nexus-candidate-v1/`, captured at `2026-09-19T18:45:48+00:00`, with aggregate SHA-256 `3a086a1cbf392d15ae961227c091afa343fde5f21b3aebc2aa81ff9d33b389f8`. Strict loading, complete secret scanning, REST/MCP parity, source certificate verification, and the expected `INCONSISTENT` / `BLOCK_DEPLOYMENT` / `DO_NOT_DEPLOY` / `TRADE_SYMBOLS MISMATCH` path passed. This remains recorded historical evidence with the limitations above; it is not a live call, independent source authentication, or profit proof.
