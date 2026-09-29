// Tennis match category plugin (L1) for PM Event Readout.
// Aligns to pm-tennis-match skill (exportable parts only).
// Quality bar: research/2026-07-09-tennis-asp-quality-spec.md
// No Leo bankroll/sizing/orders. Fixture + format must be honest.

import { round2 } from './pm-gamma-market.mjs';

const REQUIRED_GROUPS = [
  'match_moneyline',
  'set_handicap',
  'total_sets',
  'match_games_totals'
];

/**
 * @param {object} args
 * @param {object} args.market
 * @param {object|null} args.eventBundle
 * @param {object[]} args.eventMatrix
 * @param {object} [args.fixture]
 */
export function enrichTennisCategory({ market, eventBundle, eventMatrix, fixture = null }) {
  const classified = (eventMatrix || []).map((row) => ({
    ...row,
    market_group: classifyTennisGroup(row)
  }));

  const groups = groupBy(classified, (row) => row.market_group);
  const missing = [];
  for (const key of REQUIRED_GROUPS) {
    if (!groups[key]?.length) missing.push(key);
  }
  if (!groups.set1_winner?.length) missing.push('set1_winner_optional');
  if (!groups.completed_match?.length) missing.push('completed_match_optional');

  const requiredMissing = missing.filter((m) => !m.endsWith('_optional'));
  const matrix_status = requiredMissing.length ? 'incomplete' : 'complete';

  const format = detectFormat(market, eventBundle, fixture);
  const moneyline = summarizeNamedMoneyline(groups.match_moneyline || [], market);
  const setHandicap = summarizeSetHandicap(groups.set_handicap || [], moneyline);
  const totalSets = summarizeOverUnderLadder(groups.total_sets || [], 'total_sets');
  const matchGames = summarizeOverUnderLadder(groups.match_games_totals || [], 'match_games');
  const set1 = summarizeNamedMoneyline(groups.set1_winner || []);
  const completed = firstBinary(groups.completed_match);

  const fixtureGate = evaluateFixtureGate(market, eventBundle, fixture);
  const shape = buildImpliedShape({
    format,
    moneyline,
    setHandicap,
    totalSets,
    matchGames,
    set1,
    completed
  });
  const domination = buildStraightSetDominationCheck({ format, moneyline, totalSets, setHandicap, shape });
  const expressions = buildExpressionComparison({
    format,
    moneyline,
    setHandicap,
    totalSets,
    matchGames,
    shape,
    domination
  });
  const hard_veto_gaps = buildTennisHardVetoGaps({
    requiredMissing,
    fixtureGate,
    moneyline,
    format
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
    tradability_reasons.push('tennis_matrix_incomplete');
  }
  if (hard_veto_gaps.length) {
    tradability_cap = 'weak';
    tradability_reasons.push('tennis_hard_veto_gaps');
  }

  const default_action_hint = hard_veto_gaps.length || fixtureGate.fixture_status !== 'ok' || matrix_status === 'incomplete'
    ? 'no_trade'
    : (expressions.recommended
      ? 'use_decision_card_after_expression_comparison'
      : (expressions.all_core_expressions_overpriced ? 'no_trade' : 'use_decision_card_after_expression_comparison'));

  const market_surface = {};
  for (const [key, rows] of Object.entries(groups)) {
    market_surface[key] = rows.map(compactRow);
  }

  return {
    category: 'tennis',
    category_depth: 'enriched',
    format,
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
    straight_set_domination_check: domination,
    fixture: fixtureGate,
    expression_comparison: expressions,
    recommended_expression: expressions.recommended || null,
    default_action_hint,
    tradability_cap,
    tradability_reasons,
    central_thesis: shape.central_thesis,
    hard_gate: 'no_orders_no_account_mutation_no_leo_bankroll',
    skill_alignment: {
      source: 'pm-tennis-match',
      included: [
        'fixture_gate',
        'format_best_of_3_or_5',
        'full_same_event_matrix',
        'named_outcome_moneyline',
        'missing_market_groups',
        'matrix_completeness',
        'hard_veto_gaps',
        'market_implied_shape',
        'expression_comparison',
        'straight_set_domination_check',
        'thesis_expression_coherence'
      ],
      excluded_local_only: [
        'bankroll_pct',
        'u_amount_from_latest_anchor',
        'playbook_card_writeback',
        'personal_exposure',
        'independent_order_of_play_scrape'
      ]
    }
  };
}

function buildTennisHardVetoGaps({ requiredMissing, fixtureGate, moneyline, format }) {
  const gaps = [];
  if (fixtureGate?.fixture_status && fixtureGate.fixture_status !== 'ok') {
    gaps.push(`fixture_${fixtureGate.fixture_status}`);
  }
  const hasMl = Boolean(moneyline?.player_a || moneyline?.player_b);
  if (requiredMissing.includes('match_moneyline') || !hasMl) {
    gaps.push('missing_match_moneyline');
  }
  for (const key of requiredMissing) {
    if (key === 'match_moneyline') continue;
    gaps.push(`missing_${key}`);
  }
  if (!format?.best_of || format?.source === 'unknown') {
    gaps.push('format_unknown');
  }
  return [...new Set(gaps)];
}

export function extractTennisFixture(input = {}, options = {}) {
  if (options.tennisFixture && typeof options.tennisFixture === 'object') {
    return options.tennisFixture;
  }
  const raw = input.tennis && typeof input.tennis === 'object'
    ? input.tennis
    : (input.fixture && typeof input.fixture === 'object' ? input.fixture : null);
  if (!raw) return null;
  return {
    requested_window: raw.requested_window ?? raw.window ?? null,
    scheduled_time_utc: raw.scheduled_time_utc ?? raw.kickoff_utc ?? raw.start_time ?? null,
    scheduled_time_beijing: raw.scheduled_time_beijing ?? null,
    fixture_sources: Array.isArray(raw.fixture_sources)
      ? raw.fixture_sources
      : (raw.fixture_sources ? [raw.fixture_sources] : []),
    market_fixture_match: raw.market_fixture_match ?? null,
    player_a: raw.player_a ?? raw.home ?? null,
    player_b: raw.player_b ?? raw.away ?? null,
    tournament: raw.tournament ?? null,
    round: raw.round ?? null,
    format: raw.format ?? null,
    verified: raw.verified === true
  };
}

export function classifyTennisGroup(row) {
  const st = String(row.sports_market_type || '').toLowerCase();
  const text = `${row.group_item_title || ''} ${row.title || ''} ${row.slug || ''}`.toLowerCase();

  if (st.includes('completed_match') || /completed match/.test(text)) return 'completed_match';
  if (st.includes('set_handicap') || /set handicap|handicap\s*\+\/-/.test(text)) return 'set_handicap';
  // Check set_games / first_set before bare set_totals (substring traps).
  if (st.includes('first_set_winner') || /set 1 winner|first set winner/.test(text)) return 'set1_winner';
  if (st.includes('first_set_totals') || /set 1 .*o\/u|first set .*o\/u|set 1 games/.test(text)) {
    return 'set1_games';
  }
  if (st.includes('set_games_totals') || /set \d .*o\/u|set \d games/.test(text)) return 'set_games';
  if (st.includes('set_winner') || /set \d winner/.test(text)) return 'set_winner';
  if (st === 'tennis_set_totals' || st.includes('set_totals') || /total sets/.test(text)) {
    return 'total_sets';
  }
  if (st.includes('match_totals') || (/match o\/u|match over\/under/.test(text) && !/set/.test(text))) {
    return 'match_games_totals';
  }
  if (st === 'moneyline' || (st.includes('moneyline') && !/set/.test(text))) return 'match_moneyline';

  return 'other';
}

function detectFormat(market, eventBundle, fixture) {
  if (fixture?.format === 'best_of_5' || fixture?.format === 'best_of_3') {
    return {
      best_of: fixture.format === 'best_of_5' ? 5 : 3,
      source: 'caller',
      note: fixture.format
    };
  }
  const blob = [
    market?.title,
    market?.slug,
    eventBundle?.title,
    eventBundle?.slug,
    fixture?.tournament
  ].filter(Boolean).join(' ').toLowerCase();

  if (/\bwta\b/.test(blob)) {
    return { best_of: 3, source: 'tour_wta', note: 'WTA singles default best of 3' };
  }
  if (/\batp\b/.test(blob) && /wimbledon|us open|australian|roland|french open|grand slam/.test(blob)) {
    return { best_of: 5, source: 'tour_atp_gs', note: 'ATP Grand Slam singles default best of 5' };
  }
  if (/\batp\b/.test(blob)) {
    return { best_of: 3, source: 'tour_atp_tour', note: 'ATP tour default best of 3 (non-GS heuristic)' };
  }
  return { best_of: null, source: 'unknown', note: 'Pass tennis.format=best_of_3|best_of_5 when known.' };
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
      tournament: fixture.tournament,
      round: fixture.round,
      player_a: fixture.player_a,
      player_b: fixture.player_b,
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

  if (gammaStart || gammaEnd) {
    return {
      fixture_status: 'unverified',
      market_fixture_match: 'unclear',
      scheduled_time_utc: gammaStart,
      scheduled_time_end_or_resolve: gammaEnd,
      fixture_sources: gammaStart ? ['polymarket_gamma_startTime'] : ['polymarket_gamma_endDate'],
      note: 'Gamma time present but not independently verified. Pass tennis.verified=true + sources for fixture_status=ok.'
    };
  }

  return {
    fixture_status: 'failed_or_unverified',
    market_fixture_match: 'unclear',
    scheduled_time_utc: null,
    fixture_sources: [],
    note: 'No schedule on Gamma and no caller verification — stop per pm-tennis-match fixture gate.'
  };
}

function summarizeNamedMoneyline(rows, primaryMarket = null) {
  // Prefer the live-fetched primary market prices when available — Gamma event
  // bundle rows can lag the /markets slug fetch mid-match.
  if (primaryMarket?.outcomes?.length >= 2 && primaryMarket.outcome_prices?.length >= 2) {
    const player_a = {
      label: String(primaryMarket.outcomes[0]),
      yes: Number.isFinite(primaryMarket.outcome_prices[0])
        ? round2(primaryMarket.outcome_prices[0])
        : null,
      slug: primaryMarket.slug,
      ask: primaryMarket.best_ask
    };
    const player_b = {
      label: String(primaryMarket.outcomes[1]),
      yes: Number.isFinite(primaryMarket.outcome_prices[1])
        ? round2(primaryMarket.outcome_prices[1])
        : null,
      slug: primaryMarket.slug,
      ask: Number.isFinite(primaryMarket.outcome_prices[1])
        ? round2(primaryMarket.outcome_prices[1])
        : null
    };
    return {
      player_a,
      player_b,
      raw: rows.map(compactRow),
      primary_slug: primaryMarket.slug,
      price_source: 'primary_market_live'
    };
  }

  if (!rows.length) return { player_a: null, player_b: null, raw: [], price_source: 'none' };
  const row = rows.find((r) => r.is_primary) || rows[0];
  const named = row.named_outcomes?.length
    ? row.named_outcomes
    : (row.outcomes || []).map((label, idx) => ({
        label: String(label),
        price: idx === 0 ? row.yes : null
      }));

  const player_a = named[0]
    ? { label: named[0].label, yes: named[0].price, slug: row.slug, ask: row.best_ask }
    : null;
  const player_b = named[1]
    ? {
        label: named[1].label,
        yes: named[1].price,
        slug: row.slug,
        ask: named[1].price
      }
    : null;

  return {
    player_a,
    player_b,
    raw: rows.map(compactRow),
    primary_slug: row.slug,
    price_source: 'event_matrix_row'
  };
}

function summarizeSetHandicap(rows, moneyline) {
  return rows.map((row) => {
    const text = `${row.group_item_title || ''} ${row.title || ''}`;
    const line = extractLineNumber(text) ?? 1.5;
    const named = row.named_outcomes || [];
    const favoriteLabel = pickFavoriteLabel(moneyline);
    let favorite_side = null;
    let underdog_side = null;
    for (const n of named) {
      const item = { label: n.label, yes: n.price, slug: row.slug, line };
      if (favoriteLabel && namesLikelyMatch(n.label, favoriteLabel)) favorite_side = item;
      else underdog_side = underdog_side || item;
    }
    if (!favorite_side && named[0]) {
      favorite_side = { label: named[0].label, yes: named[0].price, slug: row.slug, line };
      underdog_side = named[1]
        ? { label: named[1].label, yes: named[1].price, slug: row.slug, line }
        : null;
    }
    return {
      label: row.group_item_title || row.title,
      line,
      slug: row.slug,
      favorite_side,
      underdog_side,
      ask: row.best_ask
    };
  });
}

function summarizeOverUnderLadder(rows, kind) {
  const lines = rows.map((row) => {
    const text = `${row.group_item_title || ''} ${row.title || ''} ${row.slug || ''}`;
    const line = extractLineNumber(text);
    const named = row.named_outcomes || [];
    const over = named.find((n) => /^over/i.test(n.label)) || named[0];
    const under = named.find((n) => /^under/i.test(n.label)) || named[1];
    return {
      label: row.group_item_title || row.title,
      line,
      over: over?.price ?? row.yes,
      under: under?.price ?? null,
      ask: row.best_ask,
      slug: row.slug
    };
  }).sort((a, b) => (a.line ?? 0) - (b.line ?? 0));

  // Prefer tradeable mid-range lines; avoid settled 0/1 pivots polluting shape.
  const pivot = lines
    .filter((l) => l.over != null && l.over >= 0.2 && l.over <= 0.8)
    .sort((a, b) => Math.abs(0.5 - a.over) - Math.abs(0.5 - b.over))[0]
    ?? lines
      .filter((l) => l.over != null)
      .sort((a, b) => Math.abs(0.5 - a.over) - Math.abs(0.5 - b.over))[0]
    ?? null;

  return { kind, lines, pivot, count: lines.length };
}

function buildImpliedShape({ format, moneyline, setHandicap, totalSets, matchGames, set1, completed }) {
  const fav = pickFavorite(moneyline);
  const dog = pickUnderdog(moneyline);
  const setsPivot = totalSets.pivot;
  const gamesPivot = matchGames.pivot;
  const sh = setHandicap[0] || null;

  const states = [];
  if (fav?.yes != null && fav.yes >= 0.58) states.push('favorite_leans_match');
  if (fav?.yes != null && fav.yes >= 0.7) states.push('strong_favorite');
  if (fav?.yes != null && dog?.yes != null && Math.abs(fav.yes - dog.yes) <= 0.12) {
    states.push('match_priced_close');
  }
  if (setsPivot?.over != null && setsPivot.over >= 0.55) states.push('market_leans_long_match_sets');
  if (setsPivot?.over != null && setsPivot.over <= 0.45) states.push('market_leans_short_match_sets');
  if (gamesPivot?.over != null && gamesPivot.over >= 0.55) states.push('market_leans_high_match_games');
  if (sh?.underdog_side?.yes != null && sh.underdog_side.yes >= 0.55) {
    states.push('underdog_set_cover_live');
  }
  if (sh?.favorite_side?.yes != null && sh.favorite_side.yes <= 0.25) {
    states.push('favorite_set_domination_not_priced');
  }
  if (completed?.yes != null && completed.yes < 0.85) {
    states.push('retirement_or_incomplete_risk_priced');
  }

  let central_thesis = 'Insufficient structure for a sharp tennis state map.';
  if (states.includes('match_priced_close') || states.includes('market_leans_long_match_sets')) {
    central_thesis = 'Match priced competitive / long — compare underdog set cover, total sets over, and match-games over before ML.';
  } else if (states.includes('strong_favorite') && states.includes('market_leans_short_match_sets')) {
    central_thesis = 'Strong favorite with short-sets lean — compare favorite ML vs set handicap; avoid overs unless domination check fails.';
  } else if (states.includes('favorite_leans_match') && states.includes('market_leans_long_match_sets')) {
    central_thesis = 'Favorite leans but market prices a push path — prefer total-sets over or underdog +handicap over rich ML.';
  } else if (fav) {
    central_thesis = `Market favorite leans ${fav.label} (≈${fav.yes}). Compare set handicap / total sets / match games before locking expression.`;
  }

  return {
    format,
    moneyline: {
      player_a: moneyline.player_a,
      player_b: moneyline.player_b,
      favorite: fav,
      underdog: dog
    },
    set_handicap_sample: sh,
    total_sets_pivot: setsPivot,
    match_games_pivot: gamesPivot,
    set1_sample: set1.player_a ? set1 : null,
    completed_match: completed,
    state_flags: states,
    central_thesis
  };
}

function buildStraightSetDominationCheck({ format, moneyline, totalSets, setHandicap, shape }) {
  const fav = shape.moneyline?.favorite;
  const setsPivot = totalSets.pivot;
  const sh = setHandicap[0];
  const bo = format?.best_of;

  const favorite_2_0_or_3_0_path = bo === 5
    ? `Favorite wins 3-0 (straight sets in BO5). If priced strongly, overs/covers that need a push are fragile.`
    : `Favorite wins 2-0 (straight sets in BO3). If likely, total-sets Over 2.5 and underdog +1.5 can die together.`;

  const underdog_collapse_path = fav
    ? `${fav.label} holds serve / breaks early; underdog fails to take a set.`
    : 'Favorite closes quickly; underdog never holds a set.';

  const serve_hold_break_risk = 'Serve-hold leagues (grass) raise straight-set risk; break-heavy surfaces raise push paths. ASP does not scrape live serve stats — caller must supply external_context if critical.';

  const overNeedsPush = setsPivot?.over != null && setsPivot.over >= 0.5;
  const coverNeedsPush = sh?.underdog_side?.yes != null && sh.underdog_side.yes >= 0.5;
  const strongFav = (fav?.yes ?? 0) >= 0.68;

  let survives = true;
  let why = 'Domination path not dominant enough to veto competitive expressions by default.';
  if ((overNeedsPush || coverNeedsPush) && strongFav && shape.state_flags.includes('market_leans_short_match_sets')) {
    survives = false;
    why = 'Strong favorite + short-sets lean: over / underdog cover do not clearly survive straight-set domination.';
  } else if (overNeedsPush && shape.state_flags.includes('market_leans_long_match_sets')) {
    why = 'Market already leans long sets — over/cover can survive if price is not full (decision-card still required).';
  }

  return {
    favorite_2_0_or_3_0_path,
    underdog_collapse_path,
    serve_hold_break_risk,
    why_over_or_cover_survives: why,
    survives,
    applies_when_recommending: ['total_sets_over', 'underdog_set_handicap', 'match_games_over']
  };
}

function buildExpressionComparison({
  format,
  moneyline,
  setHandicap,
  totalSets,
  matchGames,
  shape,
  domination
}) {
  const candidates = [];
  const fav = shape.moneyline?.favorite;
  const dog = shape.moneyline?.underdog;

  if (fav) {
    candidates.push({
      expression: 'favorite_match_ml',
      market: fav.label,
      slug: moneyline.primary_slug,
      yes: fav.yes,
      ask: fav.ask,
      path: 'Needs favorite to win the match.',
      why_consider: 'Direct match result.',
      why_not: 'Ignores push/set-cover paths; can be expensive vs handicap/totals.',
      aligns_with_thesis: shape.state_flags.includes('favorite_leans_match')
        && !shape.state_flags.includes('match_priced_close')
    });
  }
  if (dog) {
    candidates.push({
      expression: 'underdog_match_ml',
      market: dog.label,
      slug: moneyline.primary_slug,
      yes: dog.yes,
      ask: dog.ask,
      path: 'Needs underdog to win the match.',
      why_consider: 'Upset expression.',
      why_not: 'Usually thinner path than set cover.',
      aligns_with_thesis: shape.state_flags.includes('match_priced_close')
    });
  }

  const sh = setHandicap[0];
  if (sh?.underdog_side) {
    candidates.push({
      expression: 'underdog_set_handicap',
      market: `${sh.underdog_side.label} (+${sh.line})`,
      slug: sh.slug,
      yes: sh.underdog_side.yes,
      ask: sh.ask,
      path: format?.best_of === 5
        ? `Underdog wins match or loses 2-${Math.ceil(format.best_of / 2)} (BO5 +${sh.line} cover rules).`
        : `Underdog wins match or loses 1-2 (BO3 +${sh.line}).`,
      why_consider: 'Wider path than underdog ML when favorite may be pushed.',
      why_not: 'Dies on straight-set domination.',
      aligns_with_thesis: shape.state_flags.includes('market_leans_long_match_sets')
        || shape.state_flags.includes('match_priced_close')
        || shape.state_flags.includes('underdog_set_cover_live'),
      needs_domination_check: true
    });
  }
  if (sh?.favorite_side) {
    candidates.push({
      expression: 'favorite_set_handicap',
      market: `${sh.favorite_side.label} (-${sh.line})`,
      slug: sh.slug,
      yes: sh.favorite_side.yes,
      ask: sh.ask,
      path: 'Favorite covers set handicap (domination / multi-set margin).',
      why_consider: 'Expresses straight-set / clear-win thesis.',
      why_not: 'Fragile if match goes long.',
      aligns_with_thesis: shape.state_flags.includes('strong_favorite')
        && shape.state_flags.includes('market_leans_short_match_sets'),
      needs_domination_check: false
    });
  }

  const sets = totalSets.pivot;
  if (sets) {
    candidates.push({
      expression: 'total_sets_over',
      market: sets.label,
      slug: sets.slug,
      yes: sets.over,
      ask: sets.ask,
      path: `Needs match to go over ${sets.line} sets.`,
      why_consider: 'Expresses push / competitive match without picking winner.',
      why_not: 'Fails under straight-set domination.',
      aligns_with_thesis: shape.state_flags.includes('market_leans_long_match_sets')
        || shape.state_flags.includes('match_priced_close'),
      needs_domination_check: true
    });
    candidates.push({
      expression: 'total_sets_under',
      market: sets.label.replace(/O\/U/i, 'Under'),
      slug: sets.slug,
      yes: sets.under,
      ask: sets.under,
      path: `Needs match to stay under ${sets.line} sets.`,
      why_consider: 'Aligns with domination / short-match thesis.',
      why_not: 'Dies if underdog takes a set early and match extends.',
      aligns_with_thesis: shape.state_flags.includes('market_leans_short_match_sets')
        || shape.state_flags.includes('strong_favorite'),
      needs_domination_check: false
    });
  }

  const games = matchGames.pivot;
  if (games) {
    candidates.push({
      expression: 'match_games_over',
      market: games.label,
      slug: games.slug,
      yes: games.over,
      ask: games.ask,
      path: `Needs total match games over ${games.line}.`,
      why_consider: 'Competitive / hold-heavy match expression.',
      why_not: 'Correlated with long sets; domination kills it.',
      aligns_with_thesis: shape.state_flags.includes('market_leans_high_match_games')
        || shape.state_flags.includes('market_leans_long_match_sets'),
      needs_domination_check: true
    });
  }

  // Coherence: competitive thesis → cover/over; domination → ML/under/fav handicap
  // Price gate: never recommend full/rich expressions (yes>=0.85 or <=0.15) as tip.
  const withStatus = candidates.map((c) => ({
    ...c,
    price_status: scorePriceStatus(c.yes)
  }));

  let recommended = null;
  const flags = shape.state_flags || [];
  const pickFirstActionable = (exprs) => {
    for (const name of exprs) {
      const hit = withStatus.find((c) => c.expression === name);
      if (!hit) continue;
      if (hit.needs_domination_check && domination && domination.survives === false) continue;
      // Skill: full / rich / no_edge cannot be the final tip expression.
      if (['full', 'rich', 'no_edge'].includes(hit.price_status)) continue;
      return hit;
    }
    return null;
  };

  if (flags.includes('match_priced_close') || flags.includes('market_leans_long_match_sets')) {
    recommended = pickFirstActionable([
      'underdog_set_handicap',
      'total_sets_over',
      'match_games_over',
      'underdog_match_ml',
      'favorite_match_ml'
    ]);
  } else if (flags.includes('strong_favorite') && flags.includes('market_leans_short_match_sets')) {
    recommended = pickFirstActionable([
      'favorite_set_handicap',
      'total_sets_under',
      'favorite_match_ml'
    ]);
  } else if (flags.includes('favorite_leans_match')) {
    recommended = pickFirstActionable(['favorite_match_ml', 'total_sets_under']);
  }

  if (!recommended) {
    // All core expressions overpriced / gated → honest no tip
    recommended = null;
  }

  const all_core_expressions_overpriced = withStatus
    .filter((c) => [
      'favorite_match_ml',
      'underdog_match_ml',
      'underdog_set_handicap',
      'total_sets_over',
      'total_sets_under',
      'match_games_over'
    ].includes(c.expression))
    .every((c) => ['full', 'rich', 'no_edge'].includes(c.price_status));

  return {
    candidates: withStatus,
    recommended: recommended
      ? {
          ...recommended,
          note: 'Heuristic expression pick from market shape only — not a buy tip; run decision-card for price_status/edge.',
          coherence_with_thesis: true,
          domination_check_applied: Boolean(recommended.needs_domination_check)
        }
      : null,
    all_core_expressions_overpriced,
    rule: 'Always compare ≥2 expressions; convert set handicap into covered scores using format; run straight_set_domination_check before overs/covers; never recommend full/rich prices.'
  };
}

/**
 * Price gate cutoffs, hoisted and exported 2026-07-30.
 *
 * This gate decides whether an expression may be handed to the caller as the tip:
 * `full` / `rich` / `no_edge` are refused outright. That makes these numbers the
 * most consequential constants in the file — they are the difference between
 * "recommended" and "withheld" — yet they were inline and the module had no test
 * coverage at all. Exported so a buyer can read the rail before trusting the tip,
 * and so the boundaries can be pinned by tests.
 *
 * Values unchanged from the inline versions. Retuning would need settled-match
 * backtesting, which this service does not do.
 */
export const TENNIS_PRICE_GATE = Object.freeze({
  /** At or beyond this (either tail) the price is fully paid — never a tip. */
  full: 0.85,
  /** At or beyond this (either tail) the price is rich — never a tip. */
  rich: 0.72,
  /** Inside this band the price is acceptable. */
  acceptable_low: 0.4,
  acceptable_high: 0.6
});

export function scorePriceStatus(yes) {
  const G = TENNIS_PRICE_GATE;
  if (yes == null || !Number.isFinite(yes)) return 'unknown';
  if (yes >= G.full || yes <= 1 - G.full) return 'full';
  if (yes >= G.rich || yes <= 1 - G.rich) return 'rich';
  if (yes >= G.acceptable_low && yes <= G.acceptable_high) return 'acceptable';
  return 'watch';
}

function pickFavorite(moneyline) {
  const sides = [moneyline.player_a, moneyline.player_b].filter(Boolean);
  if (!sides.length) return null;
  return sides.slice().sort((a, b) => (b.yes ?? 0) - (a.yes ?? 0))[0];
}

function pickUnderdog(moneyline) {
  const fav = pickFavorite(moneyline);
  const sides = [moneyline.player_a, moneyline.player_b].filter(Boolean);
  return sides.find((s) => s.label !== fav?.label) || null;
}

function pickFavoriteLabel(moneyline) {
  return pickFavorite(moneyline)?.label || null;
}

function namesLikelyMatch(a, b) {
  const na = String(a).toLowerCase().split(/\s+/).filter(Boolean);
  const nb = String(b).toLowerCase().split(/\s+/).filter(Boolean);
  if (!na.length || !nb.length) return false;
  return na.some((part) => nb.includes(part)) || nb.some((part) => na.includes(part));
}

function firstBinary(rows) {
  if (!rows?.length) return null;
  const row = rows[0];
  return {
    label: row.group_item_title || row.title,
    yes: row.yes,
    ask: row.best_ask,
    slug: row.slug
  };
}

function extractLineNumber(text) {
  const m = String(text).match(/([+-]?\d+(?:\.\d+)?)\s*(?:pt)?/i)
    || String(text).match(/([OU])\s*(\d+(?:\.\d+)?)/i)
    || String(text).match(/(\d+(?:\.\d+)?)/);
  if (!m) return null;
  if (m[2] && (m[1] === 'O' || m[1] === 'U')) return Number(m[2]);
  const n = Number(m[1]);
  return Number.isFinite(n) ? Math.abs(n) : null;
}

function compactRow(row) {
  return {
    slug: row.slug,
    title: row.title,
    group_item_title: row.group_item_title,
    sports_market_type: row.sports_market_type,
    market_group: row.market_group,
    outcomes: row.outcomes,
    named_outcomes: row.named_outcomes,
    yes: row.yes,
    best_ask: row.best_ask,
    best_bid: row.best_bid,
    volume_24h_usd: row.volume_24h_usd,
    is_primary: row.is_primary
  };
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
