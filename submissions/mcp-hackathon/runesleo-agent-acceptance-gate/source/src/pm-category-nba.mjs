// NBA / basketball match category plugin (L1) for PM Event Readout.
// Lighter than football: moneyline + spread + totals + player-props sample.
// No bankroll, no orders, no scrape — fixture must be caller-verified when used.

import { round2 } from './pm-gamma-market.mjs';

/**
 * NBA shape and residual cutoffs, hoisted 2026-07-31.
 *
 * Same treatment already applied to football and tennis: these decide what a buyer is
 * told about the market ("clear favorite", "ML vs spread mismatch"), and they were
 * inline literals nobody could audit — indistinguishable from a typo once written.
 * crypto-market-regime is the pattern being followed: declare the numbers, ship them
 * with the verdict.
 *
 * Values unchanged. Retuning would need settled-game backtesting, which this service
 * does not do.
 */
export const NBA_SHAPE_THRESHOLDS = Object.freeze({
  /** Favourite at or above this reads as a clear favourite. */
  clear_favorite: 0.62,
  /** …and above this as a lean favourite; below it the ML is a coin flip. */
  lean_favorite: 0.55,
  /** Heavy favourite paired with a tiny spread is worth flagging. */
  heavy_favorite: 0.7,
  /** Spread at or under this magnitude counts as tight. */
  tight_spread_abs: 2.5,
  /** Near-even ML at or below this… */
  near_even_ml: 0.55,
  /** …paired with a spread at or above this magnitude is suspicious. */
  wide_spread_abs: 8,
  /** Totals pivot outside this band is extreme. */
  totals_extreme_high: 0.7,
  totals_extreme_low: 0.3
});

const REQUIRED_GROUPS = [
  'moneyline',
  'spreads_ladder',
  'totals_ladder'
];

/**
 * @param {object} args
 * @param {object} args.market
 * @param {object|null} args.eventBundle
 * @param {object[]} args.eventMatrix
 * @param {object} [args.fixture]
 */
export function enrichNbaCategory({ market, eventBundle, eventMatrix, fixture = null }) {
  const classified = (eventMatrix || []).map((row) => ({
    ...row,
    market_group: classifyNbaGroup(row)
  }));

  const marketType = detectNbaMarketType({ market, eventBundle, eventMatrix });
  if (marketType === 'outright_season') {
    return buildNbaOutrightCategory({ market, eventBundle, classified });
  }

  const groups = groupBy(classified, (row) => row.market_group);
  const missing = [];
  for (const key of REQUIRED_GROUPS) {
    if (!groups[key]?.length) missing.push(key);
  }
  if (!groups.player_props?.length) missing.push('player_props_optional');
  if (!groups.first_half?.length) missing.push('first_half_optional');

  const matrix_status = missing.filter((m) => !m.endsWith('_optional')).length
    ? 'incomplete'
    : 'complete';

  const moneyline = summarizeBinaryMoneyline(groups.moneyline || [], market);
  const spreads = summarizeLineLadder(groups.spreads_ladder || [], 'spread');
  const totals = summarizeLineLadder(groups.totals_ladder || [], 'total');
  const fixtureGate = evaluateFixtureGate(market, eventBundle, fixture);
  const shape = buildImpliedShape({ moneyline, spreads, totals });
  const coherence = buildNbaCoherence({ moneyline, spreads, totals, matrix_status });

  let tradability_cap = null;
  const tradability_reasons = [];
  if (fixtureGate.fixture_status !== 'ok') {
    tradability_cap = 'weak';
    tradability_reasons.push('fixture_unverified_or_failed');
  }
  if (matrix_status === 'incomplete') {
    tradability_cap = tradability_cap || 'medium';
    tradability_reasons.push('nba_matrix_incomplete');
  }

  const market_surface = {};
  for (const [key, rows] of Object.entries(groups)) {
    if (key === 'player_props') {
      market_surface.player_props_sample = rows.slice(0, 8).map(compactRow);
      market_surface.player_props_count = rows.length;
    } else {
      market_surface[key] = rows.map(compactRow);
    }
  }

  return {
    category: 'nba',
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
    missing_market_groups: missing,
    market_surface,
    market_implied_shape: shape,
    fixture: fixtureGate,
    coherence,
    recommended_expression: shape.favored_side
      ? {
          expression: 'moneyline_favorite',
          side: shape.favored_side,
          yes: shape.favorite_yes,
          note: 'Heuristic favorite from ML mass only — not a buy tip.'
        }
      : null,
    default_action_hint: fixtureGate.fixture_status !== 'ok' || matrix_status === 'incomplete'
      ? 'no_trade'
      : 'use_decision_card_after_shape_check',
    tradability_cap,
    tradability_reasons,
    central_thesis: shape.central_thesis,
    hard_gate: 'no_orders_no_account_mutation_no_leo_bankroll',
    skill_alignment: {
      source: 'sports_generalization_nba_l1',
      included: [
        'fixture_gate',
        'moneyline_spread_totals_matrix',
        'heuristic_coherence',
        'player_props_sample'
      ],
      excluded_local_only: [
        'bankroll_pct',
        'player_prop_full_dump',
        'live_injury_scrape'
      ]
    }
  };
}

export function extractNbaFixture(input = {}, options = {}) {
  if (options.nbaFixture && typeof options.nbaFixture === 'object') {
    return options.nbaFixture;
  }
  const raw = input.nba && typeof input.nba === 'object'
    ? input.nba
    : (input.nfl && typeof input.nfl === 'object'
      ? input.nfl
      : (input.ufc && typeof input.ufc === 'object'
        ? input.ufc
        : (input.mlb && typeof input.mlb === 'object'
          ? input.mlb
          : (input.basketball && typeof input.basketball === 'object'
            ? input.basketball
            : (input.fixture && typeof input.fixture === 'object' ? input.fixture : null)))));
  if (!raw) return null;
  const competition = raw.competition
    ?? (input.ufc ? 'UFC' : (input.mlb ? 'MLB' : (input.nfl ? 'NFL' : 'NBA')));
  return {
    scheduled_time_utc: raw.scheduled_time_utc ?? raw.tipoff_utc ?? raw.kickoff_utc ?? raw.start_time ?? null,
    fixture_sources: Array.isArray(raw.fixture_sources) ? raw.fixture_sources : (raw.fixture_sources ? [raw.fixture_sources] : []),
    market_fixture_match: raw.market_fixture_match ?? raw.match ?? null,
    home_team: raw.home_team ?? raw.home ?? raw.fighter_a ?? null,
    away_team: raw.away_team ?? raw.away ?? raw.fighter_b ?? null,
    competition,
    verified: raw.verified === true
  };
}

function detectNbaMarketType({ market, eventBundle, eventMatrix }) {
  const blob = [
    market?.question,
    market?.slug,
    eventBundle?.title,
    eventBundle?.slug,
    ...(eventMatrix || []).flatMap((row) => [row.title, row.group_item_title, row.slug])
  ].filter(Boolean).join(' ').toLowerCase();
  const looksMatch = /\bvs\.?\b|\bv\b|versus|moneyline|spread|o\/u|over\/under|tip-?off/.test(blob);
  const looksOutright = /nba finals|championship|conference|outright|season|to win the|title|mvp/.test(blob)
    && /win|champion|finals|title|mvp/.test(blob);
  if (looksOutright && !looksMatch) return 'outright_season';
  return 'match';
}

function buildNbaOutrightCategory({ market, eventBundle, classified }) {
  const leaderboard = (classified || [])
    .filter((row) => Number.isFinite(row.yes))
    .map((row) => ({
      label: cleanNbaOutrightLabel(row),
      yes: row.yes,
      slug: row.slug,
      best_ask: row.best_ask,
      best_bid: row.best_bid,
      volume_24h_usd: row.volume_24h_usd,
      is_primary: row.is_primary === true
    }))
    .filter((row) => !isPlaceholderNbaOutrightRow(row))
    .sort((a, b) => b.yes - a.yes || (b.volume_24h_usd || 0) - (a.volume_24h_usd || 0));

  const leader = leaderboard[0] || null;
  const runner = leaderboard[1] || null;
  const yesMass = leaderboard.reduce((sum, row) => sum + (row.yes || 0), 0);
  const missing = leaderboard.length >= 2 ? [] : ['outright_winner_field'];
  const central_thesis = leader
    ? `NBA outright/futures leaderboard leads "${leader.label}" at yes≈${leader.yes}`
      + (runner ? ` vs "${runner.label}" ≈${runner.yes}` : '')
      + '. Not a single-game moneyline/spread/totals map.'
    : 'NBA finals/futures surface detected, but priced field rows are thin.';

  return {
    category: 'nba',
    category_depth: 'enriched',
    market_type: 'outright_season',
    primary_event_slug: eventBundle?.primary_event_slug || eventBundle?.slug || null,
    sibling_event_slugs: eventBundle?.sibling_event_slugs || [],
    linked_event_count: eventBundle?.linked_event_count
      ?? (1 + (eventBundle?.sibling_event_slugs?.length || 0)),
    discovery: eventBundle?.discovery || null,
    related_market_count: (classified || []).length,
    group_counts: { outright_winner: (classified || []).length },
    matrix_status: missing.length ? 'incomplete' : 'complete',
    missing_market_groups: missing,
    market_surface: {
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
      note: 'NBA finals/futures outright; tipoff fixture gate not applicable.'
    },
    coherence: {
      coherence_status: missing.length ? 'incomplete_matrix' : 'ok_heuristic',
      cross_market_residuals: yesMass > 1.15
        ? [{ type: 'yes_mass_over_one', note: `Yes-mass ≈${round2(yesMass)}` }]
        : [],
      distribution_note: 'Futures leaderboard only; not a single-game state map.'
    },
    recommended_expression: null,
    default_action_hint: missing.length ? 'no_trade' : 'use_decision_card_after_field_definition_check',
    tradability_cap: missing.length ? 'weak' : null,
    tradability_reasons: missing.length ? ['nba_outright_field_thin'] : [],
    central_thesis,
    hard_gate: 'no_orders_no_account_mutation_no_leo_bankroll',
    skill_alignment: {
      source: 'sports_generalization_nba_outright_extension',
      included: ['outright_leaderboard', 'yes_mass_sanity'],
      excluded_local_only: ['injury_scrape', 'full_player_props']
    }
  };
}

function cleanNbaOutrightLabel(row) {
  const raw = row.group_item_title || row.title || row.slug || 'unknown';
  return String(raw)
    .replace(/^will\s+(?:the\s+)?/i, '')
    .replace(/\s+win\s+(?:the\s+)?(?:nba finals|nba championship|championship|title|conference).*$/i, '')
    .replace(/\s+be\s+(?:the\s+)?(?:202\d\s+)?nba\s+(?:western|eastern)\s+conference\s+champion.*$/i, '')
    .replace(/\s+be\s+(?:the\s+)?(?:nba\s+)?mvp.*$/i, '')
    .replace(/\?$/, '')
    .trim() || String(raw);
}

function isPlaceholderNbaOutrightRow(row) {
  const label = String(row.label || '').trim();
  const slug = String(row.slug || '').toLowerCase();
  if (/^team\s*[a-z]$/i.test(label) || /^other$/i.test(label) || /^another team/i.test(label)) {
    return true;
  }
  if (/will-team-[a-z]-|will-another-team-/.test(slug)) return true;
  const vol = Number(row.volume_24h_usd) || 0;
  const ask = row.best_ask;
  const bid = row.best_bid;
  if (vol <= 0 && (ask == null || ask >= 0.99) && bid == null && Number(row.yes) === 0.5) {
    return true;
  }
  return false;
}

export function classifyNbaGroup(row) {
  const st = String(row.sports_market_type || '').toLowerCase();
  const gt = String(row.group_item_title || '').trim();
  const text = `${gt} ${row.title || ''} ${row.slug || ''}`.toLowerCase();

  if (st.includes('player') || /points|rebounds|assists|threes|pra\b|player prop/.test(text)) {
    return 'player_props';
  }
  if (st.includes('first_half') || /1st half|first half|halftime/.test(text)) return 'first_half';
  if (st.includes('second_half') || /2nd half|second half/.test(text)) return 'second_half';
  if (st.includes('spread') || /spread|handicap|\([+-]?\d/.test(text)) return 'spreads_ladder';
  if (st.includes('total') || /o\/u|over\/under|total points|totals/.test(text)) return 'totals_ladder';
  if (st.includes('moneyline') || st.includes('winner') || /moneyline|to win|winner/.test(text)) {
    return 'moneyline';
  }
  // Binary team-named markets often are ML when not O/U/spread.
  if (gt && !/o\/u|over|under|spread|\+|\-/.test(gt) && (row.yes != null || row.no != null)) {
    return 'moneyline';
  }
  return 'other';
}

function evaluateFixtureGate(market, eventBundle, fixture) {
  if (!fixture) {
    return {
      fixture_status: 'missing',
      detail: 'Pass nba:{verified:true, scheduled_time_utc, market_fixture_match:"yes"} for tipoff honesty.',
      scheduled_time_utc: eventBundle?.start_time || market?.start_time || null
    };
  }
  if (fixture.verified !== true) {
    return {
      fixture_status: 'unverified',
      detail: 'nba.verified must be true — ASP does not scrape tipoff sources.',
      ...fixture
    };
  }
  const match = String(fixture.market_fixture_match || '').toLowerCase();
  if (match && match !== 'yes' && match !== 'match' && match !== 'true') {
    return {
      fixture_status: 'mismatch',
      detail: 'Caller marked market_fixture_match as not yes.',
      ...fixture
    };
  }
  return {
    fixture_status: 'ok',
    detail: 'Caller-verified tipoff/fixture.',
    ...fixture
  };
}

function summarizeBinaryMoneyline(rows, market) {
  if (!rows.length) return null;
  const sorted = rows.slice().sort((a, b) => (b.yes ?? 0) - (a.yes ?? 0));
  const favorite = sorted[0];
  const underdog = sorted[1] || null;
  return {
    count: rows.length,
    favorite: favorite ? {
      label: favorite.group_item_title || favorite.title,
      yes: favorite.yes,
      slug: favorite.slug,
      is_primary: favorite.is_primary
    } : null,
    underdog: underdog ? {
      label: underdog.group_item_title || underdog.title,
      yes: underdog.yes,
      slug: underdog.slug
    } : null,
    primary_yes: market?.yes ?? favorite?.yes ?? null
  };
}

function summarizeLineLadder(rows, kind) {
  const lines = rows.map((row) => {
    const label = row.group_item_title || row.title || row.slug || '';
    const line = parseLine(label);
    return {
      label,
      line,
      yes: row.yes,
      ask: row.best_ask,
      bid: row.best_bid,
      slug: row.slug
    };
  }).sort((a, b) => (a.line ?? 0) - (b.line ?? 0));
  const pivot = lines.filter((l) => l.yes != null).sort((a, b) => Math.abs((a.yes ?? 0.5) - 0.5) - Math.abs((b.yes ?? 0.5) - 0.5))[0] || null;
  return { kind, count: lines.length, lines, pivot };
}

function parseLine(label) {
  const m = String(label).match(/([+-]?\d+(?:\.\d+)?)/);
  return m ? Number(m[1]) : null;
}

function buildImpliedShape({ moneyline, spreads, totals }) {
  const favoriteYes = moneyline?.favorite?.yes ?? null;
  const favored_side = moneyline?.favorite?.label ?? null;
  const spreadPivot = spreads?.pivot?.line ?? null;
  const totalPivot = totals?.pivot?.line ?? null;
  let central_thesis = 'Insufficient ML/spread/totals mass for a central thesis.';
  if (favoriteYes != null && favored_side) {
    const S = NBA_SHAPE_THRESHOLDS;
    const edge = favoriteYes >= S.clear_favorite
      ? 'clear favorite'
      : (favoriteYes >= S.lean_favorite ? 'lean favorite' : 'coin-flip ML');
    central_thesis = `${favored_side} is ${edge} (yes≈${favoriteYes})`
      + (spreadPivot != null ? `; spread pivot ${spreadPivot}` : '')
      + (totalPivot != null ? `; total pivot ${totalPivot}` : '')
      + '.';
  }
  return {
    favored_side,
    favorite_yes: favoriteYes,
    spread_pivot: spreadPivot,
    total_pivot: totalPivot,
    central_thesis
  };
}

function buildNbaCoherence({ moneyline, spreads, totals, matrix_status }) {
  const residuals = [];
  const fav = moneyline?.favorite?.yes ?? null;
  const spreadLine = spreads?.pivot?.line ?? null;
  const spreadYes = spreads?.pivot?.yes ?? null;
  const totalYes = totals?.pivot?.yes ?? null;

  const S = NBA_SHAPE_THRESHOLDS;

  if (fav != null && fav >= S.heavy_favorite && spreadLine != null
      && Math.abs(spreadLine) <= S.tight_spread_abs) {
    residuals.push({
      type: 'ml_vs_spread_tight',
      note: 'Heavy ML favorite with a tiny spread — check whether juice/alt lines are misaligned.',
      triggered_by: `fav>=${S.heavy_favorite} && |spread|<=${S.tight_spread_abs}`
    });
  }
  if (fav != null && fav <= S.near_even_ml && spreadLine != null
      && Math.abs(spreadLine) >= S.wide_spread_abs) {
    residuals.push({
      type: 'ml_vs_spread_wide',
      note: 'Near-even ML with a large spread is unusual — verify team mapping.',
      triggered_by: `fav<=${S.near_even_ml} && |spread|>=${S.wide_spread_abs}`
    });
  }
  if (totalYes != null && (totalYes > S.totals_extreme_high || totalYes < S.totals_extreme_low)
      && spreads?.count) {
    residuals.push({
      type: 'totals_extreme_vs_spread_present',
      note: 'Totals pivot is extreme while spreads exist — confirm tipoff/context before acting.',
      triggered_by: `total>${S.totals_extreme_high} || total<${S.totals_extreme_low}`
    });
  }

  return {
    coherence_status: residuals.length
      ? 'tension'
      : (matrix_status === 'complete' ? 'ok_heuristic' : 'incomplete_matrix'),
    cross_market_residuals: residuals,
    spread_yes_at_pivot: spreadYes,
    distribution_note: 'Heuristic only — not a player-prop or possession model.',
    // Ship the ruleset with the verdict so the buyer can audit the cutoffs.
    shape_thresholds: { ...NBA_SHAPE_THRESHOLDS }
  };
}

function compactRow(row) {
  return {
    title: row.title ?? null,
    group_item_title: row.group_item_title ?? null,
    slug: row.slug ?? null,
    yes: row.yes ?? null,
    no: row.no ?? null,
    best_ask: row.best_ask ?? null,
    best_bid: row.best_bid ?? null,
    spread: row.spread ?? null,
    volume_24h_usd: row.volume_24h_usd ?? null,
    sports_market_type: row.sports_market_type ?? null,
    is_primary: row.is_primary === true
  };
}

function groupBy(rows, keyFn) {
  const out = {};
  for (const row of rows) {
    const key = keyFn(row) || 'other';
    if (!out[key]) out[key] = [];
    out[key].push(row);
  }
  return out;
}
