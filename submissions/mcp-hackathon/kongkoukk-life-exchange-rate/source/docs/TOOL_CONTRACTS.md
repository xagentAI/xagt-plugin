# MCP and REST contracts

Canonical Streamable HTTP endpoint: `/mcp/`. MCP Python SDK v2 is retained; installed dependency versions are pinned in `uv.lock`.

| MCP tool | REST endpoint | Inputs / behavior |
| --- | --- | --- |
| `get_macro_events` | GET `/v1/events/demo` | `mode=demo`; three fixed, explicitly synthetic scenarios. |
| `get_official_macro_headlines` | GET `/v1/headlines/official` | `source=fed|ecb`, `limit=1..50`; headline triggers only. |
| `get_live_fx_event` | GET `/v1/events/fx` | MCP `base_currency`, `quote_currency`; REST `base`, `quote`; distinct three-letter codes, `lookback_days=2..90` (default 7). Live official reference observations plus transparent anomaly metadata. |
| `get_policy_rate_event` | GET `/v1/events/policy-rate` | ECB euro-area deposit rate; `lookback_days=2..365` (default 30), `mode=live|fixture|live_or_fixture`. |
| `get_energy_event` | GET `/v1/events/energy` | EIA Brent daily spot; `lookback_days=2..365` (default 7), same modes. |
| `rank_events_for_user` | POST `/v1/radar/rank` | Structured `events`, `profile`; returns significance, relevance, method and reasons. |
| `translate_event_to_life` | POST `/v1/translate` | Structured `event`, `profile`, optional `assumptions`; deterministic impact with provenance and trace. |
| `convert_to_life_units` | POST `/v1/convert` | `amount`, `currency`, `profile`; requires home currency, uses declared income and prices. |
| `compare_event_scenarios` | POST `/v1/scenarios` | MCP multipliers (default 0.5, 1.5) plus baseline 1.0; REST named `scenarios`; optional `assumptions`. All outputs are scenarios, never forecasts. |

## Numeric boundary

Events require old/new numeric values, event type, unit and identifiers. FX/oil rates must be positive and finite; `change_pct`, when supplied, must agree with the derived change within 0.0001 percentage points. Missing FX/oil percentages are derived from old/new values. Policy rate units are `percent`; explicit matching `affected_currencies` are required to calculate rate impact. Timestamps include a timezone. Headline-only objects are rejected by validation.

`ImpactAssumptions` defaults are explicitly declared illustrative choices: `interest_rate_pass_through=0.5`, `oil_to_fuel_pass_through=0.25`, each bounded from 0 to 1. Both REST and MCP callers can override them. Life-unit prices in another currency are excluded; no FX conversion or local price is invented.

Money carries a signed direction; work and life-unit equivalents use its magnitude. FX travel has a one-off horizon. Mortgage/savings and fuel outputs have a monthly scenario horizon and must not be added to one-off travel costs without a stated period.

## Provider modes and errors

`fixture` makes no request; `live` returns only observed data or an error; `live_or_fixture` may return synthetic data with `metadata.fallback_used` and a sanitized reason. Synthetic events retain fixed source dates, while adapter retrieval timestamps record the actual read. They never claim an official evidence URL. EIA keys remain in environment variables and are omitted from output URLs/errors.

REST invalid inputs return 422; upstream failures return sanitized 502 responses. MCP returns tool errors for invalid input or unavailable live data. Clients must check `is_error` and must not replace unavailable observations with invented values.
