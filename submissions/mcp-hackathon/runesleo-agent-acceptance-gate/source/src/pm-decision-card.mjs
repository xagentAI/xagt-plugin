// PM Decision Card — paid trading-loop SKU.
// Composes trade-preflight (+ optional event readout snippet) into one replayable
// gate: skip / watch / eligible_for_manual_review. Not a buy tip, no orders.

import {
  assessPmTradePreflightLive,
  buildPmTradePreflightFallback
} from './pm-trade-preflight.mjs';
import {
  assessPmEventReadoutLive,
  buildPmEventReadoutFallback
} from './pm-event-readout.mjs';
import { resolveMarketRef } from './pm-gamma-market.mjs';

const SERVICE_ID = 'pm_decision_card';
const SCHEMA_VERSION = '0.4';
const PUBLIC_THRESHOLD_SOURCE = 'asp_public_heuristic';
const PUBLIC_THRESHOLD_VERSION = 'v0.4';
const PUBLIC_HARD_GATE = 'no_orders_no_signing_no_wallet_custody_no_leo_private_bankroll';
const DEFAULT_FEE_BUFFER = 0.02;
/** Caller-supplied bankroll only — never Leo private SSOT. */
const CALLER_SIZING_AUTHORITY = 'caller_supplied_bankroll_or_size_usd';
const B_MINUS_PROBE_BANKROLL_FRAC = 0.015;

const STANDARD_CAVEATS = [
  'Decision card is a mechanical + event-context gate only. Not investment advice.',
  'eligible_for_manual_review ≠ buy tip; no order routing, no wallet custody.',
  'Fair band / max_entry are heuristic buffers around market price — not an external model fair value.'
];

/**
 * @param {object} input
 * @param {string} [input.market_url]
 * @param {string} [input.slug]
 * @param {string} [input.condition_id]
 * @param {string} [input.side]
 * @param {number} [input.size_usd]
 * @param {number} [input.bankroll_usd] caller-supplied only; never Leo private SSOT
 * @param {number} [input.existing_exposure_usd]
 * @param {number} [input.fair_prob]
 * @param {boolean} [input.include_event_context=true]
 */
export async function assessPmDecisionCardLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const includeEvent = input.include_event_context !== false;
  const ref = resolveMarketRef(input);
  if (!ref.slug && !ref.condition_id) {
    throw new Error('pm-decision-card requires market_url, slug, or condition_id');
  }

  const [preflightResult, readoutResult] = await Promise.allSettled([
    assessPmTradePreflightLive(input, { fetchImpl }),
    includeEvent
      ? assessPmEventReadoutLive({
          ...input,
          include_matrix: input.include_matrix !== false,
          enrich_category: input.enrich_category !== false
        }, { fetchImpl })
      : Promise.resolve(null)
  ]);

  if (preflightResult.status === 'rejected') {
    throw preflightResult.reason;
  }
  const preflight = preflightResult.value;
  const readout = readoutResult.status === 'fulfilled' ? readoutResult.value : null;
  const readoutError = readoutResult.status === 'rejected'
    ? (readoutResult.reason?.message || String(readoutResult.reason))
    : null;

  const decision = composeDecision(preflight, readout, input, { readoutError, includeEvent });
  const generated_at = new Date().toISOString();
  const stale_after_minutes = 5;
  const stale_at = new Date(Date.parse(generated_at) + stale_after_minutes * 60_000).toISOString();
  const paid_checks = buildPaidChecks(preflight, readout, decision);
  const value_loop = {
    why_pay_again: 'Market price, spread, volume and event matrix change; re-run before each order attempt.',
    stale_after_minutes,
    stale_at,
    best_used_in: 'agent_trading_loop_before_manual_or_automated_order',
    not_a_subscription_to: 'price_alerts_or_auto_execution',
    paid_value_tier: 'A_repeat_trading_loop',
    fulfillment: 'edge_on_demand_no_llm',
    operator_always_online: false,
    llm_api_key_required: false
  };

  return {
    schema_version: SCHEMA_VERSION,
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at,
    input: {
      market_url: input.market_url ?? null,
      condition_id: ref.condition_id,
      slug: ref.slug,
      side: preflight.input?.side,
      size_usd: preflight.input?.size_usd ?? null,
      bankroll_usd: decision.public_fields.bankroll_usd,
      include_event_context: includeEvent,
      existing_exposure_usd: decision.public_fields.existing_exposure_usd,
      decision_mode_override: normalizeDecisionMode(input.decision_mode),
      fair_prob: parseProbability(input.fair_prob ?? input.fair_probability)
    },
    action: decision.action,
    confidence: decision.confidence,
    opportunity_state: decision.public_fields.opportunity_state,
    decision_mode: decision.public_fields.decision_mode,
    current_price: decision.public_fields.current_price,
    current_executable_ask: decision.public_fields.current_executable_ask,
    max_entry: decision.public_fields.max_entry,
    order_quantity_shares: decision.public_fields.order_quantity_shares,
    estimated_cost_u: decision.public_fields.estimated_cost_u,
    sizing_role: decision.public_fields.sizing_role,
    sizing_authority: decision.public_fields.sizing_authority,
    market_implied_prob: decision.public_fields.market_implied_prob,
    fair_prob_range: decision.public_fields.fair_prob_range,
    price_status: decision.public_fields.price_status,
    edge_after_fees_buffer: decision.public_fields.edge_after_fees_buffer,
    threshold_role: decision.public_fields.threshold_role,
    threshold_scope: decision.public_fields.threshold_scope,
    threshold_source: decision.public_fields.threshold_source,
    threshold_version: decision.public_fields.threshold_version,
    best_alternative_market: decision.public_fields.best_alternative_market,
    best_alternative_ask: decision.public_fields.best_alternative_ask,
    best_alternative_why: decision.public_fields.best_alternative_why,
    chosen_market_beats_alternative: decision.public_fields.chosen_market_beats_alternative,
    missing_evidence: decision.public_fields.missing_evidence,
    consistency_check: decision.public_fields.consistency_check,
    hard_gate: decision.public_fields.hard_gate,
    buyer_summary_zh: decision.buyer_summary_zh,
    buyer_summary_en: decision.buyer_summary_en,
    paid_checks,
    value_loop,
    agent_loop: {
      step_1: 'Call this card with market ref + side (+ optional size_usd / bankroll_usd / existing_exposure_usd)',
      step_2: 'Read order_quantity_shares (share-first); if pending_* → supply size/bankroll or stop',
      step_3: 'If skip → stop; if watch → shrink/wait; if eligible_for_manual_review → human risk check',
      step_4: 'Only then place order elsewhere (this ASP never routes orders); re-run if stale'
    },
    decision_card: {
      ...preflight.decision_card_lite,
      ...decision.public_fields,
      action: decision.action,
      confidence: decision.confidence,
      reasons: decision.reasons,
      risk_flags: decision.risk_flags,
      next_actions: decision.next_actions,
      event_context: decision.event_context,
      paid_checks
    },
    preflight: {
      action: preflight.action,
      confidence: preflight.confidence,
      side_price: preflight.side_price,
      reasons: preflight.reasons,
      risk_flags: preflight.risk_flags,
      market: preflight.market
    },
    event_readout: readout
      ? {
          category: readout.category,
          category_depth: readout.category_depth,
          tradability: readout.tradability,
          tradability_reasons: readout.tradability_reasons,
          matrix_status: readout.matrix_status,
          base_case: readout.base_case,
          category_plugin_hint: readout.category_plugin
            ? {
                category: readout.category_plugin.category,
                default_action_hint: readout.category_plugin.default_action_hint,
                central_thesis: readout.category_plugin.central_thesis
                  || readout.category_plugin.market_implied_shape?.central_thesis
                  || null
              }
            : null
        }
      : null,
    caveats: [
      ...STANDARD_CAVEATS,
      ...(preflight.caveats || []).slice(0, 3),
      ...(readoutResult.status === 'rejected'
        ? [`Event context unavailable: ${readoutResult.reason?.message || readoutResult.reason}`]
        : [])
    ],
    next_gate: 'Human_or_hard_risk_limit_before_any_order',
    source: {
      method: 'compose_pm_trade_preflight_plus_optional_pm_event_readout',
      paid_value_tier: 'A_repeat_trading_loop'
    }
  };
}

export function buildPmDecisionCardFallback(input = {}) {
  const preflight = buildPmTradePreflightFallback(input);
  const generated_at = new Date().toISOString();
  const fallbackFields = {
    opportunity_state: 'data_blocked',
    decision_mode: normalizeDecisionMode(input.decision_mode) ?? 'no_trade',
    current_price: preflight.side_price ?? null,
    current_executable_ask: preflight.side_price ?? null,
    max_entry: preflight.decision_card_lite?.max_entry ?? null,
    market_implied_prob: preflight.side_price ?? null,
    fair_prob_range: preflight.decision_card_lite?.fair_prob_range ?? null,
    price_status: 'no_edge',
    edge_after_fees_buffer: null,
    threshold_role: 'block_or_verify',
    threshold_scope: 'public_market_price_liquidity_event_matrix_no_private_bankroll',
    threshold_source: PUBLIC_THRESHOLD_SOURCE,
    threshold_version: PUBLIC_THRESHOLD_VERSION,
    best_alternative_market: null,
    best_alternative_ask: null,
    best_alternative_why: null,
    chosen_market_beats_alternative: 'unknown',
    missing_evidence: ['live_market_data_unavailable', 'event_context_unavailable'],
    consistency_check: 'incomplete',
    hard_gate: PUBLIC_HARD_GATE,
    existing_exposure_usd: parseOptionalUsd(input.existing_exposure_usd ?? input.exposure_usd),
    bankroll_usd: parseOptionalUsd(input.bankroll_usd),
    order_quantity_shares: 'pending_caller_size',
    estimated_cost_u: null,
    sizing_role: 'none',
    sizing_authority: CALLER_SIZING_AUTHORITY
  };
  return {
    schema_version: SCHEMA_VERSION,
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at,
    input: preflight.input,
    action: 'watch',
    confidence: 0.4,
    ...fallbackFields,
    buyer_summary_zh: '演示回退：opportunity_state=data_blocked；缺口 live_market_data_unavailable。默认 watch。',
    buyer_summary_en: 'Demo fallback: opportunity_state=data_blocked; missing live_market_data_unavailable. Default watch.',
    paid_checks: {
      pass_count: 0,
      fail_count: 1,
      warn_count: 0,
      checks: [{ id: 'live_market', status: 'fail', detail: 'live_data_unavailable' }]
    },
    value_loop: {
      why_pay_again: 'Live market state changes; re-run before each order attempt.',
      stale_after_minutes: 5,
      stale_at: new Date(Date.parse(generated_at) + 5 * 60_000).toISOString(),
      best_used_in: 'agent_trading_loop_before_manual_or_automated_order',
      not_a_subscription_to: 'price_alerts_or_auto_execution'
    },
    decision_card: {
      ...preflight.decision_card_lite,
      ...fallbackFields,
      action: 'watch',
      next_actions: ['retry_with_live_market_ref']
    },
    preflight,
    event_readout: null,
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Human_or_hard_risk_limit_before_any_order',
    source: { method: 'static_fallback' }
  };
}

function composeDecision(preflight, readout, input = {}, context = {}) {
  let action = mapPreflightAction(preflight.action);
  const reasons = [...(preflight.reasons || [])];
  const risk_flags = [...(preflight.risk_flags || [])];
  let confidence = Number(preflight.confidence) || 0.5;

  const event_context = readout
    ? {
        category: readout.category,
        tradability: readout.tradability,
        matrix_status: readout.matrix_status,
        plugin_action_hint: readout.category_plugin?.default_action_hint ?? null
      }
    : null;

  if (readout) {
    if (readout.tradability === 'weak' || readout.tradability === 'low') {
      if (action === 'eligible_for_manual_review') action = 'watch';
      risk_flags.push('event_tradability_weak');
      reasons.push(`Event readout tradability=${readout.tradability}; tighten to watch.`);
      confidence -= 0.08;
    }
    const hint = readout.category_plugin?.default_action_hint;
    if (hint === 'no_trade' || hint === 'no_trade_until_source_and_ladder_ok') {
      action = action === 'skip' ? 'skip' : 'watch';
      risk_flags.push('category_plugin_no_trade_hint');
      reasons.push(`Category plugin hint=${hint}.`);
      confidence -= 0.1;
    }
    if (readout.matrix_status === 'incomplete') {
      risk_flags.push('event_matrix_incomplete');
      reasons.push('Same-event matrix incomplete — compare expressions carefully.');
      confidence -= 0.05;
    }
  }

  confidence = Math.max(0.35, Math.min(0.9, Math.round(confidence * 100) / 100));

  const public_fields = buildPublicDecisionFields({
    preflight,
    readout,
    input,
    action,
    risk_flags,
    readoutError: context.readoutError,
    includeEvent: context.includeEvent
  });

  const next_actions = [];
  if (action === 'skip') {
    next_actions.push('do_not_enter', 'pick_another_market_or_wait_for_reopen');
  } else if (action === 'watch') {
    next_actions.push('reduce_size_or_wait', 'recheck_after_liquidity_improves', 'optional_run_category_match_card');
  } else {
    next_actions.push('manual_risk_check', 'optional_compare_adjacent_ladder', 'only_then_consider_order');
  }

  const buyer_summary_zh = buildBuyerSummaryZh(action, preflight, readout, confidence, public_fields);
  const buyer_summary_en = buildBuyerSummaryEn(action, preflight, readout, confidence, public_fields);

  return {
    action,
    confidence,
    reasons,
    risk_flags: [...new Set(risk_flags)],
    next_actions,
    event_context,
    public_fields,
    buyer_summary_zh,
    buyer_summary_en
  };
}

function mapPreflightAction(action) {
  if (action === 'skip') return 'skip';
  if (action === 'watch') return 'watch';
  if (action === 'eligible') return 'eligible_for_manual_review';
  return 'watch';
}

function buildPublicDecisionFields({
  preflight,
  readout,
  input,
  action,
  risk_flags,
  readoutError,
  includeEvent
}) {
  const current_price = numberOrNull(preflight.side_price);
  const current_executable_ask = resolveExecutableAsk(preflight, input);
  const market_implied_prob = current_price;
  const callerFair = parseProbability(input.fair_prob ?? input.fair_probability);
  const lite = preflight.decision_card_lite || {};
  const fair_prob_range = callerFair !== null
    ? [roundProb(clamp(callerFair - 0.02, 0.01, 0.99)), roundProb(clamp(callerFair + 0.02, 0.01, 0.99))]
    : (Array.isArray(lite.fair_prob_range) ? lite.fair_prob_range : null);
  const max_entry = callerFair !== null
    ? roundProb(clamp(callerFair - DEFAULT_FEE_BUFFER, 0.01, 0.99))
    : numberOrNull(lite.max_entry);
  const edge_after_fees_buffer = callerFair !== null && current_executable_ask !== null
    ? roundProb(callerFair - current_executable_ask - DEFAULT_FEE_BUFFER)
    : null;

  const decision_mode = normalizeDecisionMode(input.decision_mode)
    ?? inferDecisionModeFromReadout(readout);
  const price_status = classifyPublicPriceStatus({
    action,
    current_executable_ask,
    max_entry,
    callerFair,
    edge_after_fees_buffer,
    risk_flags,
    decision_mode
  });
  const alternative = extractBestAlternative(readout, preflight.market?.slug);
  const chosen_market_beats_alternative = computeChosenBeatsAlternative(readout, preflight.market?.slug);
  const missing_evidence = collectMissingEvidence({
    preflight,
    readout,
    input,
    risk_flags,
    readoutError,
    includeEvent
  });
  const criticalMissing = missing_evidence.filter((item) => ![
    'existing_exposure_usd_not_supplied',
    'caller_size_or_bankroll_not_supplied'
  ].includes(item));
  const opportunity_state = inferOpportunityState({
    action,
    decision_mode,
    price_status,
    criticalMissing,
    chosen_market_beats_alternative
  });
  const consistency_check = inferConsistencyCheck({
    criticalMissing,
    chosen_market_beats_alternative,
    decision_mode,
    action
  });
  const threshold_role = inferThresholdRole({ opportunity_state, decision_mode, price_status });
  const sizing = computeCallerShareFirstSizing({
    input,
    current_executable_ask,
    opportunity_state,
    action
  });

  return {
    opportunity_state,
    decision_mode,
    current_price,
    current_executable_ask,
    max_entry,
    order_quantity_shares: sizing.order_quantity_shares,
    estimated_cost_u: sizing.estimated_cost_u,
    sizing_role: sizing.sizing_role,
    sizing_authority: sizing.sizing_authority,
    market_implied_prob,
    fair_prob_range,
    price_status,
    edge_after_fees_buffer,
    threshold_role,
    threshold_scope: 'public_market_price_liquidity_event_matrix_no_private_bankroll',
    threshold_source: PUBLIC_THRESHOLD_SOURCE,
    threshold_version: PUBLIC_THRESHOLD_VERSION,
    best_alternative_market: alternative?.market ?? null,
    best_alternative_ask: alternative?.ask ?? null,
    best_alternative_why: alternative?.why ?? null,
    chosen_market_beats_alternative,
    missing_evidence,
    consistency_check,
    hard_gate: PUBLIC_HARD_GATE,
    existing_exposure_usd: parseOptionalUsd(input.existing_exposure_usd ?? input.exposure_usd),
    bankroll_usd: sizing.bankroll_usd
  };
}

/**
 * Share-first sizing from caller-supplied bankroll/size only.
 * Never reads Leo private bankroll SSOT. No orders.
 */
function computeCallerShareFirstSizing({ input, current_executable_ask, opportunity_state, action }) {
  const bankroll_usd = parseOptionalUsd(input.bankroll_usd);
  const size_usd = parseOptionalUsd(input.size_usd ?? input.target_cost_usd);
  const exposure_usd = parseOptionalUsd(input.existing_exposure_usd ?? input.exposure_usd);
  const ask = current_executable_ask;

  if (action === 'skip' || ask == null || ask <= 0) {
    return {
      bankroll_usd,
      order_quantity_shares: size_usd == null && bankroll_usd == null ? 'pending_caller_size' : 'pending_anchor',
      estimated_cost_u: null,
      sizing_role: 'none',
      sizing_authority: CALLER_SIZING_AUTHORITY
    };
  }

  if (size_usd == null && bankroll_usd == null) {
    return {
      bankroll_usd: null,
      order_quantity_shares: 'pending_caller_size',
      estimated_cost_u: null,
      sizing_role: 'none',
      sizing_authority: CALLER_SIZING_AUTHORITY
    };
  }

  // Share math is still returned when opportunity_state=data_blocked so the
  // caller gets an enterable quantity; missing_evidence remains the hard gate.

  let targetCost = size_usd;
  let sizing_role = 'caller_supplied';
  if (targetCost == null && bankroll_usd != null) {
    // Public heuristic probe envelope only — not Leo risk SSOT B_normal ceiling.
    targetCost = Math.round(bankroll_usd * B_MINUS_PROBE_BANKROLL_FRAC * 100) / 100;
    sizing_role = 'B_minus_probe';
  } else if (bankroll_usd != null && size_usd != null) {
    const frac = size_usd / bankroll_usd;
    sizing_role = frac <= B_MINUS_PROBE_BANKROLL_FRAC + 1e-9 ? 'B_minus_probe' : 'caller_supplied';
  }

  if (exposure_usd != null && bankroll_usd != null && exposure_usd + (targetCost || 0) > bankroll_usd * 0.25) {
    return {
      bankroll_usd,
      order_quantity_shares: 'pending_anchor',
      estimated_cost_u: null,
      sizing_role: 'none',
      sizing_authority: CALLER_SIZING_AUTHORITY
    };
  }

  const shares = Math.floor((targetCost || 0) / ask);
  if (shares <= 0) {
    return {
      bankroll_usd,
      order_quantity_shares: 'pending_caller_size',
      estimated_cost_u: null,
      sizing_role: 'none',
      sizing_authority: CALLER_SIZING_AUTHORITY
    };
  }

  return {
    bankroll_usd,
    order_quantity_shares: shares,
    estimated_cost_u: Math.round(shares * ask * 100) / 100,
    sizing_role,
    sizing_authority: CALLER_SIZING_AUTHORITY
  };
}

function resolveExecutableAsk(preflight, input = {}) {
  const current = numberOrNull(preflight.side_price);
  if (current === null) return null;
  const side = String(preflight.input?.side ?? input.side ?? 'yes').trim().toLowerCase();
  const bestAsk = numberOrNull(preflight.market?.best_ask);
  // Gamma bestAsk is reliable for the primary Yes token; for No, outcomePrices is
  // the safer public approximation unless a side-aware CLOB book is added later.
  if (side === 'yes' && bestAsk !== null) return roundProb(bestAsk);
  return current;
}

function inferDecisionModeFromReadout(readout) {
  const hint = readout?.category_plugin?.default_action_hint;
  if (typeof hint === 'string' && hint.includes('no_trade')) return 'no_trade';
  const batchAction = readout?.category_plugin?.batch2_public?.action;
  if (batchAction === 'skip' || batchAction === 'no_trade') return 'no_trade';
  return 'price_edge';
}

function classifyPublicPriceStatus({
  action,
  current_executable_ask,
  max_entry,
  callerFair,
  edge_after_fees_buffer,
  risk_flags,
  decision_mode
}) {
  if (current_executable_ask === null || action === 'skip' || decision_mode === 'no_trade') return 'no_edge';
  if (callerFair !== null && edge_after_fees_buffer !== null) {
    if (edge_after_fees_buffer >= 0.05) return 'cheap';
    if (edge_after_fees_buffer >= 0) return 'acceptable';
    if (current_executable_ask <= callerFair + 0.02) return 'full';
    return 'rich';
  }
  if (max_entry !== null && current_executable_ask <= max_entry - 0.03) return 'cheap';
  if (action === 'eligible_for_manual_review') return 'acceptable';
  if ((risk_flags || []).includes('extreme_implied_probability')) return 'rich';
  if (action === 'watch') return 'full';
  return 'no_edge';
}

function extractBestAlternative(readout, currentSlug) {
  const plugin = readout?.category_plugin;
  const cmp = plugin?.expression_comparison;
  if (cmp?.recommended) {
    const rec = compactAlternative(cmp.recommended);
    if (rec && !sameSlug(rec.slug, currentSlug)) return rec;
  }
  if (Array.isArray(cmp?.candidates)) {
    const candidate = cmp.candidates.find((row) => row && !sameSlug(row.slug, currentSlug));
    const alt = compactAlternative(candidate);
    if (alt) return alt;
  }
  const bestExpression = plugin?.batch2_public?.best_expression ?? plugin?.best_expression;
  if (bestExpression?.market) {
    return {
      market: bestExpression.market,
      slug: bestExpression.market,
      ask: numberOrNull(bestExpression.ask ?? bestExpression.yes),
      why: bestExpression.why ?? bestExpression.note ?? 'Best expression from category plugin.'
    };
  }
  return null;
}

function compactAlternative(row) {
  if (!row) return null;
  return {
    market: row.market ?? row.expression ?? row.slug ?? null,
    slug: row.slug ?? null,
    ask: numberOrNull(row.ask ?? row.yes ?? row.price),
    why: row.why_consider ?? row.why ?? row.path ?? row.note ?? null
  };
}

function computeChosenBeatsAlternative(readout, currentSlug) {
  const recommended = readout?.category_plugin?.expression_comparison?.recommended;
  if (!recommended?.slug || !currentSlug) return 'unknown';
  return sameSlug(recommended.slug, currentSlug) ? 'yes' : 'no';
}

function collectMissingEvidence({
  preflight,
  readout,
  input,
  risk_flags,
  readoutError,
  includeEvent
}) {
  const missing = [];
  if ((risk_flags || []).includes('missing_side_price')) missing.push('current_side_price_missing');
  if ((risk_flags || []).includes('market_closed_or_inactive')) missing.push('market_closed_or_inactive');
  if (readoutError) missing.push('event_context_unavailable');
  if (includeEvent === false) missing.push('event_context_omitted');
  if (!readout && includeEvent !== false) missing.push('event_context_unavailable');
  if (readout?.matrix_status === 'incomplete') missing.push('same_event_matrix_incomplete');
  const plugin = readout?.category_plugin;
  const fixtureStatus = plugin?.fixture?.fixture_status ?? plugin?.batch2_public?.fixture_status ?? plugin?.fixture_status;
  if (fixtureStatus && !['ok', 'not_applicable'].includes(fixtureStatus)) {
    missing.push(`fixture_${fixtureStatus}`);
  }
  if (Array.isArray(plugin?.missing_market_groups) && plugin.missing_market_groups.length) {
    missing.push(`missing_market_groups:${plugin.missing_market_groups.slice(0, 5).join(',')}`);
  }
  const hint = plugin?.default_action_hint;
  if (typeof hint === 'string' && hint.includes('no_trade')) {
    missing.push(`category_plugin_${hint}`);
  }
  if (readout?.tradability === 'weak' || readout?.tradability === 'low') {
    missing.push(`event_tradability_${readout.tradability}`);
  }
  if (parseOptionalUsd(input.existing_exposure_usd ?? input.exposure_usd) === null) {
    missing.push('existing_exposure_usd_not_supplied');
  }
  if (
    parseOptionalUsd(input.size_usd ?? input.target_cost_usd) === null
    && parseOptionalUsd(input.bankroll_usd) === null
  ) {
    missing.push('caller_size_or_bankroll_not_supplied');
  }
  return [...new Set(missing)];
}

function inferOpportunityState({
  action,
  decision_mode,
  price_status,
  criticalMissing,
  chosen_market_beats_alternative
}) {
  if (criticalMissing.length) return 'data_blocked';
  if (chosen_market_beats_alternative === 'no') return 'no_edge';
  if (decision_mode === 'event_outcome') return 'event_outcome';
  if (action === 'skip' || decision_mode === 'no_trade' || ['rich', 'no_edge'].includes(price_status)) {
    return 'no_edge';
  }
  if (action === 'eligible_for_manual_review' && ['cheap', 'acceptable'].includes(price_status)) {
    return 'strong_micro_candidate';
  }
  if (action === 'watch') return 'manual_micro_validation';
  return 'no_edge';
}

function inferConsistencyCheck({ criticalMissing, chosen_market_beats_alternative, decision_mode, action }) {
  if (criticalMissing.length) return 'incomplete';
  if (chosen_market_beats_alternative === 'no') return 'conflict';
  if (decision_mode === 'no_trade' && action === 'eligible_for_manual_review') return 'conflict';
  return 'ok';
}

function inferThresholdRole({ opportunity_state, decision_mode, price_status }) {
  if (opportunity_state === 'data_blocked') return 'verification_block';
  if (opportunity_state === 'no_edge') return 'block_or_wait';
  if (decision_mode === 'event_outcome') return 'event_path_participation';
  if (opportunity_state === 'strong_micro_candidate' && ['cheap', 'acceptable'].includes(price_status)) {
    return 'public_promotion_candidate';
  }
  return 'manual_micro_validation';
}

function buildPaidChecks(preflight, readout, decision) {
  const flags = new Set(decision.risk_flags || []);
  const checks = [
    checkFromFlag('market_open', !flags.has('market_closed_or_inactive'), 'market not closed/inactive'),
    checkFromFlag('side_price', !flags.has('missing_side_price'), `side_price=${preflight.side_price ?? 'n/a'}`),
    checkFromFlag('liquidity_24h', !flags.has('low_liquidity'), '24h volume vs threshold'),
    checkFromFlag('spread', !flags.has('wide_spread'), 'bid/ask spread heuristic'),
    checkFromFlag('price_zone', !flags.has('extreme_implied_probability'), 'not extreme entry zone'),
    checkFromFlag('size_vs_volume', !flags.has('size_large_vs_daily_volume'), 'size vs 24h volume')
  ];
  if (readout) {
    checks.push(
      checkFromFlag(
        'event_tradability',
        !flags.has('event_tradability_weak'),
        `tradability=${readout.tradability ?? 'n/a'}`
      ),
      checkFromFlag(
        'event_matrix',
        !flags.has('event_matrix_incomplete'),
        `matrix_status=${readout.matrix_status ?? 'n/a'}`
      ),
      checkFromFlag(
        'category_plugin',
        !flags.has('category_plugin_no_trade_hint'),
        `plugin_hint=${readout.category_plugin?.default_action_hint ?? 'none'}`
      )
    );
  } else {
    checks.push({ id: 'event_context', status: 'warn', detail: 'event context omitted or unavailable' });
  }

  const pass_count = checks.filter((c) => c.status === 'pass').length;
  const fail_count = checks.filter((c) => c.status === 'fail').length;
  const warn_count = checks.filter((c) => c.status === 'warn').length;
  return { pass_count, fail_count, warn_count, checks };
}

function checkFromFlag(id, ok, detail) {
  return { id, status: ok ? 'pass' : 'fail', detail };
}

function buildBuyerSummaryZh(action, preflight, readout, confidence, publicFields = {}) {
  const actionZh = {
    skip: '跳过',
    watch: '先观望',
    eligible_for_manual_review: '机械检查过关，仍需人工风控'
  }[action] || action;
  const price = preflight.side_price;
  const cat = readout?.category ? `；事件品类 ${readout.category}/${readout.tradability}` : '';
  const missingTop = publicFields.missing_evidence?.[0]
    ? `；主要缺口 ${publicFields.missing_evidence[0]}`
    : '';
  return `决策卡：${actionZh}（置信 ${confidence}）。opportunity_state=${publicFields.opportunity_state ?? 'unknown'}${missingTop}。侧价 ${price ?? 'n/a'}${cat}。eligible≠买点；下单前再跑一次。`;
}

function buildBuyerSummaryEn(action, preflight, readout, confidence, publicFields = {}) {
  const actionEn = {
    skip: 'skip',
    watch: 'watch',
    eligible_for_manual_review: 'eligible for manual review (not a buy tip)'
  }[action] || action;
  const price = preflight.side_price;
  const cat = readout?.category ? `; event ${readout.category}/${readout.tradability}` : '';
  const missingTop = publicFields.missing_evidence?.[0]
    ? `; top missing evidence: ${publicFields.missing_evidence[0]}`
    : '';
  return `Decision card: ${actionEn} (confidence ${confidence}). opportunity_state=${publicFields.opportunity_state ?? 'unknown'}${missingTop}. Side price ${price ?? 'n/a'}${cat}. Re-run before any order.`;
}

function normalizeDecisionMode(value) {
  const raw = String(value ?? '').trim().toLowerCase();
  if (raw === 'event_outcome' || raw === 'price_edge' || raw === 'no_trade') return raw;
  return null;
}

function parseProbability(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return n > 0 && n < 1 ? roundProb(n) : null;
}

function parseOptionalUsd(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) / 100 : null;
}

function numberOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? roundProb(n) : null;
}

function roundProb(value) {
  return Math.round(value * 1000) / 1000;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function sameSlug(a, b) {
  if (!a || !b) return false;
  return String(a).trim().toLowerCase() === String(b).trim().toLowerCase();
}
