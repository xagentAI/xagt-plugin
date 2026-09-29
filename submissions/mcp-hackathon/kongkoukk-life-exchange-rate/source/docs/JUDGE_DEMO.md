# 90-second judging demo

## 0–15 seconds: the problem

“Macro headlines are everywhere. What changes in my own budget?” Explain that headline text triggers attention while independent structured observations supply all arithmetic.

## 15–35 seconds: the radar

Run `uv run --frozen python -m life_exchange_rate.demo` or fetch `/v1/radar/demo`. Show the explicit sample profile, the three **synthetic** events, and separate significance/relevance scores. The Japan travel budget makes the SEK/JPY event relevant.

For a current-data demo use `uv run --frozen python verification/smoke_mcp.py --live-fx`. Open `verification/end-to-end-demo.json`: the selected event contains actual ECB-filtered FX observations, dates, query URL, and historical anomaly statistics. The separately fetched Fed headline is unrelated context used to prove the headline boundary; do not claim it caused the FX move. Other fixture cards remain labeled synthetic.

## 35–65 seconds: the impact

Select the SEK/JPY event and call `translate_event_to_life`, then `convert_to_life_units`. Show the cost of restoring the same Japan trip purchasing power, work hours and coffee/lunch equivalents. In the fixed offline scenario: **1,739.13 SEK = 8.70 work hours = 38.65 coffees = 12.42 lunches**. In live mode, read the captured computed amounts instead; never reuse the synthetic numbers as a live result.

## 65–80 seconds: inspect the calculation

Show old/new rates and source timestamps, user-supplied travel budget/income/prices, the formula trace, and the explicit FX fee exclusion. For rate/fuel examples show pass-through assumptions and currency scope. A EUR policy event does not directly price a SEK mortgage.

## 80–90 seconds: why MCP

“Any agent can call the same nine tools and explain the returned numbers without inventing market data or rebuilding the calculation logic.” Show recorded current/legacy protocol smoke results and the successful rejection of a headline-only translation request.
