// Politics / election ladder plugin (L1) for PM Event Readout.
// Binary + multi-candidate yes-mass surface; no scrape, no orders.

import { round2 } from './pm-gamma-market.mjs';

/**
 * @param {object} args
 * @param {object} args.market
 * @param {object|null} args.eventBundle
 * @param {object[]} args.eventMatrix
 */
export function enrichPoliticsCategory({ market, eventBundle, eventMatrix }) {
  const rows = (eventMatrix || []).map((row) => ({
    label: row.group_item_title || row.title || row.slug || 'unknown',
    slug: row.slug,
    yes: row.yes,
    no: row.no,
    volume_24h_usd: row.volume_24h_usd,
    best_ask: row.best_ask,
    best_bid: row.best_bid,
    spread: row.spread,
    is_primary: row.is_primary === true
  }));

  const ranked = rows
    .filter((r) => Number.isFinite(r.yes))
    .slice()
    .sort((a, b) => b.yes - a.yes);

  const yesSum = ranked.reduce((sum, r) => sum + (r.yes || 0), 0);
  const leader = ranked[0] || null;
  const runner = ranked[1] || null;
  const ladder_status = ranked.length >= 3 ? 'multi_candidate' : (ranked.length === 2 ? 'binary_or_pair' : 'thin');

  const residuals = [];
  if (yesSum > 1.15) {
    residuals.push({
      type: 'yes_mass_over_one',
      note: `Sum of yes prices ≈ ${round2(yesSum)} — overlapping/non-exclusive outcomes or nested markets.`
    });
  }
  if (leader && runner && leader.yes - runner.yes < 0.05 && leader.yes > 0.35) {
    residuals.push({
      type: 'tight_leaderboard',
      note: 'Top two candidates nearly tied — watch liquidity and nested contract definitions.'
    });
  }

  const primaryYes = market?.yes ?? leader?.yes ?? null;
  const central_thesis = leader
    ? `Market mass leads "${leader.label}" at yes≈${leader.yes}`
      + (runner ? ` vs "${runner.label}" ≈${runner.yes}` : '')
      + '.'
    : 'Insufficient priced candidates for a politics thesis.';

  return {
    category: 'politics',
    category_depth: 'enriched',
    primary_event_slug: eventBundle?.primary_event_slug || eventBundle?.slug || null,
    related_market_count: rows.length,
    ladder_status,
    yes_mass_sum: round2(yesSum),
    leaderboard: ranked.slice(0, 8).map((r) => ({
      label: r.label,
      yes: r.yes,
      share_of_yes_mass: yesSum > 0 ? round2(r.yes / yesSum) : null,
      slug: r.slug,
      is_primary: r.is_primary
    })),
    market_implied_shape: {
      leader: leader ? { label: leader.label, yes: leader.yes } : null,
      runner_up: runner ? { label: runner.label, yes: runner.yes } : null,
      primary_yes: primaryYes,
      central_thesis
    },
    coherence: {
      coherence_status: residuals.length ? 'tension' : (ladder_status === 'thin' ? 'incomplete_matrix' : 'ok_heuristic'),
      cross_market_residuals: residuals
    },
    default_action_hint: ladder_status === 'thin' ? 'no_trade' : 'use_decision_card_after_definition_check',
    tradability_cap: ladder_status === 'thin' ? 'weak' : null,
    tradability_reasons: ladder_status === 'thin' ? ['politics_ladder_thin'] : [],
    hard_gate: 'no_orders_no_account_mutation_no_polling_scrape',
    skill_alignment: {
      source: 'prediction-copilot_politics_surface_lite',
      included: ['candidate_yes_mass_leaderboard', 'yes_mass_sanity', 'definition_caution'],
      excluded_local_only: ['poll_aggregation', 'bankroll', 'news_scrape']
    }
  };
}
