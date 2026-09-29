# AlphaLitmus Methodology

Implementation reference: `app/contracts.py`, `app/lab.py`, `app/release_gate.py`, `app/reconcile.py`, `app/certificates.py`, `app/research.py`, and `app/nexus_compute.py`, reviewed 2026-09-19. This describes executable rules, not independent validation. The challenge certificate schema is `alphalitmus-1`, product version `AlphaLitmus-2.0`, engine `alphalitmus-ema-v1`. The release-gate projection schema is `alphalitmus-release-gate-1` (`app/release_gate.py`, verified projection over the authoritative `Report`: existing `verify_report` first, then mapping; no duplicated calculations, no LLM). The separate window-compute report does not claim that engine or certificate provenance.

## Input Domain

`ChallengeRequest` rejects extra fields and nonfinite values. `mode` is `reference` (default) or `nexus`. Reference requires nested `research`; Nexus forbids it. Challenge and research symbols must match, with pattern `^[A-Z0-9]{2,12}/[A-Z0-9]{2,12}$` and default `BTC/USDT`.

| Field | Domain / default |
| --- | --- |
| `attempted_variants` | Null or integer 1 through 1,000,000; default null |
| `additional_cost_max_bps` | 0 through 200; default 100 |
| `cost_resolution_bps` | 0.5 through 10; default 1 |
| `bootstrap_iterations` | Integer 50 through 500; default 200 |
| `as_of` | Null or Unix seconds 0 through 253402214400; default null |
| `research.candles` | 250 through 3000 daily candles |
| `research.data_kind` | Required `synthetic` or `historical`, caller declared |
| `research.source` | 1 through 160 printable, nonblank characters; secret-like content rejected |
| `research.fee_bps`, `slippage_bps` | Each 0 through 200; defaults 10 and 5 |

Candles are `{t,o,h,l,c,v}` with UTC-midnight opening milliseconds, unique ascending timestamps exactly 86,400,000 ms apart, and fully closed days. `t` is in [0,253402214400000]; OHLC must be internally consistent. Research prices are in [1e-9,1e12], but challenge prices have the tighter [1e-8,1e12] bound and dataset-wide maximum/minimum price ratio <= 1e6. Volume is in [0,1e18], validated but not used for execution or capacity. Source labels and historical classification are not authenticated.

## Reference Replay

For closes `C_i`, initialize each EMA at `C_0`, then `EMA_p(i) = EMA_p(i-1) + 2/(p+1) * (C_i - EMA_p(i-1))`. Long intent is `i >= slow` and `EMA_fast(i) > EMA_slow(i)`. Default periods are 20 and 50. Log returns are `r_i = ln(C_i) - ln(C_(i-1))`. Volatility is the population standard deviation of the latest 20 log returns, available from index 20: `sqrt(sum((r-mean(r))^2)/20)`. It is not annualized.

For `n` bars, let `a=floor(0.6*n)` and `b=floor(0.8*n)`. Index ranges are half-open: training `[56,a)`, validation `[a,b)`, test `[b,n)`. Indicators are causal over the full chronological series; holdings reset flat at every fold. Sort available training volatility from `[55,a)` into `v`; the frozen gate is `v[floor(0.8*(len(v)-1))]`, without interpolation. Guarded intent also requires volatility <= this gate. The baseline has no gate; buy-and-hold enters at the fold's first open and exits at its final close, paying both costs.

At execution bar `i`, intent and volatility come from index `i-1-delay`. Thus delay 0 already means next-open execution; delays 1, 2, 3 use progressively staler signals, not an order-queue model. The strategy is all-in, unlevered, spot long/flat. No shorts, funding, borrow, intraday fills/stops, partial fills, capacity or order-book simulation.

Let one-way cost fraction `c=(fee_bps+slippage_bps+additional_bps)/10000`. Entry divides wealth by `1+c`; exit multiplies wealth by `1-c`. In log equity, deduct `ln(1+c)` on entry and add `ln(1-c)` on exit. A held position first receives overnight `ln(O_i/C_(i-1))`; a position held after the open receives intraday `ln(C_i/O_i)`. Liquidate at the final close, including one-bar trades. No trade crosses a fold boundary.

Start log equity `L=0` and peak `P=0`. Return is `100*expm1(L)`. At daily marks, `P=max(P,L)` and drawdown is the maximum `-100*expm1(L-P)`. Daily marks miss intraday risk. Conversion rejects nonfinite cumulative or individual closed-trade log returns, or values outside **[-100,100]**. A bound failure in any reference replay makes the **entire reference analysis unavailable** with `NUMERIC_DOMAIN_EXCEEDED`; partial folds/trials are not retained, and this is not a profitable result. Bootstrap-only bound failures have the narrower handling described below.

For closed trade log returns `l_j`, simple percentage returns are `q_j=100*expm1(l_j)`. Expectancy is `mean(q_j)` or null with no trades. Profit factor is `sum(q_j for q_j > 0)/(-sum(q_j for q_j < 0))`. It is equal-notional net-trade-return profit factor, not compounded currency-PnL profit factor. It is null with no losses or a ratio above 1e12. `profit_factor_status` distinguishes `defined`, `no_trades`, `no_losses` and `bounded`; null is not a pass or infinity. `observations` counts bars; `trade_count` counts closed trades, including forced liquidation.

## Perturbations and Boundaries

The test-fold EMA neighborhood is the nine Cartesian pairs `{18,20,22} x {45,50,55}`. The volatility gate stays frozen. All four delays `{0,1,2,3}` are tested. Costs use `0, resolution, 2*resolution, ... <= maximum`, appending the exact maximum if not a grid multiple. Costs are additional **one-way** basis points, not round-trip totals. Maximum base cost is 400 bps; maximum stressed cost is 600 bps.

Return frontier failure means return <= 0; its status is `fails_at_baseline`, `bracketed`, or `survives_bound`. Expectancy break-even failure means expectancy <= 0; profit-factor break-even failure means profit factor <= 1. Break-even scans retain null-metric costs in `unavailable_bps` and continue rather than hiding later failures. Failure at cost 0 is `fails_at_baseline`; a later failure after any unavailable trial is `observed_failure`, with `first_failing_bps` retained and `last_passing_bps` null. A fully observed crossing is `bracketed`. If no failure is found but any trial was unavailable, status is `unavailable`, not survival; the last observed passing cost can still be reported. Only a fully available all-passing scan is `survives_bound`. No bracket crosses an unavailable trial, and no bracket is a continuous root or extrapolation.

Each reported minimal failure boundary tests return <= 0 within one dimension. Cost and delay use their full tested domains; fast EMA uses `{18,20,22}` holding slow=50; slow EMA uses `{45,50,55}` holding fast=20. Failing trials sort by absolute distance from baseline, then lower parameter value. `delta=boundary-baseline`; `effect=trial_return-base_guarded_test_return` in percentage points. A baseline failure has delta 0. No failure means null boundary/delta/effect. This is the smallest discovered failure in that dimension's tested domain, **not a global minimum**, joint optimization, or proof of robustness outside the domain.

## Resampling and Regimes

The dataset hash is SHA-256 of canonical candle-array JSON. Seed is the first eight hex digits interpreted as an integer. A local Python `random.Random(seed)` performs `B` iterations. With `m` closed guarded test trades, each bootstrap samples `m` net trade log returns with replacement and computes `100*expm1(sum(sample))`. Independently within each iteration, a shuffled copy of those original trades gives closed-trade-path maximum drawdown. The shared seeded generator makes replay deterministic in the supported environment.

Sort bootstrap returns. The reported p05 is index `floor((B-1)*0.05)`, p95 is `ceil((B-1)*0.95)`; permutation drawdown p95 uses that same upper index. No interpolation, studentization, BCa correction, or calibrated significance claim is implemented. No trades gives null statistics; 1 through 29 gives descriptive numbers but `insufficient` status and unavailable statistical tests. At least 30 closed test trades is a policy floor, not proof of independence or adequate power.

If even one bootstrap sum exceeds the conversion domain [-100,100], `bootstrap_status` is `numeric_domain_exceeded` and **all bootstrap return quantiles are withheld**. The code does not exclude failed samples and publish a selectively truncated distribution. It completes the iterations, retains permutation statistics and the other reference analyses, adds `BOOTSTRAP_NUMERIC_DOMAIN_EXCEEDED`, and makes the bootstrap test unavailable and the verdict ineligible. `bootstrap_status` is otherwise `available` or `no_trades`, separate from sample-count sufficiency. No trade or bootstrap-sample exclusion is used to rescue a result.

The **IID assumption is strong and usually questionable for strategy trades**: serial dependence, volatility clustering, regime change, overlapping selection and repeated research can invalidate the bootstrap interpretation. Resampling trades ignores holding-time variation, intratrade paths and calendar-time dependence. Permuting order preserves total compounded return and probes ordering drawdown only; it is not a return-significance test. Neither analysis establishes future profitability. No probabilistic Sharpe ratio (PSR), deflated Sharpe ratio, or selection-adjusted significance is calculated. `attempted_variants` only changes the disclosure from `unknown` to `not_estimated`.

Regime trend is `abs(ln(C_i)-ln(C_max(0,i-20)))`; thresholds are training medians on `[55,a)` for trend and available volatility. Trending/high means strictly greater than the corresponding median; equality belongs to sideways/lower. Each test bar is classified from its prior close. Attribute each complete trade to its prior-close regime at entry. Four cells report bar count, trade count, and mean simple trade return. A cell with fewer than 30 trades is `insufficient`; otherwise it remains `descriptive_only`, never a significance pass.

## Decision Policy

Reference eligibility requires caller-labeled historical data, available numeric analysis, at least 30 closed test trades and no bootstrap numeric-domain failure. Synthetic data, missing/small samples or bootstrap numeric-domain failure remain `UNPROVEN`, even if observed failures exist. When eligible, any failed rule yields `FRAGILE`; otherwise `SURVIVED_TESTS` means only survival of these bounded tests.

| Passing rule | Exact requirement |
| --- | --- |
| Test and validation returns | Both guarded returns > 0 |
| Guard improvement | Guarded test return strictly greater than baseline |
| Relative drawdown | Guarded test drawdown <= baseline |
| Absolute drawdown | Guarded test drawdown <= 15% |
| Cost stress | Return > 0 at requested maximum additional cost |
| Delay stress | Return > 0 for all delays 0 through 3 |
| Neighborhood | At least 5 of 9 returns > 0 |
| Bootstrap, when sufficient | Return p05 > 0 |
| Permutation, when sufficient | Drawdown p95 <= 15% |

These thresholds are explicit application policies, not statistically derived safety limits or citations-backed investment rules. A zero requested cost bound is permitted and weakens the experiment. Nexus mode is never eligible because the bound strategy is not replayed. Any reconciliation mismatch takes verdict precedence as `INCONSISTENT`; otherwise Nexus stays `UNPROVEN`. `FRAGILE`/`INCONSISTENT` produce a Failure Certificate, `UNPROVEN` an Evidence Limitation Certificate, and `SURVIVED_TESTS` a Survival Report. Failure observations are retained even when eligibility is absent.

## Nexus Reconciliation

Four sanitized surfaces are signal, metrics, equity and trades. Exact symbols are compared without normalization. BUY/SELL/HOLD presence is checked. Signal age is `as_of-timestamp` in Unix seconds, accepted inclusively in [0,900]. Without explicit caller `as_of`, certificate freshness is unavailable; a caller timestamp is not a trusted clock. Equity and trades must have identical run IDs. Metrics and signal have no documented run binding, so full run attestation is always insufficient.

All cross-surface quantitative comparisons (`TRADE_COUNT`, `WIN_RATE_PCT`, `PROFIT_FACTOR`, `TOTAL_RETURN_PCT`, `MAX_DRAWDOWN`, `PNL_EQUITY_CHANGE`) are **always `INSUFFICIENT_EVIDENCE`**, even when values agree or disagree. Metrics lack run binding; recent fills and sampled equity lack an attested complete, aligned window without cash flows. Count tolerance is 0; the other absolute tolerances are 0.01 in their respective units, including percentage points for returns/drawdown/win rate. Explanations distinguish unavailable arithmetic, agreement within tolerance, and discrepancy beyond tolerance. None of these numerical comparisons alone yields `MATCH`, `MISMATCH` or `INCONSISTENT`.

Wins/losses/breakevens count positive/negative/zero PnL. Gross profit sums positive PnL, gross loss negates the negative sum, total PnL sums all valid rows. Win rate is `100*wins/count`; currency-PnL profit factor is gross profit/gross loss, undefined with zero gross loss. Recomputed quantities remain descriptive summaries, not bound-strategy performance validation.

Equity needs at least two positive points and strictly increasing timestamps. Change is `last-first`; return is `100*(last/first-1)`; sampled drawdown is `max(100*(1-value/running_peak))`. Integrity of the sample can match without establishing completeness. Explicit signal/trade symbol contradictions and conflicting equity/trade run IDs still produce `MISMATCH`; freshness outside [0,900] also mismatches when an explicit `as_of` is available. Missing required values remain insufficient/unavailable. Fees, slippage, position closure, Sharpe methodology and out-of-sample performance remain unattested. `MATCH` denotes only its named structural or freshness check, never profit authentication.

Sanitization is a pure allowlist operation: offline reconciliation/verification does not read a local secret or depend on `NEXUS_API_KEY`. Only live ingestion explicitly supplies the key for additional redaction. Invalid rows are retained as empty records rather than silently dropping observations; they prevent unsupported arithmetic rather than creating a cleaner sample.

## Certificate Integrity

The certificate and verifier described below apply to challenge `Report`, not `WindowExperimentReport`. The latter is an allowlisted observation report, not an independently replayable remote-compute certificate.

Canonical JSON sorts string keys, uses ASCII-escaped strings, rejects depth >32 and nonfinite or absolute numbers >1e100, and normalizes numerically equivalent 1/1.0 and signed zero without rounding. SHA-256 content identity excludes `created_at`, `report_id` and `canonical_report_hash`; both report hashes must equal that digest. Creation time is therefore explicitly not checksum-bound. Dataset identity covers candles, not source authenticity.

Verification enforces the strict report schema, checksum, request references, deterministic reference replay or sanitized Nexus reconciliation, decision policy, disclosures, boundaries, matrix and certificate classification. Serialized duplicate keys are rejected; certificates are capped at 4,000,000 bytes with an additional canonical-length check. CLI returns 0 for valid, 1 otherwise. Verification makes no network call; timestamp and provenance syntax checks do not authenticate time, claimed commit, authorship or original market data. An adversary can fabricate internally consistent inputs and recompute a valid certificate. This is not a signature or attestation.

## Legacy Research

`app.research.research` is deprecated, not the certificate engine. It uses training `[51,a)`, volatility calibration `[50,a)`, currency wealth starting at 10,000, cost stresses at 1x/2x/3x, and rounded trade logs/equity. Its daily Sharpe is `mean(daily_simple_returns)/population_sd * sqrt(365)`, zero risk-free rate, undefined at zero deviation; bounded ratios above 1e12 are null. Currency-PnL profit factor uses rounded trade PnL. Win rate counts positive-PnL trades; exposure counts held bars; blocked days count intents rejected by the gate. Legacy `WAIT`/`PAPER_CANDIDATE` is not a current verdict or execution recommendation. Legacy hashes are not current canonical certificates. Do not silently migrate or relabel old reports.

## Provenance Contract

`Provenance` (`app/contracts.py`, generated by `app/provenance.py`) is a syntax-only build claim. `commit_reviewable=true` requires exactly 40 nonzero lowercase hexadecimal characters; `commit_reviewable=false` permits only the sentinel `commit="local-dev"`. `None`, empty strings, short commits such as `abc123`, all-zero SHAs, uppercase hex, and non-boolean flags are all rejected. Generation revalidates the process snapshot, so `model_construct` instances cannot bypass the contract. The offline verifier rejects rehashed reports carrying `commit_reviewable=true` with `commit="abc123"`. Reviewability never proves Git object existence, source authenticity, or build attestation.

## Nexus Window Stability

The window experiment (`app/nexus_compute.py`) is separate from the reference lab and the challenge certificate. It requires `ALPHALITMUS_ENABLE_NEXUS=true`, `ALPHALITMUS_ENABLE_NEXUS_BACKTEST=true`, an externally injected `NEXUS_API_KEY`, and literal JSON `confirm_compute: true`. Windows are 1-3 unique ascending integers in 20-500 (default `[100,250,500]`), executed largest-first with the largest as baseline. At most three sequential submissions occur, with no retries; one experiment per process; one-second poll sleeps; a total deadline of 5-60 s (default 30 s); an HTTP-call ceiling of `timeout_seconds + 15`; a 2,000,000-byte streamed per-response cap; identity encoding only; redirects disabled; and connect/write/pool timeouts of 5 s with read timeout 15 s.

`run_backtest` sends only `{"n_bars": n}`; `get_backtest_job` sends only the exact submitted `run_id`. `status == "completed"` is accepted as terminal solely on the documented hint "Call `get_backtest_job` until completed"; `queued`/`running` continue polling and any other status fails closed. Post-completion, the four documented read surfaces are fetched once per window. Equity/trade run IDs must equal the submitted ID or the report is `INCONSISTENT`. Metrics and signals lack documented run binding, so metric comparisons are descriptive only and the report can only be `UNPROVEN` or `INCONSISTENT`: `confirmed_counterexample=false`, `definitive_boundary_n_bars=null`, `baseline_survived=null`. `smallest_observed_failing_n_bars` is the minimum sampled window whose cached metrics show return <= 0, profit factor <= 1, or `NOT_QUALIFIED`, scoped to the sampled grid, not a global or causal boundary. Equity return/drawdown recomputation requires strictly increasing timestamps and positive values; the first observed point is not initial capital. Full upstream requests, quotas, and pending live evidence are in [window stability](NEXUS-WINDOW-STABILITY.md).

## Release-Gate Projection

`app/release_gate.py::project` converts a verified authoritative `Report` into a strict `ReleaseGateResult` without recomputation and without duplicating certificate/hash/policy verification. It first validates the source with the existing `app.certificates.verify_report`; any invalid certificate fails closed with a sanitized `REPORT_VERIFICATION_FAILED` error and no gate decision is issued. Exact mapping: `FRAGILE`→`BLOCK_DEPLOYMENT`, `INCONSISTENT`→`BLOCK_DEPLOYMENT`, `UNPROVEN`→`INSUFFICIENT_EVIDENCE`, `SURVIVED_TESTS`→`SURVIVED_BOUNDED_TESTS`; actions `BLOCK_DEPLOYMENT`→`DO_NOT_DEPLOY`, `INSUFFICIENT_EVIDENCE`→`COLLECT_MORE_EVIDENCE`, `SURVIVED_BOUNDED_TESTS`→`CONTINUE_PAPER_VALIDATION`. Reason codes, observed failures, and unavailable tests are sorted for deterministic ordering; the Report is never mutated. Successful results carry `report_id`, canonical hash, `no_execution:true`, `profitability_claimed:false`, `source_report_verified:true`, the complete `report`, and the disclaimer that it is not financial advice or deployment approval. Certificate verification replays the bounded reference/reconciliation calculations, so a release-gate call costs roughly one `challenge()` execution plus one verification replay; production `ChallengeRequest` execution still calls the challenge engine exactly once. Synthetic `synthetic_reference` reports remain `UNPROVEN` by the decision policy, hence `INSUFFICIENT_EVIDENCE`. REST (`POST /v1/release-gate`, `GET /v1/release-gate/demo/{mixed,shock}`) and MCP (`evaluate_strategy_release`) share `app.transport.run_release_gate`; unknown demo scenarios return 404 `UNKNOWN_SCENARIO`. REST invalid-source failures return only `{"detail":"REPORT_VERIFICATION_FAILED"}`; MCP surfaces only the same stable code.

## Recorded Nexus Replay

`app/recorded_nexus.py` loads only snapshot `candidate-v1` from `evidence/nexus-candidate-v1/` (`signal.json`, `metrics.json`, `equity.json`, `trades.json`, `manifest.json`). It rejects traversal/arbitrary IDs, bounds bytes/depth/rows/strings/numbers/file count, rejects duplicate keys, recomputes per-file and aggregate SHA-256, re-runs `app.nexus.sanitize` on every surface, verifies strategy/run/symbol/schema/flags/tools/limitations, never mutates input, and fails closed with `RECORDED_EVIDENCE_UNAVAILABLE`/`INVALID`/`INTEGRITY_FAILED` without exposing paths or raw errors. `replay_recorded_nexus_evidence()` injects the verified evidence into the existing `reconcile`/`_challenge_impl`/`project`/`verify_report` path, using the snapshot capture time as historical `as_of` and deterministic `created_at` via the internal-only `_challenge_impl` (public callers cannot choose timestamps). The result is byte-identical across calls, performs zero network calls, and embeds the authoritative `ReleaseGateResult` in strict `RecordedNexusReplay` (`alphalitmus-recorded-replay-1`). REST (`GET /v1/nexus/replay/candidate-v1`) and MCP (`replay_recorded_nexus_evidence`, strict empty args, `openWorldHint=false`) share `app.transport.run_recorded_replay`.

## Fixed Live Nexus Pulse

`app/live_nexus.py` permits only Candidate v1 (`str_b840280ce037`, `BTC/USDT`) and calls the four read-only Nexus surfaces through the existing bounded transport. Every surface must be received and carry a UTC fetch time no more than 120 seconds old at evaluation. The existing challenge, reconciliation, projection, and certificate verifier remain authoritative; no parallel trading decision engine exists. `LiveNexusResult` exposes per-surface freshness, a 60-second cache, upstream latency, exact live/historical/no-execution/profit flags, and the verified gate. It never invokes backtest, strategy mutation, order, wallet, or recorded replay paths. REST and MCP share `app.transport.run_live_nexus_candidate`; both reject caller-selected identity. Failure produces only bounded `LIVE_NEXUS_*` codes and no fallback result.

## References

- Efron, B. (1979), "Bootstrap Methods: Another Look at the Jackknife," *The Annals of Statistics* 7(1), 1-26. https://doi.org/10.1214/aos/1176344552. Foundational bootstrap reference, not validation of this application.
- Efron, B. and Tibshirani, R. J. (1993), *An Introduction to the Bootstrap*, Chapman & Hall. https://doi.org/10.1201/9780429246593. Background on bootstrap assumptions and uncertainty; does not justify IID strategy trades or the application's policy thresholds.
- Local implementation files listed above are the authority for exact formulas. Bibliographic citations are methodological context, not claimed external replication or profitability evidence.
