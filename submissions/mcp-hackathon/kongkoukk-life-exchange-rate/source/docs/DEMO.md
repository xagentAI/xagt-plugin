# Demo script

Use the included sample profile: a SEK-based user with a Tokyo travel budget, mortgage, savings, fuel use, and prices for beer/coffee/lunch.

## Demo 1 — Yen move

Prompt to the agent:

> The yen strengthened sharply. I live in Sweden and have 20,000 SEK set aside for Tokyo. What changed for me?

Expected flow:

`get_macro_events` or `get_live_fx_event` → `translate_event_to_life` → explanation.

Show: extra SEK required to restore the old JPY purchasing power, work-hours equivalent, and everyday-unit equivalents.

## Demo 2 — Rate move

> If the policy rate rises by 25 bp, what might that mean for my mortgage and savings?

Show: scenario-labelled pass-through, payment change, savings offset, warnings.

## Demo 3 — Oil spike

> Brent is up 15%. What could that mean for my monthly driving cost?

Show: scenario range rather than a false one-to-one forecast.
