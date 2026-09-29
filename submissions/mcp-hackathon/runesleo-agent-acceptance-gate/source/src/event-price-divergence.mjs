// Event Price Divergence Radar (event_price_divergence_radar).
// Compares 24h Polymarket event-probability moves against 24h spot momentum on
// OKX and flags markets where the two disagree in direction.
//
// Public endpoints used (no API key required), response shapes verified 2026-07-05:
// - Gamma: https://gamma-api.polymarket.com/public-search?q=<asset>&events_status=active&limit_per_type=10
//          -> { events: [{ title, closed, markets: [{ conditionId, question, slug,
//             outcomes: '["Yes","No"]', outcomePrices: '["0.0075","0.9925"]',
//             oneDayPriceChange: -0.002, volume24hr, active, closed, ... }] }] }
//          (oneDayPriceChange = 24h absolute change of the first outcome price;
//           the field is missing on some quiet markets — those are skipped, never estimated)
// - OKX:   https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT
//          -> { code: '0', data: [{ instId, last: '63215.9', open24h: '62593.7', ... }] }
//          (24h spot change derived as (last - open24h) / open24h)

import { classifyAssetStance } from './market-stance.mjs';

const SERVICE_ID = 'event_price_divergence_radar';
const GAMMA_BASE = 'https://gamma-api.polymarket.com';
const OKX_BASE = 'https://www.okx.com';

const FETCH_TIMEOUT_MS = 8000;
const MARKETS_PER_ASSET = 8;
const MIN_MARKET_VOLUME_24H = 500;
// Divergence thresholds: probability move in absolute points, spot move in %.
const MIN_PROB_CHANGE = 0.02;
const MIN_PRICE_CHANGE_PCT = 0.3;

const ASSETS = {
  bitcoin: { search: 'bitcoin', instId: 'BTC-USDT', aliases: ['btc', 'xbt'] },
  ethereum: { search: 'ethereum', instId: 'ETH-USDT', aliases: ['eth', 'ether'] },
  solana: { search: 'solana', instId: 'SOL-USDT', aliases: ['sol'] },
  xrp: { search: 'xrp', instId: 'XRP-USDT', aliases: ['ripple'] },
  dogecoin: { search: 'dogecoin', instId: 'DOGE-USDT', aliases: ['doge'] }
};
const DEFAULT_SCAN = ['bitcoin', 'ethereum', 'solana'];

const STANDARD_CAVEATS = [
  'Data and analytics only. Not investment advice and not a guarantee of future returns.',
  'No wallet custody, no user funds, no trade execution, no order routing.',
  'Divergence signals are heuristic reads of 24h probability vs spot momentum and can be wrong, stale, or explained by market-specific factors (e.g. strike distance, expiry).'
];

/**
 * Build the full live response payload.
 * Throws when every upstream lookup fails so callers can decide how to degrade.
 */
export async function assessEventPriceDivergenceLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const limit = clampInteger(input.limit, 1, 10, 5);
  const assetKeys = resolveAssetKeys(input.asset);

  const assets = await Promise.all(assetKeys.map(async (key) => {
    const spec = ASSETS[key] ?? { search: key, instId: `${key.toUpperCase()}-USDT` };
    const [ticker, markets] = await Promise.all([
      fetchOkxTicker(fetchImpl, spec.instId).catch(() => null),
      fetchAssetMarkets(fetchImpl, spec.search).catch(() => null)
    ]);
    return { asset: key, instId: spec.instId, ticker, markets };
  }));

  if (assets.every((entry) => entry.ticker === null && entry.markets === null)) {
    throw new Error('All upstream lookups (OKX ticker + Polymarket Gamma) failed');
  }

  const caveats = [...STANDARD_CAVEATS];
  const signals = [];
  const assetReadouts = [];

  for (const { asset, instId, ticker, markets } of assets) {
    const priceChangePct = ticker ? round2(((ticker.last - ticker.open24h) / ticker.open24h) * 100) : null;

    assetReadouts.push({
      asset,
      inst_id: instId,
      spot_last: ticker ? ticker.last : null,
      price_change_24h_pct: priceChangePct,
      pm_markets_scanned: markets ? markets.length : 0
    });

    if (!ticker) {
      caveats.push(`OKX ticker for ${instId} was unavailable; ${asset} spot fields are null and no divergence was computed for it.`);
      continue;
    }
    if (!markets) {
      caveats.push(`Polymarket Gamma search for "${asset}" failed; no event markets were scanned for it.`);
      continue;
    }
    if (!markets.length) {
      caveats.push(`No active Polymarket markets with a 24h probability change matched "${asset}".`);
      continue;
    }

    for (const market of markets) {
      const signal = evaluateDivergence(asset, instId, market, priceChangePct);
      if (signal) signals.push(signal);
    }
  }

  signals.sort((a, b) => b.confidence - a.confidence);
  const top = signals.slice(0, limit);
  const source_status = {
    as_of: new Date().toISOString(),
    overall: assets.every((a) => a.ticker && a.markets) ? 'green'
      : assets.some((a) => a.ticker || a.markets) ? 'yellow' : 'red',
    assets: assets.map((a) => ({
      asset: a.asset,
      okx_ticker: a.ticker ? 'ok' : 'fail',
      polymarket_search: a.markets ? 'ok' : 'fail',
      pm_markets: Array.isArray(a.markets) ? a.markets.length : 0,
      spot_change_24h_pct: a.ticker
        ? round2(((a.ticker.last - a.ticker.open24h) / a.ticker.open24h) * 100)
        : null
    })),
    thresholds: {
      min_probability_change: MIN_PROB_CHANGE,
      min_price_change_pct: MIN_PRICE_CHANGE_PCT,
      min_market_volume_24h_usdt: MIN_MARKET_VOLUME_24H
    }
  };

  const summary = buildSummary(top, assetReadouts);

  return {
    schema_version: '0.3',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      asset: input.asset ?? null,
      assets_scanned: assetKeys,
      limit
    },
    summary,
    buyer_summary_zh: buildDivergenceBuyerSummaryZh(top, assetReadouts, source_status),
    signals: top,
    assets: assetReadouts,
    caveats,
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: {
      probability_provider: 'polymarket_gamma_public_search (oneDayPriceChange)',
      price_provider: 'okx_public_market_ticker (last vs open24h)',
      min_probability_change: MIN_PROB_CHANGE,
      min_price_change_pct: MIN_PRICE_CHANGE_PCT,
      min_market_volume_24h_usdt: MIN_MARKET_VOLUME_24H,
      source_status
    }
  };
}

/**
 * Static degraded payload for when the live path fails. The worker cache layer
 * stamps `mode: 'degraded'` and prepends the failure caveat.
 */
export function buildEventPriceDivergenceFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      asset: input?.asset ?? null,
      assets_scanned: resolveAssetKeys(input?.asset),
      limit: clampInteger(input?.limit, 1, 10, 5)
    },
    summary: 'Static fallback: live probability/price feeds were unavailable, no divergence computed.',
    signals: [],
    assets: [],
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: {
      probability_provider: 'unavailable',
      price_provider: 'unavailable'
    }
  };
}

function evaluateDivergence(asset, instId, market, priceChangePct) {
  // stance: does the first outcome going UP imply the asset going UP?
  const stance = classifyStance(market);
  if (stance === 0) return null;

  const probChange = market.one_day_price_change;
  const impliedDirection = Math.sign(probChange) * stance;
  const priceDirection = Math.sign(priceChangePct);

  if (impliedDirection === 0 || priceDirection === 0) return null;
  if (impliedDirection === priceDirection) return null;
  if (Math.abs(probChange) < MIN_PROB_CHANGE) return null;
  if (Math.abs(priceChangePct) < MIN_PRICE_CHANGE_PCT) return null;

  const direction = impliedDirection > 0 ? 'event_probability_bullish_price_down' : 'event_probability_bearish_price_up';
  const magnitude = round2(Math.abs(probChange) * 100 + Math.abs(priceChangePct));

  return {
    asset,
    inst_id: instId,
    market_id: market.market_id,
    market_title: market.title,
    outcome: market.primary_outcome,
    event_probability: market.primary_price,
    probability_change_24h: probChange,
    market_stance: stance > 0 ? 'bullish_if_probability_up' : 'bearish_if_probability_up',
    price_change_24h_pct: priceChangePct,
    direction,
    magnitude,
    confidence: scoreConfidence(probChange, priceChangePct, market.volume_24hr),
    rationale: buildRationale(asset, market, probChange, priceChangePct, impliedDirection)
  };
}

/** Shared classifier (src/market-stance.mjs) — see that file for the 2026-07-30
 * measurement that removed the dollar-amount bullish fallback. */
function classifyStance(market) {
  return classifyAssetStance(market);
}

function scoreConfidence(probChange, priceChangePct, volume24hr) {
  let score = 0.5;
  score += 0.15 * Math.min(Math.abs(probChange) / 0.1, 1);
  score += 0.15 * Math.min(Math.abs(priceChangePct) / 3, 1);
  score += 0.1 * Math.min(toNumber(volume24hr) / 50_000, 1);
  return round2(Math.min(0.9, Math.max(0.5, score)));
}

function buildRationale(asset, market, probChange, priceChangePct, impliedDirection) {
  const probMove = `${probChange > 0 ? '+' : ''}${round2(probChange * 100)} pts`;
  const priceMove = `${priceChangePct > 0 ? '+' : ''}${priceChangePct}%`;
  const readout = impliedDirection > 0
    ? `event odds lean more bullish while spot moved ${priceMove}`
    : `event odds lean more bearish while spot moved ${priceMove}`;
  return `"${market.title}" probability of "${market.primary_outcome}" moved ${probMove} in 24h (now ${market.primary_price}); ${readout} on OKX for ${asset}.`;
}

function buildSummary(signals, assetReadouts) {
  const scanned = assetReadouts.map((entry) => entry.asset).join(', ');
  if (!signals.length) {
    return `No probability-vs-price divergence above thresholds across ${scanned || 'the requested assets'}.`;
  }
  const top = signals[0];
  return `${signals.length} divergence signal${signals.length === 1 ? '' : 's'} found across ${scanned}. Top: ${top.direction} on "${top.market_title}" (${top.asset}).`;
}

function buildDivergenceBuyerSummaryZh(signals, assetReadouts, sourceStatus) {
  const scanned = assetReadouts.map((a) => a.asset).join('/') || '指定资产';
  const health = sourceStatus?.overall || 'unknown';
  if (!signals.length) {
    return `未发现超阈值背离（扫描 ${scanned}；数据健康 ${health}）。启发式信号，非交易建议。`;
  }
  const top = signals[0];
  return `发现 ${signals.length} 条背离；最强：${top.asset}「${top.market_title}」→ ${top.direction}（置信 ${top.confidence}）。数据健康 ${health}；非交易建议。`;
}

function resolveAssetKeys(assetInput) {
  const raw = normalizeText(assetInput);
  if (!raw || raw === 'all') return [...DEFAULT_SCAN];
  for (const [key, spec] of Object.entries(ASSETS)) {
    if (raw === key || spec.aliases.includes(raw)) return [key];
  }
  // Unknown asset: still try it (Gamma text search + <ASSET>-USDT ticker);
  // failures surface as caveats rather than errors.
  return [raw];
}

async function fetchOkxTicker(fetchImpl, instId) {
  const payload = await fetchJson(fetchImpl, `${OKX_BASE}/api/v5/market/ticker?instId=${encodeURIComponent(instId)}`);
  if (payload?.code !== '0' || !Array.isArray(payload.data) || !payload.data.length) return null;
  const row = payload.data[0];
  const last = Number(row.last);
  const open24h = Number(row.open24h);
  if (!Number.isFinite(last) || !Number.isFinite(open24h) || open24h <= 0) return null;
  return { last, open24h };
}

async function fetchAssetMarkets(fetchImpl, searchTerm) {
  const result = await fetchJson(
    fetchImpl,
    `${GAMMA_BASE}/public-search?q=${encodeURIComponent(searchTerm)}&events_status=active&limit_per_type=10`
  );
  const markets = [];
  for (const event of Array.isArray(result?.events) ? result.events : []) {
    if (event.closed) continue;
    for (const market of event.markets ?? []) {
      if (!market.conditionId || market.closed || market.active === false) continue;
      const oneDay = Number(market.oneDayPriceChange);
      if (!Number.isFinite(oneDay)) continue; // field missing on quiet markets — never estimated
      const volume = toNumber(market.volume24hr);
      if (volume < MIN_MARKET_VOLUME_24H) continue;
      const outcomes = parseJsonArray(market.outcomes);
      const prices = parseJsonArray(market.outcomePrices);
      if (!outcomes.length || !prices.length) continue;
      markets.push({
        market_id: market.slug ?? market.conditionId,
        condition_id: market.conditionId,
        title: market.question ?? market.slug ?? market.conditionId,
        primary_outcome: String(outcomes[0]),
        primary_price: Number(prices[0]),
        one_day_price_change: oneDay,
        volume_24hr: volume
      });
    }
  }
  markets.sort((a, b) => b.volume_24hr - a.volume_24hr);
  return markets.slice(0, MARKETS_PER_ASSET);
}

async function fetchJson(fetchImpl, url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, {
      signal: controller.signal,
      headers: { accept: 'application/json' }
    });
    if (!response.ok) {
      throw new Error(`Upstream ${response.status} for ${url}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function parseJsonArray(value) {
  if (Array.isArray(value)) return value;
  try {
    const parsed = JSON.parse(String(value ?? '[]'));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function round2(value) {
  return Math.round(Number(value) * 100) / 100;
}

function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function normalizeText(value) {
  return String(value ?? '').trim().toLowerCase();
}

function clampInteger(value, min, max, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}
