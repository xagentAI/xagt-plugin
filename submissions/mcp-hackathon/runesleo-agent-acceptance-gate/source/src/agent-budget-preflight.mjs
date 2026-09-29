// Agent Budget Preflight — deterministic spend gate before an agent pays for a call.
// Productized from arc-budget-agent policy (read-only decision; no wallet / settle).

const SERVICE_ID = 'agent_budget_preflight';

const STANDARD_CAVEATS = [
  'Decision-only preflight. Does not hold funds, sign, settle, or call facilitators.',
  'Caller supplies budget state + offer; ASP returns buy / skip / reject with reasons.',
  'Not investment advice. For agent commerce safety before x402 / paid API calls.'
];

/**
 * @param {object} input
 * @param {number|string} input.budget_cap_usdt
 * @param {number|string} [input.spent_usdt]
 * @param {number|string} [input.held_usdt]
 * @param {number|string} [input.max_per_call_usdt]
 * @param {string[]} [input.allowlisted_providers]
 * @param {boolean} [input.evidence_sufficient]
 * @param {object} input.offer
 *   { provider, price_usdt, resource_url?, network?, asset?, id? }
 */
export function assessAgentBudgetPreflight(input = {}) {
  const budgetCap = toUsdt(input.budget_cap_usdt ?? input.budget_cap);
  const spent = toUsdt(input.spent_usdt ?? input.spent ?? 0);
  const held = toUsdt(input.held_usdt ?? input.held ?? 0);
  const maxPerCall = toUsdt(input.max_per_call_usdt ?? input.max_per_call ?? budgetCap);
  const evidenceSufficient = Boolean(input.evidence_sufficient);
  const allowlisted = normalizeProviders(input.allowlisted_providers ?? input.allowlist);
  const offer = normalizeOffer(input.offer ?? input.purchase ?? input.call);

  if (budgetCap === null || budgetCap <= 0) {
    throw new Error('budget_cap_usdt is required (positive number)');
  }
  if (!offer) {
    throw new Error('offer is required ({ provider, price_usdt, ... })');
  }
  // 2026-07-30: remaining = cap - spent - held, and nothing checked the sign of the
  // caller-supplied ledger. budget_cap_usdt=1 with spent_usdt=-100 reported
  // remaining=101 and returned action=buy for a 50 USDT offer — a spend gate
  // approving 50x its own cap. Negative ledger values are always a caller bug or an
  // attempt to widen the cap; refuse them instead of arithmetically absorbing them.
  if (spent === null || spent < 0) {
    throw new Error('spent_usdt must be zero or positive');
  }
  if (held === null || held < 0) {
    throw new Error('held_usdt must be zero or positive');
  }
  if (maxPerCall === null || maxPerCall <= 0) {
    throw new Error('max_per_call_usdt must be a positive number when provided');
  }

  const remaining = round4(Math.max(0, budgetCap - spent - held));
  const checks = [];

  if (allowlisted.length && !allowlisted.includes(offer.provider)) {
    return result({
      input: echo(input, budgetCap, spent, held, maxPerCall, offer, allowlisted, evidenceSufficient),
      action: 'reject_policy',
      reason: 'provider_not_allowed',
      remaining_usdt: remaining,
      checks: [...checks, failCheck('provider_allowlist', `provider ${offer.provider} not in allowlist`)]
    });
  }
  checks.push(passCheck('provider_allowlist', allowlisted.length ? 'provider allowed' : 'allowlist open'));

  if (offer.price_usdt > maxPerCall + 1e-9) {
    return result({
      input: echo(input, budgetCap, spent, held, maxPerCall, offer, allowlisted, evidenceSufficient),
      action: 'reject_budget',
      reason: 'per_call_cap_exceeded',
      remaining_usdt: remaining,
      checks: [...checks, failCheck('per_call_cap', `price ${offer.price_usdt} > max_per_call ${maxPerCall}`)]
    });
  }
  checks.push(passCheck('per_call_cap', 'within max_per_call_usdt'));

  if (offer.price_usdt > remaining + 1e-9) {
    return result({
      input: echo(input, budgetCap, spent, held, maxPerCall, offer, allowlisted, evidenceSufficient),
      action: 'reject_budget',
      reason: 'total_cap_exceeded',
      remaining_usdt: remaining,
      checks: [...checks, failCheck('total_cap', `price ${offer.price_usdt} > remaining ${remaining}`)]
    });
  }
  checks.push(passCheck('total_cap', 'within remaining budget'));

  if (evidenceSufficient) {
    return result({
      input: echo(input, budgetCap, spent, held, maxPerCall, offer, allowlisted, evidenceSufficient),
      action: 'skip_sufficient',
      reason: 'evidence_already_sufficient',
      remaining_usdt: remaining,
      checks: [...checks, failCheck('evidence_gate', 'caller marked evidence_sufficient=true — skip paid call')]
    });
  }
  checks.push(passCheck('evidence_gate', 'evidence not marked sufficient'));

  return result({
    input: echo(input, budgetCap, spent, held, maxPerCall, offer, allowlisted, evidenceSufficient),
    action: 'buy',
    reason: 'within_policy_and_budget',
    remaining_usdt: remaining,
    amount_usdt: offer.price_usdt,
    checks: [...checks, passCheck('decision', 'buy allowed (decision-only; caller settles)')]
  });
}

export function buildAgentBudgetPreflightFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    action: 'reject_policy',
    reason: 'demo_fallback',
    amount_usdt: 0,
    remaining_usdt: null,
    checks: [],
    input: { note: 'Provide budget_cap_usdt + offer.price_usdt' },
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Caller_executes_or_skips_payment',
    source: {
      method: 'rule_based_budget_preflight',
      oss_lineage: 'arc-budget-agent evaluateSpendDecision (generalized, no settle)'
    }
  };
}

function result({ input, action, reason, remaining_usdt, checks, amount_usdt = 0 }) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    action,
    reason,
    amount_usdt,
    remaining_usdt,
    checks,
    input,
    buyer_summary_zh: buildBudgetBuyerSummaryZh(action, reason, amount_usdt, remaining_usdt),
    value_loop: {
      why_pay_again: 'Budget state and offer change every call; re-run before each paid x402/API spend.',
      stale_after_minutes: null,
      best_used_in: 'agent_spend_gate_before_payment',
      paid_value_tier: 'A_repeat_workflow',
      fulfillment: 'edge_on_demand_no_llm'
    },
    caveats: [...STANDARD_CAVEATS],
    next_gate: action === 'buy'
      ? 'Caller_may_proceed_to_x402_or_paid_API'
      : 'Caller_must_skip_or_revise_offer',
    source: {
      method: 'rule_based_budget_preflight',
      oss_lineage: 'arc-budget-agent evaluateSpendDecision (generalized, no settle)'
    }
  };
}

function buildBudgetBuyerSummaryZh(action, reason, amount, remaining) {
  const actionZh = {
    buy: '可买（仅决策，不代付）',
    skip_sufficient: '证据已够，建议跳过付费',
    reject_budget: '预算不足/超单笔上限',
    reject_policy: '策略拒绝'
  }[action] || action;
  return `预算闸门：${actionZh}（${reason}）。本次报价 ${amount} USDT，剩余额度约 ${remaining} USDT。不签名、不结算。`;
}

function echo(input, budgetCap, spent, held, maxPerCall, offer, allowlisted, evidenceSufficient) {
  return {
    budget_cap_usdt: budgetCap,
    spent_usdt: spent,
    held_usdt: held,
    max_per_call_usdt: maxPerCall,
    allowlisted_providers: allowlisted,
    evidence_sufficient: evidenceSufficient,
    offer
  };
}

function normalizeOffer(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const price = toUsdt(raw.price_usdt ?? raw.price ?? raw.fee_usdt);
  const provider = String(raw.provider ?? raw.vendor ?? raw.asp ?? '').trim().toLowerCase();
  if (price === null || price <= 0 || !provider) return null;
  return {
    id: raw.id ? String(raw.id) : null,
    provider,
    price_usdt: price,
    resource_url: raw.resource_url ?? raw.endpoint ?? raw.url ?? null,
    network: raw.network ?? null,
    asset: raw.asset ?? 'USDT'
  };
}

function normalizeProviders(value) {
  if (!Array.isArray(value)) return [];
  return value.map((p) => String(p).trim().toLowerCase()).filter(Boolean);
}

function toUsdt(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? round4(n) : null;
}

function round4(n) {
  return Math.round(n * 10000) / 10000;
}

function passCheck(id, note) {
  return { id, status: 'pass', note };
}

function failCheck(id, note) {
  return { id, status: 'fail', note };
}
