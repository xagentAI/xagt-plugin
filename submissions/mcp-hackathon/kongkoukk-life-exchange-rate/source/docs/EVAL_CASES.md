# Eval / edge-case matrix

These cases should remain true when the Agent layer is added.

| Case | Expected behavior |
| --- | --- |
| SEK user + JPY travel budget + SEK/JPY shock | Quantify travel purchasing-power impact. |
| SEK user + USD Fed rate move + SEK mortgage | Do **not** mechanically apply the Fed move to the SEK mortgage. Explain that cross-border spillovers are outside the MVP. |
| FX shock but no travel budget | Mark relevant but unquantified; request the missing exposure. |
| FX pair does not match travel target currency | Do not produce a travel-cost number. |
| Oil shock but no fuel-use profile | Return an unquantified result, not an invented commute estimate. |
| Policy-rate event with matching currency + mortgage | Return a scenario estimate with explicit pass-through assumption. |
| News headline contains “rate hike” but no numeric observation | Keep it as a headline trigger; do not invent basis points. |
| Same event/profile/assumptions repeated | Deterministic numeric output should match. |
