// PM Market Health — spread / depth / overround for one market or event.
// Lineage: polymarket-toolkit markets surface + prediction-trader overround idea (read-only).
// No keys, no orders.

import { resolveMarketRef } from './pm-gamma-market.mjs';

const SERVICE_ID = 'pm_market_health';
const GAMMA_BASE = 'https://gamma-api.polymarket.com';
const FETCH_TIMEOUT_MS = 12000;

const STANDARD_CAVEATS = [
  'Read-only book/overround snapshot. Not a buy tip.',
  'Overround = sum of outcome yes-prices; >1 means vig/overlap, <1 may mean incomplete quotes.',
  'No orders, no wallet custody.',
  'OSS lineage: polymarket-toolkit markets + public Gamma fields.'
];

/**
 * @param {object} input
 * @param {string} [input.market_url]
 * @param {string} [input.slug]
 * @param {string} [input.condition_id]
 * @param {string} [input.event_slug]
 */
export async function assessPmMarketHealthLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const ref = resolveMarketRef(input);
  const eventSlug = String(input.event_slug ?? input.eventSlug ?? '').trim();

  if (!ref.slug && !ref.condition_id && !eventSlug) {
    throw new Error('pm-market-health requires market_url, slug, condition_id, or event_slug');
  }

  let markets = [];
  let event_title = null;
  let resolved_via = null;

  if (eventSlug) {
    const events = await fetchJson(fetchImpl, `${GAMMA_BASE}/events?slug=${encodeURIComponent(eventSlug)}`).catch(() => []);
    const event = Array.isArray(events) ? events[0] : null;
    if (!event) throw new Error(`No Gamma event for slug: ${eventSlug}`);
    event_title = event.title ?? eventSlug;
    markets = event.markets || [];
    resolved_via = 'event_slug';
  } else if (ref.slug) {
    const rows = await fetchJson(fetchImpl, `${GAMMA_BASE}/markets?slug=${encodeURIComponent(ref.slug)}`).catch(() => []);
    markets = Array.isArray(rows) ? rows : [];
    resolved_via = 'market_slug';
    event_title = markets[0]?.events?.[0]?.title ?? null;
  } else {
    const rows = await fetchJson(
      fetchImpl,
      `${GAMMA_BASE}/markets?condition_ids=${encodeURIComponent(ref.condition_id)}`
    ).catch(() => []);
    markets = Array.isArray(rows) ? rows : [];
    resolved_via = 'condition_id';
  }

  if (!markets.length) throw new Error('No markets found for health check');

  const assessed = markets.slice(0, 40).map(assessOneMarket);
  const primary = assessed[0];
  const overround_event = round4(assessed.reduce((sum, m) => sum + (m.yes_price ?? 0), 0));
  const verdict = classifyHealth(primary, assessed.length > 1 ? overround_event : primary.overround);

  const generated_at = new Date().toISOString();
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at,
    input: {
      market_url: input.market_url ?? null,
      slug: ref.slug,
      condition_id: ref.condition_id,
      event_slug: eventSlug || null,
      resolved_via
    },
    event_title,
    primary,
    related_markets: assessed.slice(0, 12),
    event_yes_sum: assessed.length > 1 ? overround_event : null,
    health_verdict: verdict,
    buyer_summary_zh: buildZh(primary, verdict, assessed.length),
    buyer_summary_en: buildEn(primary, verdict, assessed.length),
    value_loop: {
      why_pay_again: 'Spread and overround move with the book; re-check before size.',
      stale_after_minutes: 5,
      paid_value_tier: 'toolkit_market_health',
      oss_lineage: 'polymarket-toolkit markets · overround identity',
      llm_api_key_required: false
    },
    hard_gate: 'no_orders_no_signing',
    caveats: STANDARD_CAVEATS,
    next_gate: verdict === 'avoid_thin_or_incoherent'
      ? 'Do_not_size_until_book_improves'
      : 'Optional_pm_trade_preflight_or_decision_card',
    source: { provider: 'polymarket_gamma_public_api', method: 'market_health_overround' }
  };
}

export function buildPmMarketHealthFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    health_verdict: 'unknown',
    buyer_summary_zh: '盘口健康回退：上游不可用。',
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    source: { provider: 'static_fallback' },
    input
  };
}

function assessOneMarket(m) {
  const prices = parsePrices(m.outcomePrices);
  const yes = prices[0] ?? null;
  const no = prices[1] ?? null;
  const overround = yes != null && no != null ? round4(yes + no) : null;
  const spread = numOrNull(m.spread);
  const bestBid = numOrNull(m.bestBid);
  const bestAsk = numOrNull(m.bestAsk);
  const volume24hr = toNumber(m.volume24hr ?? m.volumeNum);
  const liquidity = toNumber(m.liquidityNum ?? m.liquidity);

  return {
    slug: m.slug ?? null,
    question: m.question ?? m.groupItemTitle ?? null,
    yes_price: yes,
    no_price: no,
    overround,
    spread,
    best_bid: bestBid,
    best_ask: bestAsk,
    volume_24h_usd: volume24hr,
    liquidity_usd: liquidity,
    active: m.active !== false && m.closed !== true,
    accepting_orders: m.acceptingOrders !== false
  };
}

function classifyHealth(primary, overround) {
  if (!primary?.active) return 'closed_or_inactive';
  if (primary.spread != null && primary.spread > 0.08) return 'wide_spread';
  if (overround != null && (overround > 1.08 || overround < 0.92)) return 'avoid_thin_or_incoherent';
  if ((primary.volume_24h_usd || 0) < 500) return 'low_volume';
  if (primary.spread != null && primary.spread <= 0.03 && overround != null && overround >= 0.98 && overround <= 1.05) {
    return 'ok_tight';
  }
  return 'ok_usable';
}

function buildZh(primary, verdict, n) {
  return `盘口健康：verdict=${verdict}；yes≈${primary?.yes_price ?? 'n/a'} no≈${primary?.no_price ?? 'n/a'} overround=${primary?.overround ?? 'n/a'} spread=${primary?.spread ?? 'n/a'}；关联盘 ${n}。非买点。`;
}

function buildEn(primary, verdict, n) {
  return `Market health: verdict=${verdict}; yes≈${primary?.yes_price ?? 'n/a'} overround=${primary?.overround ?? 'n/a'} spread=${primary?.spread ?? 'n/a'}; related=${n}. Not a buy tip.`;
}

function parsePrices(raw) {
  if (Array.isArray(raw)) return raw.map((x) => Number(x)).filter((n) => Number.isFinite(n));
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.map((x) => Number(x)).filter((n) => Number.isFinite(n));
    } catch {
      return [];
    }
  }
  return [];
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

function toNumber(value) {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function numOrNull(value) {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function round4(value) {
  return Math.round(value * 10000) / 10000;
}
