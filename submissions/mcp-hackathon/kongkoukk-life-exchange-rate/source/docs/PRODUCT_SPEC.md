# Life Exchange Rate — product spec v0.2

## Product thesis

**Every headline has a price. See yours.**

Life Exchange Rate is not a macro-news summarizer. It is a personal macro-impact engine: it detects or receives a quantified macro event, checks whether the user is exposed to it, and converts the impact into money, work time, and user-defined everyday units.

## The key UX distinction

A **headline** is a trigger, not a number. Example: “Fed issues FOMC statement.” The system must not infer a 25 bp move from the title. It retrieves/receives a structured numeric event separately, then performs the life-impact calculation.

This avoids the most dangerous demo failure: an LLM inventing market numbers from news text.

## MVP user flow

1. User supplies a minimal life profile: home currency/country, net income, work hours, optional travel budget/target currency, mortgage/savings, fuel use, and optional life-unit prices.
2. Macro Event Radar retrieves structured market events and official central-bank headlines.
3. Events are ranked by **market significance** and **user relevance**.
4. The user or Agent selects one event.
5. `translate_event_to_life` returns a deterministic impact, assumptions, warnings, and calculation trace.
6. The Agent explains the result in plain language without changing the numbers.

## MVP event categories

- FX movement → travel purchasing power.
- Policy-rate change → mortgage/savings scenario, only when currency exposure matches.
- Brent/oil movement → driving-cost scenario with explicit pass-through assumption.

## Non-goals for v0.2

- Personalized investment advice.
- Predicting future FX/rates/oil.
- Inferring a numerical policy move solely from a headline.
- Modeling cross-border monetary-policy spillovers.
- Pretending crude oil maps one-for-one to pump prices.
