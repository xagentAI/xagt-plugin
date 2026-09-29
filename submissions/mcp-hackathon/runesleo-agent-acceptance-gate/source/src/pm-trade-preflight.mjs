// PM Trade Preflight (pm_trade_preflight) — read-only eligible/watch/skip gate before
// a prediction-market order. Uses public Polymarket Gamma market metadata only.
// `eligible` means mechanical checks passed — NOT a buy/sell tip and NOT order routing.

import {
  fetchMarket,
  resolveMarketRef,
  clamp,
  round2,
  toNumber
} from './pm-gamma-market.mjs';

const SERVICE_ID = 'pm_trade_preflight';

const MIN_VOLUME_24H_USD = 5_000;
const EXTREME_PRICE_LOW = 0.08;
const EXTREME_PRICE_HIGH = 0.92;
const MAX_SPREAD = 0.06;
const SIZE_VS_VOLUME_RATIO = 0.05;

const STANDARD_CAVEATS = [
  'Read-only preflight gate. Not investment advice; does not place, cancel, or route orders.',
  'Heuristic checks on liquidity, price zone, and spread only — not a full event readout.',
  'Caller retains all risk limits and manual approval before any real-money action.'
];

export async function assessPmTradePreflightLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const side = normalizeSide(input.side);
  const sizeUsd = parseOptionalUsd(input.size_usd ?? input.sizeUsd);
  const marketRef = resolveMarketRef(input);

  const market = await fetchMarket(fetchImpl, marketRef);
  if (!market) {
    throw new Error('Market not found for the provided slug, condition_id, or market_url');
  }

  const evaluation = evaluatePreflight(market, side, sizeUsd);
  const decisionLite = buildDecisionCardLite(market, side, evaluation);

  return {
    schema_version: '0.2',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      market_url: input.market_url ?? null,
      condition_id: marketRef.condition_id,
      slug: marketRef.slug,
      side,
      size_usd: sizeUsd
    },
    market: {
      condition_id: market.condition_id,
      slug: market.slug,
      title: market.title,
      active: market.active,
      closed: market.closed,
      volume_24h_usd: market.volume_24hr,
      best_bid: market.best_bid,
      best_ask: market.best_ask,
      spread: market.spread,
      outcomes: market.outcomes,
      outcome_prices: market.outcome_prices
    },
    action: evaluation.action,
    confidence: evaluation.confidence,
    reasons: evaluation.reasons,
    risk_flags: evaluation.risk_flags,
    side_price: evaluation.side_price,
    decision_card_lite: decisionLite,
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'Leo_manual_order_approval_required',
    source: {
      provider: 'polymarket_gamma_public_api',
      min_volume_24h_usd: MIN_VOLUME_24H_USD,
      extreme_price_band: [EXTREME_PRICE_LOW, EXTREME_PRICE_HIGH]
    }
  };
}

export function buildPmTradePreflightFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      market_url: input?.market_url ?? null,
      condition_id: input?.condition_id ?? null,
      slug: input?.slug ?? 'demo-market',
      side: normalizeSide(input?.side),
      size_usd: parseOptionalUsd(input?.size_usd)
    },
    market: {
      condition_id: 'demo',
      slug: 'demo-market',
      title: 'Demo market (live data unavailable)',
      active: true,
      closed: false,
      volume_24h_usd: 25_000,
      outcomes: ['Yes', 'No'],
      outcome_prices: [0.42, 0.58]
    },
    action: 'watch',
    confidence: 0.4,
    reasons: ['Live Polymarket lookup unavailable; demo preflight only.'],
    risk_flags: ['live_data_unavailable'],
    side_price: 0.42,
    decision_card_lite: {
      fair_prob_range: [0.35, 0.5],
      max_entry: 0.45,
      price_status: 'unknown_demo',
      edge_after_fees_buffer: null,
      best_alternative_market: null,
      decision_mode: 'demo_only'
    },
    caveats: [...STANDARD_CAVEATS, 'Demo mode: do not trade on this response.'],
    next_gate: 'Leo_manual_order_approval_required',
    source: { provider: 'static_fallback' }
  };
}

function evaluatePreflight(market, side, sizeUsd) {
  const reasons = [];
  const risk_flags = [];
  let action = 'eligible';
  let confidence = 0.72;

  if (market.closed || !market.active) {
    return {
      action: 'skip',
      confidence: 0.9,
      reasons: ['Market is closed or inactive.'],
      risk_flags: ['market_closed_or_inactive'],
      side_price: getSidePrice(market, side)
    };
  }

  const sidePrice = getSidePrice(market, side);
  if (sidePrice === null) {
    return {
      action: 'skip',
      confidence: 0.85,
      reasons: [`Could not resolve price for side "${side}".`],
      risk_flags: ['missing_side_price'],
      side_price: null
    };
  }

  if (market.volume_24hr < MIN_VOLUME_24H_USD) {
    risk_flags.push('low_liquidity');
    reasons.push(`24h volume $${Math.round(market.volume_24hr)} is below $${MIN_VOLUME_24H_USD} threshold.`);
    action = 'watch';
    confidence -= 0.15;
  }

  if (sidePrice <= EXTREME_PRICE_LOW || sidePrice >= EXTREME_PRICE_HIGH) {
    risk_flags.push('extreme_implied_probability');
    reasons.push(`Side price ${round2(sidePrice)} is in an extreme zone for new entry.`);
    action = 'watch';
    confidence -= 0.12;
  }

  if (market.spread !== null && market.spread > MAX_SPREAD) {
    risk_flags.push('wide_spread');
    reasons.push(`Bid/ask spread ~${round2(market.spread)} looks wide.`);
    action = 'watch';
    confidence -= 0.1;
  }

  if (sizeUsd !== null && market.volume_24hr > 0 && sizeUsd > market.volume_24hr * SIZE_VS_VOLUME_RATIO) {
    risk_flags.push('size_large_vs_daily_volume');
    reasons.push(`Requested size $${sizeUsd} is large vs 24h volume $${Math.round(market.volume_24hr)}.`);
    action = 'watch';
    confidence -= 0.1;
  }

  if (action === 'eligible') {
    reasons.push('Liquidity, price zone, and spread checks passed heuristic preflight (eligible ≠ buy tip).');
  }

  return {
    action,
    confidence: round2(clamp(confidence, 0.35, 0.9)),
    reasons,
    risk_flags,
    side_price: round2(sidePrice)
  };
}

/**
 * Decision-card-lite: mechanical fair band + entry ceiling from price/liquidity
 * heuristics only. Not a full pm-decision-card (no account/exposure/sizing).
 */
function buildDecisionCardLite(market, side, evaluation) {
  const sidePrice = evaluation.side_price;
  if (sidePrice === null || sidePrice === undefined) {
    return {
      fair_prob_range: null,
      max_entry: null,
      price_status: 'missing_price',
      edge_after_fees_buffer: null,
      best_alternative_market: null,
      decision_mode: evaluation.action
    };
  }

  // Without an external model, treat a narrow band around mid as a "watch" fair zone,
  // and require a small edge buffer before considering entry.
  const halfBand = 0.04;
  const feeBuffer = 0.02;
  const fairLow = round2(clamp(sidePrice - halfBand, 0.01, 0.99));
  const fairHigh = round2(clamp(sidePrice + halfBand, 0.01, 0.99));
  const maxEntry = round2(clamp(sidePrice - feeBuffer, 0.01, 0.99));

  let price_status = 'at_market';
  if (evaluation.risk_flags.includes('extreme_implied_probability')) price_status = 'extreme_zone';
  else if (evaluation.action === 'eligible') price_status = 'mechanically_ok_not_a_buy';
  else if (evaluation.action === 'watch') price_status = 'watch_constraints';
  else if (evaluation.action === 'skip') price_status = 'skip';

  const otherOutcomes = (market.outcomes || [])
    .map((name, idx) => ({
      outcome: name,
      price: market.outcome_prices?.[idx] ?? null
    }))
    .filter((row) => String(row.outcome).toLowerCase() !== normalizeSide(side));

  return {
    fair_prob_range: [fairLow, fairHigh],
    max_entry: maxEntry,
    price_status,
    edge_after_fees_buffer: feeBuffer,
    best_alternative_market: otherOutcomes[0] ?? null,
    decision_mode: evaluation.action,
    note: 'fair_prob_range is a mechanical band around the live price, not a model-implied fair value.'
  };
}

function getSidePrice(market, side) {
  const normalized = normalizeSide(side);
  const idx = market.outcomes.findIndex((outcome) => String(outcome).toLowerCase() === normalized);
  if (idx < 0) return null;
  const price = market.outcome_prices[idx];
  return Number.isFinite(price) ? price : null;
}

function normalizeSide(side) {
  const raw = String(side ?? 'yes').trim().toLowerCase();
  if (raw === 'no') return 'no';
  return 'yes';
}

function parseOptionalUsd(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? round2(n) : null;
}
