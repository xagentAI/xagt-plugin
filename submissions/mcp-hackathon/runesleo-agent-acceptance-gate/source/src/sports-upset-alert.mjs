// Sports Upset Alert — generic sports/PM low-probability smart-money filter.
// World Cup Upset Alert is a thin legacy wrapper (league=world_cup).

import {
  resolveSportsMarkets,
  resolveWorldCupMarkets,
  scanMarketsForSmartMoney
} from './worldcup-smart-money-live.mjs';

const SERVICE_ID = 'sports_upset_alert';
const LEGACY_SERVICE_ID = 'world_cup_upset_alert';

const MAX_UPSET_PROBABILITY = 0.35;
const DEEP_UPSET_PROBABILITY = 0.2;
const SCAN_CANDIDATES = 12;

const STANDARD_CAVEATS = [
  'Data and analytics only. Not investment advice, not betting advice, and not a guarantee of future returns.',
  'No wallet custody, no user funds, no trade execution, no order routing.',
  'Upset alerts are heuristic reads of recent large public trades on Polymarket: a profitable wallet buying the low-probability side can also be hedging, market-making, or wrong.',
  'seven-day PnL comes from the Polymarket 7d profit leaderboard; wallets absent from it are excluded from alerts (never estimated).',
  'World Cup is one sports scope — pass sport/league for EPL/UCL/tennis/NBA/etc.'
];

export async function assessWorldCupUpsetAlertLive(input = {}, options = {}) {
  return assessSportsUpsetAlertLive({
    ...input,
    sport: input.sport ?? 'football',
    league: input.league ?? 'world_cup',
    tag_slug: input.tag_slug ?? 'world-cup'
  }, { ...options, serviceId: LEGACY_SERVICE_ID, legacyWorldCup: true });
}

export async function assessSportsUpsetAlertLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const limit = clampInteger(input.limit, 1, 10, 5);
  const serviceId = options.serviceId ?? SERVICE_ID;
  const maxProb = clampProbability(
    input.max_prob ?? input.max_implied_probability ?? input.max_upset_probability,
    0.05,
    0.5,
    MAX_UPSET_PROBABILITY
  );
  const deepProb = Math.min(DEEP_UPSET_PROBABILITY, maxProb * 0.6);

  let markets;
  let usedFallback;
  let discovery = null;

  if (options.legacyWorldCup) {
    const marketHint = normalizeText(input.market ?? input.market_id ?? input.query ?? 'all');
    const resolved = await resolveWorldCupMarkets(fetchImpl, marketHint);
    markets = resolved.markets;
    usedFallback = resolved.usedFallback;
    discovery = resolved.discovery;
  } else {
    const resolved = await resolveSportsMarkets(fetchImpl, input);
    markets = resolved.markets;
    usedFallback = resolved.usedFallback;
    discovery = resolved.discovery;
  }

  const { scanned, enriched, wallet_cohort = [] } = await scanMarketsForSmartMoney(
    fetchImpl,
    markets,
    SCAN_CANDIDATES
  );

  const alerts = enriched
    .filter((signal) => isUpsetCandidate(signal, maxProb))
    .map((signal) => buildUpsetAlert(signal, deepProb))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, limit);

  const caveats = [...STANDARD_CAVEATS];
  if (discovery?.scope_expanded) {
    caveats.push(`No active ${discovery.requested_scope} markets matched; expanded live discovery to ${discovery.effective_scope} sports markets.`);
  } else if (usedFallback) {
    caveats.push(options.legacyWorldCup
      ? 'No active World Cup markets matched; fell back to Polymarket top-volume markets site-wide.'
      : 'No active scoped sports markets matched; fell back to top-volume / search.');
  }
  if (maxProb !== MAX_UPSET_PROBABILITY) {
    caveats.push(`Caller overridden max_implied_probability=${maxProb} (default ${MAX_UPSET_PROBABILITY}).`);
  }

  return {
    schema_version: '0.3',
    service_id: serviceId,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      sport: input.sport ?? null,
      league: input.league ?? null,
      tag_slug: input.tag_slug ?? null,
      query: input.query ?? input.market ?? input.market_id ?? 'all',
      max_prob: maxProb,
      limit
    },
    buyer_summary_zh: buildBuyerSummaryZh(alerts, scanned, enriched, discovery),
    buyer_summary_en: buildBuyerSummaryEn(alerts, scanned, enriched, discovery),
    summary: buildSummary(alerts, scanned, enriched),
    upset_alerts: alerts,
    wallet_cohort: wallet_cohort.filter((w) => w.cross_market).slice(0, 5),
    caveats,
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: {
      provider: 'polymarket_public_api',
      pipeline: 'sports_smart_money scan + upset filter',
      filter: {
        wallet_7d_pnl: '> 0 (leaderboard-confirmed profitable wallets only)',
        action: 'new_position or increased_position (net buying)',
        max_implied_probability: maxProb,
        deep_upset_probability: deepProb
      },
      discovery,
      markets_scanned: scanned.map((market) => ({
        market_id: market.market_id,
        condition_id: market.condition_id,
        title: market.title
      }))
    }
  };
}

export function buildWorldCupUpsetAlertFallback(input = {}) {
  return buildSportsUpsetAlertFallback({ ...input, service_id: LEGACY_SERVICE_ID });
}

export function buildSportsUpsetAlertFallback(input = {}) {
  return {
    schema_version: '0.2',
    service_id: input.service_id ?? SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      sport: input.sport ?? null,
      league: input.league ?? null,
      query: input.query ?? 'all',
      limit: clampInteger(input.limit, 1, 10, 5)
    },
    summary: 'Demo fallback — live sports upset scan unavailable.',
    upset_alerts: [],
    caveats: [...STANDARD_CAVEATS, 'Demo mode: empty alerts.'],
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: { provider: 'static_fallback' }
  };
}

function isUpsetCandidate(signal, maxProb = MAX_UPSET_PROBABILITY) {
  const price = Number(signal.last_trade_price);
  const pnl = signal.seven_day_pnl_usdt;
  const action = signal.action;
  if (!Number.isFinite(price) || price >= maxProb) return false;
  if (pnl === null || pnl === undefined || Number(pnl) <= 0) return false;
  if (action !== 'new_position' && action !== 'increased_position') return false;
  return true;
}

function buildUpsetAlert(signal, deepProb = DEEP_UPSET_PROBABILITY) {
  const price = Number(signal.last_trade_price);
  const deep = price < deepProb;
  return {
    ...signal,
    upset_band: deep ? 'deep_upset' : 'upset',
    implied_probability: price,
    confidence: Number(signal.confidence ?? 0.5) + (deep ? 0.05 : 0)
  };
}

function buildSummary(alerts, scanned, enriched) {
  return `Scanned ${scanned.length} markets / ${enriched.length} smart-money candidates → ${alerts.length} upset alert(s).`;
}

function buildBuyerSummaryZh(alerts, scanned, enriched, discovery) {
  const summary = buildSummary(alerts, scanned, enriched);
  if (discovery?.scope_expanded) {
    return `请求范围 ${discovery.requested_scope} 当前无活跃市场，已自动扩展到 ${discovery.effective_scope} 体育市场并返回真实 upset 扫描。${summary}`;
  }
  return `已扫描真实 Polymarket 体育市场的低概率大额交易。${summary}`;
}

function buildBuyerSummaryEn(alerts, scanned, enriched, discovery) {
  const summary = buildSummary(alerts, scanned, enriched);
  if (discovery?.scope_expanded) {
    return `Requested ${discovery.requested_scope} had no active markets, so live discovery expanded to ${discovery.effective_scope} sports markets and returned a real upset scan. ${summary}`;
  }
  return `Scanned real Polymarket sports markets for low-probability large-trade entries. ${summary}`;
}

function normalizeText(value) {
  return String(value ?? '').trim().toLowerCase();
}

function clampInteger(value, min, max, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function clampProbability(value, min, max, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}
