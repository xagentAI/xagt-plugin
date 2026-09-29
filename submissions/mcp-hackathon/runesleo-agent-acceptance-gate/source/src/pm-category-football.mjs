// Football match category plugin (L1) for PM Event Readout.
// Aligns to pm-football-match skill (exportable parts only).
// Quality bar: research/2026-07-09-hackathon-quality-bar.md
// No Leo bankroll/sizing/orders. Fixture must be honest.

import { round2 } from './pm-gamma-market.mjs';

/**
 * Cross-market residual cutoffs, hoisted 2026-07-30.
 *
 * These were inline magic numbers. They are not wrong — labelling a market as
 * "draw heavy" does need a cutoff — but a buyer paying per call could not see why
 * 0.55 rather than 0.6, and could not tell a tuned threshold from a typo. The
 * repo already has the better pattern: crypto-market-regime declares its weights
 * and normalisation scales so they surface in the response and can be audited.
 * Same treatment here: named, commented, echoed back on every residual via
 * `triggered_by`, and exported so a caller can read the ruleset before trusting it.
 *
 * Values are unchanged from the inline versions — this is a disclosure change, not
 * a retune. Retuning needs settled-match backtesting, which this service does not do.
 */
export const CROSS_MARKET_RESIDUAL_THRESHOLDS = Object.freeze({
  /** Both moneyline sides below this = neither side is favoured. */
  ml_side_short: 0.35,
  /** Draw priced above this while both sides are short = draw-heavy shape. */
  ml_draw_elevated: 0.3,
  /** Over 2.5 above this reads as a high-scoring market. */
  over25_rich: 0.62,
  /** …but only counts as tension when the best moneyline side stays under this. */
  ml_max_side_tight: 0.4,
  /** BTTS Yes above this is rich. */
  btts_rich: 0.6,
  /** …and conflicts when Over 2.5 sits below this. */
  over25_subdued: 0.45
});

const REQUIRED_GROUPS = [
  'moneyline_90m',
  'totals_ladder',
  'spreads_ladder',
  'btts',
  'team_totals'
];

/**
 * @param {object} args
 * @param {object} args.market
 * @param {object|null} args.eventBundle  may include sibling_event_slugs
 * @param {object[]} args.eventMatrix
 * @param {object} [args.fixture] caller-provided verification
 */
export function enrichFootballCategory({ market, eventBundle, eventMatrix, fixture = null }) {
  const classified = (eventMatrix || []).map((row) => ({
    ...row,
    market_group: classifyFootballGroup(row)
  }));

  const marketType = detectFootballMarketType({ market, eventBundle, eventMatrix: classified });
  if (marketType === 'outright_season') {
    return buildFootballOutrightCategory({ market, eventBundle, classified });
  }

  const groups = groupBy(classified, (row) => row.market_group);
  const missing = [];
  for (const key of REQUIRED_GROUPS) {
    if (!groups[key]?.length) missing.push(key);
  }

  // Knockout often has advance on sibling — note if absent
  if (!groups.advance?.length) missing.push('advance_or_match_winner_optional');

  const requiredMissing = missing.filter((m) => !m.endsWith('_optional'));
  const matrix_status = requiredMissing.length ? 'incomplete' : 'complete';

  const moneyline = summarizeMoneyline(groups.moneyline_90m || []);
  const totals = summarizeLadder(groups.totals_ladder || [], 'totals');
  const spreads = summarizeLadder(groups.spreads_ladder || [], 'spreads');
  const btts = firstYes(groups.btts);
  const advance = firstYes(groups.advance);
  const teamTotals = summarizeTeamTotals(groups.team_totals || []);

  const fixtureGate = evaluateFixtureGate(market, eventBundle, fixture);
  const shape = buildImpliedShape({ moneyline, totals, spreads, btts, advance, teamTotals, missing_market_groups: missing });
  const expressions = buildExpressionComparison({ moneyline, totals, spreads, btts, advance, shape });
  const hard_veto_gaps = buildFootballHardVetoGaps({
    requiredMissing,
    fixtureGate,
    moneyline,
    totals,
    expressions
  });
  const matrix_completeness = {
    status: matrix_status,
    required_groups: REQUIRED_GROUPS,
    required_present: REQUIRED_GROUPS.filter((g) => (groups[g] || []).length > 0),
    required_missing: requiredMissing,
    hard_veto_gaps
  };

  let tradability_cap = null;
  const tradability_reasons = [];
  if (fixtureGate.fixture_status !== 'ok') {
    tradability_cap = 'weak';
    tradability_reasons.push('fixture_unverified_or_failed');
  }
  if (matrix_status === 'incomplete') {
    tradability_cap = tradability_cap || 'medium';
    tradability_reasons.push('football_matrix_incomplete');
  }
  if (hard_veto_gaps.length) {
    tradability_cap = 'weak';
    tradability_reasons.push('football_hard_veto_gaps');
  }

  const default_action_hint = hard_veto_gaps.length || fixtureGate.fixture_status !== 'ok' || matrix_status === 'incomplete'
    ? 'no_trade'
    : 'use_decision_card_after_expression_comparison';

  // Full dump of player_props (often 200+) blows payload; keep count + sample.
  const SURFACE_FULL = new Set([
    'moneyline_90m', 'totals_ladder', 'spreads_ladder', 'btts', 'team_totals',
    'advance', 'first_half', 'second_half', 'extra_time', 'penalty_shootout',
    'exact_score', 'corners', 'first_to_score'
  ]);
  const market_surface = {};
  for (const [key, rows] of Object.entries(groups)) {
    if (SURFACE_FULL.has(key)) {
      market_surface[key] = rows.map(compactRow);
    } else if (key === 'player_props') {
      market_surface.player_props_sample = rows.slice(0, 8).map(compactRow);
    } else {
      market_surface[key] = rows.slice(0, 12).map(compactRow);
    }
  }

  return {
    category: 'football',
    category_depth: 'enriched',
    market_type: 'match',
    primary_event_slug: eventBundle?.primary_event_slug || eventBundle?.slug || null,
    sibling_event_slugs: eventBundle?.sibling_event_slugs || [],
    linked_event_count: eventBundle?.linked_event_count
      ?? (1 + (eventBundle?.sibling_event_slugs?.length || 0)),
    discovery: eventBundle?.discovery || null,
    related_market_count: classified.length,
    group_counts: Object.fromEntries(
      Object.entries(groups).map(([key, rows]) => [key, rows.length])
    ),
    matrix_status,
    matrix_completeness,
    hard_veto_gaps,
    missing_market_groups: missing,
    market_surface,
    market_implied_shape: shape,
    fixture: fixtureGate,
    expression_comparison: expressions,
    recommended_expression: expressions.recommended || null,
    default_action_hint,
    tradability_cap,
    tradability_reasons,
    central_thesis: shape.central_thesis,
    coherence: buildFootballCoherence({ moneyline, totals, spreads, btts, shape, matrix_status }),
    hard_gate: 'no_orders_no_account_mutation_no_leo_bankroll',
    skill_alignment: {
      source: 'pm-football-match',
      included: [
        'fixture_gate',
        'full_same_event_matrix_via_parent_event_id',
        'missing_market_groups',
        'matrix_completeness',
        'hard_veto_gaps',
        'market_implied_shape',
        'expression_comparison',
        'adjacent_ladder_context',
        'thesis_expression_coherence',
        'heuristic_coherence_and_top_scorelines'
      ],
      excluded_local_only: [
        'bankroll_pct',
        'u_amount_from_latest_anchor',
        'playbook_card_writeback',
        'personal_exposure',
        'full_player_props_dump',
        'full_joint_poisson_engine'
      ]
    }
  };
}

function buildFootballHardVetoGaps({ requiredMissing, fixtureGate, moneyline, totals, expressions }) {
  const gaps = [];
  if (fixtureGate?.fixture_status && fixtureGate.fixture_status !== 'ok') {
    gaps.push(`fixture_${fixtureGate.fixture_status}`);
  }
  if (requiredMissing.includes('moneyline_90m') || !moneyline?.home) {
    gaps.push('missing_moneyline_90m');
  }
  for (const key of requiredMissing) {
    if (key === 'moneyline_90m') continue;
    gaps.push(`missing_${key}`);
  }
  const ladderCount = expressions?.ladder_context?.totals_ladder_count ?? totals?.lines?.length ?? 0;
  if (ladderCount < 2) {
    gaps.push('totals_ladder_thin_or_missing');
  }
  return [...new Set(gaps)];
}

function buildFootballCoherence({ moneyline, totals, spreads, btts, shape, matrix_status }) {
  const residuals = [];
  const top_scorelines = [];

  const home = moneyline?.home?.yes ?? null;
  const draw = moneyline?.draw?.yes ?? null;
  const away = moneyline?.away?.yes ?? null;
  const over25 = totals?.lines?.find((x) => Number(x.line) === 2.5)?.yes
    ?? totals?.pivot?.yes
    ?? null;
  const bttsYes = btts?.yes ?? null;

  const T = CROSS_MARKET_RESIDUAL_THRESHOLDS;

  if (home != null && away != null && home < T.ml_side_short && away < T.ml_side_short
      && draw != null && draw > T.ml_draw_elevated) {
    residuals.push({
      type: 'ml_draw_heavy',
      note: 'Both sides short-priced with elevated draw — check if totals/spreads agree.',
      triggered_by: `home<${T.ml_side_short} && away<${T.ml_side_short} && draw>${T.ml_draw_elevated}`
    });
  }
  if (over25 != null && over25 > T.over25_rich && home != null && away != null
      && Math.max(home, away) < T.ml_max_side_tight) {
    residuals.push({
      type: 'totals_vs_ml_tension',
      note: 'Market prices high Over 2.5 while ML looks tight — possible expression conflict.',
      triggered_by: `over2.5>${T.over25_rich} && max(home,away)<${T.ml_max_side_tight}`
    });
  }
  if (bttsYes != null && over25 != null && bttsYes > T.btts_rich && over25 < T.over25_subdued) {
    residuals.push({
      type: 'btts_vs_totals_tension',
      note: 'BTTS Yes rich vs subdued Over — review ladder consistency.',
      triggered_by: `btts>${T.btts_rich} && over2.5<${T.over25_subdued}`
    });
  }

  // Illustrative scoreline ranks from crude ML weights (not calibrated Poisson).
  const weights = [
    { scoreline: '1-0', w: home != null ? Math.max(0.01, home) * 0.55 : 0.1 },
    { scoreline: '2-1', w: home != null ? Math.max(0.01, home) * 0.35 : 0.08 },
    { scoreline: '0-0', w: draw != null ? draw * 0.55 : 0.1 },
    { scoreline: '1-1', w: draw != null ? draw * 0.45 : 0.1 },
    { scoreline: '0-1', w: away != null ? Math.max(0.01, away) * 0.55 : 0.1 },
    { scoreline: '1-2', w: away != null ? Math.max(0.01, away) * 0.35 : 0.08 }
  ];
  const sum = weights.reduce((a, b) => a + b.w, 0) || 1;
  for (const row of weights.sort((a, b) => b.w - a.w).slice(0, 5)) {
    top_scorelines.push({
      scoreline: row.scoreline,
      approx_mass: round2(row.w / sum),
      method: 'heuristic_ml_weights_not_poisson'
    });
  }

  const coherence_status = residuals.length
    ? 'tension'
    : (matrix_status === 'complete' ? 'ok_heuristic' : 'incomplete_matrix');

  return {
    coherence_status,
    cross_market_residuals: residuals,
    top_scorelines,
    distribution_note: 'Not a full joint_score_distribution_90m; use as triage only.',
    market_implied_shape_ref: shape?.central_thesis ?? null,
    spreads_present: Boolean(spreads?.count || spreads?.lines?.length),
    // Ship the ruleset with the verdict so the buyer can audit the cutoffs.
    residual_thresholds: { ...CROSS_MARKET_RESIDUAL_THRESHOLDS }
  };
}

export function extractFootballFixture(input = {}, options = {}) {
  if (options.footballFixture && typeof options.footballFixture === 'object') {
    return options.footballFixture;
  }
  const raw = input.football && typeof input.football === 'object'
    ? input.football
    : (input.fixture && typeof input.fixture === 'object' ? input.fixture : null);
  if (!raw) return null;
  return {
    requested_window: raw.requested_window ?? raw.window ?? null,
    scheduled_time_utc: raw.scheduled_time_utc ?? raw.kickoff_utc ?? raw.start_time ?? null,
    scheduled_time_beijing: raw.scheduled_time_beijing ?? null,
    fixture_sources: Array.isArray(raw.fixture_sources) ? raw.fixture_sources : (raw.fixture_sources ? [raw.fixture_sources] : []),
    market_fixture_match: raw.market_fixture_match ?? raw.match ?? null,
    home_team: raw.home_team ?? raw.home ?? null,
    away_team: raw.away_team ?? raw.away ?? null,
    competition: raw.competition ?? null,
    verified: raw.verified === true
  };
}

export function classifyFootballGroup(row) {
  const st = String(row.sports_market_type || '').toLowerCase();
  const gt = String(row.group_item_title || '').trim();
  const text = `${gt} ${row.title || ''} ${row.slug || ''}`.toLowerCase();

  if (st.includes('team_to_advance') || /team to advance/.test(text)) return 'advance';
  if (st.includes('both_teams_to_score') || /\bbtts\b|both teams to score/.test(text)) return 'btts';
  if (st.includes('extra_time') || /extra time/.test(text)) return 'extra_time';
  if (st.includes('penalty') || /penalty shootout/.test(text)) return 'penalty_shootout';
  if (st.includes('exact_score') || /exact score|correct score/.test(text)) return 'exact_score';
  if (st.includes('corner') || /corner/.test(text)) return 'corners';
  if (st.includes('first_to_score') || /first to score|first goal/.test(text)) return 'first_to_score';
  if (st.includes('player_') || /player prop|anytime goalscorer|shots on target/.test(text)) {
    return 'player_props';
  }
  if (st.includes('first_half') || /1st half|first half|halftime/.test(text)) return 'first_half';
  if (st.includes('second_half') || /2nd half|second half/.test(text)) return 'second_half';

  // Team totals: sportsMarketType or "France O/U 1.5" (not bare "O/U 1.5")
  if (st.includes('team_total') || st === 'soccer_team_totals') return 'team_totals';
  if (/o\/u|over\/under/.test(gt) && !/^[ou]\/u\s*\d/i.test(gt) && !/^over\/under\s*\d/i.test(gt)) {
    return 'team_totals';
  }

  if (st.includes('spread') || /spread|handicap|\(-?\d/.test(text)) return 'spreads_ladder';

  // Match totals: bare O/U lines
  if (st === 'totals' || /^[ou]\/u\s*\d/i.test(gt) || /^over\/under\s*\d/i.test(gt)) {
    return 'totals_ladder';
  }
  if (/o\/u|over\/under|total/.test(text) && !/team total|1st half|2nd half|first half|second half/.test(text)) {
    return 'totals_ladder';
  }

  if (st === 'moneyline' || /moneyline/.test(st) || (/\bdraw\b/.test(text) && /vs\.|vs /.test(text))) {
    return 'moneyline_90m';
  }

  return 'other';
}

export function detectFootballMarketType({ market, eventBundle, eventMatrix = [] } = {}) {
  const blob = [
    market?.title,
    market?.slug,
    market?.group_item_title,
    eventBundle?.title,
    eventBundle?.slug,
    ...(eventMatrix || []).flatMap((row) => [row.title, row.group_item_title, row.slug])
  ].filter(Boolean).join(' ').toLowerCase();

  const looksMatch = /\bvs\.?\b|\bv\b|versus|moneyline|90m|team to advance/.test(blob);
  const looksOutright = /outright|season winner|league winner|cup winner|championship|title winner|to win (?:the )?.*(?:cup|league|championship|tournament)|winner of .*(?:season|league|cup|championship)|lift (?:the )?cup|world.?cup.*winner|premier league.*winner|champions league.*winner/.test(blob);
  if (looksOutright && !looksMatch) return 'outright_season';
  if (looksOutright && /world.?cup.*winner|season winner|league winner|cup winner|outright/.test(blob)) {
    return 'outright_season';
  }
  return 'match';
}

function buildFootballOutrightCategory({ market, eventBundle, classified }) {
  const rows = (classified || []).map((row) => ({
    ...row,
    market_group: 'outright_winner'
  }));
  const leaderboard = rows
    .filter((row) => Number.isFinite(row.yes))
    .map((row) => ({
      label: cleanOutrightLabel(row),
      yes: row.yes,
      slug: row.slug,
      best_ask: row.best_ask,
      best_bid: row.best_bid,
      volume_24h_usd: row.volume_24h_usd,
      is_primary: row.is_primary === true
    }))
    .filter((row) => !isPlaceholderOutrightRow(row))
    .sort((a, b) => b.yes - a.yes || (b.volume_24h_usd || 0) - (a.volume_24h_usd || 0));

  const leader = leaderboard[0] || null;
  const runner = leaderboard[1] || null;
  const yesMass = leaderboard.reduce((sum, row) => sum + (row.yes || 0), 0);
  const missing = leaderboard.length >= 2 ? [] : ['outright_winner_field'];
  const residuals = [];
  if (yesMass > 1.15) {
    residuals.push({
      type: 'yes_mass_over_one',
      note: `Outright yes-mass sums to ≈${round2(yesMass)}; field may be overlapping or incomplete.`
    });
  }
  if (leader && runner && leader.yes - runner.yes < 0.05 && leader.yes > 0.20) {
    residuals.push({
      type: 'tight_outright_leaderboard',
      note: 'Leader and runner-up are tightly priced; avoid over-reading a single favorite.'
    });
  }

  const central_thesis = leader
    ? `Outright leaderboard leads "${leader.label}" at yes≈${leader.yes}`
      + (runner ? ` vs "${runner.label}" ≈${runner.yes}` : '')
      + '. This is a season/cup winner surface, not a 90m match state map.'
    : 'Outright season/cup market detected, but priced team-winner rows are missing.';

  const matrix_status = missing.length ? 'incomplete' : 'complete';
  const tradability_cap = missing.length ? 'weak' : null;

  return {
    category: 'football',
    category_depth: 'enriched',
    market_type: 'outright_season',
    primary_event_slug: eventBundle?.primary_event_slug || eventBundle?.slug || null,
    sibling_event_slugs: eventBundle?.sibling_event_slugs || [],
    linked_event_count: eventBundle?.linked_event_count
      ?? (1 + (eventBundle?.sibling_event_slugs?.length || 0)),
    discovery: eventBundle?.discovery || null,
    related_market_count: rows.length,
    group_counts: { outright_winner: rows.length },
    matrix_status,
    missing_market_groups: missing,
    match_state_map_diagnostic: {
      status: 'not_applicable_outright',
      missing_groups_if_forced: REQUIRED_GROUPS,
      note: 'Outright markets do not have home/draw/away, totals, spreads, or BTTS state-map requirements.'
    },
    market_surface: {
      outright_winner: rows.map(compactRow),
      outright_leaderboard: leaderboard.slice(0, 12)
    },
    market_implied_shape: {
      leader: leader ? { label: leader.label, yes: leader.yes } : null,
      runner_up: runner ? { label: runner.label, yes: runner.yes } : null,
      yes_mass_sum: round2(yesMass),
      central_thesis
    },
    fixture: {
      fixture_status: 'not_applicable',
      note: 'Season/cup outright; single-match fixture gate not applicable.'
    },
    expression_comparison: {
      candidates: leaderboard.slice(0, 8).map((row) => ({
        expression: 'outright_winner',
        market: row.label,
        slug: row.slug,
        yes: row.yes,
        ask: row.best_ask,
        path: 'Needs team to win the named season/cup/tournament.',
        why_consider: 'Direct expression of the outright thesis.',
        why_not: 'Long horizon, field/definition risk, and no match-state hedge.'
      })),
      recommended: null,
      rule: 'Outrights require field completeness and definition checks; do not map to 90m home/draw/away.'
    },
    recommended_expression: null,
    default_action_hint: missing.length ? 'no_trade' : 'use_decision_card_after_field_definition_check',
    tradability_cap,
    tradability_reasons: missing.length ? ['football_outright_field_thin'] : [],
    central_thesis,
    coherence: {
      coherence_status: residuals.length ? 'tension' : (matrix_status === 'complete' ? 'ok_heuristic' : 'incomplete_matrix'),
      cross_market_residuals: residuals,
      distribution_note: 'Outright leaderboard only; no 90m scoreline distribution.'
    },
    hard_gate: 'no_orders_no_account_mutation_no_leo_bankroll',
    skill_alignment: {
      source: 'pm-football-match_outright_season_extension',
      included: ['outright_leaderboard', 'yes_mass_sanity', 'match_state_map_diagnostic'],
      excluded_local_only: ['bankroll_pct', 'news_scrape', 'full_field_fundamental_model']
    }
  };
}

function evaluateFixtureGate(market, eventBundle, fixture) {
  const gammaStart = eventBundle?.start_time || market?.start_time || null;
  const gammaEnd = eventBundle?.end_date || market?.end_date || null;

  if (fixture?.verified === true && fixture.market_fixture_match === 'yes') {
    return {
      fixture_status: 'ok',
      market_fixture_match: 'yes',
      scheduled_time_utc: fixture.scheduled_time_utc || gammaStart,
      scheduled_time_beijing: fixture.scheduled_time_beijing,
      fixture_sources: fixture.fixture_sources?.length
        ? fixture.fixture_sources
        : ['caller_verified'],
      note: 'Caller marked fixture verified and matching the market.'
    };
  }

  if (fixture?.market_fixture_match === 'no') {
    return {
      fixture_status: 'failed_or_unverified',
      market_fixture_match: 'no',
      scheduled_time_utc: fixture.scheduled_time_utc || gammaStart,
      fixture_sources: fixture.fixture_sources || [],
      note: 'Caller reports market/fixture mismatch — no_trade.'
    };
  }

  // Without independent verification, Gamma kickoff alone is weak evidence.
  if (gammaStart) {
    return {
      fixture_status: 'unverified',
      market_fixture_match: 'unclear',
      scheduled_time_utc: gammaStart,
      scheduled_time_end_or_resolve: gammaEnd,
      fixture_sources: ['polymarket_gamma_startTime'],
      note: 'Gamma startTime present but not independently verified. Pass football.verified=true + sources for fixture_status=ok.'
    };
  }

  return {
    fixture_status: 'failed_or_unverified',
    market_fixture_match: 'unclear',
    scheduled_time_utc: null,
    fixture_sources: [],
    note: 'No kickoff on Gamma and no caller verification — stop per pm-football-match fixture gate.'
  };
}

function summarizeMoneyline(rows) {
  const out = { home: null, draw: null, away: null, raw: rows.map(compactRow) };
  for (const row of rows) {
    const label = `${row.group_item_title || ''} ${row.title || ''}`.toLowerCase();
    const item = { label: row.group_item_title || row.title, yes: row.yes, slug: row.slug, ask: row.best_ask };
    if (/\bdraw\b/.test(label)) out.draw = item;
    else if (!out.home) out.home = item;
    else out.away = item;
  }
  // If three moneylines without clear draw tag, keep order by matrix
  if (!out.draw && rows.length >= 3) {
    out.home = { label: rows[0].group_item_title || rows[0].title, yes: rows[0].yes, slug: rows[0].slug, ask: rows[0].best_ask };
    out.draw = { label: rows[1].group_item_title || rows[1].title, yes: rows[1].yes, slug: rows[1].slug, ask: rows[1].best_ask };
    out.away = { label: rows[2].group_item_title || rows[2].title, yes: rows[2].yes, slug: rows[2].slug, ask: rows[2].best_ask };
  }
  return out;
}

function summarizeLadder(rows, kind) {
  const lines = rows
    .map((row) => {
      const line = extractLineNumber(`${row.group_item_title || ''} ${row.title || ''} ${row.slug || ''}`);
      return {
        label: row.group_item_title || row.title,
        line,
        yes: row.yes,
        ask: row.best_ask,
        slug: row.slug
      };
    })
    .filter((r) => r.yes !== null)
    .sort((a, b) => (a.line ?? 0) - (b.line ?? 0));

  const nearCoin = lines
    .filter((l) => l.yes >= 0.35 && l.yes <= 0.65)
    .sort((a, b) => Math.abs(0.5 - a.yes) - Math.abs(0.5 - b.yes))[0] ?? null;

  return { kind, lines, pivot: nearCoin, count: lines.length };
}

function summarizeTeamTotals(rows) {
  return rows.map((row) => ({
    label: row.group_item_title || row.title,
    yes: row.yes,
    ask: row.best_ask,
    slug: row.slug,
    line: extractLineNumber(`${row.group_item_title || ''} ${row.slug || ''}`)
  }));
}

function buildImpliedShape({ moneyline, totals, spreads, btts, advance, teamTotals, missing_market_groups = [] }) {
  const homeYes = moneyline.home?.yes;
  const drawYes = moneyline.draw?.yes;
  const awayYes = moneyline.away?.yes;
  const fav = pickFavorite(moneyline);
  const ou25 = totals.lines.find((l) => l.line === 2.5) || totals.pivot;
  const spread15 = spreads.lines.find((l) => Math.abs((l.line ?? 0) - 1.5) < 0.01);

  const states = [];
  if (fav && homeYes !== null && homeYes >= 0.55) {
    states.push('favorite_leans_90m_win');
  }
  if (drawYes !== null && drawYes >= 0.22) {
    states.push('draw_has_material_mass');
  }
  if (ou25 && ou25.yes >= 0.55) states.push('market_leans_open_game_over_2pt5');
  if (ou25 && ou25.yes <= 0.45) states.push('market_leans_tight_under_2pt5');
  if (btts?.yes >= 0.55) states.push('btts_likely');
  if (btts?.yes <= 0.45) states.push('btts_unlikely');
  if (spread15 && fav && spread15.yes < (fav.yes ?? 1) - 0.15) {
    states.push('favorite_win_but_margin_not_fully_priced');
  }
  if (advance?.yes != null && fav?.yes != null && advance.yes > fav.yes + 0.08) {
    states.push('advance_richer_than_90m_ml_knockout_variance');
  }

  const missingRequired = (missing_market_groups || []).filter((m) => !m.endsWith('_optional'));
  let central_thesis = missingRequired.length
    ? `Match state map incomplete: missing ${missingRequired.join(', ')}.`
    : 'Insufficient structure for a sharp state map.';
  if (states.includes('favorite_leans_90m_win') && states.includes('market_leans_tight_under_2pt5')) {
    central_thesis = 'Favorite favored in 90m with a relatively tight totals regime — prefer expressions that do not require a blowout.';
  } else if (states.includes('favorite_leans_90m_win') && states.includes('market_leans_open_game_over_2pt5')) {
    central_thesis = 'Favorite favored with an open-game totals lean — ML / team totals / overs may share the same path; compare prices.';
  } else if (states.includes('draw_has_material_mass')) {
    central_thesis = 'Draw carries material probability — favorite ML is not a free lunch; check spreads and unders.';
  } else if (fav) {
    central_thesis = `Market favorite leans ${fav.label} in 90m (Yes≈${fav.yes}). Compare advance/spreads/totals before choosing expression.`;
  }
  if (missingRequired.length && !central_thesis.includes('missing')) {
    central_thesis += ` Missing groups limiting match state map: ${missingRequired.join(', ')}.`;
  }

  return {
    moneyline: {
      home: moneyline.home,
      draw: moneyline.draw,
      away: moneyline.away
    },
    totals_pivot: ou25,
    spreads_note: spread15 || spreads.pivot,
    btts,
    advance,
    team_totals_sample: teamTotals.slice(0, 6),
    state_flags: states,
    central_thesis
  };
}

function buildExpressionComparison({ moneyline, totals, spreads, btts, advance, shape }) {
  const candidates = [];
  if (moneyline.home) {
    candidates.push({
      expression: 'home_90m_ml',
      market: moneyline.home.label,
      slug: moneyline.home.slug,
      yes: moneyline.home.yes,
      ask: moneyline.home.ask,
      path: 'Needs home win in 90 minutes.',
      why_consider: 'Direct 90m result expression.',
      why_not: 'Ignores knockout advance paths; can be expensive vs advance.',
      aligns_with_thesis: !shape.state_flags.includes('draw_has_material_mass')
        || (moneyline.home.yes != null && moneyline.home.yes < 0.55)
    });
  }
  if (moneyline.draw) {
    candidates.push({
      expression: 'draw_90m',
      market: moneyline.draw.label,
      slug: moneyline.draw.slug,
      yes: moneyline.draw.yes,
      ask: moneyline.draw.ask,
      path: 'Needs 90m draw.',
      why_consider: 'Prices tactical/tight-game thesis.',
      why_not: 'Binary on draw; no margin for favorite win.',
      aligns_with_thesis: shape.state_flags.includes('draw_has_material_mass')
        || shape.state_flags.includes('market_leans_tight_under_2pt5')
    });
  }
  if (advance) {
    candidates.push({
      expression: 'team_to_advance',
      market: advance.label || 'Team to Advance',
      slug: advance.slug,
      yes: advance.yes,
      ask: advance.ask,
      path: 'Needs side to win tie (may include ET/PEN).',
      why_consider: 'Wider path than 90m ML in knockout.',
      why_not: 'Often richer/more expensive than 90m ML; wrong pick when thesis is tight/draw-heavy.',
      aligns_with_thesis: shape.state_flags.includes('advance_richer_than_90m_ml_knockout_variance')
        && !shape.state_flags.includes('draw_has_material_mass')
    });
  }
  const ou = shape.totals_pivot;
  if (ou) {
    candidates.push({
      expression: 'totals_pivot',
      market: ou.label,
      slug: ou.slug,
      yes: ou.yes,
      ask: ou.ask,
      path: 'Needs goals relative to the pivot line (check adjacent O/U).',
      why_consider: 'Expresses open vs tight game without picking a winner.',
      why_not: 'Must compare adjacent ladder lines — single O/U is incomplete alone.',
      aligns_with_thesis: shape.state_flags.includes('market_leans_tight_under_2pt5')
        || shape.state_flags.includes('market_leans_open_game_over_2pt5')
        || shape.state_flags.includes('draw_has_material_mass')
    });
  }
  if (btts) {
    candidates.push({
      expression: 'btts',
      market: btts.label || 'BTTS',
      slug: btts.slug,
      yes: btts.yes,
      ask: btts.ask,
      path: 'Both teams score.',
      why_consider: 'Aligns with open-game / both-attacks thesis.',
      why_not: 'Orthogonal to pure favorite-win thesis.',
      aligns_with_thesis: shape.state_flags.includes('btts_likely')
        || shape.state_flags.includes('market_leans_open_game_over_2pt5')
    });
  }

  const ladder_context = buildAdjacentLadderContext(totals, spreads);

  // Consistency gate (pm-football-match): central_thesis → shape → expression must cohere.
  // Prefer expressions that align with the dominant thesis; never pick advance when draw mass is the story.
  let recommended = null;
  const flags = shape.state_flags || [];
  if (flags.includes('draw_has_material_mass')) {
    recommended = candidates.find((c) => c.expression === 'draw_90m')
      || candidates.find((c) => c.expression === 'totals_pivot')
      || null;
  } else if (flags.includes('market_leans_tight_under_2pt5') && ou) {
    recommended = candidates.find((c) => c.expression === 'totals_pivot') || null;
  } else if (flags.includes('advance_richer_than_90m_ml_knockout_variance') && advance) {
    recommended = candidates.find((c) => c.expression === 'team_to_advance') || null;
  } else if (flags.includes('market_leans_open_game_over_2pt5') && (ou || btts)) {
    recommended = candidates.find((c) => c.expression === 'totals_pivot')
      || candidates.find((c) => c.expression === 'btts')
      || null;
  } else if (moneyline.home) {
    recommended = candidates.find((c) => c.expression === 'home_90m_ml') || null;
  }

  const coherence_ok = !recommended
    || recommended.aligns_with_thesis !== false
    || !flags.includes('draw_has_material_mass')
    || recommended.expression === 'draw_90m'
    || recommended.expression === 'totals_pivot';

  if (!coherence_ok) {
    recommended = candidates.find((c) => c.expression === 'draw_90m')
      || candidates.find((c) => c.expression === 'totals_pivot')
      || null;
  }

  return {
    candidates,
    ladder_context,
    recommended: recommended
      ? {
          ...recommended,
          note: 'Heuristic expression pick from market shape only — not a buy tip; run decision-card for price_status/edge.',
          coherence_with_thesis: true
        }
      : null,
    rule: 'Always compare ≥2 expressions; never recommend a total/handicap without adjacent ladder context; thesis and recommended expression must cohere.'
  };
}

function buildAdjacentLadderContext(totals, spreads) {
  const totalsLines = (totals?.lines || []).slice().sort((a, b) => (a.line ?? 0) - (b.line ?? 0));
  const spreadLines = (spreads?.lines || []).slice().sort((a, b) => (a.line ?? 0) - (b.line ?? 0));
  const pivot = totals?.pivot || null;
  const adjacentTotals = pivot
    ? totalsLines.filter((l) => l.line != null && Math.abs(l.line - (pivot.line ?? 2.5)) <= 1.01)
    : totalsLines.slice(0, 5);

  return {
    totals_ladder_count: totalsLines.length,
    spreads_ladder_count: spreadLines.length,
    totals_adjacent_to_pivot: adjacentTotals.map((l) => ({
      label: l.label,
      line: l.line,
      yes: l.yes,
      ask: l.ask,
      slug: l.slug
    })),
    spreads_sample: spreadLines.slice(0, 6).map((l) => ({
      label: l.label,
      line: l.line,
      yes: l.yes,
      ask: l.ask,
      slug: l.slug
    })),
    note: totalsLines.length < 2
      ? 'Totals ladder thin — do not treat a single O/U as sufficient.'
      : 'Compare adjacent O/U and spread lines before locking an interval expression.'
  };
}

function pickFavorite(moneyline) {
  const sides = [moneyline.home, moneyline.away].filter(Boolean);
  if (!sides.length) return null;
  return sides.slice().sort((a, b) => (b.yes ?? 0) - (a.yes ?? 0))[0];
}

function firstYes(rows) {
  if (!rows?.length) return null;
  const row = rows[0];
  return { label: row.group_item_title || row.title, yes: row.yes, ask: row.best_ask, slug: row.slug };
}

function extractLineNumber(text) {
  const m = String(text).match(/(-?\d+(?:\.\d+)?)\s*(?:pt)?/i) || String(text).match(/([OU])\s*(\d+(?:\.\d+)?)/i);
  if (!m) return null;
  if (m[2] && (m[1] === 'O' || m[1] === 'U')) return Number(m[2]);
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

function compactRow(row) {
  return {
    slug: row.slug,
    title: row.title,
    group_item_title: row.group_item_title,
    sports_market_type: row.sports_market_type,
    market_group: row.market_group,
    yes: row.yes,
    best_ask: row.best_ask,
    best_bid: row.best_bid,
    volume_24h_usd: row.volume_24h_usd,
    is_primary: row.is_primary
  };
}

function cleanOutrightLabel(row) {
  const raw = row.group_item_title || row.title || row.slug || 'unknown';
  let label = String(raw)
    .replace(/^will\s+/i, '')
    .replace(/\s+win\s+(?:the\s+)?(?:english\s+)?(?:premier league|epl|champions league|world cup|fifa world cup|championship|cup|tournament|serie a|la liga|bundesliga).*$/i, '')
    .replace(/\s+to\s+win\s+(?:the\s+)?.+$/i, '')
    .replace(/\?$/, '')
    .trim();
  // Avoid opaque placeholders when title parsing failed
  if (!label || /^team\s*[a-z]$/i.test(label) || /^outcome\s*\d+$/i.test(label)) {
    const fromSlug = String(row.slug || '')
      .replace(/^will-/, '')
      .replace(/-win-the-.*$/, '')
      .replace(/-/g, ' ')
      .trim();
    if (fromSlug && !/^team\s*[a-z]$/i.test(fromSlug) && !/^another team/i.test(fromSlug)) {
      label = fromSlug;
    }
  }
  return label || String(raw);
}

function isPlaceholderOutrightRow(row) {
  const label = String(row.label || '').trim();
  const slug = String(row.slug || '').toLowerCase();
  if (/^team\s*[a-z]$/i.test(label) || /^other$/i.test(label) || /^another team/i.test(label)) {
    return true;
  }
  if (/will-team-[a-z]-|will-another-team-/.test(slug)) return true;
  // Ghost quotes: flat 0.5 with no bid / ask=1 / zero volume
  const vol = Number(row.volume_24h_usd) || 0;
  const ask = row.best_ask;
  const bid = row.best_bid;
  if (vol <= 0 && (ask == null || ask >= 0.99) && (bid == null) && Number(row.yes) === 0.5) {
    return true;
  }
  return false;
}

function groupBy(items, fn) {
  const out = {};
  for (const item of items) {
    const key = fn(item) || 'other';
    if (!out[key]) out[key] = [];
    out[key].push(item);
  }
  return out;
}
