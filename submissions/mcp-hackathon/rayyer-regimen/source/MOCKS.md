# Real versus simulated

Where the line falls, drawn explicitly so nobody has to guess which numbers came from a
market and which came from a random number generator.

## Real, from a live third party

| Thing | Source | Notes |
|---|---|---|
| Strategy equity curve, trades, published metrics | OlaXBT Nexus `get_strategy_equity`, `get_strategy_trades`, `get_strategy_metrics` | Bound to the caller's own API key; one key resolves to one strategy. |
| Live trading intent | Nexus `get_strategy_signal` | |
| VIX, 10-year yield, effective fed funds | Nexus `get_macro`, with an explicit `as_of` | Point-in-time. |
| Perpetual funding rate | Nexus `get_historical_funding`, with `as_of` | Point-in-time. |
| Open interest and long/short ratio | Nexus `get_open_interest`, with `as_of` | Point-in-time. |
| Fear & Greed index | Nexus `get_fear_greed`, with `as_of` | Point-in-time. |
| Trend-template gate count | Nexus `get_vcp`, with `as_of` | Point-in-time. |

There is **no mock market data anywhere in the service**. If Nexus cannot be reached, the
affected factor is recorded as `null` with the failure noted, and the analysis proceeds
with the remaining factors rather than inventing a value. A missing funding rate and a
funding rate of zero are different facts and are never conflated.

## Simulated, and labelled as such wherever it appears

| Thing | What it is | Where it is used |
|---|---|---|
| Null-strategy population | Seeded Gaussian draws matched to the real series' length and volatility, with a true Sharpe of exactly zero | `/api/v1/self-attack`, to place the real result as a percentile against luck |
| Mean-centred control | The strategy's own returns with their sample mean subtracted | `/api/v1/self-attack`, as a control whose correct answer is known |
| Permutation labels | The real regime labels, randomly reshuffled with a seeded PRNG | The regime-map p-value |
| Bootstrap resamples | Stationary-bootstrap draws from the real return series | Sharpe confidence intervals |
| Evaluation suite | ~60 fully synthetic strategies with known ground truth | `EVAL.md` only. None of it touches a user-facing analysis. |

Every simulated quantity is seeded. Re-running with the same seed reproduces the same
number, which is why the intervals and p-values in this repository are quotable.

## Caching, and why it is not a mock

Point-in-time reads are immutable by construction — what the VIX closed at on a past date
does not change — so any read carrying a past `as_of` is cached and may be served from
memory on a later request. The response records this: every value carries a `provenance`
entry naming the upstream operation, the `as_of` key, when it was fetched, and whether it
came from cache. Live reads (signals, current metrics) are never cached.

## Credentials

The deployment can hold one Nexus key so that a reviewer with no OlaXBT account can still
exercise the Nexus-backed endpoints. When that key is in use the response says so:
`meta.mode` is `demo` rather than `byo_key`. Results in demo mode are real Nexus output for
the demo strategy — not synthetic — but they describe that strategy, not yours.
`GET /api/v1/status` reports whether a demo key is configured at all.
