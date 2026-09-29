/**
 * Project agent-facing PM Event Readout (schema 0.2) onto
 * Copilot Research Unit (copilot.read-model.v0.1).
 *
 * Pure / sync. No network. Never invents BET eligibility from L0 tradability.
 * Contract: research/2026-07-12-pm-event-analyst-dual-surface-contract.md
 */

export const COPILOT_SCHEMA_ID = 'copilot.read-model.v0.1';
export const COPILOT_SCHEMA_VERSION = '0.1.0';
export const AGENT_EXTENSION_KEY = 'pm-event-readout.v0.2';

const FORBIDDEN_ROOT_KEYS = new Set([
  'city',
  'cities',
  'temperature',
  'tempF',
  'tempC',
  'weather',
  'bucketId',
  'buckets',
  'metar',
  'stationId',
  'articleSlug',
  'blogPath',
  'contentTaxonomy',
  'seoTitle',
  'internalLinks',
  'order',
  'orders',
  'positionSize',
  'wallet',
  'privateKey',
  'apiKey',
  'copyTrade'
]);

/**
 * @param {object} agentPayload — assessPmEventReadoutLive result (or fixture)
 * @param {{ unitId: string }} options
 * @returns {{ ok: true, value: object } | { ok: false, errors: string[] }}
 */
export function toCopilotResearchUnit(agentPayload, options = {}) {
  const errors = [];
  if (!agentPayload || typeof agentPayload !== 'object' || Array.isArray(agentPayload)) {
    return { ok: false, errors: ['agentPayload must be a non-null object'] };
  }
  const unitId = typeof options.unitId === 'string' ? options.unitId.trim() : '';
  if (!unitId) {
    return { ok: false, errors: ['options.unitId is required and non-empty'] };
  }

  const asOf =
    typeof agentPayload.generated_at === 'string' && agentPayload.generated_at
      ? agentPayload.generated_at
      : null;
  if (!asOf) errors.push('generated_at missing');

  const marketId =
    pickString(agentPayload.market) ||
    pickString(agentPayload.input?.slug) ||
    pickString(agentPayload.input?.condition_id) ||
    '';
  if (!marketId) errors.push('market identity missing (market / input.slug / condition_id)');

  const matrixStatus = agentPayload.matrix_status;
  const freshnessStatus = mapFreshnessStatus(agentPayload);
  const analysisAllowed = mapAnalysisAllowed(agentPayload.hard_gate);
  const decision = mapDecision(agentPayload, freshnessStatus, analysisAllowed);

  if (freshnessStatus === 'missing' && decision !== null) {
    errors.push('decision must be null when freshness.status=missing');
  }
  if (!analysisAllowed && decision !== null) {
    errors.push('decision must be null when analysisAllowed=false');
  }
  if (decision?.eligibility === 'BET') {
    errors.push('L0 projection must never emit eligibility=BET');
  }

  if (errors.length) return { ok: false, errors };

  const partialReasons =
    freshnessStatus === 'partial'
      ? uniqueStrings([
          ...(Array.isArray(agentPayload.tradability_reasons) ? agentPayload.tradability_reasons : []),
          matrixStatus === 'incomplete' ? 'matrix_incomplete' : null,
          'partial_surface'
        ])
      : undefined;

  const evidence = buildEvidence(agentPayload);
  const summary = buildSummary(agentPayload);

  const value = {
    schemaId: COPILOT_SCHEMA_ID,
    schemaVersion: COPILOT_SCHEMA_VERSION,
    unitId,
    market: {
      platform: 'polymarket',
      marketId,
      eventId: pickString(agentPayload.event_slug) || undefined,
      slug: pickString(agentPayload.market) || pickString(agentPayload.input?.slug) || undefined,
      title: pickString(agentPayload.market_title) || pickString(agentPayload.event) || undefined,
      url: pickString(agentPayload.input?.market_url) || undefined
    },
    freshness: {
      status: freshnessStatus,
      asOf,
      ...(partialReasons?.length ? { partialReasons } : {})
    },
    evidence,
    compliance: {
      analysisAllowed,
      viewMode: 'summary',
      reason: analysisAllowed ? undefined : `hard_gate:${String(agentPayload.hard_gate)}`,
      policyVersion: 'pm-event-analyst-dual-surface-v0.1'
    },
    decision,
    ...(summary ? { summary } : {}),
    extensions: {
      [AGENT_EXTENSION_KEY]: agentPayload
    }
  };

  const forbidden = Object.keys(value).filter((k) => FORBIDDEN_ROOT_KEYS.has(k));
  if (forbidden.length) {
    return { ok: false, errors: [`forbidden root keys: ${forbidden.join(',')}`] };
  }

  return { ok: true, value };
}

function mapFreshnessStatus(payload) {
  const matrix = payload.matrix_status;
  const prices = payload.current_price;
  const hasPrice =
    prices &&
    typeof prices === 'object' &&
    Object.values(prices).some((v) => typeof v === 'number' && Number.isFinite(v));

  if (!hasPrice && (!Array.isArray(payload.event_matrix) || payload.event_matrix.length === 0)) {
    return 'missing';
  }
  if (matrix === 'complete') return 'complete';
  if (matrix === 'incomplete' || payload.tradability === 'weak') return 'partial';
  if (matrix == null && hasPrice) return 'partial';
  return hasPrice ? 'complete' : 'missing';
}

function mapAnalysisAllowed(hardGate) {
  if (hardGate == null || hardGate === 'no_orders_no_account_mutation') return true;
  return false;
}

function mapDecision(payload, freshnessStatus, analysisAllowed) {
  if (!analysisAllowed || freshnessStatus === 'missing') return null;

  const t = payload.tradability;
  if (t === 'high') {
    return {
      eligibility: 'OBSERVE',
      coverage_score: clamp01(evidenceCoverage(payload)),
      liquidity_score: clamp01(evidenceLiquidity(payload)),
      rules_clarity: 'MED',
      confidence: 0.7,
      edge: null
    };
  }
  if (t === 'medium') {
    return {
      eligibility: 'OBSERVE',
      coverage_score: clamp01(evidenceCoverage(payload)),
      liquidity_score: clamp01(evidenceLiquidity(payload)),
      rules_clarity: 'MED',
      confidence: 0.5,
      edge: null
    };
  }
  // weak | low | unknown — never BET from L0
  return {
    eligibility: 'AVOID',
    coverage_score: clamp01(evidenceCoverage(payload)),
    liquidity_score: clamp01(evidenceLiquidity(payload)),
    rules_clarity: freshnessStatus === 'partial' ? 'LOW' : 'UNKNOWN',
    confidence: 0.3,
    edge: null
  };
}

function buildEvidence(payload) {
  const sources = Array.isArray(payload.sources_read) ? payload.sources_read : [];
  const matrix = Array.isArray(payload.event_matrix) ? payload.event_matrix : [];
  const priceObj = payload.current_price;
  const hasCurrentPrice =
    priceObj &&
    typeof priceObj === 'object' &&
    Object.values(priceObj).some((v) => typeof v === 'number' && Number.isFinite(v));
  const hasPrices =
    matrix.some(
      (row) =>
        row &&
        ((typeof row.yes_price === 'number' && Number.isFinite(row.yes_price)) ||
          (typeof row.price === 'number' && Number.isFinite(row.price)))
    ) || hasCurrentPrice;
  return {
    coverageScore: clamp01(evidenceCoverage(payload)),
    sourcesCount: sources.length,
    hasRules: Boolean(payload.fixture_status || payload.market_fixture_match),
    hasPrices: Boolean(hasPrices),
    hasLiquidity: evidenceLiquidity(payload) > 0
  };
}

function evidenceCoverage(payload) {
  const matrix = Array.isArray(payload.event_matrix) ? payload.event_matrix : [];
  if (payload.matrix_status === 'complete' && matrix.length >= 2) return 0.85;
  if (matrix.length >= 1) return 0.55;
  return 0.2;
}

function evidenceLiquidity(payload) {
  const matrix = Array.isArray(payload.event_matrix) ? payload.event_matrix : [];
  const withLiq = matrix.filter((row) => typeof row?.liquidity === 'number' && row.liquidity > 0);
  if (withLiq.length >= 2) return 0.7;
  if (withLiq.length === 1) return 0.4;
  return payload.tradability === 'high' ? 0.5 : 0.15;
}

function buildSummary(payload) {
  const parts = [pickString(payload.base_case), pickString(payload.market_implied_view)].filter(Boolean);
  if (!parts.length) return undefined;
  return { en: parts.join(' ') };
}

function pickString(v) {
  return typeof v === 'string' && v.trim() ? v.trim() : null;
}

function uniqueStrings(items) {
  return [...new Set(items.filter((x) => typeof x === 'string' && x.trim()))];
}

function clamp01(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}
