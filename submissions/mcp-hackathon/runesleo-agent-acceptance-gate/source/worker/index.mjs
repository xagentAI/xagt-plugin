import { assessWorldCupSmartMoney } from '../src/worldcup-smart-money.mjs';
import {
  assessPolymarketSmartMoneyLive,
  assessWorldCupSmartMoneyLive,
  assessSportsSmartMoneyLive
} from '../src/worldcup-smart-money-live.mjs';
import {
  assessOkxAiDataService,
  getOkxAiDataServiceByPath,
  listOkxAiDataServices
} from '../src/okx-ai-data-services.mjs';
import {
  assessEventPriceDivergenceLive,
  buildEventPriceDivergenceFallback
} from '../src/event-price-divergence.mjs';
import {
  assessCryptoMarketRegimeLive,
  buildCryptoMarketRegimeFallback
} from '../src/crypto-market-regime.mjs';
import {
  assessWorldCupUpsetAlertLive,
  buildWorldCupUpsetAlertFallback,
  assessSportsUpsetAlertLive,
  buildSportsUpsetAlertFallback
} from '../src/world-cup-upset-alert.mjs';
import {
  assessPmProfileLive,
  buildPmProfileFallback
} from '../src/pm-profile.mjs';
import {
  assessPmPnlAuditLive,
  buildPmPnlAuditFallback
} from '../src/pm-pnl-audit.mjs';
import {
  assessAgentBudgetPreflight,
  buildAgentBudgetPreflightFallback
} from '../src/agent-budget-preflight.mjs';
import {
  assessTokenDdVerdictLive,
  buildTokenDdVerdictFallback
} from '../src/token-dd-verdict.mjs';
import {
  assessPmTradePreflightLive,
  buildPmTradePreflightFallback
} from '../src/pm-trade-preflight.mjs';
import {
  assessPmEventReadoutLive,
  buildPmEventReadoutFallback
} from '../src/pm-event-readout.mjs';
import {
  assessContentVerifyClaims
} from '../src/content-verify-claims.mjs';
import {
  assessContentSlopCheck,
  buildContentSlopCheckFallback
} from '../src/content-slop-check.mjs';
import {
  assessPmBrierLive,
  buildPmBrierFallback
} from '../src/pm-brier.mjs';
import {
  assessPublishReadiness,
  buildPublishReadinessFallback
} from '../src/publish-readiness.mjs';
import {
  assessFinanceCockpitLive,
  buildFinanceCockpitFallback
} from '../src/finance-cockpit.mjs';
import {
  assessSportsCockpitLive,
  buildSportsCockpitFallback
} from '../src/sports-cockpit.mjs';
import {
  assessWeatherEventReadoutLive,
  buildWeatherEventReadoutFallback,
  assessPoliticsEventReadoutLive,
  buildPoliticsEventReadoutFallback,
  assessMacroFedReadoutLive,
  buildMacroFedReadoutFallback,
  assessFootballMatchCardLive,
  buildFootballMatchCardFallback,
  assessTennisMatchCardLive,
  buildTennisMatchCardFallback,
  assessNbaMatchCardLive,
  buildNbaMatchCardFallback,
  samplePayloadForScenario
} from '../src/pm-scenario-skus.mjs';
import {
  assessPmDecisionCardLive,
  buildPmDecisionCardFallback
} from '../src/pm-decision-card.mjs';
import {
  assessPmMarketScanLive,
  buildPmMarketScanFallback
} from '../src/pm-market-scan.mjs';
import {
  assessPmMarketHealthLive,
  buildPmMarketHealthFallback
} from '../src/pm-market-health.mjs';
import {
  assessPmWalletReportLive,
  buildPmWalletReportFallback
} from '../src/pm-wallet-report.mjs';
import {
  assessPmUpdownReadoutLive,
  buildPmUpdownReadoutFallback
} from '../src/pm-updown-readout.mjs';
import { auditDelivery } from '../src/auditor.mjs';
import { handlePaidRequest, isX402Enabled, X402_CORS_HEADERS } from './x402.mjs';
import { getFeeAtomicForPath, getServiceCatalogEntry, LISTED_SERVICE_PATHS, SERVICE_CATALOG } from './service-catalog.mjs';
import {
  hasUsedFreeTrial,
  isFreeTrialEnabled,
  markFreeTrialUsed,
  withTrialBilling
} from './trial.mjs';

// Base headers are byte-identical to the pre-paywall deployment; x402-specific
// CORS additions are only applied when X402_ENABLED === 'true'.
const JSON_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, POST, OPTIONS',
  'access-control-allow-headers': 'content-type'
};

// Paid A2MCP endpoints (per-service x402 fee; optional one free trial per IP when X402_FREE_TRIAL=true).
const PAID_RADAR_ROUTES = {
  '/world-cup-smart-money-radar': {
    description: 'World Cup Smart Money Radar (legacy alias) — sports-generic pipeline scoped to world_cup; prefer /sports-smart-money-radar for other leagues.',
    load: (payload) => worldCupRadarWithCache(payload)
  },
  '/sports-smart-money-radar': {
    description: 'Sports Smart Money Radar — profitable Polymarket wallet signals for football/tennis/NBA/NFL/UFC/MLB etc. Pass sport + optional league/query/tag_slug.',
    load: (payload) => sportsSmartMoneyWithCache(payload)
  },
  '/polymarket-smart-money-radar': {
    description: 'Polymarket Smart Money Radar — site-wide or tag/event_type scoped wallet signals from large public trades.',
    load: (payload) => polymarketRadarWithCache(payload)
  },
  '/event-price-divergence-radar': {
    description: 'Event Price Divergence Radar — flags Polymarket event-probability moves that diverge from 24h crypto spot momentum on OKX.',
    load: (payload) => eventPriceDivergenceWithCache(payload)
  },
  '/crypto-market-regime-radar': {
    description: 'Crypto Market Regime Radar — blends OKX spot momentum, perp funding/premium and Polymarket event-probability drift into an explainable risk_on / risk_off / neutral / mixed regime call with a 0-100 score.',
    load: (payload) => cryptoMarketRegimeWithCache(payload)
  },
  '/world-cup-upset-alert': {
    description: 'World Cup Upset Alert (legacy alias) — prefer /sports-upset-alert for other competitions.',
    load: (payload) => worldCupUpsetAlertWithCache(payload)
  },
  '/sports-upset-alert': {
    description: 'Sports Upset Alert — profitable wallets entering low-probability sports outcomes (football leagues, tennis, NBA, etc.).',
    load: (payload) => sportsUpsetAlertWithCache(payload)
  },
  '/pm-profile': {
    description: 'PM Profile — read-only Polymarket wallet snapshot (7d LB PnL + positions sample). Productized from polymarket-toolkit.',
    load: (payload) => pmProfileWithCache(payload)
  },
  '/pm-pnl-audit': {
    description: 'PM PnL Audit — quick LB vs position cashPnL, or mode=full Worker-safe cashflow replay with honest pagination_incomplete. Data only.',
    load: (payload) => pmPnlAuditWithCache(payload)
  },
  '/pm-brier': {
    description: 'PM Brier — read-only calibration score from settled Polymarket positions (Brier). Productized from polymarket-toolkit.',
    load: (payload) => pmBrierWithCache(payload)
  },
  '/agent-budget-preflight': {
    description: 'Agent Budget Preflight — deterministic buy/skip/reject gate before an agent pays for an API/x402 call. No wallet, no settle. From arc-budget-agent policy.',
    load: (payload) => runAgentBudgetPreflight(payload)
  },
  '/agent-delivery-acceptance-audit': {
    description: 'Agent Delivery Audit Gate — audits an agent task delivery (evidence, validation, hard gates) and returns pass / needs_review / fail with a buyer summary.',
    // Deterministic per-payload audit — no cache (every audit input is unique).
    load: (payload) => runDeliveryAcceptanceAudit(payload)
  },
  '/token-dd-verdict': {
    description: 'Token DD Verdict — Standard-lite rule-based token research gate with optional DexScreener heuristics for EVM contracts.',
    load: (payload) => tokenDdVerdictWithCache(payload)
  },
  '/pm-trade-preflight': {
    description: 'PM Trade Preflight — read-only eligible/watch/skip gate + decision-card-lite fields before a Polymarket order.',
    load: (payload) => pmTradePreflightWithCache(payload)
  },
  '/pm-event-readout': {
    description: 'PM Event Analyst — same-event matrix + football/tennis/NBA/politics/weather/macro-Fed/Musk plugins; fixture/hard_veto where applicable.',
    load: (payload) => pmEventReadoutWithCache(payload)
  },
  '/content-verify-claims': {
    description: 'Content Verify Claims — rule-based check that publish claims overlap caller-supplied source excerpts (numbers + keywords); returns pass, needs_review, or fail.',
    load: (payload) => runContentVerifyClaims(payload)
  },
  '/content-slop-check': {
    description: 'Content Slop Check — rule-based AI-filler / spam-pattern detector for draft text; returns slop_score and flags. Not a rewrite service.',
    load: (payload) => runContentSlopCheck(payload)
  },
  '/publish-readiness': {
    description: 'Publish Readiness — combines slop check + claim verify into ready / edit_first / block before publish. No rewrite, no post.',
    load: (payload) => runPublishReadiness(payload)
  },
  '/finance-cockpit': {
    description: 'Finance Cockpit — composed crypto co-pilot: regime score + event-price divergence in one card. Data only.',
    load: (payload) => financeCockpitWithCache(payload)
  },
  '/sports-cockpit': {
    description: 'Sports Cockpit — composed sports co-pilot: smart-money + upset alerts (+ wallet cohort) in one card. Data only.',
    load: (payload) => sportsCockpitWithCache(payload)
  },
  '/weather-event-readout': {
    description: 'Weather Event Readout — temperature-ladder + hard_veto_gaps/adjacent-ladder; optional caller weather{}; no scrape. Pass query or slug.',
    load: (payload) => scenarioSkuWithCache('weather_event_readout', payload)
  },
  '/politics-event-readout': {
    description: 'Politics Event Readout — election/politics yes-mass ladder card. Pass query or slug.',
    load: (payload) => scenarioSkuWithCache('politics_event_readout', payload)
  },
  '/macro-fed-readout': {
    description: 'Macro Fed Readout — Fed/FOMC L1 rate ladder + expected-move heuristic; honest anchor gaps. Pass query or slug.',
    load: (payload) => scenarioSkuWithCache('macro_fed_readout', payload)
  },
  '/football-match-card': {
    description: 'Football Match Card — matrix + fixture gate + hard_veto_gaps + expression compare; match vs outright. Pass query or slug.',
    load: (payload) => scenarioSkuWithCache('football_match_card', payload)
  },
  '/tennis-match-card': {
    description: 'Tennis Match Card — format-aware matrix + fixture/hard_veto_gaps + domination check. Pass query or slug.',
    load: (payload) => scenarioSkuWithCache('tennis_match_card', payload)
  },
  '/nba-match-card': {
    description: 'NBA Match Card — moneyline/spread/totals matrix; match vs outright filter. Pass query or slug.',
    load: (payload) => scenarioSkuWithCache('nba_match_card', payload)
  },
  '/pm-decision-card': {
    description: 'PM Decision Card — opportunity_state + skip/watch/eligible; optional size/bankroll → share-first quantity. Replay before each order. Not a buy tip.',
    load: (payload) => pmDecisionCardWithCache(payload)
  },
  '/pm-market-scan': {
    description: 'PM Market Scan — read-only Gamma volume+spread scanner (polymarket-toolkit pm scan). Optional query; min_volume + limit.',
    load: (payload) => pmMarketScanWithCache(payload)
  },
  '/pm-market-health': {
    description: 'PM Market Health — spread / depth / overround snapshot for one market or event. Read-only; not a buy tip.',
    load: (payload) => pmMarketHealthWithCache(payload)
  },
  '/pm-wallet-report': {
    description: 'PM Wallet Report — one-pager composing profile + brier + pnl audit (quick/full). Read-only toolkit Drawer A.',
    load: (payload) => pmWalletReportWithCache(payload)
  },
  '/pm-updown-readout': {
    description: 'PM Up/Down Readout — crypto up/down event surface + resolution-source pitfalls (polymarket-toolkit pm updown). Read-only.',
    load: (payload) => pmUpdownReadoutWithCache(payload)
  }
};

export default {
  async fetch(request, env) {
    try {
      if (request.method === 'OPTIONS') {
        return new Response(null, {
          status: 204,
          headers: isX402Enabled(env) ? { ...JSON_HEADERS, ...X402_CORS_HEADERS } : JSON_HEADERS
        });
      }

      const url = new URL(request.url);

      if (request.method === 'GET' && url.pathname === '/health') {
        const identity = xAgentDeploymentIdentity(env);
        if (!identity.ok) {
          return json({
            status: 'misconfigured',
            commit: null,
            error: identity.error
          }, 503);
        }
        return json({
          status: 'ok',
          commit: identity.commit,
          ok: true,
          service: 'agent-acceptance-gate',
          mode: 'edge_worker',
          launch_lane: 'okx_ai_asp'
        });
      }

      if (
        request.method === 'GET'
        && url.pathname === '/.well-known/xagent-verification.json'
      ) {
        const identity = xAgentDeploymentIdentity(env);
        if (!identity.ok) {
          return json({
            schemaVersion: 1,
            slug: identity.slug,
            commit: null,
            error: identity.error
          }, 503);
        }
        return json({
          schemaVersion: 1,
          slug: identity.slug,
          commit: identity.commit
        });
      }

      if (request.method === 'GET' && url.pathname === '/api/okx-ai-services') {
        const trialOn = isFreeTrialEnabled(env);
        const listed = [...LISTED_SERVICE_PATHS].map((path) => {
          const meta = SERVICE_CATALOG[path];
          const route = PAID_RADAR_ROUTES[path];
          const row = {
            service_id: meta.service_id,
            path,
            title: meta.title,
            category: meta.category,
            fee_usdt: meta.fee_usdt,
            description: route?.description ?? meta.title,
            mode: meta.mode
          };
          if (trialOn) row.free_trial = 'one_per_client_ip_per_service';
          return row;
        });
        const unlisted = Object.entries(SERVICE_CATALOG)
          .filter(([path]) => !LISTED_SERVICE_PATHS.has(path))
          .map(([path, meta]) => ({
            service_id: meta.service_id,
            path,
            title: meta.title,
            category: meta.category,
            fee_usdt: meta.fee_usdt,
            mode: meta.mode
          }));
        return json({
          schema_version: '0.1',
          mode: 'edge_worker_live',
          billing: {
            x402_enabled: isX402Enabled(env),
            free_trial: trialOn
              ? 'One POST per client IP per service path, then x402 at fee_usdt.'
              : 'disabled (unpaid POST returns 402; set X402_FREE_TRIAL=true to opt in)',
            sample_get: 'GET the same service path for a public sample payload.'
          },
          fulfillment: {
            model: 'edge_on_demand',
            host: 'Cloudflare Worker at api.leolabs.me',
            operator_always_online: false,
            always_on_agent_required: false,
            llm_api_key_required: false,
            detail:
              'Each paid POST is fulfilled synchronously by the Worker: verify x402 → fetch public data / run rules → return JSON. No seller laptop, no standing agent, no LLM key for listed SKUs.'
          },
          services: [...listed, ...unlisted]
        });
      }

      if (
        request.method === 'POST'
        && url.pathname === '/xagent/agent-delivery-acceptance-audit'
      ) {
        if (!isXAgentReviewEnabled(env)) {
          return json({
            error: 'not_found',
            message: 'X-Agent review capability is disabled.'
          }, 404);
        }
        const identity = xAgentDeploymentIdentity(env);
        if (!identity.ok) {
          return json({
            error: 'misconfigured',
            message: identity.error
          }, 503);
        }
        return json(runDeliveryAcceptanceAudit(await readJson(request)));
      }

      if (request.method === 'GET' && PAID_RADAR_ROUTES[url.pathname]) {
        // Edge-cache public samples: each GET used to hit upstream data sources
        // live, so an unauthenticated crawler could burn upstream API quota.
        const sampleCache = globalThis.caches?.default;
        const sampleCacheKey = new Request(`${url.origin}${url.pathname}`, { method: 'GET' });
        if (sampleCache) {
          const cachedSample = await sampleCache.match(sampleCacheKey);
          if (cachedSample) return cachedSample;
        }
        const route = PAID_RADAR_ROUTES[url.pathname];
        const meta = getServiceCatalogEntry(url.pathname);
        const sampleRequest = samplePayloadForPath(url.pathname);
        const sampleResponse = await route.load(sampleRequest);
        const trialOn = isFreeTrialEnabled(env);
        const body = {
          schema_version: '0.1',
          mode: 'public_sample',
          path: url.pathname,
          fee_usdt: meta?.fee_usdt ?? null,
          sample_request: sampleRequest,
          sample_response: sampleResponse
        };
        if (trialOn) {
          body.free_trial = 'POST once without payment per client IP, then x402.';
        } else {
          body.billing = {
            mode: 'x402',
            unpaid_post: 'HTTP 402 payment-required challenge'
          };
        }
        const sampleResp = json(body, 200, { 'cache-control': 'public, max-age=600' });
        if (sampleCache) await sampleCache.put(sampleCacheKey, sampleResp.clone());
        return sampleResp;
      }

      if (request.method === 'POST' && PAID_RADAR_ROUTES[url.pathname]) {
        const route = PAID_RADAR_ROUTES[url.pathname];
        const pathname = url.pathname;
        const catalog = getServiceCatalogEntry(pathname);
        const priceAtomic = getFeeAtomicForPath(pathname);

        if (!isX402Enabled(env)) {
          return json(await route.load(await readJson(request)));
        }

        const hasPayment = request.headers.get('payment')
          || request.headers.get('payment-signature')
          || request.headers.get('x-payment');

        // Opt-in free trial only. Default unpaid path must 402 for OKX listing checks.
        if (
          !hasPayment
          && isFreeTrialEnabled(env)
          && !(await hasUsedFreeTrial(env, request, pathname))
        ) {
          const payload = await route.load(await readJson(request));
          await markFreeTrialUsed(env, request, pathname);
          return json(
            withTrialBilling(payload, { pathname, fee_usdt: catalog?.fee_usdt ?? '0.1' }),
            200,
            X402_CORS_HEADERS
          );
        }

        return handlePaidRequest(request, env, {
          resourceUrl: `${url.origin}${pathname}`,
          description: route.description,
          priceAtomic,
          deliver: async () => route.load(await readJson(request)),
          respond: (payload, status = 200, extraHeaders = undefined) =>
            json(payload, status, { ...X402_CORS_HEADERS, ...(extraHeaders || {}) })
        });
      }

      if (request.method === 'POST') {
        const service = getOkxAiDataServiceByPath(url.pathname);
        if (service) {
          const payload = await readJson(request);
          return json(assessOkxAiDataService(service, payload));
        }
      }

      return json({
        error: 'not_found',
        message: 'Use GET /health, GET /api/okx-ai-services, or POST one of the listed service paths.'
      }, 404);
    } catch (error) {
      return json({
        error: 'bad_request',
        message: error instanceof Error ? error.message : String(error)
      }, 400);
    }
  }
};

// In-memory per-isolate cache for radar responses. Shields the paid A2MCP
// endpoints from Polymarket rate limits; entries expire after CACHE_TTL_MS.
const CACHE_TTL_MS = 120_000;
const radarCache = new Map();

async function worldCupRadarWithCache(payload) {
  const market = String(payload?.market ?? payload?.market_id ?? payload?.query ?? 'all').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `wc|${market}|${limit}`,
    loadLive: () => assessWorldCupSmartMoneyLive(payload),
    loadFallback: () => assessWorldCupSmartMoney(payload)
  });
}

async function sportsSmartMoneyWithCache(payload) {
  const sport = String(payload?.sport ?? 'all').trim().toLowerCase();
  const league = String(payload?.league ?? '').trim().toLowerCase();
  const query = String(payload?.query ?? payload?.market ?? 'all').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `sports-sm|${sport}|${league}|${query}|${limit}`,
    loadLive: () => assessSportsSmartMoneyLive(payload),
    loadFallback: () => assessWorldCupSmartMoney(payload)
  });
}

async function sportsUpsetAlertWithCache(payload) {
  const sport = String(payload?.sport ?? 'all').trim().toLowerCase();
  const league = String(payload?.league ?? '').trim().toLowerCase();
  const query = String(payload?.query ?? payload?.market ?? 'all').trim().toLowerCase();
  const maxProb = String(payload?.max_prob ?? payload?.max_implied_probability ?? '0.35');
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `sports-upset|${sport}|${league}|${query}|${maxProb}|${limit}`,
    loadLive: () => assessSportsUpsetAlertLive(payload),
    loadFallback: () => buildSportsUpsetAlertFallback(payload)
  });
}

async function pmProfileWithCache(payload) {
  const key = String(payload?.address ?? payload?.wallet ?? payload?.username ?? payload?.query ?? '').trim().toLowerCase();
  if (!key) {
    throw new Error('pm-profile requires address or username.');
  }

  return radarWithCache({
    cacheKey: `pm-profile|${key}`,
    loadLive: () => assessPmProfileLive(payload),
    loadFallback: () => buildPmProfileFallback(payload)
  });
}

async function pmPnlAuditWithCache(payload) {
  const key = String(payload?.address ?? payload?.wallet ?? payload?.username ?? payload?.query ?? '').trim().toLowerCase();
  if (!key) {
    throw new Error('pm-pnl-audit requires address or username.');
  }
  const mode = String(payload?.mode ?? 'quick').trim().toLowerCase() === 'full' ? 'full' : 'quick';
  const limit = Number.parseInt(payload?.positions_limit ?? payload?.limit, 10) || 100;

  return radarWithCache({
    cacheKey: `pm-pnl-audit|${key}|${mode}|${limit}`,
    loadLive: () => assessPmPnlAuditLive(payload),
    loadFallback: () => buildPmPnlAuditFallback(payload)
  });
}

async function pmBrierWithCache(payload) {
  const key = String(payload?.address ?? payload?.wallet ?? payload?.username ?? payload?.query ?? '').trim().toLowerCase();
  if (!key) {
    throw new Error('pm-brier requires address or username.');
  }
  const limit = Number.parseInt(payload?.limit, 10) || 200;

  return radarWithCache({
    cacheKey: `pm-brier|${key}|${limit}`,
    loadLive: () => assessPmBrierLive(payload),
    loadFallback: () => buildPmBrierFallback(payload)
  });
}

async function polymarketRadarWithCache(payload) {
  const query = String(payload?.market ?? payload?.topic ?? payload?.query ?? 'all').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `pm|${query}|${limit}`,
    loadLive: () => assessPolymarketSmartMoneyLive(payload),
    loadFallback: () => {
      const service = getOkxAiDataServiceByPath('/polymarket-smart-money-radar');
      return assessOkxAiDataService(service, payload);
    }
  });
}

async function eventPriceDivergenceWithCache(payload) {
  const asset = String(payload?.asset ?? 'all').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `divergence|${asset}|${limit}`,
    loadLive: () => assessEventPriceDivergenceLive(payload),
    loadFallback: () => buildEventPriceDivergenceFallback(payload)
  });
}

async function cryptoMarketRegimeWithCache(payload) {
  const focus = String(payload?.focus ?? payload?.asset ?? 'all').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `regime|${focus}|${limit}`,
    loadLive: () => assessCryptoMarketRegimeLive(payload),
    loadFallback: () => buildCryptoMarketRegimeFallback(payload)
  });
}

async function financeCockpitWithCache(payload) {
  const focus = String(payload?.focus ?? payload?.asset ?? 'all').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `finance-cockpit|${focus}|${limit}`,
    loadLive: () => assessFinanceCockpitLive(payload),
    loadFallback: () => buildFinanceCockpitFallback(payload)
  });
}

async function sportsCockpitWithCache(payload) {
  const sport = String(payload?.sport ?? 'all').trim().toLowerCase();
  const league = String(payload?.league ?? '').trim().toLowerCase();
  const query = String(payload?.query ?? payload?.market ?? 'all').trim().toLowerCase();
  const maxProb = String(payload?.max_prob ?? payload?.max_implied_probability ?? '0.35');
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `sports-cockpit|${sport}|${league}|${query}|${maxProb}|${limit}`,
    loadLive: () => assessSportsCockpitLive(payload),
    loadFallback: () => buildSportsCockpitFallback(payload)
  });
}

const SCENARIO_LOADERS = {
  weather_event_readout: {
    live: assessWeatherEventReadoutLive,
    fallback: buildWeatherEventReadoutFallback
  },
  politics_event_readout: {
    live: assessPoliticsEventReadoutLive,
    fallback: buildPoliticsEventReadoutFallback
  },
  macro_fed_readout: {
    live: assessMacroFedReadoutLive,
    fallback: buildMacroFedReadoutFallback
  },
  football_match_card: {
    live: assessFootballMatchCardLive,
    fallback: buildFootballMatchCardFallback
  },
  tennis_match_card: {
    live: assessTennisMatchCardLive,
    fallback: buildTennisMatchCardFallback
  },
  nba_match_card: {
    live: assessNbaMatchCardLive,
    fallback: buildNbaMatchCardFallback
  }
};

async function scenarioSkuWithCache(scenarioId, payload) {
  const loader = SCENARIO_LOADERS[scenarioId];
  if (!loader) throw new Error(`Unknown scenario ${scenarioId}`);
  const ref = String(
    payload?.condition_id
    ?? payload?.slug
    ?? payload?.market_url
    ?? payload?.query
    ?? payload?.market
    ?? 'default'
  ).trim().toLowerCase();

  return radarWithCache({
    cacheKey: `scenario|${scenarioId}|${ref}`,
    loadLive: () => loader.live(payload),
    loadFallback: () => loader.fallback(payload)
  });
}

async function pmDecisionCardWithCache(payload) {
  const ref = String(
    payload?.condition_id
    ?? payload?.slug
    ?? payload?.market_url
    ?? ''
  ).trim().toLowerCase();
  if (!ref) {
    throw new Error('pm-decision-card requires market_url, condition_id, or slug.');
  }
  const side = String(payload?.side ?? 'yes').trim().toLowerCase();
  const includeEvent = payload?.include_event_context === false ? '0' : '1';

  return radarWithCache({
    cacheKey: `decision-card|${ref}|${side}|${includeEvent}|${payload?.size_usd ?? ''}`,
    loadLive: () => assessPmDecisionCardLive(payload),
    loadFallback: () => buildPmDecisionCardFallback(payload)
  });
}

async function pmMarketScanWithCache(payload) {
  const query = String(payload?.query ?? payload?.q ?? '').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 10;
  const minVolume = Number(payload?.min_volume ?? payload?.minVolume ?? 1000) || 1000;

  return radarWithCache({
    cacheKey: `pm-scan|${query || 'top'}|${limit}|${minVolume}`,
    loadLive: () => assessPmMarketScanLive(payload),
    loadFallback: () => buildPmMarketScanFallback(payload)
  });
}

async function pmMarketHealthWithCache(payload) {
  const ref = String(
    payload?.event_slug
    ?? payload?.eventSlug
    ?? payload?.condition_id
    ?? payload?.slug
    ?? payload?.market_url
    ?? ''
  ).trim().toLowerCase();
  if (!ref) {
    throw new Error('pm-market-health requires market_url, slug, condition_id, or event_slug.');
  }

  return radarWithCache({
    cacheKey: `pm-health|${ref}`,
    loadLive: () => assessPmMarketHealthLive(payload),
    loadFallback: () => buildPmMarketHealthFallback(payload)
  });
}

async function pmWalletReportWithCache(payload) {
  const key = String(payload?.address ?? payload?.wallet ?? payload?.username ?? payload?.query ?? '').trim().toLowerCase();
  if (!key) {
    throw new Error('pm-wallet-report requires address or username.');
  }
  const pnlMode = String(payload?.pnl_mode ?? payload?.mode ?? 'quick').trim().toLowerCase() === 'full' ? 'full' : 'quick';

  return radarWithCache({
    cacheKey: `pm-wallet-report|${key}|${pnlMode}`,
    loadLive: () => assessPmWalletReportLive(payload),
    loadFallback: () => buildPmWalletReportFallback(payload)
  });
}

async function pmUpdownReadoutWithCache(payload) {
  const ref = String(
    payload?.event_slug
    ?? payload?.slug
    ?? payload?.query
    ?? payload?.q
    ?? ''
  ).trim().toLowerCase();
  if (!ref) {
    throw new Error('pm-updown-readout requires event_slug/slug or query.');
  }

  return radarWithCache({
    cacheKey: `pm-updown|${ref}`,
    loadLive: () => assessPmUpdownReadoutLive(payload),
    loadFallback: () => buildPmUpdownReadoutFallback(payload)
  });
}

async function worldCupUpsetAlertWithCache(payload) {
  const market = String(payload?.market ?? payload?.market_id ?? payload?.query ?? 'all').trim().toLowerCase();
  const limit = Number.parseInt(payload?.limit, 10) || 5;

  return radarWithCache({
    cacheKey: `upset|${market}|${limit}`,
    loadLive: () => assessWorldCupUpsetAlertLive(payload),
    loadFallback: () => buildWorldCupUpsetAlertFallback(payload)
  });
}

async function tokenDdVerdictWithCache(payload) {
  const asset = String(payload?.asset ?? payload?.token ?? payload?.query ?? '').trim().toLowerCase();
  if (!asset) {
    throw new Error('token-dd-verdict requires asset (ticker, contract address, or URL).');
  }

  return radarWithCache({
    cacheKey: `token-dd|${asset}`,
    loadLive: () => assessTokenDdVerdictLive(payload),
    loadFallback: () => buildTokenDdVerdictFallback(payload)
  });
}

async function pmTradePreflightWithCache(payload) {
  const ref = String(
    payload?.condition_id
    ?? payload?.slug
    ?? payload?.market_url
    ?? ''
  ).trim().toLowerCase();
  const side = String(payload?.side ?? 'yes').trim().toLowerCase();
  if (!ref) {
    throw new Error('pm-trade-preflight requires market_url, condition_id, or slug.');
  }

  return radarWithCache({
    cacheKey: `preflight|${ref}|${side}|${payload?.size_usd ?? ''}`,
    loadLive: () => assessPmTradePreflightLive(payload),
    loadFallback: () => buildPmTradePreflightFallback(payload)
  });
}

async function pmEventReadoutWithCache(payload) {
  const ref = String(
    payload?.condition_id
    ?? payload?.slug
    ?? payload?.market_url
    ?? ''
  ).trim().toLowerCase();
  if (!ref) {
    throw new Error('pm-event-readout requires market_url, condition_id, or slug.');
  }

  // Fixture / musk / tennis options change the enriched output — must be part of cache key.
  const football = payload?.football && typeof payload.football === 'object' ? payload.football : null;
  const tennis = payload?.tennis && typeof payload.tennis === 'object' ? payload.tennis : null;
  const nba = payload?.nba && typeof payload.nba === 'object' ? payload.nba : null;
  const nfl = payload?.nfl && typeof payload.nfl === 'object' ? payload.nfl : null;
  const musk = payload?.musk && typeof payload.musk === 'object' ? payload.musk : null;
  const optionKey = [
    football?.verified === true ? `fv:${football.market_fixture_match || 'yes'}` : 'fv:none',
    tennis?.verified === true ? `tv:${tennis.market_fixture_match || 'yes'}` : 'tv:none',
    nba?.verified === true ? `nv:${nba.market_fixture_match || 'yes'}` : 'nv:none',
    nfl?.verified === true ? `nf:${nfl.market_fixture_match || 'yes'}` : 'nf:none',
    musk?.current_count != null ? `mc:${musk.current_count}` : 'mc:none'
  ].join('|');

  return radarWithCache({
    cacheKey: `readout|${ref}|${optionKey}`,
    loadLive: () => assessPmEventReadoutLive(payload),
    loadFallback: () => buildPmEventReadoutFallback(payload)
  });
}

function runContentVerifyClaims(payload) {
  return assessContentVerifyClaims(payload);
}

function runContentSlopCheck(payload) {
  try {
    return assessContentSlopCheck(payload);
  } catch (error) {
    if (String(error?.message || error).includes('required')) throw error;
    return buildContentSlopCheckFallback(payload);
  }
}

function runAgentBudgetPreflight(payload) {
  try {
    return assessAgentBudgetPreflight(payload);
  } catch (error) {
    if (String(error?.message || error).includes('required')) throw error;
    return buildAgentBudgetPreflightFallback(payload);
  }
}

function runPublishReadiness(payload) {
  try {
    return assessPublishReadiness(payload);
  } catch (error) {
    if (String(error?.message || error).includes('required')) throw error;
    return buildPublishReadinessFallback(payload);
  }
}

// ---- Agent Delivery Audit Gate ---------------------------------------------
// Accepts either the full auditor schema ({task, delivery, context}) or the
// compact buyer shape {task, delivery_summary, artifacts, validation,
// hard_gates?, next_gate?} and adapts it before calling auditDelivery.
// Invalid input throws BEFORE x402 settle, so a bad request never burns a payment.
function runDeliveryAcceptanceAudit(payload) {
  const input = normalizeAuditInput(payload);
  return auditDelivery(input);
}

function normalizeAuditInput(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Audit input must be a JSON object with at least {task, delivery_summary}.');
  }

  // Full auditor schema passes through untouched (context defaulted).
  if (payload.delivery && typeof payload.delivery === 'object') {
    return { ...payload, context: payload.context ?? { repo_state: 'unknown' } };
  }

  const task = typeof payload.task === 'string'
    ? { buyer_goal: payload.task }
    : (payload.task && typeof payload.task === 'object' ? { ...payload.task } : null);
  if (task && !task.buyer_goal) {
    task.buyer_goal = task.goal ?? task.description ?? null;
  }
  if (!task?.buyer_goal || !payload.delivery_summary) {
    throw new Error('Audit input requires task (string or {buyer_goal, ...}) and delivery_summary. Optional: artifacts[], validation[], changed_files[], hard_gates[], next_gate, context.');
  }

  return {
    schema_version: '0.1',
    mode: payload.mode ?? 'full',
    task,
    delivery: {
      writeback_text: String(payload.delivery_summary),
      artifact_paths: toStringArray(payload.artifacts),
      changed_files: toStringArray(payload.changed_files),
      validation: toStringArray(payload.validation),
      validation_output: payload.validation_output ?? null,
      rollback_plan: payload.rollback_plan ?? null,
      hard_gates_declared: toStringArray(payload.hard_gates),
      next_gate: payload.next_gate
        ? String(payload.next_gate)
        : 'Buyer manual review before acceptance (seller declared no next gate).'
    },
    context: payload.context && typeof payload.context === 'object'
      ? payload.context
      : { repo_state: payload.repo_state ?? 'unknown' }
  };
}

function toStringArray(value) {
  if (value === null || value === undefined) return [];
  const items = Array.isArray(value) ? value : [value];
  return items.map((item) => String(item)).filter((item) => item.trim().length > 0);
}

async function radarWithCache({ cacheKey, loadLive, loadFallback }) {
  const cached = radarCache.get(cacheKey);
  if (cached && Date.now() - cached.storedAt < CACHE_TTL_MS) {
    return { ...cached.payload, cache: 'hit' };
  }

  try {
    const live = await loadLive();
    radarCache.set(cacheKey, { storedAt: Date.now(), payload: live });
    pruneCache();
    return live;
  } catch (error) {
    // Never 5xx a paid call: serve stale cache first, then degraded demo data.
    if (cached) {
      return {
        ...cached.payload,
        cache: 'stale',
        mode: 'degraded_stale_cache',
        capability_status: 'upstream_degraded',
        caveats: [
          `Live upstream fetch failed (${error instanceof Error ? error.message : String(error)}); serving stale cached live data.`,
          'Treat this as stale evidence and retry shortly before acting.',
          ...(cached.payload.caveats || [])
        ]
      };
    }
    const fallback = loadFallback();
    fallback.mode = 'degraded';
    fallback.capability_status = 'upstream_degraded';
    fallback.action = fallback.action ?? 'retry_later';
    fallback.live_data_status = 'unavailable';
    fallback.caveats = [
      `Live upstream fetch failed (${error instanceof Error ? error.message : String(error)}); serving static fallback data only.`,
      'This is not a live market readout. Do not treat sample/static fields as current capability output; retry shortly for live data.',
      ...fallback.caveats
    ];
    fallback.source = {
      ...(fallback.source || {}),
      provider: fallback.source?.provider ?? 'static_fallback',
      degraded_reason: 'upstream_fetch_failed'
    };
    return fallback;
  }
}

function pruneCache() {
  if (radarCache.size <= 32) return;
  const oldestFirst = [...radarCache.entries()].sort((a, b) => a[1].storedAt - b[1].storedAt);
  for (const [key] of oldestFirst.slice(0, radarCache.size - 32)) {
    radarCache.delete(key);
  }
}

function samplePayloadForPath(pathname) {
  switch (pathname) {
    case '/agent-delivery-acceptance-audit':
      return {
        task: 'Ship a read-only health endpoint for the worker.',
        delivery_summary: 'Added GET /health and npm test passes.',
        artifacts: ['worker/index.mjs'],
        validation: ['npm test']
      };
    case '/event-price-divergence-radar':
      return { asset: 'bitcoin', limit: 2 };
    case '/polymarket-smart-money-radar':
      return { query: 'bitcoin', limit: 2 };
    case '/world-cup-smart-money-radar':
    case '/world-cup-upset-alert':
      return { query: 'all', limit: 2 };
    case '/sports-smart-money-radar':
    case '/sports-upset-alert':
      return { sport: 'football', league: 'epl', limit: 2 };
    case '/pm-profile':
      return { address: '0x63ce342161250d705dc0b16df89036c8e5f9ba9a' };
    case '/pm-pnl-audit':
      return { address: '0x63ce342161250d705dc0b16df89036c8e5f9ba9a', mode: 'quick' };
    case '/pm-brier':
      return { address: '0x63ce342161250d705dc0b16df89036c8e5f9ba9a', limit: 50 };
    case '/agent-budget-preflight':
      return {
        budget_cap_usdt: 1,
        spent_usdt: 0.2,
        max_per_call_usdt: 0.5,
        evidence_sufficient: false,
        offer: {
          provider: 'leo-labs',
          price_usdt: 0.1,
          resource_url: 'https://api.leolabs.me/pm-profile'
        }
      };
    case '/crypto-market-regime-radar':
      return { focus: 'bitcoin', limit: 2 };
    case '/token-dd-verdict':
      return { asset: '0x000000000000000000000000000000000000dead' };
    case '/pm-trade-preflight':
      return { slug: 'will-argentina-win-the-2026-fifa-world-cup-245', side: 'yes' };
    case '/pm-event-readout':
      return {
        slug: 'fifwc-fra-mar-2026-07-09-fra',
        football: {
          verified: true,
          market_fixture_match: 'yes',
          scheduled_time_utc: '2026-07-09T20:00:00Z',
          fixture_sources: ['caller_verified']
        }
      };
    case '/content-verify-claims':
      return {
        claims: ['Platform has about 360 ASPs and roughly 3000 cumulative calls.'],
        sources: [{
          text: 'Marketplace scan on 2026-07-07: 358 unique ASPs and about 2982 cumulative soldCount.'
        }]
      };
    case '/content-slop-check':
      return {
        text: 'In today\'s digital landscape, it is crucial to delve into synergy and leverage robust holistic frameworks. As an AI, I am excited to underscore the importance of this game-changer.'
      };
    case '/publish-readiness':
      return {
        text: 'Marketplace scan on 2026-07-07 found 358 unique ASPs and 2982 cumulative soldCount.',
        claims: ['Marketplace has 358 unique ASPs and 2982 cumulative soldCount.'],
        sources: [{ text: 'Marketplace scan on 2026-07-07 found 358 unique ASPs and 2982 cumulative soldCount.' }]
      };
    case '/finance-cockpit':
      return { focus: 'bitcoin', limit: 2 };
    case '/sports-cockpit':
      return { sport: 'football', league: 'epl', limit: 2 };
    case '/weather-event-readout':
      return samplePayloadForScenario('weather_event_readout');
    case '/politics-event-readout':
      return samplePayloadForScenario('politics_event_readout');
    case '/macro-fed-readout':
      return samplePayloadForScenario('macro_fed_readout');
    case '/football-match-card':
      return samplePayloadForScenario('football_match_card');
    case '/tennis-match-card':
      return samplePayloadForScenario('tennis_match_card');
    case '/nba-match-card':
      return samplePayloadForScenario('nba_match_card');
    case '/pm-decision-card':
      return {
        slug: 'will-argentina-win-the-2026-fifa-world-cup-245',
        side: 'yes',
        size_usd: 25,
        include_event_context: true
      };
    case '/pm-market-scan':
      return { limit: 5, min_volume: 1000 };
    case '/pm-market-health':
      return { slug: 'will-argentina-win-the-2026-fifa-world-cup-245' };
    case '/pm-wallet-report':
      return { address: '0x63ce342161250d705dc0b16df89036c8e5f9ba9a', pnl_mode: 'quick' };
    case '/pm-updown-readout':
      return { query: 'btc updown' };
    default:
      return { limit: 2 };
  }
}

async function readJson(request) {
  const text = await request.text();
  if (!text.trim()) return {};
  if (text.length > 1_000_000) {
    throw new Error('Request body too large');
  }
  return JSON.parse(text);
}

function isXAgentReviewEnabled(env) {
  return String(env?.XAGENT_REVIEW_ENABLED ?? '').trim().toLowerCase() === 'true';
}

function xAgentDeploymentIdentity(env) {
  const commit = String(env?.XAGENT_GIT_COMMIT ?? '').trim().toLowerCase();
  const slug = String(
    env?.XAGENT_PROJECT_SLUG ?? 'runesleo-agent-acceptance-gate'
  ).trim().toLowerCase();

  if (!/^[0-9a-f]{40}$/.test(commit)) {
    return {
      ok: false,
      slug,
      commit: null,
      error: 'XAGENT_GIT_COMMIT must be the exact 40-character deployed Git commit.'
    };
  }
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
    return {
      ok: false,
      slug,
      commit: null,
      error: 'XAGENT_PROJECT_SLUG must be a lowercase kebab-case slug.'
    };
  }
  return { ok: true, slug, commit };
}

function json(payload, status = 200, extraHeaders = undefined) {
  return new Response(`${JSON.stringify(payload, null, 2)}\n`, {
    status,
    headers: extraHeaders ? { ...JSON_HEADERS, ...extraHeaders } : JSON_HEADERS
  });
}
