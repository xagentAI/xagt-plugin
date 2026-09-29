// Crypto Market Regime Radar (crypto_market_regime_radar).
// Decision-layer service: blends OKX spot momentum, perp funding/premium and
// Polymarket event-probability drift into one explainable regime call
// (risk_on / risk_off / neutral / mixed) with a 0-100 score. Every dimension's
// weight and contribution is spelled out in `dimensions` + `rationale` — no
// black box.
//
// Public endpoints used (no API key required), response shapes verified 2026-07-05:
// - OKX:   https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT
//          -> { code: '0', data: [{ last: '63105.3', open24h: '62565.9', ... }] }
// - OKX:   https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP
//          -> { code: '0', data: [{ fundingRate: '0.0001', premium: '-0.00045', ... }] }
// - OKX:   https://www.okx.com/api/v5/public/open-interest?instId=BTC-USDT-SWAP
//          -> { code: '0', data: [{ oiUsd: '1922638943.46', ... }] }
//          (NOTE: /api/v5/market/open-interest does NOT exist — returns 404, verified 2026-07-05)
// - Gamma: https://gamma-api.polymarket.com/public-search?q=<asset>&events_status=active&limit_per_type=10
//          -> { events: [{ closed, markets: [{ conditionId, question, outcomes,
//             outcomePrices, oneDayPriceChange, volume24hr, active, closed }] }] }
//          (oneDayPriceChange missing on quiet markets — those are skipped, never estimated)

import { classifyAssetStance } from './market-stance.mjs';

const SERVICE_ID = 'crypto_market_regime_radar';
const OKX_BASE = 'https://www.okx.com';
const GAMMA_BASE = 'https://gamma-api.polymarket.com';

const FETCH_TIMEOUT_MS = 8000;
const PM_MARKETS_PER_ASSET = 8;
const MIN_PM_VOLUME_24H = 500;

const ASSETS = {
  bitcoin: { search: 'bitcoin', spot: 'BTC-USDT', swap: 'BTC-USDT-SWAP', aliases: ['btc', 'xbt'] },
  ethereum: { search: 'ethereum', spot: 'ETH-USDT', swap: 'ETH-USDT-SWAP', aliases: ['eth', 'ether'] },
  solana: { search: 'solana', spot: 'SOL-USDT', swap: 'SOL-USDT-SWAP', aliases: ['sol'] }
};
const DEFAULT_SCAN = ['bitcoin', 'ethereum', 'solana'];

// Explainable weighting rules. Each dimension maps a raw reading to a
// normalized [-1, +1] direction score; contribution = 50 * weight% * normalized.
// Normalization scales (the "full conviction" magnitudes) are declared here so
// they show up in `source.method` and can be audited by the buyer.
const DIMENSIONS = {
  spot_momentum_24h: { weight_pct: 40, full_scale: '±3% avg 24h spot move' },
  perp_funding_rate: { weight_pct: 20, full_scale: '±0.05% deviation from 0.01% baseline funding' },
  perp_premium: { weight_pct: 15, full_scale: '±0.10% perp premium vs index' },
  polymarket_event_sentiment: { weight_pct: 25, full_scale: '±5 pts volume-weighted 24h bullish-probability drift' }
};

const STANDARD_CAVEATS = [
  'Not financial advice. Data-only research signal for downstream agents; final trading decisions and risk limits stay with the caller.',
  'No wallet custody, no user funds, no trade execution, no order routing.',
  'Regime call is a heuristic weighted blend of 24h snapshots (spot momentum, funding, perp premium, Polymarket probability drift); it can be wrong, stale, or dominated by asset-specific events.',
  'Open interest is reported as context only — a single OI snapshot has no direction and does not enter the score.'
];

/**
 * Build the full live response payload.
 * Throws when every upstream lookup fails so callers can decide how to degrade.
 */
export async function assessCryptoMarketRegimeLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const limit = clampInteger(input.limit, 1, 10, 5);
  const assetKeys = resolveAssetKeys(input.focus ?? input.asset);

  const assets = await Promise.all(assetKeys.map(async (key) => {
    const spec = ASSETS[key] ?? {
      search: key,
      spot: `${key.toUpperCase()}-USDT`,
      swap: `${key.toUpperCase()}-USDT-SWAP`
    };
    const [ticker, funding, openInterest, pmMarkets] = await Promise.all([
      fetchOkxTicker(fetchImpl, spec.spot).catch(() => null),
      fetchOkxFunding(fetchImpl, spec.swap).catch(() => null),
      fetchOkxOpenInterest(fetchImpl, spec.swap).catch(() => null),
      fetchAssetMarkets(fetchImpl, spec.search).catch(() => null)
    ]);
    return { asset: key, spec, ticker, funding, openInterest, pmMarkets };
  }));

  if (assets.every((a) => a.ticker === null && a.funding === null && a.pmMarkets === null)) {
    throw new Error('All upstream lookups (OKX market data + Polymarket Gamma) failed');
  }

  const caveats = [...STANDARD_CAVEATS];
  const readouts = assets.map((entry) => buildAssetReadout(entry, caveats));

  const dimensions = [
    buildSpotMomentumDimension(readouts),
    buildFundingDimension(readouts),
    buildPremiumDimension(readouts),
    buildPolymarketDimension(readouts)
  ];

  const scoredDimensions = dimensions.filter((dim) => dim.normalized_score !== null);
  for (const dim of dimensions) {
    if (dim.normalized_score === null) {
      caveats.push(`Dimension "${dim.dimension}" had no usable upstream data; it contributed 0 points and its weight was excluded.`);
    }
  }

  const { score, regime } = scoreRegime(scoredDimensions);
  const confidence = scoreConfidence(score, scoredDimensions, dimensions.length);
  const watchItems = buildWatchItems(readouts, scoredDimensions).slice(0, limit);
  const source_status = buildRegimeSourceStatus(assets, dimensions);
  const oi_context = buildOiContext(readouts);

  return {
    schema_version: '0.3',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      focus: input.focus ?? null,
      assets_scanned: assetKeys,
      limit
    },
    regime,
    direction: regime,
    score,
    confidence,
    summary: buildSummary(regime, score, assetKeys),
    buyer_summary_zh: buildBuyerSummaryZh(regime, score, confidence, oi_context),
    dimensions,
    rationale: buildRationale(dimensions, score, regime),
    assets: readouts,
    oi_context,
    watch_items: watchItems,
    caveats,
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: {
      price_provider: 'okx_public_market_ticker (last vs open24h)',
      funding_provider: 'okx_public_funding_rate (fundingRate + premium)',
      open_interest_provider: 'okx_public_open_interest (context only, not scored)',
      probability_provider: 'polymarket_gamma_public_search (oneDayPriceChange, volume-weighted)',
      source_status,
      method: {
        formula: 'score = 50 + 50 * sum(weight_pct/100 * normalized_score); normalized_score in [-1, +1] per dimension',
        regime_rule: 'mixed when two dimensions conflict at |normalized| >= 0.35; else risk_on if score >= 60, risk_off if score <= 40, neutral otherwise',
        dimension_scales: Object.fromEntries(
          Object.entries(DIMENSIONS).map(([name, spec]) => [name, `${spec.weight_pct}% weight, full conviction at ${spec.full_scale}`])
        )
      }
    }
  };
}

function buildRegimeSourceStatus(assets, dimensions) {
  const perAsset = assets.map((a) => ({
    asset: a.asset,
    okx_ticker: a.ticker ? 'ok' : 'fail',
    okx_funding: a.funding ? 'ok' : 'fail',
    okx_open_interest: a.openInterest ? 'ok' : 'fail',
    polymarket_search: a.pmMarkets ? 'ok' : 'fail',
    pm_markets: Array.isArray(a.pmMarkets) ? a.pmMarkets.length : 0
  }));
  const dims = dimensions.map((d) => ({
    dimension: d.dimension,
    status: d.normalized_score === null ? 'missing' : 'ok',
    contribution_points: d.contribution_points ?? null
  }));
  const failCount = perAsset.reduce(
    (n, row) => n + ['okx_ticker', 'okx_funding', 'polymarket_search'].filter((k) => row[k] === 'fail').length,
    0
  );
  return {
    as_of: new Date().toISOString(),
    overall: failCount === 0 ? 'green' : (failCount <= 2 ? 'yellow' : 'red'),
    assets: perAsset,
    dimensions: dims
  };
}

/**
 * Static degraded payload for when the live path fails. The worker cache layer
 * stamps `mode: 'degraded'` and prepends the failure caveat.
 */
export function buildCryptoMarketRegimeFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      focus: input?.focus ?? null,
      assets_scanned: resolveAssetKeys(input?.focus ?? input?.asset),
      limit: clampInteger(input?.limit, 1, 10, 5)
    },
    regime: 'neutral',
    direction: 'neutral',
    score: 50,
    confidence: 0,
    summary: 'Static fallback: live OKX/Polymarket feeds were unavailable; regime defaults to neutral with zero confidence.',
    dimensions: [],
    rationale: 'No live data — no regime judgment was computed. Do not act on this response.',
    assets: [],
    watch_items: [],
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: { price_provider: 'unavailable', funding_provider: 'unavailable', probability_provider: 'unavailable' }
  };
}

// ---- per-asset readouts ------------------------------------------------------

function buildAssetReadout(entry, caveats) {
  const { asset, spec, ticker, funding, openInterest, pmMarkets } = entry;

  const priceChangePct = ticker ? round2(((ticker.last - ticker.open24h) / ticker.open24h) * 100) : null;
  if (!ticker) caveats.push(`OKX ticker for ${spec.spot} was unavailable; ${asset} spot fields are null.`);
  if (!funding) caveats.push(`OKX funding rate for ${spec.swap} was unavailable; ${asset} funding/premium fields are null.`);
  if (pmMarkets === null) caveats.push(`Polymarket Gamma search for "${asset}" failed; its event sentiment is null.`);

  const pmSentiment = pmMarkets && pmMarkets.length ? computePmSentiment(pmMarkets) : null;

  return {
    asset,
    spot_inst_id: spec.spot,
    swap_inst_id: spec.swap,
    spot_last: ticker ? ticker.last : null,
    price_change_24h_pct: priceChangePct,
    funding_rate: funding ? funding.fundingRate : null,
    funding_rate_annualized_pct: funding ? round2(funding.fundingRate * 3 * 365 * 100) : null,
    perp_premium: funding ? funding.premium : null,
    open_interest_usd: openInterest,
    pm_markets_scanned: pmMarkets ? pmMarkets.length : 0,
    // Volume-weighted 24h drift of "bullish for the asset" probability, in pts.
    pm_sentiment_drift_pts: pmSentiment ? round2(pmSentiment.drift * 100) : null,
    pm_top_market: pmSentiment ? pmSentiment.topMarket : null
  };
}

/**
 * Volume-weighted average of stance-adjusted 24h probability changes across
 * the asset's Polymarket markets. Positive drift = event odds moved in the
 * asset-bullish direction over the last 24h.
 */
function computePmSentiment(markets) {
  let weighted = 0;
  let volume = 0;
  let topMarket = null;
  for (const market of markets) {
    const stance = classifyStance(market);
    if (stance === 0) continue;
    const directional = stance * market.one_day_price_change;
    weighted += directional * market.volume_24hr;
    volume += market.volume_24hr;
    if (!topMarket || Math.abs(directional) > Math.abs(topMarket.directional)) {
      topMarket = {
        title: market.title,
        outcome: market.primary_outcome,
        probability: market.primary_price,
        probability_change_24h: market.one_day_price_change,
        directional
      };
    }
  }
  if (!(volume > 0) || !topMarket) return null;
  return {
    drift: weighted / volume,
    topMarket: {
      title: topMarket.title,
      outcome: topMarket.outcome,
      probability: topMarket.probability,
      probability_change_24h: topMarket.probability_change_24h
    }
  };
}

/** Shared classifier (src/market-stance.mjs) — see that file for the 2026-07-30
 * measurement that removed the dollar-amount bullish fallback. */
function classifyStance(market) {
  return classifyAssetStance(market);
}

// ---- dimensions ---------------------------------------------------------------

function buildSpotMomentumDimension(readouts) {
  const values = readouts.map((r) => r.price_change_24h_pct).filter((v) => v !== null);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return buildDimension({
    name: 'spot_momentum_24h',
    normalized: avg === null ? null : clamp(avg / 3, -1, 1),
    reading: avg === null ? null : `${signed(round2(avg))}% avg 24h spot change (${readouts.filter((r) => r.price_change_24h_pct !== null).map((r) => `${r.asset} ${signed(r.price_change_24h_pct)}%`).join(', ')})`,
    detail: 'OKX spot last vs open24h, averaged across scanned assets. Full conviction at ±3%.'
  });
}

function buildFundingDimension(readouts) {
  const values = readouts.map((r) => r.funding_rate).filter((v) => v !== null);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  const NEUTRAL = 0.0001; // 0.01% per 8h is the customary baseline funding
  return buildDimension({
    name: 'perp_funding_rate',
    normalized: avg === null ? null : clamp((avg - NEUTRAL) / 0.0005, -1, 1),
    reading: avg === null ? null : `${round4(avg * 100)}% avg current funding vs 0.01% baseline (${readouts.filter((r) => r.funding_rate !== null).map((r) => `${r.asset} ${round4(r.funding_rate * 100)}%`).join(', ')})`,
    detail: 'Funding above baseline = longs paying up (risk-on positioning); below/negative = shorts paying (risk-off). Full conviction at ±0.05% deviation.'
  });
}

function buildPremiumDimension(readouts) {
  const values = readouts.map((r) => r.perp_premium).filter((v) => v !== null);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return buildDimension({
    name: 'perp_premium',
    normalized: avg === null ? null : clamp(avg / 0.001, -1, 1),
    reading: avg === null ? null : `${round4(avg * 100)}% avg perp premium vs index (${readouts.filter((r) => r.perp_premium !== null).map((r) => `${r.asset} ${round4(r.perp_premium * 100)}%`).join(', ')})`,
    detail: 'Perp trading above index = leveraged demand to be long; below = to be short. Full conviction at ±0.10%.'
  });
}

function buildPolymarketDimension(readouts) {
  const values = readouts.map((r) => r.pm_sentiment_drift_pts).filter((v) => v !== null);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return buildDimension({
    name: 'polymarket_event_sentiment',
    normalized: avg === null ? null : clamp(avg / 5, -1, 1),
    reading: avg === null ? null : `${signed(round2(avg))} pts avg 24h bullish-probability drift (${readouts.filter((r) => r.pm_sentiment_drift_pts !== null).map((r) => `${r.asset} ${signed(r.pm_sentiment_drift_pts)} pts`).join(', ')})`,
    detail: 'Volume-weighted, stance-adjusted 24h change of Polymarket crypto event probabilities. Positive = odds drifted asset-bullish. Full conviction at ±5 pts.'
  });
}

function buildDimension({ name, normalized, reading, detail }) {
  const spec = DIMENSIONS[name];
  const contribution = normalized === null ? 0 : round1(50 * (spec.weight_pct / 100) * normalized);
  return {
    dimension: name,
    weight_pct: spec.weight_pct,
    reading,
    direction: normalized === null ? 'unavailable' : normalized > 0.15 ? 'bullish' : normalized < -0.15 ? 'bearish' : 'neutral',
    normalized_score: normalized === null ? null : round2(normalized),
    contribution_points: contribution,
    detail
  };
}

// ---- scoring ------------------------------------------------------------------

function scoreRegime(scoredDimensions) {
  const total = scoredDimensions.reduce((sum, dim) => sum + dim.contribution_points, 0);
  const score = Math.round(Math.min(100, Math.max(0, 50 + total)));

  const norms = scoredDimensions.map((dim) => dim.normalized_score);
  const conflicting = norms.some((n) => n >= 0.35) && norms.some((n) => n <= -0.35);

  let regime;
  if (conflicting) regime = 'mixed';
  else if (score >= 60) regime = 'risk_on';
  else if (score <= 40) regime = 'risk_off';
  else regime = 'neutral';
  return { score, regime };
}

/**
 * Confidence in [0, 0.9]: distance from 50 adds conviction, missing
 * dimensions subtract it.
 */
function scoreConfidence(score, scoredDimensions, totalDimensions) {
  const coverage = totalDimensions ? scoredDimensions.length / totalDimensions : 0;
  const conviction = Math.abs(score - 50) / 50;
  return round2(Math.min(0.9, (0.35 + 0.55 * conviction) * coverage));
}

function buildRationale(dimensions, score, regime) {
  const parts = dimensions.map((dim) => {
    if (dim.normalized_score === null) {
      return `${dim.dimension} (0 pts, no data): upstream unavailable.`;
    }
    return `${dim.dimension} (${signed(dim.contribution_points)} pts of ±${round1(50 * dim.weight_pct / 100)} possible, ${dim.direction}): ${dim.reading}.`;
  });
  parts.push(`Weighted total ${score}/100 → ${regime}.`);
  return parts.join(' ');
}

function buildSummary(regime, score, assetKeys) {
  return `Crypto market regime: ${regime} (score ${score}/100) across ${assetKeys.join(', ')}.`;
}

function buildOiContext(readouts) {
  const rows = readouts
    .filter((r) => r.open_interest_usd != null)
    .map((r) => ({
      asset: r.asset,
      open_interest_usd: r.open_interest_usd,
      funding_rate: r.funding_rate,
      note: r.funding_rate != null && Math.abs(r.funding_rate) >= 0.0005
        ? 'elevated_funding_with_oi_snapshot'
        : 'oi_snapshot_only'
    }));
  const total = rows.reduce((sum, r) => sum + (r.open_interest_usd || 0), 0);
  return {
    role: 'context_only_not_scored',
    assets: rows,
    total_open_interest_usd: total || null,
    interpretation: rows.length
      ? 'OI is a leverage backlog snapshot; direction comes from spot/funding/premium/PM dimensions, not from OI alone.'
      : 'OI unavailable from OKX public open-interest endpoint for scanned assets.'
  };
}

function buildBuyerSummaryZh(regime, score, confidence, oiContext) {
  const regimeZh = {
    risk_on: '偏多/风险偏好',
    risk_off: '偏空/避险',
    neutral: '中性',
    mixed: '信号打架'
  }[regime] || regime;
  const oiBit = oiContext?.total_open_interest_usd
    ? `；OI 快照合计约 $${Math.round(oiContext.total_open_interest_usd).toLocaleString('en-US')}（仅上下文，不计入分数）`
    : '；OI 暂缺';
  return `市场状态 ${regimeZh}，分数 ${score}/100，置信 ${confidence}${oiBit}。解释见 dimensions/rationale；非交易建议。`;
}

function buildWatchItems(readouts, scoredDimensions) {
  const items = [];
  for (const dim of scoredDimensions) {
    if (Math.abs(dim.normalized_score) >= 0.5) {
      items.push(`${dim.dimension} is at ${dim.normalized_score} of full conviction (${dim.direction}) — watch for reversal or confirmation.`);
    }
  }
  for (const r of readouts) {
    if (r.funding_rate !== null && Math.abs(r.funding_rate) >= 0.0005) {
      items.push(`${r.asset} funding at ${round4(r.funding_rate * 100)}% per period — crowded positioning, squeeze risk.`);
    }
    if (r.pm_top_market) {
      items.push(`${r.asset} Polymarket mover: "${r.pm_top_market.title}" (${r.pm_top_market.outcome} at ${r.pm_top_market.probability}, ${signed(round2(r.pm_top_market.probability_change_24h * 100))} pts/24h).`);
    }
  }
  return items;
}

// ---- upstream fetchers ----------------------------------------------------------

async function fetchOkxTicker(fetchImpl, instId) {
  const row = await fetchOkxData(fetchImpl, `/api/v5/market/ticker?instId=${encodeURIComponent(instId)}`);
  if (!row) return null;
  const last = Number(row.last);
  const open24h = Number(row.open24h);
  if (!Number.isFinite(last) || !Number.isFinite(open24h) || open24h <= 0) return null;
  return { last, open24h };
}

async function fetchOkxFunding(fetchImpl, instId) {
  const row = await fetchOkxData(fetchImpl, `/api/v5/public/funding-rate?instId=${encodeURIComponent(instId)}`);
  if (!row) return null;
  const fundingRate = Number(row.fundingRate);
  if (!Number.isFinite(fundingRate)) return null;
  const premium = Number(row.premium);
  return { fundingRate, premium: Number.isFinite(premium) ? premium : null };
}

async function fetchOkxOpenInterest(fetchImpl, instId) {
  const row = await fetchOkxData(fetchImpl, `/api/v5/public/open-interest?instId=${encodeURIComponent(instId)}`);
  if (!row) return null;
  const oiUsd = Number(row.oiUsd);
  return Number.isFinite(oiUsd) ? Math.round(oiUsd) : null;
}

async function fetchOkxData(fetchImpl, path) {
  const payload = await fetchJson(fetchImpl, `${OKX_BASE}${path}`);
  if (payload?.code !== '0' || !Array.isArray(payload.data) || !payload.data.length) return null;
  return payload.data[0];
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
      if (!Number.isFinite(oneDay)) continue; // missing on quiet markets — never estimated
      const volume = toNumber(market.volume24hr);
      if (volume < MIN_PM_VOLUME_24H) continue;
      const outcomes = parseJsonArray(market.outcomes);
      const prices = parseJsonArray(market.outcomePrices);
      if (!outcomes.length || !prices.length) continue;
      markets.push({
        market_id: market.slug ?? market.conditionId,
        title: market.question ?? market.slug ?? market.conditionId,
        primary_outcome: String(outcomes[0]),
        primary_price: Number(prices[0]),
        one_day_price_change: oneDay,
        volume_24hr: volume
      });
    }
  }
  markets.sort((a, b) => b.volume_24hr - a.volume_24hr);
  return markets.slice(0, PM_MARKETS_PER_ASSET);
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

// ---- small utils ----------------------------------------------------------------

function resolveAssetKeys(focusInput) {
  const raw = normalizeText(focusInput);
  if (!raw || raw === 'all' || raw === 'global') return [...DEFAULT_SCAN];
  for (const [key, spec] of Object.entries(ASSETS)) {
    if (raw === key || spec.aliases.includes(raw)) return [key];
  }
  // Unknown focus: still try it (Gamma text search + <FOCUS>-USDT instruments);
  // failures surface as caveats rather than errors.
  return [raw];
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

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function signed(value) {
  return `${value >= 0 ? '+' : ''}${value}`;
}

function round1(value) {
  return Math.round(Number(value) * 10) / 10;
}

function round2(value) {
  return Math.round(Number(value) * 100) / 100;
}

function round4(value) {
  return Math.round(Number(value) * 10000) / 10000;
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
