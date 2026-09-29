# 2026-07-26 Service Depth Upgrade

Leo's feedback was correct: several paid surfaces were too shallow in ways that could look confident while missing the actual market structure.

## What was shallow

- Scenario discovery ranked same-category volume too heavily, so specific entity queries could drift into unrelated high-volume markets.
- Macro Fed readouts detected the category but stayed L0/core-only, leaving rate-decision buckets unparsed.
- Football L1 treated all football markets like match cards, which made season/cup outright markets look like incomplete home/draw/away matrices.

## What deepened

- Added semantic entity matching for scenario discovery (`pm-semantic-match.mjs`), including modest aliases for teams, players, cities, and Fed/FOMC terms. Entity-looking queries now require strong candidate overlap before selection or category fallback.
- Added a Macro Fed L1 plugin that parses hold/cut/hike brackets, builds a yes-price leaderboard, estimates implied expected move when enough brackets exist, and reports missing brackets plus coherence residuals.
- Split football depth into `match` vs `outright_season`. Outrights now return a team-winner leaderboard and thesis; incomplete match cards name the missing groups blocking a state map.

## Guardrails preserved

- No SKU count expansion.
- No orders, bankroll, scraping, or onchain mutation.
- Category defaults remain available for generic queries, but no longer override a specific wrong-entity query.

## Follow-up 2026-07-26b
- Filter Polymarket Team A/B/Other ghost outright rows from football/NBA leaderboards.
- Match-card discovery prefers match surface over season winner when available.
