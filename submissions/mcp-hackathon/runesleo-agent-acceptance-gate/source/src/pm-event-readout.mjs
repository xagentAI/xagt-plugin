// PM Event Readout (pm_event_readout) — L0 generic event evidence card.
// Framework: research/2026-07-09-pm-event-analyst-framework.md
// Rule-based + public Gamma (+ optional external anchors). No Leo relay / no orders.

import {
  fetchMarket,
  fetchEventBySlug,
  fetchEventBundleWithSiblings,
  eventSlugFromMarket,
  resolveMarketRef,
  round2,
  toNumber
} from './pm-gamma-market.mjs';
import { enrichMuskCategory, extractMuskSnapshot } from './pm-category-musk.mjs';
import { enrichFootballCategory, extractFootballFixture } from './pm-category-football.mjs';
import { enrichTennisCategory, extractTennisFixture } from './pm-category-tennis.mjs';
import { enrichWeatherCategory, extractWeatherSnapshot } from './pm-category-weather.mjs';
import { enrichNbaCategory, extractNbaFixture } from './pm-category-nba.mjs';
import { enrichPoliticsCategory } from './pm-category-politics.mjs';
import { enrichMacroFedCategory } from './pm-category-macro-fed.mjs';

const SERVICE_ID = 'pm_event_readout';
const SCHEMA_VERSION = '0.2';

const STANDARD_CAVEATS = [
  'Event readout only. Not investment advice; does not place or route orders.',
  'Separates event likelihood from trade attractiveness — use pm-trade-preflight or pm-decision-card for action.',
  'L0 core: Gamma matrix + optional public anchors. Category plugins (sports/weather/musk) are not required for generic events.'
];

const FED_HOLD_HINTS = [
  /no change in fed interest rates/i,
  /fed.*no change/i,
  /interest rates after the .+ meeting/i
];

/**
 * @param {object} input
 * @param {object} [options]
 * @param {typeof fetch} [options.fetchImpl]
 * @param {object[]} [options.externalAnchors] inject anchors in tests
 * @param {boolean} [options.includeMatrix=true]
 */
export async function assessPmEventReadoutLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const includeMatrix = input.include_matrix !== false && options.includeMatrix !== false;
  const marketRef = resolveMarketRef(input);
  const market = await fetchMarket(fetchImpl, marketRef);
  if (!market) {
    throw new Error('Market not found for the provided slug, condition_id, or market_url');
  }

  let eventBundle = null;
  const parentSlug = eventSlugFromMarket(market);
  if (includeMatrix && parentSlug) {
    try {
      // Football/tennis often split ML vs more-markets — merge siblings for serious matrix.
      eventBundle = await fetchEventBundleWithSiblings(fetchImpl, parentSlug);
    } catch {
      try {
        eventBundle = await fetchEventBySlug(fetchImpl, parentSlug);
      } catch {
        eventBundle = null;
      }
    }
  }

  const injectedAnchors = Array.isArray(options.externalAnchors) ? options.externalAnchors : null;
  const externalAnchors = injectedAnchors ?? await resolveExternalAnchors(market, eventBundle, fetchImpl);

  const readout = buildEventReadout(market, eventBundle, externalAnchors);
  const muskSnapshot = extractMuskSnapshot(input, options);
  const footballFixture = extractFootballFixture(input, options);
  const tennisFixture = extractTennisFixture(input, options);
  const weatherSnapshot = extractWeatherSnapshot(input, options);
  const nbaFixture = extractNbaFixture(input, options);
  const categoryPlugin = maybeApplyCategoryPlugin({
    readout,
    market,
    eventBundle,
    muskSnapshot,
    footballFixture,
    tennisFixture,
    weatherSnapshot,
    nbaFixture,
    enrichCategory: input.enrich_category !== false && options.enrichCategory !== false
  });

  // Category plugins may tighten tradability (fixture/matrix honesty).
  let tradability = readout.tradability;
  let tradability_reasons = [...(readout.tradability_reasons || [])];
  if (categoryPlugin.category_plugin?.tradability_cap) {
    tradability = capTradability(tradability, categoryPlugin.category_plugin.tradability_cap);
    tradability_reasons = [
      ...tradability_reasons,
      ...(categoryPlugin.category_plugin.tradability_reasons || [])
    ];
  }

  return {
    schema_version: SCHEMA_VERSION,
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      market_url: input.market_url ?? null,
      condition_id: marketRef.condition_id,
      slug: marketRef.slug,
      include_matrix: includeMatrix,
      enrich_category: input.enrich_category !== false,
      musk: muskSnapshot,
      football: footballFixture,
      tennis: tennisFixture,
      nba: nbaFixture
    },
    ...readout,
    tradability,
    tradability_reasons,
    ...categoryPlugin,
    caveats: [
      ...STANDARD_CAVEATS,
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'football'
        ? ['Football plugin applied: sibling more-markets merged; fixture gate + expression comparison. Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'tennis'
        ? ['Tennis plugin applied: format + named ML + set handicap/totals + domination check. Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'nba'
        ? ['NBA plugin applied: moneyline/spread/totals matrix + heuristic coherence. Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'nfl'
        ? ['NFL plugin applied (same ML/spread/totals matrix shape as NBA L1). Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'ufc'
        ? ['UFC/MMA plugin applied (fight moneyline-focused matrix via US-sports L1). Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'mlb'
        ? ['MLB plugin applied (ML/spread/totals matrix via US-sports L1). Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'politics'
        ? ['Politics plugin applied: candidate yes-mass leaderboard + exclusivity sanity. Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'macro_fed'
        ? ['Macro Fed plugin applied: rate-decision ladder + expected-move heuristic. Not a buy tip.']
        : []),
      ...(categoryPlugin.category_depth === 'enriched' && categoryPlugin.category === 'musk'
        ? ['Musk ladder plugin applied (shape demo). Prefer football/tennis/nba for sports depth.']
        : [])
    ],
    next_gate: 'Use_pm_trade_preflight_or_manual_decision_card_before_orders',
    source: {
      provider: 'polymarket_gamma_public_api',
      fields: ['outcomePrices', 'volume24hr', 'oneDayPriceChange', 'endDate', 'bestBid/Ask', 'events', 'event.markets', 'siblings'],
      framework: categoryPlugin.category_depth === 'enriched'
        ? `pm-event-analyst-framework-L0+L1-${categoryPlugin.category}`
        : 'pm-event-analyst-framework-L0'
    }
  };
}

function capTradability(current, maxLevel) {
  const order = ['weak', 'low', 'medium', 'high'];
  return order[Math.min(order.indexOf(current), order.indexOf(maxLevel))];
}

function maybeApplyCategoryPlugin({
  readout,
  market,
  eventBundle,
  muskSnapshot,
  footballFixture,
  tennisFixture,
  weatherSnapshot,
  nbaFixture,
  enrichCategory
}) {
  if (!enrichCategory) {
    return {
      category_depth: 'core_only',
      category_plugin: null
    };
  }
  if (readout.category === 'football') {
    const plugin = enrichFootballCategory({
      market,
      eventBundle,
      eventMatrix: readout.event_matrix,
      fixture: footballFixture
    });
    return {
      category: plugin.category,
      category_depth: plugin.category_depth,
      // Football plugin owns matrix honesty when enriched
      matrix_status: plugin.matrix_status,
      missing_market_groups: plugin.missing_market_groups,
      related_market_count: plugin.related_market_count,
      category_plugin: plugin
    };
  }
  if (readout.category === 'tennis') {
    const plugin = enrichTennisCategory({
      market,
      eventBundle,
      eventMatrix: readout.event_matrix,
      fixture: tennisFixture
    });
    return {
      category: plugin.category,
      category_depth: plugin.category_depth,
      matrix_status: plugin.matrix_status,
      missing_market_groups: plugin.missing_market_groups,
      related_market_count: plugin.related_market_count,
      category_plugin: plugin
    };
  }
  if (readout.category === 'nba' || readout.category === 'nfl' || readout.category === 'ufc' || readout.category === 'mlb') {
    const plugin = enrichNbaCategory({
      market,
      eventBundle,
      eventMatrix: readout.event_matrix,
      fixture: nbaFixture
    });
    if (readout.category === 'nfl' || readout.category === 'ufc' || readout.category === 'mlb') {
      plugin.category = readout.category;
      plugin.skill_alignment = {
        ...(plugin.skill_alignment || {}),
        source: `sports_generalization_${readout.category}_via_us_sports_l1_matrix`
      };
    }
    return {
      category: plugin.category,
      category_depth: plugin.category_depth,
      matrix_status: plugin.matrix_status,
      missing_market_groups: plugin.missing_market_groups,
      related_market_count: plugin.related_market_count,
      category_plugin: plugin
    };
  }
  if (readout.category === 'weather') {
    const plugin = enrichWeatherCategory({
      market,
      eventBundle,
      eventMatrix: readout.event_matrix,
      snapshot: weatherSnapshot
    });
    return {
      category: plugin.category,
      category_depth: plugin.category_depth,
      category_plugin: plugin
    };
  }
  if (readout.category === 'musk') {
    const plugin = enrichMuskCategory({
      market,
      eventBundle,
      eventMatrix: readout.event_matrix,
      snapshot: muskSnapshot
    });
    return {
      category: plugin.category,
      category_depth: plugin.category_depth,
      category_plugin: plugin
    };
  }
  if (readout.category === 'politics') {
    const plugin = enrichPoliticsCategory({
      market,
      eventBundle,
      eventMatrix: readout.event_matrix
    });
    return {
      category: plugin.category,
      category_depth: plugin.category_depth,
      category_plugin: plugin
    };
  }
  if (readout.category === 'macro_fed') {
    const plugin = enrichMacroFedCategory({
      market,
      eventBundle,
      eventMatrix: readout.event_matrix
    });
    return {
      category: plugin.category,
      category_depth: plugin.category_depth,
      category_plugin: plugin
    };
  }
  return {
    category_depth: 'core_only',
    category_plugin: null
  };
}

export function buildPmEventReadoutFallback(input = {}) {
  return {
    schema_version: SCHEMA_VERSION,
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      market_url: input?.market_url ?? null,
      slug: input?.slug ?? 'demo-market',
      include_matrix: true
    },
    event: 'Demo event',
    event_slug: null,
    market: 'Demo market (live data unavailable)',
    current_price: { yes: 0.42, no: 0.58 },
    event_time: null,
    event_time_source: null,
    fixture_status: 'unknown',
    market_fixture_match: 'unknown',
    category: 'generic',
    category_depth: 'core_only',
    plugins_available: ['football', 'tennis', 'nba', 'nfl', 'ufc', 'mlb', 'politics', 'macro_fed', 'weather', 'musk'],
    sources_read: ['static_fallback'],
    base_case: 'Demo readout only.',
    key_uncertainties: ['live_data_unavailable'],
    market_implied_view: 'Demo mode — no live implied view.',
    what_is_already_priced: null,
    what_may_not_be_priced: null,
    event_matrix: [],
    matrix_status: 'incomplete',
    related_market_count: 0,
    missing_market_groups: ['live_event_lookup_unavailable'],
    external_anchors: [],
    tradability: 'weak',
    tradability_reasons: ['live_data_unavailable'],
    next_decision_card_needed: 'no',
    hard_gate: 'no_orders_no_account_mutation',
    caveats: [...STANDARD_CAVEATS, 'Demo mode: do not trade on this response.'],
    next_gate: 'Use_pm_trade_preflight_or_manual_decision_card_before_orders',
    source: { provider: 'static_fallback' }
  };
}

function buildEventReadout(market, eventBundle, externalAnchors) {
  const yesIdx = market.outcomes.findIndex((o) => String(o).toLowerCase() === 'yes');
  const noIdx = market.outcomes.findIndex((o) => String(o).toLowerCase() === 'no');
  const primaryIdx = yesIdx >= 0 ? yesIdx : 0;
  const primaryOutcome = market.outcomes[primaryIdx] ?? 'Yes';
  const primaryPrice = Number.isFinite(market.outcome_prices[primaryIdx])
    ? market.outcome_prices[primaryIdx]
    : null;

  const prices = {};
  if (yesIdx >= 0 && Number.isFinite(market.outcome_prices[yesIdx])) {
    prices.yes = round2(market.outcome_prices[yesIdx]);
  }
  if (noIdx >= 0 && Number.isFinite(market.outcome_prices[noIdx])) {
    prices.no = round2(market.outcome_prices[noIdx]);
  }
  // Tennis / named two-way markets: expose both sides when Yes/No absent.
  if (prices.yes == null && prices.no == null && market.outcomes?.length >= 2) {
    prices.named = market.outcomes.map((label, idx) => ({
      label: String(label),
      price: Number.isFinite(market.outcome_prices[idx]) ? round2(market.outcome_prices[idx]) : null
    }));
    if (Number.isFinite(market.outcome_prices[0])) prices.outcome_0 = round2(market.outcome_prices[0]);
    if (Number.isFinite(market.outcome_prices[1])) prices.outcome_1 = round2(market.outcome_prices[1]);
  }

  const matrixInfo = buildEventMatrix(market, eventBundle);
  const category = detectCategory(market, eventBundle);
  const { tradability, tradability_reasons } = scoreTradability(market, matrixInfo, externalAnchors);
  const implied = buildImpliedView(market, primaryOutcome, primaryPrice, matrixInfo);
  const priced = buildPricedInNotes(market, primaryPrice, matrixInfo, externalAnchors);
  const uncertainties = buildUncertainties(market, matrixInfo, externalAnchors);
  const sources = ['polymarket_gamma_market_metadata'];
  if (eventBundle?.slug) sources.push(`polymarket_gamma_event:${eventBundle.slug}`);
  for (const anchor of externalAnchors) {
    if (anchor?.id) sources.push(`external_anchor:${anchor.id}`);
  }

  const eventTitle = eventBundle?.title || market.events?.[0]?.title || market.title;
  const eventSlug = eventBundle?.slug || eventSlugFromMarket(market);

  // Tennis fixture gate overrides L0's naive endDate→ok mapping.
  if (category === 'tennis' && !eventBundle?.start_time && !market.start_time) {
    // leave as-is; L1 plugin will set honest fixture
  }

  return {
    event: eventTitle,
    event_slug: eventSlug,
    market: market.slug,
    market_title: market.title,
    group_item_title: market.group_item_title,
    current_price: prices,
    event_time: market.end_date,
    event_time_source: market.end_date ? 'polymarket_gamma_endDate' : null,
    fixture_status: market.end_date ? 'ok' : 'unknown',
    market_fixture_match: eventSlug ? 'ok' : 'single_market_no_parent_event',
    category,
    category_depth: 'core_only',
    plugins_available: ['football', 'tennis', 'nba', 'nfl', 'ufc', 'mlb', 'politics', 'macro_fed', 'weather', 'musk'],
    sources_read: sources,
    base_case: primaryPrice !== null
      ? `Market prices "${primaryOutcome}" at ${round2(primaryPrice)} (${Math.round(primaryPrice * 100)}% implied).`
      : 'Outcome prices unavailable from Gamma.',
    key_uncertainties: uncertainties,
    market_implied_view: implied,
    what_is_already_priced: priced.already,
    what_may_not_be_priced: priced.may_not,
    event_matrix: matrixInfo.event_matrix,
    matrix_status: matrixInfo.matrix_status,
    related_market_count: matrixInfo.related_market_count,
    missing_market_groups: matrixInfo.missing_market_groups,
    external_anchors: externalAnchors,
    tradability,
    tradability_reasons,
    next_decision_card_needed: ['medium', 'high'].includes(tradability) ? 'yes' : 'no',
    hard_gate: 'no_orders_no_account_mutation'
  };
}

function buildEventMatrix(primaryMarket, eventBundle) {
  if (!eventBundle?.markets?.length) {
    return {
      event_matrix: [matrixRow(primaryMarket, true)],
      matrix_status: 'incomplete',
      related_market_count: 1,
      missing_market_groups: ['parent_event_not_resolved']
    };
  }

  const rows = eventBundle.markets
    .map((m) => matrixRow(m, m.condition_id === primaryMarket.condition_id))
    .sort((a, b) => (b.volume_24h_usd || 0) - (a.volume_24h_usd || 0));

  const missing = [];
  if (rows.length < 2) missing.push('expected_multi_outcome_event_but_only_one_market');

  // Soft check for FOMC-style brackets when category looks macro_fed
  const titles = rows.map((r) => `${r.title} ${r.group_item_title || ''}`.toLowerCase());
  const looksFed = titles.some((t) => t.includes('fed') || t.includes('bps') || t.includes('no change'));
  if (looksFed) {
    const hasHold = titles.some((t) => t.includes('no change'));
    const hasHike25 = titles.some((t) => t.includes('25') && t.includes('increase'));
    const hasCut25 = titles.some((t) => t.includes('25') && t.includes('decrease'));
    if (!hasHold) missing.push('fed_bracket_missing_no_change');
    if (!hasHike25) missing.push('fed_bracket_missing_25bps_increase');
    if (!hasCut25) missing.push('fed_bracket_missing_25bps_decrease');
  }

  return {
    event_matrix: rows,
    matrix_status: missing.length ? 'incomplete' : 'complete',
    related_market_count: rows.length,
    missing_market_groups: missing
  };
}

function matrixRow(market, isPrimary) {
  const yesIdx = market.outcomes.findIndex((o) => String(o).toLowerCase() === 'yes');
  const overIdx = market.outcomes.findIndex((o) => /^over/i.test(String(o)));
  const primaryIdx = yesIdx >= 0 ? yesIdx : (overIdx >= 0 ? overIdx : 0);
  const yes = Number.isFinite(market.outcome_prices[primaryIdx])
    ? round2(market.outcome_prices[primaryIdx])
    : null;

  const named_outcomes = (market.outcomes || []).map((label, idx) => ({
    label: String(label),
    price: Number.isFinite(market.outcome_prices[idx]) ? round2(market.outcome_prices[idx]) : null
  }));

  return {
    slug: market.slug,
    condition_id: market.condition_id,
    title: market.title,
    group_item_title: market.group_item_title,
    sports_market_type: market.sports_market_type,
    outcomes: market.outcomes || [],
    named_outcomes,
    yes,
    volume_24h_usd: round2(market.volume_24hr),
    best_bid: market.best_bid,
    best_ask: market.best_ask,
    spread: market.spread !== null ? round2(market.spread) : null,
    active: market.active,
    closed: market.closed,
    is_primary: Boolean(isPrimary)
  };
}

function scoreTradability(market, matrixInfo, externalAnchors) {
  const reasons = [];
  if (market.closed || !market.active) {
    return { tradability: 'weak', tradability_reasons: ['market_closed_or_inactive'] };
  }
  if (!market.outcome_prices.length || market.outcome_prices.every((p) => !Number.isFinite(p))) {
    return { tradability: 'weak', tradability_reasons: ['missing_outcome_prices'] };
  }

  let level = 'medium';
  if (market.volume_24hr < 1_000) {
    level = 'weak';
    reasons.push('volume_24h_below_1000');
  } else if (market.volume_24hr < 5_000) {
    level = 'low';
    reasons.push('volume_24h_below_5000');
  } else if (market.volume_24hr >= 50_000 && (market.spread === null || market.spread <= 0.03)) {
    level = 'high';
    reasons.push('high_volume_tight_spread');
  } else {
    reasons.push('adequate_liquidity');
  }

  if (market.spread !== null && market.spread > 0.06) {
    level = downgrade(level);
    reasons.push('wide_spread');
  }

  if (matrixInfo.matrix_status === 'incomplete') {
    level = capAt(level, 'medium');
    reasons.push('matrix_incomplete');
  }

  const conflict = externalAnchors.some((a) => a?.status === 'conflict' || a?.agreement === 'disagree');
  if (conflict) {
    level = capAt(level, 'medium');
    reasons.push('external_anchor_conflict');
  }

  const unavailableMacro = externalAnchors.some(
    (a) => a?.id === 'cme_fedwatch_style' && a?.status === 'unavailable'
  );
  if (unavailableMacro && detectCategory(market, null) === 'macro_fed') {
    level = capAt(level, 'medium');
    reasons.push('macro_anchor_unavailable');
  }

  return { tradability: level, tradability_reasons: reasons };
}

function downgrade(level) {
  if (level === 'high') return 'medium';
  if (level === 'medium') return 'low';
  if (level === 'low') return 'weak';
  return 'weak';
}

function capAt(level, maxLevel) {
  const order = ['weak', 'low', 'medium', 'high'];
  return order[Math.min(order.indexOf(level), order.indexOf(maxLevel))];
}

function buildImpliedView(market, primaryOutcome, primaryPrice, matrixInfo) {
  if (primaryPrice === null) return 'Implied probabilities unavailable.';
  const pct = Math.round(primaryPrice * 100);
  let view = `Market implies ~${pct}% on "${primaryOutcome}".`;
  if (market.one_day_price_change !== null) {
    const pts = round2(market.one_day_price_change * 100);
    view += ` 24h change: ${pts >= 0 ? '+' : ''}${pts} pts on primary outcome.`;
  }
  if (matrixInfo.related_market_count > 1) {
    const tops = matrixInfo.event_matrix
      .filter((row) => row.yes !== null)
      .slice()
      .sort((a, b) => b.yes - a.yes)
      .slice(0, 3)
      .map((row) => `${row.group_item_title || row.title}: ${Math.round(row.yes * 100)}%`)
      .join('; ');
    if (tops) view += ` Same-event top brackets — ${tops}.`;
  }
  return view;
}

function buildPricedInNotes(market, primaryPrice, matrixInfo, externalAnchors) {
  const already = [];
  const may_not = [];

  if (primaryPrice !== null) {
    if (primaryPrice >= 0.85) {
      already.push('High consensus — outcome treated as likely by this market.');
    } else if (primaryPrice <= 0.15) {
      already.push('Low base rate — outcome treated as unlikely by this market.');
    } else if (primaryPrice > 0.35 && primaryPrice < 0.65) {
      may_not.push('Mid-range price on primary — meaningful room for news to move odds.');
    } else if (primaryPrice >= 0.65) {
      already.push('Primary outcome is majority-priced (>65%); residual mass sits in other brackets or No.');
    } else {
      already.push('Primary outcome is minority-priced (<35%); upside is in a re-rating, not a consensus hold.');
    }
  }

  if (market.one_day_price_change !== null && Math.abs(market.one_day_price_change) >= 0.03) {
    already.push('Recent 24h probability move may reflect fresh public information.');
  } else {
    may_not.push('Quiet 24h move — stale narrative risk if you rely on old headlines.');
  }

  if (market.volume_24hr < 5_000) {
    may_not.push('Thin liquidity — price may not reflect full information set.');
  }

  if (matrixInfo.related_market_count > 1) {
    already.push(`Same-event matrix has ${matrixInfo.related_market_count} markets (see event_matrix).`);
  }

  for (const anchor of externalAnchors) {
    if (anchor?.status === 'ok' && typeof anchor.hold_prob === 'number' && primaryPrice !== null) {
      const gap = round2(primaryPrice - anchor.hold_prob);
      if (Math.abs(gap) >= 0.08) {
        may_not.push(
          `Cross-venue gap vs ${anchor.id}: Polymarket primary ${round2(primaryPrice)} vs anchor hold ${round2(anchor.hold_prob)} (Δ ${gap >= 0 ? '+' : ''}${gap}).`
        );
      } else {
        already.push(`Roughly aligned with ${anchor.id} hold≈${round2(anchor.hold_prob)}.`);
      }
    }
    if (anchor?.status === 'unavailable') {
      may_not.push(`${anchor.id} unavailable — ${anchor.detail || 'no live fetch'}.`);
    }
  }

  return {
    already: already.length ? already.join(' ') : 'No strong priced-in flags from metadata alone.',
    may_not: may_not.length ? may_not.join(' ') : 'External lineup/news not fully scanned by this endpoint.'
  };
}

function buildUncertainties(market, matrixInfo, externalAnchors) {
  const items = [];
  if (market.end_date) items.push(`Resolution timing: ${market.end_date}`);
  if (market.one_day_price_change === null) {
    items.push('24h price change missing on Gamma — quiet or illiquid market.');
  }
  if (market.spread !== null && market.spread > 0.04) {
    items.push(`Wide spread (~${round2(market.spread)}) — execution uncertainty.`);
  }
  if (matrixInfo.matrix_status === 'incomplete') {
    items.push(`Matrix incomplete: ${(matrixInfo.missing_market_groups || []).join(', ') || 'unknown'}.`);
  }
  if (externalAnchors.some((a) => a?.agreement === 'disagree')) {
    items.push('External anchor disagrees with Polymarket primary — do not treat tradability as high.');
  }
  items.push('Category plugins (lineup/weather/Musk ladder) not applied in L0 core_only depth.');
  return items;
}

function detectCategory(market, eventBundle) {
  const blob = [
    market?.title,
    market?.slug,
    market?.group_item_title,
    eventBundle?.title,
    eventBundle?.slug,
    eventBundle?.description
  ].filter(Boolean).join(' ').toLowerCase();

  // Esports first — short tokens like "atp" must not steal CS/Dota titles (e.g. "Atputies").
  if (/\bcounter[-\s]?strike\b|\bcs:?go\b|\bcs2\b|\bdota\b|\bleague of legends\b|\bvalorant\b|\besports?\b|\bmap\s*\d\b/.test(blob)) {
    return 'generic';
  }

  if (/\bfed\b|\bfomc\b|federal funds|interest rates after the .+ meeting|\bbps\b/.test(blob)) {
    return 'macro_fed';
  }
  if (/\btennis\b|\batp\b|\bwta\b|\bwimbledon\b/.test(blob)) return 'tennis';
  if (/\bnba\b|\bbasketball\b|\bwnba\b/.test(blob)) return 'nba';
  if (/\bnfl\b|super bowl|american football/.test(blob)) return 'nfl';
  if (/\bufc\b|\bmma\b|bellator|fight night/.test(blob)) return 'ufc';
  if (/\bmlb\b|\bbaseball\b|world series/.test(blob)) return 'mlb';
  if (/\bfootball\b|\bsoccer\b|\bfifa\b|\bfifwc\b|world.?cup|\bpremier league\b|\buefa\b|\bepl\b|\bucl\b|\bla liga\b|\bserie a\b|\bbundesliga\b|\bmls\b/.test(blob)) {
    return 'football';
  }
  if (/\btemperature\b|\bweather\b|°f|°c|\bhigh temp\b/.test(blob)) return 'weather';
  if (/musk|elon.*tweet|tweets in|# tweets/.test(blob)) return 'musk';
  if (/\bpresident\b|\belection\b|\bnominee\b|\bprimary\b|\bsenate\b|\bgovernor\b|\bparliament\b|prime minister|\belectoral\b/.test(blob)) {
    return 'politics';
  }
  return 'generic';
}

/**
 * External anchors: v1 only attempts macro_fed style comparison when the market
 * looks like a Fed hold bracket. Live CME HTML is not scraped (fragile); callers
 * may inject anchors via options.externalAnchors. Without injection we emit an
 * explicit unavailable stub so tradability stays honest.
 */
async function resolveExternalAnchors(market, eventBundle, fetchImpl) {
  const category = detectCategory(market, eventBundle);
  if (category !== 'macro_fed') return [];

  const title = `${market.title} ${market.group_item_title || ''}`;
  const isHoldBracket = FED_HOLD_HINTS.some((re) => re.test(title))
    || /no change/i.test(market.group_item_title || '');

  if (!isHoldBracket) {
    return [{
      id: 'cme_fedwatch_style',
      status: 'skipped',
      detail: 'Not a hold/no-change bracket — inject anchors or use full FOMC matrix comparison later.',
      hold_prob: null,
      agreement: null
    }];
  }

  // Optional: allow env/test injection only path for live numbers.
  // Attempt a best-effort public JSON if LEO_FEDWATCH_JSON_URL is set.
  const url = typeof process !== 'undefined' ? process.env?.LEO_FEDWATCH_JSON_URL : null;
  if (url) {
    try {
      const payload = await fetchJsonLoose(fetchImpl, url);
      const hold = toNumber(payload?.hold_prob ?? payload?.hold ?? payload?.no_change);
      if (hold > 0 && hold <= 1) {
        const yesIdx = market.outcomes.findIndex((o) => String(o).toLowerCase() === 'yes');
        const pm = yesIdx >= 0 ? market.outcome_prices[yesIdx] : market.outcome_prices[0];
        const gap = Number.isFinite(pm) ? Math.abs(pm - hold) : null;
        return [{
          id: 'cme_fedwatch_style',
          status: 'ok',
          source_url: url,
          hold_prob: round2(hold),
          as_of: payload?.as_of ?? null,
          agreement: gap !== null && gap >= 0.08 ? 'disagree' : 'agree',
          detail: payload?.detail ?? null
        }];
      }
    } catch {
      // fall through to unavailable
    }
  }

  return [{
    id: 'cme_fedwatch_style',
    status: 'unavailable',
    hold_prob: null,
    agreement: null,
    detail: 'No LEO_FEDWATCH_JSON_URL configured; set a JSON {hold_prob, as_of} feed or pass options.externalAnchors for live comparison.',
    suggested_manual_check: [
      'https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html',
      'https://www.investing.com/central-banks/fed-rate-monitor'
    ]
  }];
}

async function fetchJsonLoose(fetchImpl, url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetchImpl(url, {
      signal: controller.signal,
      headers: { accept: 'application/json' }
    });
    if (!response.ok) throw new Error(`anchor ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}
