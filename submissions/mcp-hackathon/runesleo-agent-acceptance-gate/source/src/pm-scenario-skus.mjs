// Scenario SKUs — productize category plugins as searchable ASP surfaces.
// Each wraps pm-event-readout with a fixed scenario + optional query discovery.

import {
  assessPmEventReadoutLive,
  buildPmEventReadoutFallback
} from './pm-event-readout.mjs';
import {
  GAMMA_BASE,
  resolveMarketRef,
  fetchJson
} from './pm-gamma-market.mjs';
import {
  queryRequiresEntityMatch,
  scoreSemanticMatch
} from './pm-semantic-match.mjs';

const STRONG_ENTITY_SEMANTIC_THRESHOLD = 4.5;

const SCENARIOS = {
  weather_event_readout: {
    service_id: 'weather_event_readout',
    expected: ['weather'],
    default_query: 'temperature high',
    query_variants: ['temperature high', 'high temperature', 'weather', 'temperature'],
    tag_slugs: ['weather'],
    category_keywords: ['weather', 'temperature', 'high temperature'],
    zh_name: '天气温度阶梯',
    sample: {
      query: 'temperature',
      weather: { city: 'NYC', snapshot_time: '2026-07-24T12:00:00Z', observed_temp_f: 84 }
    }
  },
  politics_event_readout: {
    service_id: 'politics_event_readout',
    expected: ['politics'],
    default_query: 'presidential election',
    query_variants: ['presidential election', 'election', 'politics', 'senate', 'governor'],
    tag_slugs: ['politics', 'elections'],
    category_keywords: ['politics', 'election', 'presidential election', 'senate'],
    zh_name: '政治选举盘口',
    sample: { query: 'president' }
  },
  macro_fed_readout: {
    service_id: 'macro_fed_readout',
    expected: ['macro_fed'],
    default_query: 'fed interest rates',
    query_variants: ['fed interest rates', 'fed decision', 'fomc', 'interest rates', 'rate cut'],
    tag_slugs: ['fed', 'federal-reserve', 'economics', 'macro'],
    category_keywords: ['fed', 'fomc', 'interest rates', 'rate cut', 'rate hike'],
    zh_name: '美联储利率宏观',
    sample: { query: 'fed rates' }
  },
  football_match_card: {
    service_id: 'football_match_card',
    expected: ['football'],
    default_query: 'premier league',
    query_variants: ['premier league', 'football', 'soccer', 'champions league', 'epl'],
    tag_slugs: ['soccer', 'football', 'epl', 'premier-league', 'ucl', 'champions-league'],
    category_keywords: ['football', 'soccer', 'premier league', 'uefa', 'fifa'],
    zh_name: '足球比赛卡',
    sample: {
      query: 'premier league',
      football: { verified: false }
    }
  },
  tennis_match_card: {
    service_id: 'tennis_match_card',
    expected: ['tennis'],
    default_query: 'atp tennis',
    // Prefer multi-token tennis queries; bare "atp" alone historically mis-hit esports names like "Atputies".
    query_variants: ['atp tennis', 'wta tennis', 'tennis match', 'wimbledon tennis', 'tennis'],
    tag_slugs: ['tennis', 'atp', 'wta'],
    category_keywords: ['tennis', 'atp', 'wta', 'wimbledon'],
    zh_name: '网球比赛卡',
    sample: {
      query: 'atp',
      tennis: { verified: false }
    }
  },
  nba_match_card: {
    service_id: 'nba_match_card',
    expected: ['nba'],
    default_query: 'nba',
    query_variants: ['nba', 'basketball', 'nba finals', 'lakers', 'celtics'],
    tag_slugs: ['nba', 'basketball'],
    category_keywords: ['nba', 'basketball', 'wnba'],
    zh_name: 'NBA 比赛卡',
    sample: {
      query: 'nba',
      nba: { verified: false }
    }
  }
};

export function listScenarioSkuIds() {
  return Object.keys(SCENARIOS);
}

export function samplePayloadForScenario(serviceId) {
  return SCENARIOS[serviceId]?.sample ?? { query: 'all' };
}

export async function assessWeatherEventReadoutLive(input = {}, options = {}) {
  return assessScenarioSkuLive('weather_event_readout', input, options);
}
export async function assessPoliticsEventReadoutLive(input = {}, options = {}) {
  return assessScenarioSkuLive('politics_event_readout', input, options);
}
export async function assessMacroFedReadoutLive(input = {}, options = {}) {
  return assessScenarioSkuLive('macro_fed_readout', input, options);
}
export async function assessFootballMatchCardLive(input = {}, options = {}) {
  return assessScenarioSkuLive('football_match_card', input, options);
}
export async function assessTennisMatchCardLive(input = {}, options = {}) {
  return assessScenarioSkuLive('tennis_match_card', input, options);
}
export async function assessNbaMatchCardLive(input = {}, options = {}) {
  return assessScenarioSkuLive('nba_match_card', input, options);
}

export function buildWeatherEventReadoutFallback(input = {}) {
  return buildScenarioFallback('weather_event_readout', input);
}
export function buildPoliticsEventReadoutFallback(input = {}) {
  return buildScenarioFallback('politics_event_readout', input);
}
export function buildMacroFedReadoutFallback(input = {}) {
  return buildScenarioFallback('macro_fed_readout', input);
}
export function buildFootballMatchCardFallback(input = {}) {
  return buildScenarioFallback('football_match_card', input);
}
export function buildTennisMatchCardFallback(input = {}) {
  return buildScenarioFallback('tennis_match_card', input);
}
export function buildNbaMatchCardFallback(input = {}) {
  return buildScenarioFallback('nba_match_card', input);
}

async function assessScenarioSkuLive(scenarioKey, input = {}, options = {}) {
  const spec = SCENARIOS[scenarioKey];
  if (!spec) throw new Error(`Unknown scenario ${scenarioKey}`);
  const fetchImpl = options.fetchImpl ?? fetch;

  const resolvedInput = await resolveScenarioInput(input, spec, fetchImpl);
  if (resolvedInput._unavailable) {
    return buildScenarioUnavailable(spec, input, resolvedInput);
  }
  const base = await assessPmEventReadoutLive(resolvedInput, {
    ...options,
    fetchImpl,
    enrichCategory: true
  });

  const category = base.category || base.category_plugin?.category || 'generic';
  const expected_ok = spec.expected.includes(category);
  const caveats = [
    ...(base.caveats || []),
    `Scenario SKU ${spec.service_id}: expects ${spec.expected.join('|')}; detected ${category}.`
  ];
  if (!expected_ok) {
    caveats.push(
      `Category mismatch: this SKU is for ${spec.zh_name}; detected "${category}". Results may be core_only — pick a matching market or use /pm-event-readout.`
    );
  }
  caveats.push(
    'Paid-value note: this is a scenario entry SKU over /pm-event-readout + category plugin — pay again when the event/market changes, not for a different wrapper of the same frozen card.'
  );

  return {
    ...base,
    schema_version: '0.1',
    service_id: spec.service_id,
    scenario: {
      id: spec.service_id,
      zh_name: spec.zh_name,
      expected_categories: spec.expected,
      detected_category: category,
      expected_ok,
      resolved_via: resolvedInput._resolved_via || 'caller_ref',
      query: resolvedInput._query || null
    },
    buyer_summary_zh: buildScenarioBuyerSummaryZh(spec, base, expected_ok),
    caveats,
    next_gate: 'Use_pm_trade_preflight_before_orders',
    source: {
      ...(base.source || {}),
      scenario_sku: spec.service_id,
      method: 'pm_event_readout_scenario_wrapper'
    }
  };
}

function buildScenarioFallback(scenarioKey, input = {}) {
  const spec = SCENARIOS[scenarioKey];
  const base = buildPmEventReadoutFallback(input);
  return {
    ...base,
    service_id: spec.service_id,
    scenario: {
      id: spec.service_id,
      zh_name: spec.zh_name,
      expected_categories: spec.expected,
      detected_category: null,
      expected_ok: false,
      resolved_via: 'fallback'
    },
    buyer_summary_zh: `演示回退：${spec.zh_name} 实时行情不可用。请传 market_url/slug 或 query。`,
    mode: 'public_safe_demo'
  };
}

async function resolveScenarioInput(input, spec, fetchImpl) {
  const ref = resolveMarketRef(input);
  if (ref.slug || ref.condition_id) {
    return { ...input, _resolved_via: 'caller_ref' };
  }

  const query = String(input.query ?? input.market ?? input.topic ?? spec.default_query).trim();
  const preferredSurface = preferredSurfaceForScenario(spec.service_id);
  const queryDiscovery = await discoverSlug(fetchImpl, buildQueryVariants(query, spec), spec.expected, {
    originalQuery: query,
    preferredSurface
  });
  if (queryDiscovery.slug) {
    return {
      ...input,
      slug: queryDiscovery.slug,
      _resolved_via: queryDiscovery.query === query ? 'public_search' : 'query_variant',
      _query: query,
      _discovery: queryDiscovery.discovery
    };
  }

  const categoryDiscovery = await discoverCategoryDefault(fetchImpl, spec, {
    originalQuery: query,
    preferredSurface
  });
  if (categoryDiscovery.slug) {
    return {
      ...input,
      slug: categoryDiscovery.slug,
      _resolved_via: 'category_default',
      _query: query || spec.default_query,
      _discovery: {
        query_attempts: queryDiscovery.discovery,
        category_default: categoryDiscovery.discovery
      }
    };
  }

  if (!queryDiscovery.hadSuccessfulFetch && !categoryDiscovery.hadSuccessfulFetch) {
    const detail = queryDiscovery.errors[0] || categoryDiscovery.errors[0] || 'unknown upstream failure';
    throw new Error(`Scenario discovery upstream unavailable for ${spec.service_id}: ${detail}`);
  }

  return {
    ...input,
    _unavailable: true,
    _resolved_via: 'no_active_markets',
    _query: query || spec.default_query,
    _discovery: {
      query_attempts: queryDiscovery.discovery,
      category_default: categoryDiscovery.discovery
    }
  };
}

async function discoverSlug(fetchImpl, queryVariants, expectedCategories, options = {}) {
  const originalQuery = String(options.originalQuery ?? queryVariants?.[0] ?? '').trim();
  const preferredSurface = options.preferredSurface || null;
  const requiresEntity = queryRequiresEntityMatch(originalQuery);
  const discovery = {
    method: null,
    query_variants: [],
    candidates_seen: 0,
    preferred_surface: preferredSurface,
    semantic_entity_required: requiresEntity,
    semantic_threshold: requiresEntity ? STRONG_ENTITY_SEMANTIC_THRESHOLD : null
  };
  const errors = [];
  let hadSuccessfulFetch = false;

  for (const query of queryVariants) {
    discovery.query_variants.push(query);
    try {
      const result = await fetchJson(
        fetchImpl,
        `${GAMMA_BASE}/public-search?q=${encodeURIComponent(query)}&events_status=active&limit_per_type=12`
      );
      hadSuccessfulFetch = true;
      const candidates = collectEventMarketCandidates(
        Array.isArray(result?.events) ? result.events : [],
        expectedCategories,
        originalQuery,
        preferredSurface
      );
      discovery.candidates_seen += candidates.length;
      const best = pickBestCandidate(candidates, { requiresEntity, preferredSurface });
      if (best) {
        return {
          slug: best.slug,
          query,
          discovery: {
            ...discovery,
            method: `public-search:${query}`,
            selected: best.slug,
            selected_semantic_score: best.semantic_score,
            selected_surface: best.surface
          },
          hadSuccessfulFetch,
          errors
        };
      }
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }

  return { slug: null, query: null, discovery, hadSuccessfulFetch, errors };
}

async function discoverCategoryDefault(fetchImpl, spec, options = {}) {
  const originalQuery = String(options.originalQuery ?? '').trim();
  const preferredSurface = options.preferredSurface || null;
  const requiresEntity = queryRequiresEntityMatch(originalQuery);
  const discovery = {
    method: null,
    tag_slugs: [],
    category_keywords: [],
    candidates_seen: 0,
    preferred_surface: preferredSurface,
    semantic_entity_required: requiresEntity,
    semantic_threshold: requiresEntity ? STRONG_ENTITY_SEMANTIC_THRESHOLD : null
  };
  const errors = [];
  let hadSuccessfulFetch = false;

  for (const tag of spec.tag_slugs || []) {
    discovery.tag_slugs.push(tag);
    try {
      const events = await fetchJson(
        fetchImpl,
        `${GAMMA_BASE}/events?closed=false&active=true&limit=25&order=volume24hr&ascending=false&tag_slug=${encodeURIComponent(tag)}`
      );
      hadSuccessfulFetch = true;
      const candidates = collectEventMarketCandidates(
        Array.isArray(events) ? events : [],
        spec.expected,
        originalQuery,
        preferredSurface
      );
      discovery.candidates_seen += candidates.length;
      const best = pickBestCandidate(candidates, { requiresEntity, preferredSurface });
      if (best) {
        return {
          slug: best.slug,
          discovery: {
            ...discovery,
            method: `tag_slug:${tag}`,
            selected: best.slug,
            selected_semantic_score: best.semantic_score,
            selected_surface: best.surface
          },
          hadSuccessfulFetch,
          errors
        };
      }
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }

  for (const keyword of spec.category_keywords || []) {
    discovery.category_keywords.push(keyword);
    try {
      const result = await fetchJson(
        fetchImpl,
        `${GAMMA_BASE}/public-search?q=${encodeURIComponent(keyword)}&events_status=active&limit_per_type=12`
      );
      hadSuccessfulFetch = true;
      const candidates = collectEventMarketCandidates(
        Array.isArray(result?.events) ? result.events : [],
        spec.expected,
        originalQuery,
        preferredSurface
      );
      discovery.candidates_seen += candidates.length;
      const best = pickBestCandidate(candidates, { requiresEntity, preferredSurface });
      if (best) {
        return {
          slug: best.slug,
          discovery: {
            ...discovery,
            method: `category_keyword:${keyword}`,
            selected: best.slug,
            selected_semantic_score: best.semantic_score,
            selected_surface: best.surface
          },
          hadSuccessfulFetch,
          errors
        };
      }
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }

  try {
    const rows = await fetchJson(
      fetchImpl,
      `${GAMMA_BASE}/markets?closed=false&active=true&limit=50&order=volume24hr&ascending=false`
    );
    hadSuccessfulFetch = true;
    const candidates = collectMarketCandidates(
      Array.isArray(rows) ? rows : [],
      spec.expected,
      originalQuery,
      preferredSurface
    );
    discovery.candidates_seen += candidates.length;
    const best = pickBestCandidate(candidates, { requiresEntity, preferredSurface });
    if (best) {
      return {
        slug: best.slug,
        discovery: {
          ...discovery,
          method: 'top_volume_category_filter',
          selected: best.slug,
          selected_semantic_score: best.semantic_score,
          selected_surface: best.surface
        },
        hadSuccessfulFetch,
        errors
      };
    }
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }

  return { slug: null, discovery, hadSuccessfulFetch, errors };
}

function preferredSurfaceForScenario(serviceId) {
  if (serviceId === 'football_match_card' || serviceId === 'tennis_match_card' || serviceId === 'nba_match_card') {
    return 'match';
  }
  if (serviceId === 'macro_fed_readout' || serviceId === 'politics_event_readout') {
    return 'ladder';
  }
  return null;
}

function buildQueryVariants(query, spec) {
  const q = String(query || '').trim();
  const extras = [];
  if (queryRequiresEntityMatch(q) && preferredSurfaceForScenario(spec.service_id) === 'match') {
    extras.push(`${q} vs`, `${q} versus`, `${q} match`);
  }
  return uniqueStrings([
    q,
    ...extras,
    ...(spec.query_variants || []),
    spec.default_query,
    ...(spec.expected || [])
  ]);
}

function collectEventMarketCandidates(events, expectedCategories, query = '', preferredSurface = null) {
  const candidates = [];
  for (const event of events) {
    if (event?.closed) continue;
    const eventBlob = `${event.title || ''} ${event.slug || ''}`.toLowerCase();
    for (const market of event.markets || []) {
      if (!market?.slug || market.closed || market.active === false) continue;
      const title = market.question || market.title || '';
      const blob = `${eventBlob} ${title} ${market.slug || ''}`.toLowerCase();
      const categoryScore = scoreCategoryMatch(blob, expectedCategories);
      if (categoryScore <= 0) continue;
      const volume = toNumber(market.volume24hr ?? market.volumeNum ?? market.volume ?? event.volume24hr);
      const semanticScore = query
        ? scoreSemanticMatch({
            query,
            title,
            slug: market.slug,
            eventTitle: event.title || event.slug
          })
        : 0;
      const surface = classifyMarketSurface(blob);
      const surfaceBoost = scoreSurfacePreference(surface, preferredSurface);
      candidates.push({
        slug: market.slug,
        score: categoryScore + semanticScore * 2 + surfaceBoost + Math.min(volume / 100000, 3),
        category_score: categoryScore,
        semantic_score: semanticScore,
        surface,
        volume
      });
    }
  }
  return candidates;
}

function collectMarketCandidates(markets, expectedCategories, query = '', preferredSurface = null) {
  const candidates = [];
  for (const market of markets) {
    if (!market?.slug || market.closed || market.active === false) continue;
    const title = market.question || market.title || market.description || '';
    const blob = `${title} ${market.slug || ''}`.toLowerCase();
    const categoryScore = scoreCategoryMatch(blob, expectedCategories);
    if (categoryScore <= 0) continue;
    const volume = toNumber(market.volume24hr ?? market.volumeNum ?? market.volume);
    const semanticScore = query
      ? scoreSemanticMatch({
          query,
          title,
          slug: market.slug,
          eventTitle: market.events?.[0]?.title || market.eventTitle
        })
      : 0;
    const surface = classifyMarketSurface(blob);
    const surfaceBoost = scoreSurfacePreference(surface, preferredSurface);
    candidates.push({
      slug: market.slug,
      score: categoryScore + semanticScore * 2 + surfaceBoost + Math.min(volume / 100000, 3),
      category_score: categoryScore,
      semantic_score: semanticScore,
      surface,
      volume
    });
  }
  return candidates;
}

function classifyMarketSurface(blob) {
  const text = String(blob || '').toLowerCase();
  if (/\bvs\.?\b|\bv\b|versus|moneyline|spread|o\/u|over\/under|90m|tip-?off|kickoff/.test(text)) {
    return 'match';
  }
  if (/championship|title|finals|outright|season winner|to win the|league winner|cup winner|fed|fomc|election|nominee|temperature|high temp/.test(text)) {
    return 'ladder_or_outright';
  }
  return 'other';
}

function scoreSurfacePreference(surface, preferredSurface) {
  if (!preferredSurface) return 0;
  if (preferredSurface === 'match') {
    if (surface === 'match') return 4;
    if (surface === 'ladder_or_outright') return -3;
  }
  if (preferredSurface === 'ladder') {
    if (surface === 'ladder_or_outright') return 2;
  }
  return 0;
}

function pickBestCandidate(candidates, options = {}) {
  const ranked = candidates
    .slice()
    .sort((a, b) => b.score - a.score || b.semantic_score - a.semantic_score || b.volume - a.volume);
  let pool = ranked;
  if (options.preferredSurface === 'match') {
    // Hard gate for Match Card SKUs: never fall back to season/outright/award surfaces.
    const matchOnly = ranked.filter((c) => c.surface === 'match');
    if (!matchOnly.length) return null;
    pool = matchOnly;
  }
  const best = pool[0] ?? null;
  if (!best) return null;
  if (options.requiresEntity && best.semantic_score < STRONG_ENTITY_SEMANTIC_THRESHOLD) {
    return null;
  }
  return best;
}

function buildScenarioUnavailable(spec, input, resolvedInput) {
  const query = resolvedInput._query || input.query || input.market || input.topic || spec.default_query;
  return {
    schema_version: '0.1',
    service_id: spec.service_id,
    mode: 'live',
    generated_at: new Date().toISOString(),
    capability_status: 'no_active_markets',
    action: 'unavailable',
    input: {
      market_url: input.market_url ?? null,
      condition_id: input.condition_id ?? null,
      slug: input.slug ?? null,
      query
    },
    scenario: {
      id: spec.service_id,
      zh_name: spec.zh_name,
      expected_categories: spec.expected,
      detected_category: null,
      expected_ok: false,
      resolved_via: 'no_active_markets',
      query,
      discovery: resolvedInput._discovery ?? null
    },
    buyer_summary_zh: `${spec.zh_name}：已实时检索 Polymarket，但没有找到仍活跃且匹配该品类的市场；本次结果不可用，不返回伪造比赛/天气/政治卡。`,
    buyer_summary_en: `${spec.zh_name}: No active Polymarket markets matched this scenario after live discovery; this response is unavailable instead of a fake demo card.`,
    paid_checks: {
      pass_count: 2,
      fail_count: 1,
      checks: [
        { id: 'live_discovery_attempted', status: 'pass', detail: 'Queried Gamma public-search, tag/category events, and top-volume category filter.' },
        { id: 'category_market_match', status: 'fail', detail: `No active ${spec.expected.join('/')} market found.` },
        { id: 'fake_card_suppressed', status: 'pass', detail: 'Returned structured unavailable response instead of static fallback card.' }
      ]
    },
    caveats: [
      'Data and analytics only. Not investment advice, not betting advice, and not a guarantee of future returns.',
      'No active matching market was found at request time; retry later or pass an explicit active market_url/slug.'
    ],
    next_gate: 'Retry_when_active_markets_exist_or_pass_explicit_slug',
    source: {
      provider: 'polymarket_gamma_public_api',
      scenario_sku: spec.service_id,
      method: 'pm_event_readout_scenario_discovery',
      discovery: resolvedInput._discovery ?? null
    }
  };
}

function uniqueStrings(values) {
  const seen = new Set();
  const result = [];
  for (const value of values) {
    const text = String(value ?? '').trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    result.push(text);
  }
  return result;
}

const ESPORTS_BLOB_RE = /\bcounter[-\s]?strike\b|\bcs:?go\b|\bcs2\b|\bdota\b|\bleague of legends\b|\bvalorant\b|\besports?\b|\bmap\s*\d\b/;

/**
 * Category match for scenario discovery. Word-boundary safe for short tokens
 * like atp/wta so "Atputies" (CS) cannot score as tennis.
 * Exported for unit tests.
 */
export function scoreCategoryMatch(blob, expected) {
  const text = String(blob || '').toLowerCase();
  if (!text || !Array.isArray(expected) || !expected.length) return 0;

  const sportsExpected = expected.some((cat) => ['tennis', 'football', 'nba'].includes(cat));
  if (sportsExpected && ESPORTS_BLOB_RE.test(text)) return 0;

  let score = 0;
  for (const cat of expected) {
    if (cat === 'weather' && /\btemperature\b|\bweather\b|°f|°c|\bhigh temp\b/.test(text)) score += 5;
    if (cat === 'politics' && /\bpresident\b|\belection\b|\bnominee\b|\bsenate\b|\bgovernor\b|\bparliament\b/.test(text)) {
      score += 5;
    }
    if (cat === 'macro_fed' && /\bfed\b|\bfomc\b|\binterest rate\b|\bbps\b/.test(text)) score += 5;
    if (cat === 'football' && (
      /\bfootball\b|\bsoccer\b|\bpremier league\b|\buefa\b|\bfifa\b|\bepl\b|\bucl\b|\bla liga\b|\bserie a\b|\bbundesliga\b/
    ).test(text)) {
      score += 5;
    }
    if (cat === 'tennis' && (/\btennis\b|\batp\b|\bwta\b|\bwimbledon\b|\bus open\b|\broland garros\b/).test(text)) {
      score += 5;
    }
    if (cat === 'nba' && (/\bnba\b|\bbasketball\b|\bwnba\b/).test(text)) score += 5;
  }
  return score;
}

function buildScenarioBuyerSummaryZh(spec, base, expectedOk) {
  const cat = base.category || 'unknown';
  const tradability = base.tradability || 'unknown';
  const depth = base.category_depth || 'core_only';
  const plugin = base.category_plugin;
  const thesis = plugin?.central_thesis
    || plugin?.market_implied_shape?.central_thesis
    || base.base_case
    || '无中心论题';
  if (!expectedOk) {
    return `${spec.zh_name} SKU：检测到品类 ${cat}（期望 ${spec.expected.join('/')}），深度 ${depth}，可交易性 ${tradability}。建议换匹配市场或改用通用 /pm-event-readout。`;
  }
  return `${spec.zh_name}：品类 ${cat}，深度 ${depth}，可交易性 ${tradability}。${String(thesis).slice(0, 120)} 非下单建议。`;
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}
