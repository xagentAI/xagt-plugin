# Structured sources and offline judging

Headlines trigger attention. Only structured observations or explicitly labeled
synthetic scenarios supply numeric event values. Adapters return the same
`MacroEvent` model, so sources remain replaceable without changing the arithmetic.

## Frankfurter with ECB provider filtering

- Purpose: current and historical FX reference rates; no key.
- Provider query explicitly selects ECB reference rates.
- Observation dates, the actual comparison window, retrieval time, source URL,
  and the transparent anomaly method travel with the event.
- Reference: [Frankfurter ECB provider](https://frankfurter.dev/providers/ecb/).

## European Central Bank policy rate

- Adapter: `PolicyRateProvider.policy_rate_move(lookback_days=30, mode="live_or_fixture")`.
- Source: [ECB deposit facility daily series](https://data.ecb.europa.eu/data/datasets/FM/FM.D.U2.EUR.4F.KR.DFR.LEV),
  series `FM.D.U2.EUR.4F.KR.DFR.LEV`.
- API: `https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV`.
  No authentication. Requests use `format=csvdata`, `startPeriod`, and `endPeriod`,
  as documented in [ECB API data examples](https://data.ecb.europa.eu/help/data-examples).
- Use the `D` daily levels; the `B` raw date-of-change series is sparse and does
  not provide daily comparison endpoints. Neither a sparse old change nor a news
  announcement is substituted for the requested observation window.
- Unit: percent per annum (`PCPA`); model unit `percent`. A move is
  `new − old` percentage points, or `100 × (new − old)` basis points.
  `change_pct` is deliberately null: a relative percentage is misleading when
  the old policy rate is zero or negative.
- Scope: euro area, affected currency EUR. The adapter does not apply this rate
  to a SEK mortgage or claim it measures every country's policy rate.

## U.S. Energy Information Administration: Brent

- Adapter: `EnergyProvider.oil_move(lookback_days=7, mode="live_or_fixture")`.
- Source: [Europe Brent spot-price history](https://www.eia.gov/dnav/pet/hist/RBRTED.htm).
- API: `https://api.eia.gov/v2/petroleum/pri/spt/data/`, `frequency=daily`,
  `data[0]=value`, `facets[series][]=RBRTE`. Legacy series ID: `PET.RBRTE.D`.
- [EIA API v2 documentation](https://www.eia.gov/opendata/documentation.php)
  specifies API-key authentication, date and facet filters, sorting, string
  numeric values, and a 5,000-row JSON limit. This bounded single-series query
  requests at most 394 calendar days, sorted by period, and rejects a response
  whose reported total differs from the returned row count.
- Live access needs an `EIA_API_KEY` environment variable (or an explicitly
  injected key). Register through [EIA Open Data](https://www.eia.gov/opendata/).
  Keys stay out of event metadata, source URLs, remote-payload echoes, and
  returned error messages. Error messages are locally controlled. Do not enable
  request-URL logging for keyed upstream calls in a deployment.
- Unit: US dollars per barrel. This is a crude-oil benchmark. Household fuel
  prices and pass-through remain separately supplied scenario inputs.

## Date selection and validation

Both new adapters accept integer lookbacks of 1–365 calendar days. They request
the lookback plus 28 days of padding. The newest published observation anchors
the comparison; the baseline is the last observation on or before that date
minus the requested lookback. Padding is never silently used as the baseline.
The baseline must be no more than 7 days before the target; the newest
observation must be no more than 14 days before the requested as-of date.
These tolerances handle weekends, holidays, and publication lag without
pretending that stale values are current. Actual dates, lag, target start, and
actual window length are explicit metadata.

Missing fields, unexpected series or units, missing/non-finite numbers,
duplicate dates, future observations, an absent baseline, and stale results
fail the live request. Brent prices must be positive for this percentage-move
adapter. Valid zero or negative policy rates are preserved. No live missing
observations are interpolated. UTC midnight encodes a date-only observation;
it is not claimed to be the publication time. `provenance.retrieved_at` is the
separate actual retrieval time.

## Fixture and fallback contract

| Mode | Behavior |
| --- | --- |
| `live` | Fetch official structured data; fail with a sanitized error if unavailable or invalid. |
| `fixture` | Make no network request; use the fixed synthetic judging scenario. |
| `live_or_fixture` | Try live, then return a visibly labeled synthetic scenario if the provider or key is unavailable. |

The JSON files under `source/life_exchange_rate/providers/data/` declare fixed
step scenarios, anchored to **2025-12-31**, covering all accepted lookbacks.
Policy levels are 3.00 then 3.25; Brent levels are 80 then 92. These are test
inputs, **not ECB or EIA historical observations**. Expanding the declared step
scenario creates deterministic daily test data only. It is never applied to
live gaps. Different requested windows may correctly produce an unchanged
synthetic value.

Fixture titles start with `Synthetic scenario`; `confidence=scenario`,
`source_type=synthetic_fixture`, and `metadata.synthetic=true`. They have no
official evidence/source URL. `fallback_used` and a sanitized `fallback_reason`
distinguish automatic fallback from explicitly requested fixtures. Original
fixture dates stay fixed; retrieval time and the attempted live as-of date are
separate. Consumers must display the fixture label and must not present these
events as current market data.

## Official RSS headline triggers

- [Federal Reserve monetary-policy RSS](https://www.federalreserve.gov/feeds/press_monetary.xml).
- [European Central Bank press RSS](https://www.ecb.europa.eu/rss/press.html).
- Each headline has `requires_quantification=true`. A headline may direct an
  agent to a compatible structured series; its text never supplies the rate,
  price, date-window move, wage, or household pass-through assumption.

## Source priority

1. Official structured statistical or central-bank observation.
2. Structured intermediary that identifies the official provider.
3. Explicit synthetic fixture for reproducible offline judging.
4. Explicit user-supplied event/scenario values.

Provider documentation and series definitions checked on 2026-09-14. Offline
tests use synthetic API-shaped responses; a passing mocked test is not a claim
that a keyed EIA live request was performed.
