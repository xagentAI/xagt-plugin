// PM Up/Down Readout — productizes polymarket-toolkit `pm updown`.
// Crypto up/down event surface with resolution-source pitfalls. Read-only.

const SERVICE_ID = 'pm_updown_readout';
const GAMMA_BASE = 'https://gamma-api.polymarket.com';
const FETCH_TIMEOUT_MS = 12000;

const STANDARD_CAVEATS = [
  'Read-only Gamma up/down event surface from polymarket-toolkit pm updown.',
  'No universal priceToBeat — verify resolutionSource + official rules before any trade.',
  'Do not treat CLOB mid as oracle target without your own window open record.',
  'No orders, no wallet custody.'
];

/**
 * @param {object} input
 * @param {string} [input.event_slug]
 * @param {string} [input.slug]
 * @param {string} [input.query] discovery hint e.g. btc updown
 */
export async function assessPmUpdownReadoutLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  let slug = String(input.event_slug ?? input.slug ?? '').trim();
  const query = String(input.query ?? input.q ?? '').trim();

  if (!slug && query) {
    slug = await discoverUpdownSlug(fetchImpl, query);
  }
  if (!slug) {
    throw new Error('pm-updown-readout requires event_slug/slug or query (e.g. "btc updown")');
  }

  const events = await fetchJson(fetchImpl, `${GAMMA_BASE}/events?slug=${encodeURIComponent(slug)}`).catch(() => []);
  const event = Array.isArray(events) ? events[0] : null;
  if (!event) throw new Error(`No Gamma event for slug: ${slug}`);

  const markets = (event.markets || []).map((m) => ({
    question: m.question ?? null,
    slug: m.slug ?? null,
    condition_id: m.conditionId ?? null,
    group_item_title: m.groupItemTitle ?? null,
    outcome_prices: m.outcomePrices ?? null,
    best_bid: m.bestBid ?? null,
    best_ask: m.bestAsk ?? null,
    spread: m.spread ?? null,
    resolution_source: m.resolutionSource ?? event.resolutionSource ?? null,
    end_date: m.endDate ?? event.endDate ?? null
  }));

  const generated_at = new Date().toISOString();
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at,
    input: { event_slug: slug, query: query || null },
    event: {
      title: event.title ?? slug,
      slug,
      end_date: event.endDate ?? null,
      resolution_source: event.resolutionSource ?? null,
      market_count: markets.length
    },
    markets: markets.slice(0, 16),
    pitfalls: [
      'No universal priceToBeat field — verify resolutionSource + official rules',
      'Do not use CLOB mid as oracle target without recording your own window open',
      'See polymarket-toolkit docs/crypto-updown-price-source.md'
    ],
    buyer_summary_zh: `涨跌盘读出：${event.title ?? slug} · ${markets.length} 个子盘 · 结算源=${String(event.resolutionSource ?? '见规则').slice(0, 60)}。先核结算定义再谈价。`,
    buyer_summary_en: `Up/down readout: ${event.title ?? slug}; ${markets.length} markets; check resolutionSource before pricing.`,
    value_loop: {
      why_pay_again: 'Up/down windows and books roll; re-fetch each window.',
      stale_after_minutes: 3,
      paid_value_tier: 'toolkit_updown',
      oss_lineage: 'polymarket-toolkit pm updown',
      llm_api_key_required: false
    },
    hard_gate: 'no_orders_verify_resolution_first',
    caveats: STANDARD_CAVEATS,
    next_gate: 'Human_verify_resolution_source_then_optional_trade_preflight',
    source: { provider: 'polymarket_gamma_public_api', method: 'toolkit_pm_updown' }
  };
}

export function buildPmUpdownReadoutFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    markets: [],
    buyer_summary_zh: '涨跌盘读出回退：上游不可用。',
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    source: { provider: 'static_fallback' },
    input
  };
}

async function discoverUpdownSlug(fetchImpl, query) {
  const q = /updown|up-down|涨跌/i.test(query) ? query : `${query} updown`;
  const result = await fetchJson(
    fetchImpl,
    `${GAMMA_BASE}/public-search?q=${encodeURIComponent(q)}&events_status=active&limit_per_type=12`
  ).catch(() => ({}));
  const events = Array.isArray(result?.events) ? result.events : [];
  const scored = events
    .map((e) => {
      const blob = `${e.title || ''} ${e.slug || ''}`.toLowerCase();
      let score = 0;
      if (/updown|up-down|up down/.test(blob)) score += 5;
      if (/btc|bitcoin|eth|ethereum|sol/.test(blob)) score += 2;
      if (/15m|1h|hourly|daily/.test(blob)) score += 1;
      return { slug: e.slug, score, volume: Number(e.volume24hr || 0) };
    })
    .filter((x) => x.slug && x.score > 0)
    .sort((a, b) => b.score - a.score || b.volume - a.volume);
  return scored[0]?.slug ?? null;
}

async function fetchJson(fetchImpl, url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, { signal: controller.signal, headers: { accept: 'application/json' } });
    if (!response.ok) throw new Error(`Upstream ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}
