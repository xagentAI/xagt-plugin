# Nexus Window Stability

Strategy-bound window experiment implemented in `app/nexus_compute.py`, exposed as `POST /v1/nexus/window-stability` and MCP `run_nexus_window_stability`. This is the only AlphaLitmus path that starts remote Nexus compute. It never places trades, signs anything, or accesses wallets. **No live call has been performed for this workspace; real validation remains pending an authorized strategy-bound key.**

## Gates

All four are required before any network call:

1. `ALPHALITMUS_ENABLE_NEXUS=true`
2. `ALPHALITMUS_ENABLE_NEXUS_BACKTEST=true`
3. `NEXUS_API_KEY` injected externally (printable ASCII, 1-512 characters)
4. Request field `confirm_compute` exactly JSON boolean `true`

With defaults, a valid request returns `UNPROVEN` with reason `NEXUS_COMPUTE_DISABLED` and performs no network call. With both switches on but no valid key, it returns `NEXUS_NOT_CONFIGURED`. Missing or non-`true` confirmation is a request-validation failure, never a silent default.

## Exact Requests

Only two Nexus tool calls are used, both `POST https://nexus.olaxbt.xyz/api/mcp/tools/call` with header `X-API-KEY`:

- `run_backtest` with `{"n_bars": <20-500 integer>}`. Requires a prior Studio Fire Backtest; deploy JSON is never accepted. Submissions are never retried.
- `get_backtest_job` with `{"run_id": <exact submitted ID>}`. Only the submitted ID is polled; the service's "latest job" is never used, and no `poll` URL from the service is followed.

After each job reaches `completed`, the four documented read surfaces (`get_strategy_signal`, `get_strategy_metrics`, `get_strategy_equity`, `get_strategy_trades`) are fetched once each per window.

## Terminal-State Assumption

The documented snapshot says only "Call `get_backtest_job` until completed" and shows a `running` example. `status == "completed"` is therefore accepted as the terminal marker; `queued` and `running` continue polling. Any other status fails closed with `NEXUS_UNKNOWN_JOB_STATE`. No completion metrics or additional completion fields are assumed.

## Window Grid and Bounds

- `windows`: 1-3 unique ascending integers, each 20-500. Default `[100, 250, 500]`; execution runs largest-first (500, 250, 100) with the largest as baseline.
- At most 3 submissions, strictly sequential, no retries including ambiguous transport failures.
- One experiment per process (`threading.Lock`, non-blocking; second caller gets `NEXUS_COMPUTE_BUSY`).
- Poll interval fixed at 1 second, with a sleep before every poll.
- Total experiment deadline: default 30 s, configurable 5-60 s; timeout yields a partial `UNPROVEN` report, never success.
- HTTP-call ceiling `timeout_seconds + 15` (45 default, 75 maximum); at most 12 evidence reads.
- Per-response cap 2,000,000 bytes streamed, identity encoding only, redirects disabled, environment proxies ignored, connect/write/pool 5 s and read 15 s.
- Duplicate JSON keys rejected at every decode layer. Cancellation propagates and releases the local lock.
- The lock cannot exclude Studio or other processes, and there is no documented remote-cancellation API: a timed-out local experiment may leave a remote job running.

## Evidence and Inference Limits

- The submitted `run_id` is preserved; every polled job, equity surface, and trades surface must carry that exact ID. Any contradiction is `NEXUS_RUN_ID_MISMATCH` and report status `INCONSISTENT`.
- Metrics and signals are cached strategy evidence with **no documented run binding**, so `metrics.binding` is always `unavailable`. Failure criteria (`total_return_pct <= 0`, `profit_factor <= 1`, `NOT_QUALIFIED`) are therefore descriptive observations only.
- Equity return/drawdown are recomputed from observed points only when timestamps strictly increase and all values are positive; the first observed point is not initial capital and cash flows are unattested.
- Drawdown has no failure threshold; qualification is a listing category, not independent profit evidence.
- The report can only be `UNPROVEN` or `INCONSISTENT`: `confirmed_counterexample` is always `false`, `definitive_boundary_n_bars` and `baseline_survived` are always `null`. `smallest_observed_failing_n_bars` is the minimum sampled window with an observed cached-metric failure, scoped `SAMPLED_GRID_ONLY_NOT_GLOBAL_OR_CAUSAL`.
- No fees, positions, trade notional, missing history, or selection-adjusted statistics are invented. No EMA result is applied to the Nexus strategy.

## Test Fixtures

All compute tests use mocked transports with explicitly synthetic/documentation-derived fixtures. They cover disabled/unconfirmed/missing-key paths with zero network calls, boundary `n_bars`, timeout, busy-lock, call-budget exhaustion, unknown job states, run-ID mismatch, oversized responses, duplicate keys, error sanitization, and cancellation propagation.

## Operational Requirements

Do not expose compute without an authenticated, rate-limiting TLS reverse proxy **and** explicit per-principal compute quotas plus a gateway-wide concurrency/submission limit across workers: the in-process lock is per process only, and each admitted experiment can trigger up to three remote backtests. See [THREAT-MODEL](THREAT-MODEL.md).

## What Still Requires the Real Invitation/Key

- An authorized Nexus account, a Studio strategy with a prior Fire Backtest, and a strategy-bound `NEXUS_API_KEY` injected at runtime.
- A live run of the default grid to observe (not to claim): per-window run IDs, completion behavior, evidence availability, and whether equity/trades IDs match submissions.
- Any claim beyond `UNPROVEN`/`INCONSISTENT` would additionally require documented metric/run/window binding, attested closed-trade history, and no-cash-flow proof, none of which the current snapshot provides.
