# Live FX observation and anomaly method

The live adapter reads structured daily ECB reference rates through the
[Frankfurter v2 ECB provider route](https://frankfurter.dev/providers/ecb/).
The [official v2 documentation](https://frankfurter.dev/) was checked on
2026-09-14: provider routes support the same `base`, `quotes`, `from`, and `to`
parameters as `/v2/rates`. The dedicated route avoids the default blend of
multiple providers. There is no API key. These are reference observations,
not intraday prices or executable travel-money quotes.

## Selecting the observed move

`FrankfurterProvider.fx_move(base, quote, lookback_days=7)` validates inputs
before any HTTP request, including when called directly or through MCP.
Currencies are distinct three-letter ASCII codes (normalized to uppercase);
the calendar lookback is an integer from 2 through 90. Unsupported currency
codes are rejected by the upstream provider.

1. Query the UTC current date back by `2 * lookback_days + 380` calendar days.
   The additional history supports estimation; it is not the event window.
2. Select the latest returned observation date `new_date`.
3. Set the requested anchor to `new_date - lookback_days`.
4. Select the most recent observation on or before that anchor. Weekends and
   holidays can extend the actual event window. Never substitute the first
   observation in the historical query or shorten an unsupported window.
   Reject an anchor more than seven calendar days behind its requested date.
5. Keep `old_value`, `new_value`, and ordinary percentage change
   `100 * (new_value / old_value - 1)` for the deterministic impact engine.

For example, a latest Friday observation with a five-day requested lookback
targets Sunday. The previous Friday becomes the old observation, and both the
actual event and its volatility comparison use a seven-calendar-day horizon.
The requested dates, actual dates, anchor gap, observation age, retrieval time,
and exact query URL are preserved. Source dates are represented as midnight
UTC; these timestamps are not claims about the source's publication time.

## Volatility comparison

Let `H = new_date - old_date` in calendar days and `r_event = ln(new/old)`.
Construct historical log returns `r_t = ln(rate_t / rate_(t-H))` only where:

- Both exact calendar endpoints were actually observed; missing rates are
  neither interpolated nor forward-filled.
- The reference endpoint `t` is on or before `old_date`, so the selected event
  never enters its own baseline.

Use the latest at most 252 valid reference returns. With at least 30 samples
and sample standard deviation greater than `1e-12`, calculate:

```text
z = (r_event - mean(reference_returns)) / sample_standard_deviation(reference_returns)
sample_standard_deviation uses denominator n - 1
market_significance = min(100, abs(z) * 25), rounded to one decimal
```

This is a descriptive rolling score, not a forecast, normal-distribution tail
probability, or trading signal. Reference windows can overlap each other and
therefore are not independent samples. A large absolute score means the
observed move differs from the preceding equal-horizon returns, including
their mean; it does not directly measure its impact on the user's budget.

`metadata.anomaly` exposes the method, formula, effective horizon, sample count,
minimum/maximum count, reference date span, event return, mean, sample standard
deviation, overlap/missing-endpoint policies, signed score, and fallback reason.
`metadata.z_score` is present only when a finite estimate is available.

With fewer than 30 observations, the score is unavailable with reason
`insufficient_history`. Zero or negligible volatility produces
`zero_or_negligible_reference_volatility`, even if the event is large. In
either case the radar explicitly uses its existing
`fallback_fx_percent_move` method, `min(100, abs(change_pct) * 18)`, rather than
inventing a z-score. The available observations still determine the impact.

## Data quality and replaceability

The adapter rejects malformed dates, dates outside the accepted query range, missing or
mismatched currencies, nonpositive/nonfinite rates, malformed rows, conflicting
duplicates, insufficient event endpoints, and nonfinite percentage changes.
Identical same-date duplicates are collapsed and counted. No headline or LLM
supplies a numeric value. An observation older than seven days gets an explicit
provenance note; the exact age is always reported, including weekends. A latest
observation more than 14 calendar days old is rejected. A baseline more than
seven calendar days before the requested anchor is also rejected, so a gap in
the feed cannot silently turn a one-week request into a months-long event.

Frankfurter may backfill a weekend or holiday query start to the previous
reference observation. For example, the live request starting 2025-08-16
returned an observation dated 2025-08-15. The adapter retains up to seven
calendar days of this start padding and discloses `history_start_date` and
`pre_query_observation_count` separately from the requested dates. Earlier rows,
or any row after the requested end date, still cause rejection.

The constructor accepts a replacement `base_url`, an optional HTTP `transport`,
and an optional timezone-aware `now` callable. Deterministic tests use
`httpx.MockTransport` and a fixed UTC clock. This preserves the async provider
interface while supporting fixture replay and network-independent verification.
`tests/test_frankfurter.py` covers date selection, independently recalculated
scores, exclusion of the event from the baseline, missing history/volatility,
invalid inputs and responses, duplicate handling, stale latest observations,
excessive anchor gaps, and HTTP failures.
