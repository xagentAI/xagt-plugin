// Macro Fed rate-decision category plugin (L1) for PM Event Readout.
// Parses FOMC decision brackets into a priced ladder; no scraping, no orders.

import { round2 } from './pm-gamma-market.mjs';

const EXPECTED_BUCKETS = ['hold', 'cut_25', 'hike_25'];

/**
 * @param {object} args
 * @param {object} args.market
 * @param {object|null} args.eventBundle
 * @param {object[]} args.eventMatrix
 */
export function enrichMacroFedCategory({ market, eventBundle, eventMatrix }) {
  const rows = (eventMatrix || []).map((row) => ({
    ...row,
    bucket: classifyRateDecisionBucket(row)
  }));
  const classified = rows.filter((row) => row.bucket.kind !== 'other');
  const leaderboard = classified
    .filter((row) => Number.isFinite(row.yes))
    .map((row) => ({
      bucket: row.bucket.id,
      direction: row.bucket.direction,
      move_bps: row.bucket.move_bps,
      label: row.group_item_title || row.title || row.slug || row.bucket.id,
      yes: row.yes,
      slug: row.slug,
      is_primary: row.is_primary === true
    }))
    .sort((a, b) => b.yes - a.yes);

  const bucketIds = new Set(classified.map((row) => row.bucket.id));
  const missing_brackets = EXPECTED_BUCKETS.filter((bucket) => !bucketIds.has(bucket));
  if (!classified.some((row) => row.bucket.direction === 'cut')) missing_brackets.push('any_cut');
  if (!classified.some((row) => row.bucket.direction === 'hike')) missing_brackets.push('any_hike');

  const yesMass = leaderboard.reduce((sum, row) => sum + (row.yes || 0), 0);
  const expectedMove = buildExpectedMove(leaderboard);
  const leader = leaderboard[0] || null;
  const runner = leaderboard[1] || null;
  const ladder_status = leaderboard.length >= 3
    ? (missing_brackets.length ? 'partial_rate_ladder' : 'rate_ladder')
    : (leaderboard.length >= 2 ? 'thin_rate_pair' : 'thin');

  const residuals = [];
  if (yesMass > 1.15) {
    residuals.push({
      type: 'yes_mass_over_one',
      note: `Fed decision yes-mass sums to ≈${round2(yesMass)}; brackets may overlap or include nested definitions.`
    });
  }
  if (leader && runner && leader.yes - runner.yes < 0.05 && leader.yes > 0.30) {
    residuals.push({
      type: 'tight_rate_leaderboard',
      note: 'Top two decision buckets are tightly priced; thesis should stay bracket-aware.'
    });
  }
  if (missing_brackets.includes('hold')) {
    residuals.push({
      type: 'missing_hold_bracket',
      note: 'No hold/no-change bracket found, so cut/hike mass cannot be centered cleanly.'
    });
  }

  const central_thesis = leader
    ? `Fed ladder leads "${leader.label}" at yes≈${leader.yes}`
      + (runner ? ` vs "${runner.label}" ≈${runner.yes}` : '')
      + (expectedMove.status === 'estimated' ? `; implied expected move ≈${expectedMove.expected_move_bps} bps.` : '.')
    : `Insufficient Fed decision brackets for a central thesis; missing ${missing_brackets.join(', ') || 'priced buckets'}.`;

  return {
    category: 'macro_fed',
    category_depth: 'enriched',
    primary_event_slug: eventBundle?.primary_event_slug || eventBundle?.slug || null,
    related_market_count: rows.length,
    ladder_status,
    missing_brackets,
    leaderboard: leaderboard.slice(0, 10),
    yes_mass_sum: round2(yesMass),
    implied_expected_move: expectedMove,
    market_implied_shape: {
      leader: leader ? { bucket: leader.bucket, label: leader.label, yes: leader.yes, move_bps: leader.move_bps } : null,
      runner_up: runner ? { bucket: runner.bucket, label: runner.label, yes: runner.yes, move_bps: runner.move_bps } : null,
      central_thesis
    },
    coherence: {
      coherence_status: residuals.length ? 'tension' : (ladder_status === 'thin' ? 'incomplete_matrix' : 'ok_heuristic'),
      cross_market_residuals: residuals
    },
    central_thesis,
    default_action_hint: ladder_status === 'thin' ? 'no_trade' : 'use_decision_card_after_macro_definition_check',
    tradability_cap: ladder_status === 'thin' ? 'weak' : null,
    tradability_reasons: ladder_status === 'thin' ? ['macro_fed_ladder_thin'] : [],
    hard_gate: 'no_orders_no_account_mutation_no_macro_scrape',
    skill_alignment: {
      source: 'macro_fed_rate_decision_l1',
      included: ['rate_decision_bucket_parse', 'yes_price_leaderboard', 'expected_move_heuristic', 'coherence_residuals'],
      excluded_local_only: ['live_cme_fedwatch_scrape', 'bankroll', 'news_scrape']
    }
  };
}

export function classifyRateDecisionBucket(row) {
  const text = `${row.group_item_title || ''} ${row.title || ''} ${row.slug || ''}`.toLowerCase();
  if (/no change|unchanged|hold|leave (?:rates|interest rates)|keeps? (?:rates|interest rates)/.test(text)) {
    return { id: 'hold', kind: 'rate_decision', direction: 'hold', move_bps: 0 };
  }

  const bps = extractBps(text);
  if (/decrease|cut|lower|reduc/.test(text) || /-\s*\d+\s*bps/.test(text)) {
    const move = bps || 25;
    return { id: `cut_${move}`, kind: 'rate_decision', direction: 'cut', move_bps: -move };
  }
  if (/increase|hike|raise/.test(text) || /\+\s*\d+\s*bps/.test(text)) {
    const move = bps || 25;
    return { id: `hike_${move}`, kind: 'rate_decision', direction: 'hike', move_bps: move };
  }
  if (/\b\d+\s*bps\b/.test(text)) {
    return { id: `other_${bps}`, kind: 'other_rate_bracket', direction: 'other', move_bps: bps };
  }
  return { id: 'other', kind: 'other', direction: 'other', move_bps: null };
}

function buildExpectedMove(leaderboard) {
  const exact = leaderboard.filter((row) => Number.isFinite(row.move_bps) && Number.isFinite(row.yes));
  const hasHold = exact.some((row) => row.move_bps === 0);
  const hasCutOrHike = exact.some((row) => row.move_bps !== 0);
  if (exact.length < 3 || !hasHold || !hasCutOrHike) {
    return {
      status: 'insufficient_brackets',
      expected_move_bps: null,
      bracket_count: exact.length,
      note: 'Need hold plus multiple cut/hike brackets for a useful expected-move heuristic.'
    };
  }
  const mass = exact.reduce((sum, row) => sum + row.yes, 0);
  if (mass <= 0) {
    return { status: 'insufficient_brackets', expected_move_bps: null, bracket_count: exact.length };
  }
  const weighted = exact.reduce((sum, row) => sum + row.yes * row.move_bps, 0) / mass;
  return {
    status: 'estimated',
    expected_move_bps: round2(weighted),
    bracket_count: exact.length,
    method: 'yes_price_weighted_rate_brackets_not_cme'
  };
}

function extractBps(text) {
  const m = String(text).match(/(\d{1,3})\s*(?:bps|bp|basis points?)/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}
