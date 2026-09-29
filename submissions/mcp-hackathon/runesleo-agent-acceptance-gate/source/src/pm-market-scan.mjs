// PM Market Scan — productizes polymarket-toolkit `pm scan` (volume + spread).
// Read-only Gamma. No keys, no orders.

const SERVICE_ID = 'pm_market_scan';
const GAMMA_BASE = 'https://gamma-api.polymarket.com';
const FETCH_TIMEOUT_MS = 12000;

const STANDARD_CAVEATS = [
  'Read-only Gamma scanner from polymarket-toolkit lineage (pm scan).',
  'Spread/volume are platform fields — not a trading signal.',
  'No orders, no wallet custody.'
];

/**
 * @param {object} input
 * @param {number} [input.limit=10]
 * @param {number} [input.min_volume=1000]
 * @param {string} [input.query]
 */
export async function assessPmMarketScanLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const limit = clampInt(input.limit, 1, 30, 10);
  const minVolume = Number(input.min_volume ?? input.minVolume ?? 1000) || 1000;
  const query = String(input.query ?? input.q ?? '').trim();

  let markets = [];
  if (query) {
    const search = await fetchJson(
      fetchImpl,
      `${GAMMA_BASE}/public-search?q=${encodeURIComponent(query)}&events_status=active&limit_per_type=20`
    ).catch(() => ({}));
    for (const event of search?.events || []) {
      for (const m of event.markets || []) {
        markets.push({ ...m, _event_title: event.title });
      }
    }
  } else {
    markets = await fetchJson(
      fetchImpl,
      `${GAMMA_BASE}/markets?active=true&closed=false&limit=80&order=volume24hr&ascending=false`
    ).catch(() => []);
  }

  const rows = rankMarketsForScan(Array.isArray(markets) ? markets : [], { minVolume24hr: minVolume, limit });
  const generated_at = new Date().toISOString();

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at,
    input: { limit, min_volume: minVolume, query: query || null },
    markets: rows,
    market_count: rows.length,
    buyer_summary_zh: rows.length
      ? `市场扫描：${rows.length} 个活跃盘（min_vol=${minVolume}）。头名 ${rows[0].slug} · 24h≈$${Math.round(rows[0].volume24hr)} · spread=${fmtSpread(rows[0].spread)}。来自 polymarket-toolkit pm scan。`
      : '市场扫描：无满足成交量门槛的活跃盘。',
    buyer_summary_en: rows.length
      ? `Market scan: ${rows.length} active markets (min_vol=${minVolume}). Top ${rows[0].slug}.`
      : 'Market scan: no active markets above volume floor.',
    value_loop: {
      why_pay_again: '24h volume and spreads move; re-scan before picking a book.',
      stale_after_minutes: 10,
      paid_value_tier: 'toolkit_scanner',
      oss_lineage: 'polymarket-toolkit src/scanner.ts · pm scan',
      llm_api_key_required: false
    },
    caveats: STANDARD_CAVEATS,
    next_gate: 'Pick a slug → /pm-market-health or /pm-trade-preflight',
    source: { provider: 'polymarket_gamma_public_api', method: 'toolkit_pm_scan' }
  };
}

export function buildPmMarketScanFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    markets: [],
    market_count: 0,
    buyer_summary_zh: '市场扫描回退：上游不可用。',
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    source: { provider: 'static_fallback' },
    input
  };
}

/** Pure ranker — ported from polymarket-toolkit/src/scanner.ts */
export function rankMarketsForScan(markets, options = {}) {
  const minVol = options.minVolume24hr ?? 0;
  const limit = options.limit ?? 20;
  const rows = [];
  for (const m of markets) {
    if (m.closed === true || m.active === false) continue;
    const volume24hr = toNumber(m.volume24hrClob ?? m.volume24hr ?? m.volumeNum);
    if (volume24hr < minVol) continue;
    rows.push({
      slug: m.slug ?? 'unknown',
      question: String(m.question ?? m.slug ?? 'unknown').slice(0, 120),
      volume24hr,
      spread: numOrNull(m.spread),
      liquidity: toNumber(m.liquidityNum ?? m.liquidity),
      best_bid: numOrNull(m.bestBid),
      best_ask: numOrNull(m.bestAsk),
      accepting_orders: m.acceptingOrders !== false,
      event_title: m._event_title ?? null
    });
  }
  rows.sort((a, b) => b.volume24hr - a.volume24hr || (a.spread ?? 999) - (b.spread ?? 999));
  return rows.slice(0, limit);
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

function clampInt(value, min, max, fallback) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
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

function fmtSpread(spread) {
  if (spread == null) return 'n/a';
  return `${(spread * 100).toFixed(2)}%`;
}
